# Stato di avanzamento

Questa versione non soddisfa ancora il criterio di completamento commerciale. Lo stato distingue codice presente, prove automatiche e verifica reale. Le approvazioni esterne non sono l'unica attività residua: restano anche attività di sviluppo autonome.

| Area | Implementato in questa versione | Residuo autonomo / prova necessaria |
| --- | --- | --- |
| Backend/database | PostgreSQL/SQLite, migrazioni Alembic, transazioni, vincoli tenant e indici | Eseguire e verificare CI PostgreSQL e build Docker; procedura di import da SQLite a PostgreSQL |
| Identità | Login/registrazione, email production, recupero, sessioni revocabili, cookie HttpOnly, CSRF, ruoli, rate limit persistente | Revisione sicurezza indipendente, MFA amministrativa e gestione inviti/team |
| Dashboard | Panoramica, CRM, inbox, agenda, servizi, istruzioni/orari, collegamenti, abbonamento, audit/coda | Collaudo browser desktop/mobile; accessibilità e ulteriori flussi di modifica |
| Prenotazioni | Concorrenza, disponibilità locale, orari/fusi, idempotenza, spostamento e cancellazione, audit | Identificazione cliente per modifiche via canali, più risorse/personale e riconciliazione dei conflitti esterni |
| AI | Ollama come interprete di strumenti; informazioni/servizi, disponibilità, proposta e conferma esplicita, handoff | Test con un modello realmente avviato; conversazione più naturale, modifiche/cancellazioni autonome e valutazioni sistematiche |
| Google | OAuth con stato monouso e PKCE, token cifrato/rinnovo, selezione calendari, freebusy, scrittura/modifica/cancellazione outbox | Sincronizzazione bidirezionale incrementale, webhook di cambiamento, controlli aggiuntivi su modifiche esterne; test live con calendario autorizzato |
| Meta | Webhook firmato, deduplica, inbox unificata, collegamento assistito con verifica ID/token, invio ufficiale in coda, scadenza token/finestra messaggi | Collegamento OAuth/Embedded Signup self-service, rinnovo/revoca avanzati, ricevute di consegna, test live e approvazioni Meta |
| Telefonia | Non implementata | Motore SIP/Asterisk, audio realtime, Whisper/Piper, barge-in, trasferimenti, persistenza, recupero errori e collaudo reale |
| Computer Use | Non implementato | Recorder, dimostrazioni, procedure versionate, runner Playwright isolato, sessioni/credenziali, verifica/recupero e test su gestionale |
| Abbonamenti | Checkout/Portal, webhook firmati e deduplica, riconciliazione stato corrente, rinnovi/cancellazioni via Stripe, consumi atomici | Test sandbox di rinnovo, insoluto, downgrade e rischio; riconciliazione periodica; prezzi e trattamento fiscale da validare |
| Operazioni | API/worker separati, outbox con lease/retry, log senza payload, healthcheck, Compose/Caddy, backup cifrato/restore su target vuoto | Restore PostgreSQL dimostrato, monitoraggio/alert e heartbeat worker, retention/export/cancellazione dati, staging reale e carico |

## Prove

- La suite originaria conteneva 6 test: tutti superati prima delle modifiche.
- La nuova suite include sicurezza, concorrenza, CRM/inbox, conferma AI, outbox, consumi e adattatori simulati.
- I risultati effettivi dell'ultima esecuzione sono riportati in `VERIFICATION.md`.
- Nessun account reale Google, Meta, Stripe, SIP o gestionale è stato usato.

## Passi successivi

1. Completare le verifiche PostgreSQL/browser/container e correggere quanto emerge.
2. Completare gli elementi testuali ancora mancanti senza credenziali.
3. Sviluppare telefonia e Computer Use, poi eseguire i collaudi autorizzati.
4. Preparare staging e collaudo live quando disponibili account, accessi e scelte commerciali.
