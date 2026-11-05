# Personalizzazione dei tipi di appuntamento

Il proprietario definisce il catalogo della propria attività: nomi dei servizi/tipi di appuntamento, nomi alternativi usati dai clienti, descrizioni, durata, prezzo eventuale e domande preliminari. Non sono imposte categorie di settore come medico, tatuatore o ristorante.

## Configurazione

Da Servizi, creare o modificare un tipo di appuntamento. La descrizione contiene i dettagli che la segretaria può spiegare. I nomi alternativi permettono di riconoscere come i clienti chiamano lo stesso servizio. È possibile aggiungere fino a 20 domande, nell'ordine desiderato, scegliendo testo, numero o scelta tra opzioni; ciascuna può essere obbligatoria o facoltativa.

Per esempio, Visita immobiliare può chiedere indirizzo dell'immobile, tipologia cercata e superficie; Laminazione ciglia può chiedere se il trattamento è già stato effettuato. Questi dati sono configurazione dell'attività, non categorie fisse nel codice.

## Comportamento della segretaria

La segretaria usa il catalogo per riconoscere il servizio e chiedere chiarimenti quando necessario. Se un nome alternativo corrisponde a più servizi, il backend chiede quale scegliere prima di interrogare il modello. Il nome completo più specifico prevale su un nome alternativo generico.

Quando sono noti servizio, giorno, ora e nome, il backend raccoglie le domande preliminari. Le risposte arrivano direttamente dai messaggi del cliente; risposte inventate negli argomenti del modello vengono ignorate. Non è possibile confermare senza le risposte obbligatorie, neppure tramite una chiamata diretta alle API di prenotazione. Una domanda facoltativa può essere saltata. Il comando per interrompere e ricominciare è «ricomincia».

Nome, giorno e ora non possono essere aggiunti dal modello se il cliente non li ha forniti. Il backend interpreta date italiane esplicite, date relative comuni, giorni della settimana e orari e confronta questi dati con la proposta. Le espressioni non riconosciute richiedono ulteriori chiarimenti. Una proposta richiede sempre conferma esplicita e lo slot viene ricontrollato al salvataggio.

I dettagli sui servizi vengono letti dalla descrizione impostata dal proprietario. Una richiesta di informazioni durante il questionario non viene registrata come risposta alla domanda precedente.

## Risultato nella dashboard

La prenotazione conserva il servizio corretto e una copia delle domande con le risposte ricevute. Il pulsante Dettagli nell'agenda permette di consultarle. Modifiche successive al questionario non riscrivono le risposte degli appuntamenti già creati. Le proposte non confermate vengono invalidate quando viene modificato il servizio; le domande cambiate durante un questionario vengono chieste nuovamente.

La chat della dashboard conserva cronologia e contesto nell'inbox e dopo un ricaricamento. I retry con la stessa chiave non duplicano risposte o operazioni; messaggi concorrenti sulla stessa conversazione non vengono elaborati contemporaneamente. I ruoli e l'isolamento delle aziende si applicano anche alla configurazione e alla lettura delle risposte.

Il runner dei gestionali può utilizzare le risposte come parametri `intake_ID_DOMANDA`, selezionabili durante la registrazione della procedura. Questo non elimina il collaudo sul gestionale effettivo.

## Confini della modifica

I questionari sono sequenziali per servizio. Questa modifica non introduce un editor di ramificazioni condizionali, capacità per più tavoli/operatori o la compatibilità universale con gestionali non ancora collaudati. Non configura account esterni, hosting permanente o pagamenti. La telefonia completa e la qualità dell'AI reale richiedono ancora i rispettivi collaudi sul prodotto aggiornato.

Stripe resta successivo al collaudo funzionale. Supabase e FindMyInk non sono stati modificati.
