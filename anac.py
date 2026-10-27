"""Fonte: Piattaforma di Pubblicità a Valore Legale (PVL) di ANAC.

Dal 2024 ogni bando, avviso ed esito italiano viene pubblicato qui per legge.
L'API JSON non è documentata: è quella che usa la ricerca avanzata del portale.
Contratto (verificato da altri progetti pubblici ad agosto 2026):

    GET https://pubblicitalegale.anticorruzione.it/api/v0/avvisi-full-text-specializzata
        ?page=0&pageSize=100
        &dataPubblicazioneStart=GG/MM/AAAA&dataPubblicazioneEnd=GG/MM/AAAA
        &cpv=722,723,...                (prefissi 3-8 cifre, separati da virgola)
        &sortField=dataPubblicazione&sortDirection=desc&operatore=AND

    -> {"content": [avviso, ...], "count": <totale>, ...}

Nessuna autenticazione. Nella risposta il campo cpv è l'etichetta testuale, non il codice.
Se ANAC cambia l'API, qui si rompe: monitor.py lo segnala su Telegram dopo 2 run falliti.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta

import requests

from models import Avviso

BASE = "https://pubblicitalegale.anticorruzione.it"
ENDPOINT = f"{BASE}/api/v0/avvisi-full-text-specializzata"

PAGE_SIZE = 100
CPV_PER_CHIAMATA = 12   # URL corti e, se un prefisso è sbagliato, si isola l'errore
MAX_PAGINE = 30         # per gruppo CPV: con i filtri IT sono di solito 1-3
PAUSA = 0.7             # cortesia verso il server
TENTATIVI = 3
HEADERS = {
    "User-Agent": "Mozilla/5.0 (gare-monitor)",
    "Accept": "application/json",
    "Accept-Language": "it-IT,it;q=0.9",
}

# Dalla "tipologia" ANAC al momento del ciclo d'acquisto.
MOMENTI = {
    "INDAGINI_DI_MERCATO_SOTTO_SOGLIA": "manifestazione",
    "CONSULTAZIONI_PRELIMINARI_DI_MERCATO": "manifestazione",
    "AVVISI_DI_PREINFORMAZIONE": "preavviso",
    "BANDI": "gara",
    "RISULTATI": "esito",
    "MODIFICHE_CONTRATTUALI": "modifica",
    "AVVISI_DI_PROROGA": "modifica",
}
ROTTE = {"gara": "bandi", "preavviso": "bandi", "esito": "esiti"}


def _get(params: dict, session: requests.Session) -> dict:
    last = None
    for attempt in range(1, TENTATIVI + 1):
        try:
            r = session.get(ENDPOINT, params=params, headers=HEADERS, timeout=90)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = e
            if attempt < TENTATIVI:
                time.sleep(2 * attempt)
    raise RuntimeError(f"ANAC non raggiungibile dopo {TENTATIVI} tentativi: {last}")


# --- normalizzazione -------------------------------------------------------

def _section(template: dict, prefix: str) -> dict:
    for s in template.get("sections") or []:
        if str(s.get("name", "")).startswith(prefix):
            return s
    return {}


def _iso_date(value) -> str | None:
    """'2026-08-31T23:59:00.000+00:00' -> '2026-08-31'."""
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None


def _first(*values):
    for v in values:
        if v not in (None, "", []):
            return v
    return None


def _clean(text) -> str:
    return " ".join(str(text or "").split())


def normalizza(raw: dict) -> Avviso | None:
    """Un avviso PVL (struttura a template/sezioni) -> Avviso piatto. None se illeggibile."""
    templates = raw.get("templates") or []
    id_avviso = raw.get("idAvviso")
    if not templates or not id_avviso:
        return None
    template = templates[0].get("template") or {}
    meta = template.get("metadata") or {}
    sa = (_section(template, "SEZ. A").get("fields") or {}).get("soggetti_sa") or []
    general = _section(template, "SEZ. B").get("fields") or {}
    items = _section(template, "SEZ. C").get("items") or []
    first = items[0] if items else {}

    momento = MOMENTI.get(raw.get("tipologia"), "altro")
    descrizione = _clean(_first(meta.get("descrizione"), first.get("descrizione")))
    titolo = _clean(_first(meta.get("titolo"), first.get("descrizione"), descrizione)) or "(senza titolo)"
    if len(titolo) > 220:
        titolo = titolo[:217].rstrip() + "…"

    stimati = [i["valore_complessivo_stimato"] for i in items
               if isinstance(i.get("valore_complessivo_stimato"), (int, float))]
    vinti = [i["valore_offerta_vincente"] for i in items
             if isinstance(i.get("valore_offerta_vincente"), (int, float))]

    aggiudicatari = []
    for i in items:
        for a in i.get("aggiudicatari") or []:
            for s in a.get("soggetti") or []:
                aggiudicatari.append({"nome": s.get("denominazione"), "importo": a.get("importo")})

    luoghi = [_first(i.get("luogo_nuts"), i.get("luogo_istat")) for i in items]
    luoghi = [str(x) for x in luoghi if x]

    return Avviso(
        id=str(id_avviso),
        momento=momento,
        titolo=titolo,
        descrizione=descrizione[:1200],
        ente=_clean(sa[0].get("denominazione_amministrazione")) or None if sa else None,
        cf_ente=sa[0].get("codice_fiscale") if sa else None,
        cig=_first(*[i.get("cig") for i in items]),
        categorie=[_clean(i["cpv"]) for i in items if i.get("cpv")],
        natura=(_clean(first.get("natura_principale")).lower() or None),
        valore=sum(stimati) if stimati else None,
        valore_aggiudicato=sum(vinti) if vinti else None,
        aggiudicatari=aggiudicatari,
        luogo=luoghi[0] if luoghi else None,
        pubblicazione=_iso_date(raw.get("dataPubblicazione")),
        scadenza=_first(_iso_date(raw.get("dataScadenza")),
                        _iso_date(first.get("termine_ricezione_offerte")),
                        _iso_date(first.get("termine_invito"))),
        url=f"{BASE}/{ROTTE.get(momento, 'avvisi')}/{id_avviso}",
        link_gara=_first(first.get("documenti_di_gara_link"), general.get("documenti_di_gara_link")),
    )


# --- download --------------------------------------------------------------

def finestra(giorni: int, oggi: date | None = None) -> tuple[str, str]:
    fine = oggi or date.today()
    return (fine - timedelta(days=giorni)).strftime("%d/%m/%Y"), fine.strftime("%d/%m/%Y")


def fetch(cfg: dict, oggi: date | None = None, log=print) -> list[Avviso]:
    """Tutti gli avvisi della finestra sui CPV in config, deduplicati per idAvviso."""
    da, a = finestra(cfg.get("giorni_finestra", 3), oggi)
    prefissi = sorted(set(str(c) for c in cfg["cpv"]))
    gruppi = [prefissi[i:i + CPV_PER_CHIAMATA] for i in range(0, len(prefissi), CPV_PER_CHIAMATA)]
    per_id: dict[str, Avviso] = {}
    scartati = 0
    with requests.Session() as s:
        for n, gruppo in enumerate(gruppi, 1):
            page, total = 0, None
            while True:
                data = _get({
                    "page": page, "pageSize": PAGE_SIZE,
                    "dataPubblicazioneStart": da, "dataPubblicazioneEnd": a,
                    "cpv": ",".join(gruppo),
                    "sortField": "dataPubblicazione", "sortDirection": "desc",
                    "operatore": "AND",
                }, s)
                content = data.get("content") or []
                if total is None:
                    total = int(data.get("count") or 0)
                    log(f"[anac] gruppo {n}/{len(gruppi)} {da}→{a}: {total} avvisi")
                for raw in content:
                    av = normalizza(raw)
                    if av:
                        per_id[av.id] = av
                    else:
                        scartati += 1
                page += 1
                if not content or page * PAGE_SIZE >= total or page >= MAX_PAGINE:
                    break
                time.sleep(PAUSA)
    if scartati:
        log(f"[anac] {scartati} avvisi con struttura non riconosciuta (ignorati)")
    return list(per_id.values())
