"""Filtri e punteggio, separati dalla fonte e testabili da soli."""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from models import Avviso

# NUTS 2 (versione 2021) -> regione
NUTS = {
    "ITC1": "Piemonte", "ITC2": "Valle d'Aosta", "ITC3": "Liguria", "ITC4": "Lombardia",
    "ITH1": "Trentino-Alto Adige", "ITH2": "Trentino-Alto Adige", "ITH3": "Veneto",
    "ITH4": "Friuli-Venezia Giulia", "ITH5": "Emilia-Romagna",
    "ITI1": "Toscana", "ITI2": "Umbria", "ITI3": "Marche", "ITI4": "Lazio",
    "ITF1": "Abruzzo", "ITF2": "Molise", "ITF3": "Campania", "ITF4": "Puglia",
    "ITF5": "Basilicata", "ITF6": "Calabria", "ITG1": "Sicilia", "ITG2": "Sardegna",
}

# Codice ISTAT del comune (6 cifre): le prime 3 sono la provincia.
ISTAT_PROVINCE = {"061": "Campania", "062": "Campania", "063": "Campania",
                  "064": "Campania", "065": "Campania"}

# Fallback testuale: capoluoghi e province (solo le regioni più probabili da indicare a mano).
PAROLE_REGIONE = {
    "Campania": ["campania", "napoli", "caserta", "salerno", "avellino", "benevento"],
    "Lazio": ["lazio", "roma", "latina", "frosinone", "viterbo", "rieti"],
    "Lombardia": ["lombardia", "milano", "bergamo", "brescia"],
    "Puglia": ["puglia", "bari", "lecce", "taranto", "foggia", "brindisi"],
}


def norm(text: str | None) -> str:
    """Minuscole, senza accenti, spazi singoli."""
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return " ".join(t.lower().split())


def regione_di(av: Avviso) -> str | None:
    luogo = str(av.luogo or "").strip().upper()
    if re.match(r"^IT[A-Z]\d", luogo):
        return NUTS.get(luogo[:4])
    if re.match(r"^\d{6}$", luogo):
        return ISTAT_PROVINCE.get(luogo[:3])
    testo = f" {norm(av.luogo)} {norm(av.ente)} "
    for regione, parole in PAROLE_REGIONE.items():
        if any(re.search(rf"\b{p}\b", testo) for p in parole):
            return regione
    return None


def _testo(av: Avviso) -> str:
    return norm(" ".join([av.titolo, av.descrizione, *av.categorie]))


def motivo_scarto(av: Avviso, cfg: dict, oggi: date) -> str | None:
    """None se l'avviso va tenuto, altrimenti il motivo dello scarto."""
    if av.momento not in cfg.get("momenti_avviso", []):
        return f"momento {av.momento}"
    if av.scadenza and av.scadenza < oggi.isoformat():
        return "scaduto"
    regioni = cfg.get("solo_regioni") or []
    if regioni and av.regione not in regioni:
        return f"regione {av.regione or '?'}"
    if av.valore is not None:
        if av.valore < cfg.get("valore_min", 0):
            return "importo basso"
        vmax = cfg.get("valore_max")
        if vmax and av.valore > vmax:
            return "importo alto"
    testo = _testo(av)
    for parola in cfg.get("escludi") or []:
        if norm(parola) in testo:
            return f"esclusa '{parola}'"
    return None


def punteggio(av: Avviso, cfg: dict) -> int:
    testo = _testo(av)
    p = sum(1 for parola in cfg.get("interesse") or [] if re.search(rf"\b{re.escape(norm(parola))}", testo))
    if av.regione and av.regione in (cfg.get("regioni_prioritarie") or []):
        p += 3
    if av.momento == "manifestazione":
        p += 1   # sotto soglia: concorrenza più bassa, adatta a una partita IVA
    return p


def prepara(avvisi: list[Avviso], cfg: dict, oggi: date) -> tuple[list[Avviso], dict[str, int]]:
    """Regione e punteggio su tutti; ritorna i tenuti (ordinati) e il conteggio degli scarti."""
    tenuti, scarti = [], {}
    for av in avvisi:
        av.regione = regione_di(av)
        av.punteggio = punteggio(av, cfg)
        motivo = motivo_scarto(av, cfg, oggi)
        if motivo:
            chiave = motivo.split(" '")[0]
            scarti[chiave] = scarti.get(chiave, 0) + 1
        else:
            tenuti.append(av)
    return ordina(tenuti), scarti


def ordina(avvisi: list[Avviso]) -> list[Avviso]:
    """Prima i più interessanti, a parità quelli che scadono prima."""
    return sorted(avvisi, key=lambda a: (-a.punteggio, a.scadenza or "9999", a.titolo))
