"""Dati in data/ (committati dal workflow): stato anti-spam, avvisi aperti, esiti, errori."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from models import Avviso

DATA = Path(__file__).parent / "data"
STATE = DATA / "state.json"
LATEST = DATA / "latest.json"
ESITI = DATA / "esiti.csv"
ERRORS = DATA / "last_errors.txt"

ESITI_COLS = ["id", "pubblicazione", "regione", "ente", "titolo", "categoria", "cig",
              "valore", "valore_aggiudicato", "aggiudicatari", "url"]
GIORNI_MEMORIA = 180   # dopo quanto si dimentica di aver notificato un avviso


def load_state() -> dict:
    state = json.loads(STATE.read_text("utf-8")) if STATE.exists() else {}
    state.setdefault("notified", {})   # idAvviso -> data della notifica
    state.setdefault("failures", 0)    # run falliti consecutivi della fonte ANAC
    state.setdefault("esiti_digest", None)
    return state


def save_state(state: dict, oggi: date) -> None:
    limite = (oggi - timedelta(days=GIORNI_MEMORIA)).isoformat()
    state["notified"] = {k: v for k, v in state["notified"].items() if v >= limite}
    DATA.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False, sort_keys=True) + "\n", "utf-8")


def nuovi(avvisi: list[Avviso], state: dict, oggi: date) -> list[Avviso]:
    """Anti-spam: solo gli avvisi mai notificati. Li segna come notificati."""
    out = [a for a in avvisi if a.id not in state["notified"]]
    for a in out:
        state["notified"][a.id] = oggi.isoformat()
    return out


def load_latest() -> list[Avviso]:
    if not LATEST.exists():
        return []
    return [Avviso.from_dict(d) for d in json.loads(LATEST.read_text("utf-8")).get("avvisi", [])]


def write_latest(avvisi: list[Avviso], oggi: date) -> list[Avviso]:
    """Unisce gli avvisi aperti già noti con quelli di questo run, toglie gli scaduti.

    La finestra di ricerca è di pochi giorni: senza unione, un bando visto lunedì
    sparirebbe dal riepilogo di giovedì anche se scade fra un mese.
    """
    per_id = {a.id: a for a in load_latest()}
    per_id.update({a.id: a for a in avvisi})
    oggi_s = oggi.isoformat()
    vecchio = (oggi - timedelta(days=60)).isoformat()
    aperti = [a for a in per_id.values()
              if (a.scadenza and a.scadenza >= oggi_s)
              or (not a.scadenza and (a.pubblicazione or oggi_s) >= vecchio)]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    DATA.mkdir(exist_ok=True)
    LATEST.write_text(json.dumps({"updated": now, "avvisi": [a.to_dict() for a in aperti]},
                                 ensure_ascii=False, indent=1) + "\n", "utf-8")
    return aperti


def append_esiti(esiti: list[Avviso]) -> int:
    """Aggiunge gli esiti nuovi a data/esiti.csv (chi ha comprato cosa, da chi). Ritorna quanti."""
    DATA.mkdir(exist_ok=True)
    noti = set()
    if ESITI.exists():
        with ESITI.open(encoding="utf-8", newline="") as f:
            noti = {row["id"] for row in csv.DictReader(f)}
    nuovi_esiti = [e for e in esiti if e.id not in noti]
    if not nuovi_esiti:
        return 0
    scrivi_header = not ESITI.exists()
    with ESITI.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ESITI_COLS)
        if scrivi_header:
            w.writeheader()
        for e in sorted(nuovi_esiti, key=lambda x: x.pubblicazione or ""):
            w.writerow({
                "id": e.id, "pubblicazione": e.pubblicazione, "regione": e.regione or "",
                "ente": e.ente or "", "titolo": e.titolo,
                "categoria": e.categorie[0] if e.categorie else "", "cig": e.cig or "",
                "valore": e.valore if e.valore is not None else "",
                "valore_aggiudicato": e.valore_aggiudicato if e.valore_aggiudicato is not None else "",
                "aggiudicatari": "; ".join(x["nome"] for x in e.aggiudicatari if x.get("nome")),
                "url": e.url,
            })
    return len(nuovi_esiti)


def load_esiti(da: date) -> list[dict]:
    if not ESITI.exists():
        return []
    with ESITI.open(encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f) if (r["pubblicazione"] or "") >= da.isoformat()]


def write_errors(errors: dict[str, str]) -> None:
    """Errori e avvisi del run: si leggono dal repo (i log di Actions spesso non sono accessibili)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = "".join(f"[{k}]\n{v}\n\n" for k, v in errors.items()) or "Nessun errore\n"
    DATA.mkdir(exist_ok=True)
    ERRORS.write_text(f"Run del {now}\n\n{body}", "utf-8")
