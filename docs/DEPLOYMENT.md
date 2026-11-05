# Deployment e operazioni

## Ambienti

Sviluppo e staging devono usare database, chiavi, app OAuth/Meta e sandbox Stripe dedicati. Non utilizzare dati reali finché i requisiti di rilascio non sono verificati. Non usare Supabase e non collegare servizi appartenenti a FindMyInk.

Il Compose incluso prepara database PostgreSQL, migrazioni, API e worker. Il profilo `ai` aggiunge Ollama; il profilo `https` aggiunge Caddy. Prima dell'uso pubblico occorrono dominio, DNS, HTTPS e le verifiche di rilascio. Le immagini base devono essere aggiornate e ricollaudate nella pipeline prima del lancio.

La produzione richiede `SECRET_AI_ENV=production`, URL pubblico HTTPS, chiave di cifratura custodita, SMTP e credenziali esterne autorizzate. Il database deve essere già migrato (`alembic upgrade head`); il processo API non esegue DDL in produzione. Le sessioni browser usano cookie Secure. Caddy limita il body a 1 MB, termina HTTPS e inoltra l'IP; Uvicorn si fida solo dell'indirizzo Caddy configurato nel network Compose. Non abilitare access log che contengano query OAuth, token o contenuti personali.

## Backup e restore

```bash
# Nel container API; il file va copiato su storage separato e protetto.
python scripts/backup.py backup /percorso/secretai.backup.fernet
# Su un ambiente distinto con database completamente vuoto:
python scripts/backup.py restore /percorso/secretai.backup.fernet
```

Servono `pg_dump`/`pg_restore` per PostgreSQL; sono inclusi nell'immagine Docker. Le credenziali vengono trasmesse via ambiente, mai come argomenti della command line. I backup sono cifrati con la chiave Fernet dell'ambiente, che va conservata separatamente. Il comando rifiuta backup sovrascritti e restore su database non vuoti. Per database grandi occorre sostituire la cifratura in memoria con una soluzione streaming prima di usarlo su grandi volumi.

Definire frequenza, conservazione, storage fuori host e RPO/RTO con il titolare. Un backup non è considerato affidabile finché un restore isolato non è stato provato e confrontato.

## Monitoraggio

`/health/live` misura il processo; `/health/ready` verifica il database. La dashboard Attività mostra job falliti/in attesa e audit senza contenuti delle conversazioni. Sono ancora da implementare heartbeat worker, alert esterni, metriche di latenza provider e monitoraggio di restore/retention. Un worker fermo può lasciare le prenotazioni correttamente in attesa senza completarle.

## Rollback

Il cambiamento applicativo va mantenuto in un commit reversibile. Prima di migrazioni in produzione, creare un backup e verificarlo in staging. Le migrazioni rifiutano downgrade distruttivi: il rollback completo del database avviene su un target vuoto dal backup verificato. Un semplice revert del codice non annulla lo schema o le operazioni già eseguite sui provider.

## Gate di lancio

Flussi live positivi per conversazione, prenotazione, pagamento, telefonia, Meta, Google e gestionale; gestione conflitti, retry e revoche; test tenant negativi e carico; revisione sicurezza; restore dimostrato; approvazioni commerciali, privacy e fornitori. I risultati simulati non sostituiscono questi gate.
