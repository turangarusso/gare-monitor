"""Messaggi Telegram (HTML), spezzati sotto il limite di 4096 caratteri."""

from __future__ import annotations

import html
import os
from datetime import date

import requests

from models import Avviso

MAX_LEN = 3900
MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]

TITOLI = {
    "manifestazione": "🙋 <b>Manifestazioni d'interesse</b> (candidati per essere invitato)",
    "preavviso": "📣 <b>Preavvisi</b> (gare in arrivo)",
    "gara": "📄 <b>Gare aperte</b>",
}
ORDINE = ["manifestazione", "gara", "preavviso"]


def e(text) -> str:
    return html.escape(str(text or ""), quote=True)


def euro(v: float | None) -> str:
    if v is None:
        return "importo n.d."
    return f"{v:,.0f} €".replace(",", ".")


def data_it(iso: str | None) -> str:
    if not iso:
        return "?"
    y, m, d = iso.split("-")
    return f"{int(d)} {MESI[int(m) - 1]}"


def scadenza(av: Avviso, oggi: date, vicina: int = 3) -> str:
    if not av.scadenza:
        return "scadenza n.d."
    giorni = (date.fromisoformat(av.scadenza) - oggi).days
    quando = "oggi" if giorni == 0 else "domani" if giorni == 1 else f"tra {giorni} g"
    icona = "⏰" if giorni <= vicina else "⏳"
    return f"{icona} scade {data_it(av.scadenza)} ({quando})"


def scheda(av: Avviso, oggi: date, prioritarie: list[str], vicina: int = 3) -> str:
    star = " ⭐" if av.regione and av.regione in prioritarie else ""
    where = " · ".join(x for x in [e(av.ente), f"📍 {e(av.regione)}" if av.regione else ""] if x)
    links = [f'<a href="{e(av.url)}">Scheda ANAC</a>']
    if av.link_gara:
        links.append(f'<a href="{e(av.link_gara)}">Documenti</a>')
    lines = [f"• <b>{e(av.titolo)}</b>{star}"]
    if where:
        lines.append(f"   🏛 {where}")
    lines.append(f"   💶 {euro(av.valore)} · {scadenza(av, oggi, vicina)}")
    if av.categorie:
        lines.append(f"   🏷 {e(av.categorie[0])}")
    lines.append("   " + " · ".join(links))
    return "\n".join(lines)


def split(lines: list[str]) -> list[str]:
    messages, cur = [], ""
    for line in lines:
        if len(cur) + len(line) + 1 > MAX_LEN and cur.strip():
            messages.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        messages.append(cur)
    return messages


def _sezioni(avvisi: list[Avviso], oggi: date, cfg: dict) -> list[str]:
    prioritarie = cfg.get("regioni_prioritarie") or []
    vicina = (cfg.get("riepilogo") or {}).get("giorni_scadenza_vicina", 3)
    lines = []
    for momento in ORDINE:
        gruppo = [a for a in avvisi if a.momento == momento]
        if not gruppo:
            continue
        lines += ["", TITOLI[momento]]
        for av in gruppo:
            lines += ["", scheda(av, oggi, prioritarie, vicina)]
    return lines


def build_alerts(nuovi: list[Avviso], oggi: date, cfg: dict, warnings: list[str]) -> list[str]:
    lines = []
    if nuovi:
        n = len(nuovi)
        lines.append(f"🆕 <b>{n} nuov{'o avviso' if n == 1 else 'i avvisi'} IT</b>")
        lines += _sezioni(nuovi, oggi, cfg)
    if warnings:
        lines += [""] + [f"⚠️ {e(w)}" for w in warnings]
    return split(lines) if lines else []


def build_digest(aperti: list[Avviso], oggi: date, cfg: dict) -> list[str]:
    limite = (cfg.get("riepilogo") or {}).get("max_elementi", 25)
    if not aperti:
        return ["☀️ Nessun avviso IT aperto che rispetti i tuoi filtri. Il monitor gira: ricontrolla i filtri in config.yaml se ti sembra strano."]
    # nel riepilogo contano le scadenze: prima quelle vicine
    mostrati = sorted(aperti, key=lambda a: (a.scadenza or "9999", -a.punteggio))[:limite]
    lines = [f"☀️ <b>Riepilogo: {len(aperti)} avvisi IT aperti</b>"]
    lines += _sezioni(mostrati, oggi, cfg)
    if len(aperti) > limite:
        lines += ["", f"…e altri {len(aperti) - limite} (vedi data/latest.json)"]
    return split(lines)


def build_esiti(esiti: list[dict], cfg: dict) -> list[str]:
    ecfg = cfg.get("esiti_lunedi") or {}
    if ecfg.get("solo_regioni_prioritarie", True):
        prioritarie = cfg.get("regioni_prioritarie") or []
        esiti = [r for r in esiti if r.get("regione") in prioritarie]
    if not esiti:
        return []
    limite = ecfg.get("max_elementi", 20)

    def importo(r):
        try:
            return float(r.get("valore_aggiudicato") or r.get("valore") or 0)
        except ValueError:
            return 0.0

    esiti = sorted(esiti, key=importo, reverse=True)
    lines = [f"📊 <b>Chi ha comprato IT questa settimana</b> ({len(esiti)} esit{'o' if len(esiti) == 1 else 'i'})",
             "Enti da contattare e albi fornitori a cui iscriversi."]
    for r in esiti[:limite]:
        vinto = r.get("aggiudicatari") or "aggiudicatario n.d."
        lines += ["",
                  f"• <b>{e(r['ente'] or '?')}</b> · {e(r.get('regione'))}",
                  f"   {e(r['titolo'][:160])}",
                  f"   🏆 {e(vinto)} · {euro(importo(r) or None)} · "
                  f'<a href="{e(r["url"])}">Esito</a>']
    if len(esiti) > limite:
        lines += ["", f"…e altri {len(esiti) - limite} in data/esiti.csv"]
    return split(lines)


def send(messages: list[str]) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    for text in messages:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=30,
        )
        r.raise_for_status()
