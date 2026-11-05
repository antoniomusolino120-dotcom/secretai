# Verifica — 5 novembre 2026

## Modifica corrente: personalizzazione e conversazioni

Sono stati ricostruiti e verificati sul codice attuale cataloghi dei tipi di appuntamento, descrizioni e nomi alternativi, domande preliminari, risposte negli appuntamenti, cronologia web e controlli sui dati delle proposte.

| Prova | Esito effettivo |
| --- | --- |
| Suite backend | 58 test superati; il test Chromium dedicato è escluso dalla suite ordinaria |
| Concorrenza della chat, aggiunta dopo la suite | 1 test aggiuntivo superato sullo stesso codice applicativo |
| Dashboard Chromium desktop/mobile | Superata: registrazione, attività, servizio con domanda numerica, prenotazione, risposte nei dettagli, refresh, cancellazione e navigazione |
| Runner gestionale Chromium | 1 test reale superato: registrazione, parametri, replay, verifica della prenotazione e recupero di esito incerto |
| Sintassi e whitespace | Python compileall, JavaScript node --check e git diff --check superati |

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

Le nuove migrazioni e immagini devono ancora superare i controlli remoti PostgreSQL e container. L'esecuzione locale PostgreSQL non è disponibile in questo ambiente perché non è consentito avviare il processo con l'utente non privilegiato richiesto dal server. I risultati remoti della precedente tranche sono conservati nei controlli della PR #2, ma non certificano questa modifica.

## Pubblicazione

Le modifiche sono preparate in un commit locale. Il push al repository `antoniomusolino120-dotcom/secretai` è stato bloccato dal controllo automatico, che richiede l'autorizzazione esplicita del titolare all'invio del codice a quella destinazione. Non sono stati usati percorsi alternativi per aggirare il blocco.
