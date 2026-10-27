# 🏛 Monitor gare IT

Controlla in automatico la piattaforma di pubblicità legale di **ANAC** (dove dal 2024 per legge passa ogni bando pubblico italiano) e ti avvisa su Telegram quando esce un avviso di **servizi informatici o software**:

- 🙋 **Manifestazioni d'interesse** sotto soglia: l'ente cerca operatori da invitare. È il momento migliore per una partita IVA, perché la concorrenza è bassa.
- 📄 **Gare aperte**
- 📣 **Preavvisi** di gare in arrivo

Ogni mattina arriva un **riepilogo** di tutti gli avvisi ancora aperti, ordinati per scadenza (⏰ se scadono entro 3 giorni). Il **lunedì** arriva anche l'elenco di **chi ha comprato servizi IT** in Campania la settimana prima: enti da contattare e albi fornitori a cui iscriversi.

Gli avvisi in **Campania** sono segnati con ⭐ e messi in cima. Gira gratis su GitHub Actions 3 volte al giorno nei feriali.

## Setup (5 minuti)

1. **Bot Telegram dedicato** (separato da quello del monitor voli): `@BotFather` → `/newbot` → copia il token. Scrivi "ciao" al nuovo bot, poi apri `https://api.telegram.org/bot<TOKEN>/getUpdates` e copia `"chat":{"id": ...}`.
2. **Repo GitHub pubblico** (minuti di Actions illimitati), per esempio `gare-monitor`, con questi file.
3. *Settings → Secrets and variables → Actions → New repository secret*: `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.
4. **Test**: tab *Actions → Monitor gare → Run workflow*. Al primo avvio ricevi "Monitor gare IT attivo" e il riepilogo; da lì in poi solo gli avvisi nuovi.

## Personalizzare (`config.yaml`)

| Voce | Cosa fa |
|---|---|
| `cpv` | Categorie cercate (72 servizi informatici, 48 software). |
| `solo_regioni` | Vuoto = tutta Italia. `[Campania]` = solo Campania. |
| `regioni_prioritarie` | Messe in cima con ⭐ e usate per gli esiti del lunedì. |
| `valore_max` | Tetto all'importo (default 250.000 €: oltre servono di solito requisiti di fatturato). |
| `escludi` | Parole che scartano un avviso (toner, stampanti, noleggio…). |
| `interesse` | Parole che lo fanno salire in classifica (sviluppo, portale, cloud…). |
| `momenti_avviso` | Quali tipi notificare. |

## Dati (`data/`, aggiornati dal workflow)

- `latest.json`: avvisi aperti che rispettano i filtri.
- `esiti.csv`: tutti gli esiti IT trovati (ente, oggetto, chi ha vinto, importo). Aprilo con Excel: è la tua lista di potenziali clienti.
- `state.json`: avvisi già notificati (anti-spam).
- `last_errors.txt`: cosa è successo nell'ultimo run. **Il primo posto da guardare se qualcosa non va.**

## Limiti da sapere

- L'API di ANAC **non è documentata**: è quella che usa il portale stesso. Se ANAC la cambia, il monitor smette di trovare avvisi e dopo 2 run falliti ti avvisa su Telegram.
- Gli **affidamenti diretti** (sotto 140.000 € per i servizi) non hanno bando: li vedi solo dopo, negli esiti. Per riceverli devi essere iscritto agli albi fornitori e al MePA degli enti.
- Il campo luogo di ANAC non è sempre compilato: alcuni avvisi arrivano senza regione (non hanno la ⭐ anche se sono in Campania).

## Comandi

```bash
pip install -r requirements.txt
python -m pytest -q                    # test
python monitor.py --dry-run --digest   # stampa i messaggi, non invia e non salva
python monitor.py --esiti              # forza il riepilogo esiti
```
