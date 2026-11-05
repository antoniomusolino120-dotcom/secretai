# Verifica del 5 novembre 2026

## Risultati eseguiti localmente

- Suite originaria prima delle modifiche: 6 test superati.
- Suite ampliata: 30 test superati su SQLite, comprendenti concorrenza, idempotenza, autenticazione, CSRF, ruoli, isolamento CRM/inbox/audit, vincoli tenant, orari, proposte AI, outbox, quote, reset password, firme webhook, adattatori Google/Meta/Stripe simulati, migrazione dati legacy e backup/restore cifrato.
- Chromium: flusso E2E superato su desktop 1440×1000 e mobile 390×844. Registrazione → azienda → servizio → appuntamento → refresh con sessione persistente → cancellazione → navigazione di tutte le sezioni. Nessun errore JavaScript o overflow orizzontale rilevato. Screenshot controllati visivamente.
- Controlli sintassi Python e JavaScript, `git diff --check`: superati.

## Risultati eseguiti su GitHub Actions

Codice verificato: `e339443bca76a8d6582d778f97cdf94e18a66cd5`.

- PostgreSQL 16: suite completa superata, con schema isolato per test. I test specifici di migrazione legacy e backup SQLite continuano a usare esplicitamente SQLite; il restore PostgreSQL non è ancora dimostrato.
- Suite SQLite: superata anche nel runner remoto.
- Chromium desktop/mobile: E2E superato anche nel runner remoto Ubuntu 24.04.
- Build Docker: superata. Il test non certifica un avvio pubblico o un ambiente di produzione.
- Durante il collaudo sono stati corretti il nome SQL riservato del rate limiter e il recupero degli ID tramite `RETURNING` per psycopg.

## Verifiche non ancora dimostrate
- Nessun test live con Google, Meta, Stripe, SIP o gestionale esterno.
- Nessun modello Ollama realmente avviato: i test AI verificano il contratto degli strumenti con un provider simulato.
- Restore PostgreSQL, carico, review sicurezza indipendente, privacy e operatività commerciale ancora da completare.

La verifica non certifica il prodotto completo. Telefonia, Computer Use, OAuth Meta self-service e sincronizzazione Google bidirezionale richiedono ancora sviluppo.
