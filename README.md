# SecretAI

Segretaria AI multiazienda con backend FastAPI e dashboard responsive. Progetto indipendente: nessun utilizzo di Supabase e nessuna modifica a FindMyInk.

## Stato verificabile

Questa versione consolida le fondamenta e una parte della segretaria testuale. **Non è un prodotto pronto al lancio.** Telefonia e Computer Use non sono implementati; i collegamenti reali ai provider e diversi flussi restano da collaudare. Vedi [stato e attività](docs/STATUS.md) e [progetto](docs/PROJECT.md).

Sono disponibili account con sessioni revocabili, cookie HttpOnly/CSRF, ruoli, audit, migrazioni, PostgreSQL, CRM, inbox, servizi/prezzi/orari, prenotazioni atomiche e idempotenti. L'AI propone prenotazioni che richiedono conferma esplicita. Google Calendar riceve scritture tramite outbox con verifica conflitti; Meta riceve webhook firmati e dispone di un adattatore di invio. Stripe dispone di Checkout, Portal, webhook e riconciliazione. Le prove automatiche dei provider usano risposte simulate e non certificano account reali.

## Avvio locale

Python 3.12, nessun account esterno necessario per agenda e dashboard.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock.txt
cp .env.example .env
uvicorn app.main:app --env-file .env --reload --no-access-log
```

Apri `http://localhost:8000`. In sviluppo le migrazioni SQLite sono automatiche; non sono inseriti utenti o aziende demo. Il login rimane disponibile dopo il refresh tramite cookie HttpOnly. La dashboard usa token CSRF per ogni scrittura.

Per l'AI occorre un server Ollama con modello compatibile con gli strumenti. Imposta `OLLAMA_URL` e `OLLAMA_MODEL`, poi esegui il worker in un processo distinto con lo stesso ambiente:

```bash
# Esporta le variabili del tuo ambiente con un gestore sicuro; non committare .env.
python -m app.worker
```

`uvicorn --env-file` carica `.env` soltanto nel processo API. Per il worker puoi usare Docker Compose, che lo carica in entrambi i processi.

## PostgreSQL e Docker

Configura `.env` con database dedicato, URL, password e chiave di cifratura. Poi:

```bash
docker compose up --build -d
# AI opzionale, dopo aver verificato risorse hardware e modello:
docker compose --profile ai up -d
docker compose exec ollama ollama pull qwen2.5:3b
```

La porta locale è `127.0.0.1:8000`. Il database non espone porte all'host. Il servizio `migrate` deve completare prima di API e worker. In produzione l'API rifiuta SQLite e schemi non aggiornati. HTTPS e go-live richiedono le verifiche descritte in [deployment](docs/DEPLOYMENT.md).

## Test

```bash
pip install -r requirements-dev.txt
python -m pytest -q
playwright install chromium
python scripts/smoke_browser.py
```

Per eseguire la suite su un database PostgreSQL di test dedicato:

```bash
# Imposta SECRET_AI_TEST_DATABASE_URL tramite il tuo gestore di ambiente.
python -m pytest -q
```

Ogni test riceve uno schema PostgreSQL separato. Non puntare questa variabile a un database di produzione. La CI include PostgreSQL 16, browser desktop/mobile e build Docker.

## Integrità e sicurezza operativa

Le operazioni di prenotazione serializzano le scritture per azienda. `Idempotency-Key` permette di ripetere una richiesta senza creare duplicati. Le relazioni servizio/cliente/appuntamento hanno vincoli di tenant nel database. La disponibilità locale non viene presentata come disponibilità globale se è collegato Google. Una prenotazione rimane in attesa finché il worker non completa l'evento esterno.

Non esiste una transazione distribuita con Google: un evento creato contemporaneamente da un'altra applicazione può richiedere riconciliazione umana. Un invio Meta dall'esito incerto non viene ripetuto automaticamente. Le istruzioni del modello non autorizzano scritture arbitrarie e il testo generato non viene usato come conferma di operazioni.

I token esterni sono cifrati con Fernet; sessioni e link monouso sono memorizzati come hash. Le chiavi e i backup vanno custoditi separatamente. `scripts/backup.py` produce backup cifrati e rifiuta il ripristino su database non vuoti. Prima del lancio vanno provati il restore PostgreSQL, i flussi live, i controlli di sicurezza e gli adempimenti commerciali/privacy.
