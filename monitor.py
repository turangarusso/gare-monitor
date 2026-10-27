"""Monitor gare d'appalto IT da ANAC con avvisi Telegram.

    python monitor.py                  # run normale: avvisa solo per gli avvisi nuovi
    python monitor.py --digest         # + riepilogo di tutti gli avvisi ancora aperti
    python monitor.py --esiti          # + riepilogo degli esiti degli ultimi 7 giorni
    python monitor.py --dry-run        # stampa i messaggi, non invia e non salva
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

import yaml

import anac
import filters
import notify
import storage

CONFIG = Path(__file__).parent / "config.yaml"
FALLIMENTI_PRIMA_DI_AVVISARE = 2


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text("utf-8"))


def annotate(level: str, msg: str) -> None:
    """Annotazione visibile nel riepilogo del run di GitHub Actions."""
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{level}::{msg}")
    else:
        print(f"[{level}] {msg}")


def run(args, cfg: dict, oggi: date) -> int:
    state = storage.load_state()
    primo_avvio = not state["notified"]
    errors: dict[str, str] = {}
    warnings: list[str] = []

    try:
        tutti = anac.fetch(cfg, oggi)
        state["failures"] = 0
    except Exception as ex:  # la fonte può rompersi: si continua col riepilogo dai dati salvati
        tutti = None
        state["failures"] += 1
        errors["anac"] = "".join(traceback.format_exception_only(type(ex), ex)).strip()
        annotate("error", f"ANAC: {ex}")
        if state["failures"] >= FALLIMENTI_PRIMA_DI_AVVISARE:
            warnings.append(f"ANAC non risponde da {state['failures']} run: {ex}")

    messages: list[str] = []
    if tutti is not None:
        for av in tutti:
            av.regione = filters.regione_di(av)
        esiti = [a for a in tutti if a.momento == "esito"]
        tenuti, scarti = filters.prepara(tutti, cfg, oggi)
        nuovi = storage.nuovi(tenuti, state, oggi)
        conteggio = (f"{len(tutti)} avvisi scaricati, {len(tenuti)} tenuti, {len(nuovi)} nuovi, "
                     f"{len(esiti)} esiti. Scarti: {scarti or 'nessuno'}")
        annotate("notice", conteggio)
        errors["riepilogo"] = conteggio

        if not args.dry_run:
            storage.append_esiti(esiti)
            aperti = storage.write_latest(tenuti, oggi)
        else:
            aperti = list({a.id: a for a in storage.load_latest() + tenuti}.values())

        if primo_avvio and not args.dry_run:
            # al primo avvio tutti gli avvisi sarebbero "nuovi": meglio un riepilogo unico
            messages += [f"✅ <b>Monitor gare IT attivo.</b> Ti avviso per ogni nuovo avviso; "
                         f"ogni mattina ricevi il riepilogo degli aperti."]
            args.digest = True
        else:
            messages += notify.build_alerts(nuovi, oggi, cfg, warnings)
            warnings = []
    else:
        aperti = storage.load_latest()

    if warnings:
        messages += notify.build_alerts([], oggi, cfg, warnings)

    if args.digest:
        # i filtri si riapplicano: se hai cambiato config.yaml vale subito anche per i vecchi avvisi
        validi, _ = filters.prepara(aperti, cfg, oggi)
        messages += notify.build_digest(validi, oggi, cfg)

    lunedi = oggi.weekday() == 0 and state.get("esiti_digest") != oggi.isoformat()
    if args.esiti or (args.digest and lunedi):
        messages += notify.build_esiti(storage.load_esiti(oggi - timedelta(days=7)), cfg)
        state["esiti_digest"] = oggi.isoformat()

    if args.dry_run:
        for m in messages:
            print("─" * 40)
            print(m)
        print(f"[dry-run] {len(messages)} messaggi, niente inviato o salvato")
        return 0

    storage.write_errors(errors)
    storage.save_state(state, oggi)

    if messages:
        if not (os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")):
            annotate("warning", "Mancano i secret TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID: messaggi non inviati")
            for m in messages:
                print(m)
        else:
            notify.send(messages)
            annotate("notice", f"Inviati {len(messages)} messaggi Telegram")
    return 1 if tutti is None and state["failures"] >= FALLIMENTI_PRIMA_DI_AVVISARE else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--digest", action="store_true", help="invia il riepilogo degli avvisi aperti")
    ap.add_argument("--esiti", action="store_true", help="invia il riepilogo esiti degli ultimi 7 giorni")
    ap.add_argument("--dry-run", action="store_true", help="stampa i messaggi senza inviare né salvare")
    ap.add_argument("--oggi", help="data AAAA-MM-GG (per test)")
    args = ap.parse_args()
    oggi = date.fromisoformat(args.oggi) if args.oggi else date.today()
    return run(args, load_config(), oggi)


if __name__ == "__main__":
    sys.exit(main())
