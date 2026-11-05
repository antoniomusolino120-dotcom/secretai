# Deployment e operazioni

## Ambienti

Sviluppo e staging devono usare database, chiavi, app OAuth/Meta e sandbox Stripe dedicati. Non utilizzare dati reali finché i requisiti di rilascio non sono verificati. Non usare Supabase e non collegare servizi appartenenti a FindMyInk.

Il Compose incluso prepara database PostgreSQL, migrazioni, API e worker. Il profilo `ai` aggiunge Ollama; il profilo `https` aggiunge Caddy. Prima dell'uso pubblico occorrono dominio, DNS, HTTPS e le verifiche di rilascio. Le immagini base devono essere aggiornate e ricollaudate nella pipeline prima del lancio.

La produzione richiede `SECRET_AI_ENV=production`, URL pubblico HTTPS, chiave di cifratura custodita, SMTP e credenziali esterne autorizzate. Il database deve essere già migrato (`alembic upgrade head`); il processo API non esegue DDL in produzione. Le sessioni browser usano cookie Secure. Caddy limita il body a 1 MB, termina HTTPS e inoltra l'IP; Uvicorn si fida solo dell'indirizzo Caddy configurato nel network Compose. Non abilitare access log che contengano query OAuth, token o contenuti personali.

## Avvio su Vercel

Vercel non deve usare il database SQLite locale del repository o un database temporaneo in `/tmp`. Il deployment del 5 novembre falliva con `sqlite3.OperationalError: unable to open database file` durante `PRAGMA journal_mode=WAL`, prima di poter servire anche i file statici. Il progetto non aveva variabili d’ambiente né database collegati.

Il runtime Vercel avvia la connessione soltanto quando serve alle API. Legge `SECRET_AI_DATABASE_URL` oppure, sul solo Vercel, `DATABASE_URL` o `POSTGRES_URL` forniti dall’integrazione del database dedicato. SQLite è rifiutato sul serverless. Le dipendenze installate da `requirements.txt` usano lo stesso lock verificato nei container.

Con database mancante o non raggiungibile, la pagina e gli asset rimangono disponibili; `/health/ready` e le operazioni dipendenti dal database restituiscono 503. La dashboard mostra l’errore di configurazione prima del login. Non vengono creati account o appuntamenti in una memoria temporanea. `/health/live` certifica soltanto il processo.

Nei collaudi non in modalità produzione, gli avvii simultanei serializzano le migrazioni con un advisory lock PostgreSQL. In modalità `SECRET_AI_ENV=production` restano necessari schema già migrato, SMTP, chiave di cifratura e configurazione completa: non vengono disattivate le verifiche di produzione.

Su Vercel i cookie sono Secure anche durante il collaudo. L’origine autorizzata deriva da `SECRET_AI_PUBLIC_URL` o dai metadati Vercel del deployment; non da header inoltrati dal client. Production e Preview devono avere database distinti. Dopo il collegamento del database serve un nuovo deployment con le variabili aggiornate.

La correzione applicativa da sola non rende operativo un progetto privo di database. La creazione di una risorsa esterna richiede l’accettazione autorizzata delle condizioni del fornitore e la verifica del piano prima della conferma. Non utilizzare risorse di FindMyInk.

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

`/health/live` misura il processo; `/health/ready` verifica il database. La dashboard Attività mostra job falliti/in attesa e audit senza contenuti delle conversazioni. Heartbeat per worker, browser e voce, riconciliazione e retention configurabile sono implementati. Il runbook descrive i runtime aggiuntivi e la verifica backup/restore PostgreSQL in CI. Collegare i controlli health e le segnalazioni al monitoraggio dell’hosting autorizzato; un worker fermo lascia le prenotazioni in attesa senza confermarle falsamente.

## Rollback

Il cambiamento applicativo va mantenuto in un commit reversibile. Prima di migrazioni in produzione, creare un backup e verificarlo in staging. Le migrazioni rifiutano downgrade distruttivi: il rollback completo del database avviene su un target vuoto dal backup verificato. Un semplice revert del codice non annulla lo schema o le operazioni già eseguite sui provider.

## Gate di lancio

Flussi live positivi per conversazione, prenotazione, pagamento, telefonia, Meta, Google e gestionale; gestione conflitti, retry e revoche; test tenant negativi e carico; revisione sicurezza; restore dimostrato; approvazioni commerciali, privacy e fornitori. I risultati simulati non sostituiscono questi gate.
