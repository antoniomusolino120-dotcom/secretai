# SecretAI — integrazione e accettazione

## 1. Ambiente dedicato

Usare esclusivamente risorse SecretAI. Compilare `.env` dai nomi in `.env.example`: database PostgreSQL indipendente, chiave Fernet, token interno casuale di almeno 32 caratteri, URL pubblico e SMTP. Credenziali e file `.runtime/` non vanno committati.

```bash
# Backend, database, browser, motori vocali e modello AI locale:
docker compose -f compose.yaml -f compose.integrations.yaml \
  --profile integrations --profile ai up --build -d
```

I servizi `migrate`, `voice-models` e `ollama-models` devono terminare positivamente. I modelli pubblici vengono scaricati automaticamente; Whisper/Piper non richiedono un account cloud. Il controllo `prepare_ai.py` verifica anche una chiamata a uno strumento del modello. Il primo download richiede spazio e tempo. Per usare Ollama su un altro host, configurare `SECRET_AI_OLLAMA_DOCKER_URL` e non avviare il profilo `ai`.

Per HTTPS aggiungere `--profile https` dopo aver impostato DNS, `SECRET_AI_DOMAIN`, `SECRET_AI_PUBLIC_URL=https://...` e `SECRET_AI_ENV=production`. Browser, voice e database non devono esporre porte pubbliche. Il token interno serve soltanto ai servizi; non è una credenziale per i clienti.

Verifiche:

```bash
docker compose -f compose.yaml -f compose.integrations.yaml ps
docker compose exec api python scripts/check_integrations.py
```

`/health/ready` verifica il database; `GET /api/operations/health?organization_id=...` mostra heartbeat e job sospesi al proprietario autenticato. Un campo `live_verified=false` è intenzionale fino al collaudo con il relativo account.

## 2. Google Calendar

Configurare client OAuth Web e redirect `https://DOMINIO/api/google/callback`, Calendar API e consenso. Dalla dashboard Collegamenti usare “Collega Google”, poi scegliere calendario di scrittura e calendari da consultare. Le notifiche usano `https://DOMINIO/api/google/notifications`; rinnovo watch e polling di recupero sono nel worker.

Accettazione: leggere uno slot; creare, spostare e cancellare; verificare una modifica eseguita direttamente in Google; verificare due richieste simultanee, revoca/rinnovo token, calendari multipli e ora legale. Una scrittura non verificata deve restare in attesa. Durante uno spostamento esterno l’orario precedente resta riservato fino all’esito.

## 3. WhatsApp e Instagram

Configurare app, versione Graph, segreto, verify token e webhook `https://DOMINIO/api/meta/webhook`. Per WhatsApp configurare `META_APP_ID` e `META_WHATSAPP_CONFIG_ID` della configurazione Embedded Signup autorizzata. `META_SIGNUP_EXTRAS_JSON` consente di applicare le opzioni previste dalla configurazione Meta corrente senza modificare il flusso. Per Instagram configurare ID/segreto app nativi e redirect `https://DOMINIO/api/meta/oauth/instagram/callback`.

La revoca usa `/api/meta/deauthorize/whatsapp` o `/api/meta/deauthorize/instagram` e verifica la richiesta firmata con il segreto della relativa app. Configurare i permessi e le subscription previsti dall’app; completare eventuale App Review e verifiche aziendali Meta.

Dalla dashboard il cliente avvia il collegamento ufficiale. Il backend verifica il numero dentro il WABA concesso; un ID dichiarato dal browser non è sufficiente. Per un nuovo numero, il PIN di registrazione viene richiesto durante il collegamento. I token restano cifrati lato server.

Accettazione: messaggio entrante, risposta, duplicato webhook, ricevuta, revoca, token scaduto, finestra di risposta scaduta, handoff all’operatore e ritorno all’AI. Il testo non supportato passa a un operatore. Un invio ambiguo non viene duplicato automaticamente.

## 4. Telefonia SIP/Asterisk

Nella dashboard Telefonia creare la linea, il saluto e la destinazione `PJSIP/...`; copiare l’ID in `SECRET_AI_VOICE_ROUTE_ID`. Abilitare anche la segretaria nelle impostazioni aziendali. Inserire le credenziali/provider autorizzati in `.runtime/pjsip.conf` a partire dal modello. Dare al file permessi leggibili soltanto dall’utente Asterisk e dal gestore. Impostare ACL sugli IP SIP del provider, NAT/media esterni e destinazione fallback. Per provider che richiedono TLS/SRTP applicare la configurazione corrispondente, senza forzare UDP.

Avviare con gli stessi file Compose e il profilo aggiuntivo `--profile sip`. Pubblicare SIP/RTP soltanto dopo aver autorizzato provider, numero e regole di rete. Il dialplan usa l’AGI autenticato e poi AudioSocket; se il motore non è disponibile torna alla destinazione operatore.

Accettazione: chiamata reale, saluto/disclosure AI, comprensione in italiano, risposta, interruzione mentre parla, prenotazione con conferma, timeout e trasferimento (anche premendo 0), chiamata terminata dal cliente e quota esaurita. Il Caller ID non autorizza la modifica di vecchi appuntamenti: occorre il codice gestione o un’identità verificata.

Whisper e Piper sono già provati localmente con audio reale; latenza, rumore, qualità e CPU vanno misurati sul server e sulla rete telefonica scelti.

## 5. Gestionale appreso per dimostrazione

Il gestore autorizza l’origine HTTPS esatta in `BROWSER_ALLOWED_ORIGINS`, ed eventuali origini di login in `BROWSER_AUTH_ORIGINS`. Il browser blocca le altre destinazioni e gli indirizzi di rete privati. Le eccezioni localhost servono soltanto ai test locali e sono disabilitate in produzione.

Dalla pagina Gestionali:

1. Creare la procedura e aprire il browser di prova.
2. Completare l’accesso, MFA e consenso manualmente, prima della registrazione.
3. Premere “Inizia registrazione dopo l’accesso”.
4. Mostrare i clic e associare i campi ai dati cliente, servizio, inizio/fine e riferimento; scegliere il formato di data/ora richiesto dal gestionale.
5. Verificare il risultato, catturare l’eventuale riferimento prenotazione e terminare con una verifica finale.
6. Salvare, controllare e approvare la versione; provarla con dati di test.
7. Associare le procedure di creazione, spostamento e cancellazione ai servizi.

I dati della dimostrazione diventano parametri; la sessione di login è cifrata. La prenotazione non viene confermata finché l’esito esterno non è verificato. Se la pagina cambia, la sessione scade, appare un CAPTCHA/MFA o il risultato è incerto, l’esecuzione si sospende. Un operatore controlla il gestionale e risolve l’esito dalla dashboard; non c’è replay automatico di un’azione potenzialmente già eseguita.

Accettazione: registrazione/replay reale, parametri diversi, formati data/ora, riferimento catturato, clic fallito, esito incerto, sessione scaduta, versione cambiata, accesso di un’altra azienda e tentativo duplicato.

## 6. Stripe

Usare sandbox dedicata, restricted API key e Prices approvati per SecretAI. Configurare `SECRET_AI_PLANS_JSON` con ID Price e quote; non sono creati prodotti né inventati prezzi. Configurare Portal e webhook `/api/billing/webhook` con i tipi gestiti in `app/billing.py` (lifecycle, invoice e rischio). La riconciliazione legge lo stato corrente da Stripe, anche quando gli eventi arrivano fuori ordine; il successo del checkout non concede da solo l’accesso.

Accettazione: checkout iniziale, rinnovo, insoluto/recupero, modifica piano/downgrade, cancellazione a fine periodo, scadenza, limite messaggi/secondi voce, duplicato webhook e evento di rischio. Concordare IVA/fatturazione prima dell’uso commerciale.

## 7. Continuità e privacy

La CI verifica backup cifrato/ripristino PostgreSQL su database vuoto e importazione read-only da SQLite. In staging ripetere con l’infrastruttura scelta, storage separato e chiave conservata separatamente. Definire RPO/RTO, retention e SMTP prima del lancio. `SECRET_AI_RETENTION_DAYS=0` lascia la cancellazione automatica disattivata finché la policy non è stata approvata. Export e anonimizzazione del CRM sono disponibili al proprietario; eventuali dati già inviati ai provider richiedono anche le rispettive procedure.

Il go-live richiede i test live del progetto originale e la validazione commerciale/privacy del titolare. La preparazione degli adattatori non sostituisce quelle prove.
