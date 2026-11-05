# Verifica — 5 novembre 2026

## Aggiornamento: dashboard di controllo

La nuova dashboard separa gli orari di risposta IA dagli orari prenotabili dell’attività, presenta interruttori per canale e la scelta Google/gestionale, e conserva Appuntamenti e Attività come storici da aprire. La prova Chromium esercita interruttori reali, persistenza degli orari notturni, scelta del calendario e lettura delle risposte e delle operazioni dell’IA. I dati di appuntamento della prova UI sono creati con le vere funzioni di proposta/conferma; non viene presentata come prova del modello.

Le nuove prove backend coprono confini orari esclusivi, finestre oltre mezzanotte, cambio ora legale, autorizzazioni, OFF durante inferenza, blocco degli output in coda, mancata ripartenza di un turno precedente dopo OFF/ON, telefonia e destinazioni non collegate. Il collaudo remoto dell’ultima modifica è registrato nei workflow della relativa pull request; le verifiche sotto appartengono alla precedente tranche.

La compilazione del container vocale e l’avvio Asterisk non certificano una conversazione vocale reale. I canali del titolare non sono stati collegati con questa modifica. Stripe resta escluso.

---

## Modifica corrente: personalizzazione e conversazioni

Sono stati ricostruiti e verificati sul codice attuale cataloghi dei tipi di appuntamento, descrizioni e nomi alternativi, domande preliminari, risposte negli appuntamenti, cronologia web e controlli sui dati delle proposte.

| Prova | Esito effettivo |
| --- | --- |
| Suite backend | 59 test superati su SQLite e su PostgreSQL 16 nei workflow remoti; il test Chromium dedicato è escluso dalla suite ordinaria |
| Dashboard Chromium desktop/mobile | Superata: registrazione, attività, servizio con domanda numerica, prenotazione, risposte nei dettagli, refresh, cancellazione e navigazione |
| Runner gestionale Chromium | 1 test reale superato: registrazione, parametri, replay, verifica della prenotazione e recupero di esito incerto |
| Sintassi e whitespace | Python compileall, JavaScript node --check e git diff --check superati |
| PostgreSQL operativo | Backup cifrato, ripristino e importazione SQLite in sola lettura superati nel workflow remoto |
| Container | Build API, browser, voce e Asterisk superate; verifica avvio AudioSocket superata |

In totale: 59 test backend distinti, oltre alle prove Chromium. Il test del runner gestionale usa un gestionale HTTP locale reale; le integrazioni Google, Meta e Stripe nei test backend usano provider controllati.

I nuovi casi verificano:

- catalogo e domande modificabili soltanto dal proprietario;
- tipi testuali, numerici e a scelta, campi obbligatori e facoltativi;
- rifiuto di risposte non valide, campi sconosciuti e identificativi duplicati;
- mancata conferma senza le risposte obbligatorie anche nelle API dirette;
- risposte ricevute dal cliente anziché inventate dal modello;
- richieste di dettagli durante il questionario;
- snapshot delle risposte e invalidazione delle proposte dopo la modifica del servizio;
- scelta esplicita quando un nome generico corrisponde a più servizi;
- dati mancanti chiesti al cliente, date/orari italiani e confronto con gli argomenti del modello;
- cronologia persistente, retry idempotenti, messaggi concorrenti e separazione delle aziende.

## Limiti della certificazione corrente

Non è stato ripetuto un collaudo con modello Ollama e motori vocali reali sulla versione corrente dopo il ripristino dell'ambiente. Le prove e i tentativi della sessione precedente non certificano automaticamente il codice attuale. La telefonia completa, la qualità dell'ascolto, i tempi di risposta e i collegamenti esterni restano da verificare.

Non sono stati collegati account reali Meta/Google/Stripe, numeri telefonici pubblici, gestionali aziendali o hosting permanente. Nessun servizio a pagamento è stato attivato. Stripe resta successivo al funzionamento del prodotto; Supabase e FindMyInk non sono stati modificati.

Le nuove migrazioni e immagini hanno superato i controlli remoti PostgreSQL e container sul commit `a62aa8804b23a345dd1d3ecfe396a286aa8ca429`. La verifica di Asterisk controlla l’avvio e AudioSocket, non una chiamata pubblica con trascrizione e sintesi vocale.

## Pubblicazione

Il titolare ha autorizzato esplicitamente la pubblicazione e l’integrazione dopo i controlli. Il codice è pubblicato nella [PR #3](https://github.com/antoniomusolino120-dotcom/secretai/pull/3).

Verifiche remote del codice applicativo:

- [Tests #50](https://github.com/antoniomusolino120-dotcom/secretai/actions/runs/42031272067): superata.
- [Full verification #23](https://github.com/antoniomusolino120-dotcom/secretai/actions/runs/42031272109): PostgreSQL, Chromium e container superati.

Questo aggiornamento del rapporto segue le prove e non modifica il codice applicativo. L’integrazione in main usa squash, così la modifica può essere annullata con un unico revert. Il repository non equivale a un’app pubblicata su hosting permanente.
