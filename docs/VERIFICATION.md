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

Sul primo commit del runtime `7e9fe59a075b347dd002d8e38e19e46f15815fcc` sono passati test backend, PostgreSQL, Chromium e backup/ripristino PostgreSQL + import SQLite. La build API, browser e voice è passata; la prima build Asterisk ha rilevato l’assenza del pacchetto nella distribuzione scelta, poi corretta usando Ubuntu 24.04. L’esito finale delle immagini e del runtime Asterisk viene verificato prima del merge.

## Confini della verifica

- OAuth/API Meta, Google e Stripe sono testati con provider simulati; serve ancora il collaudo sugli account autorizzati.
- Non è stata effettuata una chiamata su rete pubblica/SIP né utilizzato un gestionale aziendale reale.
- Nessun account, numero o hosting a pagamento è stato attivato.
- Il modello Ollama non è avviato nel runtime locale: l’installer automatico sul server scelto comprende download e verifica del tool calling.
- La certificazione di go-live richiede rete/fornitori reali, carico sul server scelto e validazione commerciale/privacy.
