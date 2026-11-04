# SecretAI

Segretaria AI multicanale — foundation MVP.

## Stato
Prima versione eseguibile **in locale**: dashboard web, registrazione e login, sessioni revocabili, aziende isolate per utente, servizi, appuntamenti, chat AI tramite Ollama (con fallback esplicito quando non disponibile). Google Calendar, telefonia, WhatsApp, Instagram e browser teaching **non sono ancora integrati**.

> Repository attualmente pubblico: non caricare credenziali, token o dati reali di clienti.

## Avvio
Richiede Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Apri http://localhost:8000

Per abilitare l'AI locale: installa Ollama, esegui `ollama pull qwen2.5:3b` e avvia Ollama. Imposta `OLLAMA_MODEL` per scegliere un modello diverso.

## Sicurezza
Questa build è **solo sviluppo locale**, con autenticazione locale di base ma senza rate limiting, verifica email, recupero password, MFA, OAuth o audit completo. Non esporla pubblicamente e non usarla con dati personali reali. Il database SQLite è locale. Prima della produzione servono autenticazione, tenant isolation, consenso/privacy, controlli prenotazioni e integrazioni verificate.

## Roadmap
1. Supabase Auth, Postgres e RLS multi-tenant.
2. Google Calendar OAuth, free/busy e booking idempotente.
3. WhatsApp e Instagram tramite API Meta autorizzate.
4. Telefonia SIP e voice worker.
5. Computer Use con teaching e sessioni isolate.
6. Stripe, audit, rate limit, test end-to-end.

## Accesso locale
Apri la dashboard, registra un account con password di almeno 12 caratteri e crea la tua azienda. I token restano solo nella memoria della scheda browser (nuovo login al refresh). I dati esistenti delle precedenti versioni non sono assegnati automaticamente a nessun account. Non utilizzare questo sistema in produzione senza ulteriori misure di sicurezza.
