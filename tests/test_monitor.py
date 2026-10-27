"""Test sulla fixture tests/fixtures/pvl_page.json (struttura reale PVL, dati inventati)."""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import anac  # noqa: E402
import filters  # noqa: E402
import monitor  # noqa: E402
import notify  # noqa: E402
import storage  # noqa: E402

OGGI = date(2026, 10, 27)   # martedì
LUNEDI = date(2026, 11, 2)
PAGE = json.loads((ROOT / "tests/fixtures/pvl_page.json").read_text("utf-8"))


@pytest.fixture
def cfg():
    return monitor.load_config()


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    """Ogni test scrive in una cartella data/ temporanea."""
    monkeypatch.setattr(storage, "DATA", tmp_path)
    for name, file in [("STATE", "state.json"), ("LATEST", "latest.json"),
                       ("ESITI", "esiti.csv"), ("ERRORS", "last_errors.txt")]:
        monkeypatch.setattr(storage, name, tmp_path / file)
    return tmp_path


@pytest.fixture
def api(monkeypatch):
    calls = []

    def fake_get(params, session):
        calls.append(params)
        return PAGE if params["page"] == 0 else {"content": [], "count": PAGE["count"]}

    monkeypatch.setattr(anac, "_get", fake_get)
    monkeypatch.setattr(anac, "PAUSA", 0)
    return calls


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(notify, "send", lambda msgs: out.extend(msgs))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    return out


def args(**kw):
    return Namespace(**{"digest": False, "esiti": False, "dry_run": False, **kw})


def by_id(avvisi):
    return {a.id: a for a in avvisi}


# --- normalizzazione -------------------------------------------------------

def test_normalizza_campi():
    a = by_id(filter(None, map(anac.normalizza, PAGE["content"])))
    assert "rotto" not in a
    m = a["a1"]
    assert m.momento == "manifestazione"
    assert m.ente == "COMUNE DI POZZUOLI"
    assert m.valore == 39000
    assert m.scadenza == "2026-11-12"
    assert m.luogo == "ITF33"
    assert m.url.endswith("/avvisi/a1")
    assert a["a2"].url.endswith("/bandi/a2")
    esito = a["a4"]
    assert esito.momento == "esito"
    assert esito.valore_aggiudicato == 52800.5
    assert esito.aggiudicatari[0]["nome"] == "ROSSI INFORMATICA SRL"
    assert a["a5"].luogo == "063021"


def test_titolo_solo_lotto():
    raw = json.loads(json.dumps(PAGE["content"][1]))
    raw["templates"][0]["template"]["metadata"]["titolo"] = "Lotto 1"
    av = anac.normalizza(raw)
    assert av.titolo.startswith("Procedura aperta per servizi di gestione")
    assert av.titolo.endswith("(Lotto 1)")


def test_fetch_parametri_e_gruppi(api, cfg):
    avvisi = anac.fetch(cfg, OGGI, log=lambda *_: None)
    assert len(avvisi) == 7                      # deduplicati tra i gruppi CPV
    assert len(api) == 2                         # 19 prefissi -> 2 gruppi da 12
    p = api[0]
    assert p["dataPubblicazioneStart"] == "24/10/2026"
    assert p["dataPubblicazioneEnd"] == "27/10/2026"
    assert p["cpv"].startswith("480,482")


# --- filtri ----------------------------------------------------------------

@pytest.mark.parametrize("luogo,ente,atteso", [
    ("ITF33", None, "Campania"),
    ("ITC4C", None, "Lombardia"),
    ("063021", None, "Campania"),
    (None, "Comune di Benevento", "Campania"),
    (None, "Comune di Bologna", "Emilia-Romagna"),
    # formati visti nel primo run reale
    ("Verona", None, "Veneto"),
    ("Monza e della Brianza", None, "Lombardia"),
    ("Roma", None, "Lazio"),
    ("ITALIA", "COMUNE DI SALERNO", "Campania"),
    ("ITALIA", "INARCASSA CASSA NAZIONALE DI PREVIDENZA", None),
    ("ITALIA", "AZIENDA USL DELLA ROMAGNA", None),
    ("ITALIA", "REGIONE CAMPANIA", "Campania"),
])
def test_regione(luogo, ente, atteso):
    av = anac.normalizza(PAGE["content"][0])
    av.luogo, av.ente = luogo, ente
    assert filters.regione_di(av) == atteso


def test_filtri(cfg):
    avvisi = list(filter(None, map(anac.normalizza, PAGE["content"])))
    tenuti, scarti = filters.prepara(avvisi, cfg, OGGI)
    ids = [a.id for a in tenuti]
    assert set(ids) == {"a1", "a5", "a7"}
    assert scarti == {"importo alto": 1, "esclusa": 1, "momento esito": 1, "scaduto": 1}
    # Campania + parole d'interesse in cima
    assert ids[0] == "a1"
    assert by_id(tenuti)["a1"].punteggio > by_id(tenuti)["a7"].punteggio


def test_solo_regioni(cfg):
    cfg["solo_regioni"] = ["Campania"]
    avvisi = list(filter(None, map(anac.normalizza, PAGE["content"])))
    tenuti, _ = filters.prepara(avvisi, cfg, OGGI)
    assert {a.id for a in tenuti} == {"a1", "a5"}


def test_app_non_prende_appalto(cfg):
    av = anac.normalizza(PAGE["content"][6])
    av.titolo = av.descrizione = "Appalto di servizi informatici"
    av.categorie = []
    assert filters.punteggio(av, cfg) == 0


# --- run completo ----------------------------------------------------------

def test_primo_avvio_manda_riepilogo_non_valanga(api, sent, cfg, tmp_data):
    assert monitor.run(args(), cfg, OGGI) == 0
    assert "Monitor gare IT attivo" in sent[0]
    assert "Riepilogo: 3 avvisi IT aperti" in sent[1]
    assert (tmp_data / "esiti.csv").exists()
    assert "Nessun errore" not in (tmp_data / "last_errors.txt").read_text()


def test_secondo_run_niente_duplicati(api, sent, cfg):
    monitor.run(args(), cfg, OGGI)
    sent.clear()
    monitor.run(args(), cfg, OGGI)
    assert sent == []


def test_nuovo_avviso_notificato(api, sent, cfg, monkeypatch):
    monitor.run(args(), cfg, OGGI)
    sent.clear()
    nuovo = json.loads(json.dumps(PAGE["content"][0]))
    nuovo["idAvviso"] = "a99"
    page2 = {"content": PAGE["content"] + [nuovo], "count": 9}
    monkeypatch.setattr(anac, "_get", lambda p, s: page2 if p["page"] == 0 else {"content": []})
    monitor.run(args(), cfg, OGGI)
    assert len(sent) == 1
    assert "1 nuovo avviso IT" in sent[0]
    assert "Manifestazioni d'interesse" in sent[0]
    assert "⭐" in sent[0]                        # Campania
    assert "/avvisi/a99" in sent[0]


def test_anac_giu_non_blocca_il_riepilogo(api, sent, cfg, monkeypatch, tmp_data):
    monitor.run(args(), cfg, OGGI)
    sent.clear()

    def boom(p, s):
        raise RuntimeError("503")

    monkeypatch.setattr(anac, "_get", boom)
    assert monitor.run(args(digest=True), cfg, OGGI) == 0        # primo fallimento: silenzio
    assert "Riepilogo" in sent[0] and "⚠️" not in "".join(sent)
    sent.clear()
    assert monitor.run(args(), cfg, OGGI) == 1                   # secondo: avviso
    assert "ANAC non risponde da 2 run" in sent[0]
    assert "503" in (tmp_data / "last_errors.txt").read_text()


def test_avvisi_restano_nel_riepilogo_finche_aperti(api, sent, cfg, monkeypatch):
    monitor.run(args(), cfg, OGGI)
    monkeypatch.setattr(anac, "_get", lambda p, s: {"content": [], "count": 0})
    sent.clear()
    monitor.run(args(digest=True), cfg, date(2026, 10, 30))
    testo = "".join(sent)
    assert "Pozzuoli".upper() in testo                        # scade il 12/11: c'è ancora
    assert "PERUGIA" not in testo                             # scaduto il 29/10


def test_esiti_del_lunedi(api, sent, cfg):
    monitor.run(args(), cfg, OGGI)
    sent.clear()
    monitor.run(args(digest=True), cfg, LUNEDI)
    testo = "".join(sent)
    assert "Chi ha comprato IT" in testo
    assert "ROSSI INFORMATICA SRL" in testo
    assert "52.800 €" in testo
    sent.clear()
    monitor.run(args(digest=True), cfg, LUNEDI)               # una volta sola al giorno
    assert "Chi ha comprato IT" not in "".join(sent)


def test_dry_run_non_salva(api, cfg, tmp_data, capsys):
    monitor.run(args(dry_run=True, digest=True), cfg, OGGI)
    assert not (tmp_data / "state.json").exists()
    assert "dry-run" in capsys.readouterr().out


def test_messaggi_sotto_il_limite(cfg):
    avvisi = list(filter(None, map(anac.normalizza, PAGE["content"]))) * 40
    for i, a in enumerate(avvisi):
        a.id = str(i)
    msgs = notify.build_alerts([a for a in avvisi if a.momento != "esito"], OGGI, cfg, [])
    assert len(msgs) > 1
    assert all(len(m) <= 4096 for m in msgs)


def test_html_escape(cfg):
    av = anac.normalizza(PAGE["content"][0])
    av.titolo = "Sviluppo <app> & sito"
    txt = notify.scheda(av, OGGI, [])
    assert "&lt;app&gt; &amp; sito" in txt
