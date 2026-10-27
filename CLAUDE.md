# gare-monitor

Monitor gratuito di avvisi di gara per servizi IT dalla piattaforma ANAC di pubblicità legale (PVL), con avvisi Telegram. Usato dall'utente come partita IVA nei servizi IT, forse da vendere ad altri in futuro. Tutto in italiano (messaggi, commenti, commit). Stessa architettura di `flight-monitor` (skill `monitor-prezzi-telegram`).

## Architettura

```
GitHub Actions (monitor.yml: 05:17 UTC con riepilogo, 11:17 e 15:17 UTC feriali; repo pubblico)
  monitor.py
    anac.py      GET /api/v0/avvisi-full-text-specializzata, CPV in gruppi da 12 -> list[Avviso]
    filters.py   regione (province.py, nome ente, NUTS/ISTAT), scarti (momento, scadenza, importo, parole), punteggio
    storage.py   data/state.json (anti-spam per idAvviso), latest.json (aperti), esiti.csv
    notify.py    messaggi: nuovi avvisi, riepilogo del mattino, esiti del lunedì
  -> commit di data/ su main
```

## Insidie

- L'API PVL non è documentata. Il campo `cpv` nella risposta è l'etichetta, non il codice: il filtro CPV si fa solo lato server.
- Struttura avviso: `templates[0].template.sections` con `SEZ. A` (soggetti_sa), `SEZ. B`, `SEZ. C` (items: cig, cpv, valore_complessivo_stimato, luogo_nuts/luogo_istat, aggiudicatari…). `normalizza()` ritorna None se manca.
- Luogo (verificato dal primo run reale, 27/10/2026): ANAC lo scrive come **nome di provincia** ("Verona", "Monza e della Brianza") oppure "ITALIA". `regione_di` usa `province.py`, poi il nome dell'ente ("COMUNE DI SALERNO"), poi NUTS/ISTAT se mai arrivassero.
- A volte il titolo è solo "Lotto 1": si usa la descrizione.
- Primo run: 58 avvisi in 3 giorni sui CPV IT, di cui 5 con tipologia sconosciuta (`momento altro`).
- Al primo avvio (`state.notified` vuoto) non si mandano centinaia di avvisi: un messaggio di benvenuto + riepilogo.
- I filtri si riapplicano nel riepilogo: cambiare `config.yaml` vale subito anche per gli avvisi già salvati.
- Il container di Claude non raggiunge ANAC: la verifica vera si fa lanciando il workflow e leggendo `data/last_errors.txt` e `data/latest.json`.

## Comandi
```bash
python -m pytest -q
python monitor.py --dry-run --digest
```
