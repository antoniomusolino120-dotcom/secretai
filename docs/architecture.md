# Architettura attuale

`app.main` espone API e dashboard. `app.db` gestisce connessioni SQLAlchemy e transazioni; le modifiche di schema vivono in migrazioni Alembic. SQLite è soltanto un'opzione locale, PostgreSQL è obbligatorio in produzione. Tutto appartiene esclusivamente a SecretAI.

`auth` gestisce identità, ruoli e sessioni; `workspace` contiene azienda, catalogo, CRM, inbox e audit. `booking` è l'unico punto di creazione degli appuntamenti per API e AI. Le scritture prendono un lock sull'azienda e le relazioni usano vincoli tenant nel database. `assistant` interpreta le intenzioni tramite Ollama e produce risposte operative deterministiche dagli strumenti: la scrittura richiede una proposta e conferma esplicita.

`jobs` è una transactional outbox nel database: la prenotazione e l'operazione esterna vengono salvate nella stessa transazione. `worker` esegue i lavori separatamente dall'API. Gli adattatori `google_calendar`/`google_sync`, `meta_channels` e `billing` gestiscono provider, token, errori e deduplica. Gli effetti non idempotenti dall'esito incerto richiedono verifica umana.

Non esiste ancora un motore telefonico o un runner di Computer Use. Non esiste ancora sincronizzazione Google bidirezionale completa. Lo stato dettagliato è in `STATUS.md`.
