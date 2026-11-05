# Controllo della segretaria

## Schermata principale

- WhatsApp, Instagram, Telefono, Email e Chat di prova, ciascuno con il proprio interruttore.
- Risposte tutto il giorno oppure tra inizio e fine; giorni di inizio selezionabili.
- Fuso dell’attività, configurabile in Impostazioni IA. Gli orari prenotabili sono una configurazione separata.
- Scelta tra Google Calendar e altro strumento, con accesso alla registrazione guidata della procedura.
- Appuntamenti e Attività sono chiusi a ogni nuova visita o ricaricamento. I dati vengono caricati quando si apre la sezione.

Servizi e domande permette di configurare il catalogo e i questionari. Impostazioni IA conserva istruzioni, informazioni aziendali e chat di prova. Il menu non espone agenda manuale, rubrica, fatturazione o un CRM aggiuntivo.

## Interruttori e orari

OFF ferma l’automazione del singolo canale e conserva l’autorizzazione del provider. Il successivo ON non richiede un nuovo accesso. L’effettiva revoca dell’account resta un comando separato. Messaggi ricevuti con OFF restano nello storico quando il provider continua a consegnarli, senza risposta automatica.

La configurazione viene controllata all’ingresso, all’elaborazione, prima di operazioni di prenotazione e prima dell’invio. Ogni salvataggio cambia la revisione: un turno o invio della vecchia revisione non può ripartire dopo una sequenza OFF/ON. Le risposte umane esplicite non sono soppresse dall’interruttore IA. Richieste HTTP già inviate al provider non possono essere ritirate.

Una fascia lunedì 18:00–09:00 finisce martedì mattina. L’inizio è incluso e la fine esclusa. Con tutto il giorno sono attivi solo i giorni selezionati. Date e cambio dell’ora seguono Europe/Rome o il fuso impostato.

La telefonia rifiuta nuove sessioni IA fuori fascia e interrompe le sessioni attive dopo la disattivazione. Asterisk verifica la disponibilità prima di rispondere e usa la destinazione operatore/fallback configurata. Il controllo delle sessioni in corso viene ripetuto ogni secondo. Il comportamento del numero reale e del trasferimento va collaudato con il provider.

## Calendario e storici

La selezione del calendario si applica alle nuove prenotazioni; quelle già create conservano la propria destinazione. Con Google selezionato ma scollegato, la prenotazione viene rifiutata indicando il collegamento necessario. Con altro strumento selezionato servono procedure approvate e associate al servizio. L’esito esterno deve essere verificato prima della conferma definitiva.

Appuntamenti elenca le prenotazioni create dall’IA, comprese quelle cancellate, con risposte al questionario, destinazione ed esito. Attività separa le conversazioni per canale e cliente, mostra i messaggi e le operazioni registrate. Non produce riassunti inventati delle telefonate.

## Fase di test

Non sono stati collegati nuovi account o attivati servizi a pagamento. La chat usa il motore configurato nell’ambiente; la prova automatica della dashboard non certifica il modello. Il collegamento del microfono browser non fa parte di questa modifica. Email non ha ancora un adattatore operativo ed è esplicitamente disabilitata. Una linea telefonica configurata non certifica il collegamento SIP sul numero pubblico.

Il test resta sui canali del titolare. Stripe, il blocco commerciale al pagamento e l’onboarding autonomo di altre aziende restano sospesi. Gli endpoint di gestione preesistenti rimangono compatibili, anche se la dashboard offre soltanto i controlli e gli storici concordati.
