# Verifica del 5 novembre 2026

## Prove locali

- Prima tranche: 30 test backend.
- Runtime integrazioni: 44 test superati, inclusi rinnovo, insoluto, downgrade e cancellazione Stripe con provider simulato.
- Chromium reale: registrazione, azienda, servizio, prenotazione, refresh, cancellazione e navigazione desktop/mobile, comprese Telefonia e Gestionali.
- Computer Use reale su gestionale HTTP locale: dimostrazione → campi parametrizzati → approvazione → replay con dati diversi → riferimento catturato → prenotazione applicativa confermata. Ripetere lo stesso run non duplica l’operazione. L’esito incerto resta sospeso e può essere risolto dopo verifica manuale.
- Protocollo telefonico reale su socket locale con motori sostituiti: UUID/framing AudioSocket, voce bidirezionale, interruzione del saluto, trascrizione in inbox, consumi e handoff.
- Motori vocali reali: Piper italiano Paola medium → PCM 8 kHz → Whisper small. Frase di prova sintetizzata e riconosciuta: “Buongiorno, vorrei prenotare un appuntamento per domani mattina.” Prova locale iniziale, comprensiva del caricamento: circa 11,5 s; sintesi successiva a modelli caricati: circa 0,08 s. Non è un benchmark della futura rete telefonica.
- Controlli sintassi Python/JavaScript e `git diff --check`.

## Prove remote già acquisite

Sul commit applicativo `14a04556429eb6141525c48adffc851296d78087` sono verdi tutti gli otto controlli GitHub Actions (push e pull request):

- test unitari;
- PostgreSQL 16: 43 test superati, con il solo test Chromium eseguito nel job dedicato;
- backup cifrato/ripristino PostgreSQL e importazione read-only da SQLite, incluse le sequenze;
- Chromium desktop/mobile e registrazione/replay del gestionale;
- build delle immagini API, browser, voce e Asterisk;
- avvio Asterisk senza rete: modulo AudioSocket e dialplan inbound verificati.

La verifica iniziale ha rilevato e corretto la distribuzione del pacchetto Asterisk e il percorso multiarch del suo modulo audio. Il codice verificato include il conteggio dei secondi di chiamata sul tempo effettivamente trascorso, comprese le pause.

Le prove remote sono consultabili nella [pull request #2](https://github.com/antoniomusolino120-dotcom/secretai/pull/2/checks). Gli aggiornamenti successivi a questo rapporto riguardano soltanto la documentazione.

## Confini della verifica

- OAuth/API Meta, Google e Stripe sono testati con provider simulati; serve ancora il collaudo sugli account autorizzati.
- Non è stata effettuata una chiamata su rete pubblica/SIP né utilizzato un gestionale aziendale reale.
- Nessun account, numero o hosting a pagamento è stato attivato.
- Il modello Ollama non è avviato nel runtime locale: l’installer automatico sul server scelto comprende download e verifica del tool calling.
- La certificazione di go-live richiede rete/fornitori reali, carico sul server scelto e validazione commerciale/privacy.
