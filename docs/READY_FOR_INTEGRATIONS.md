# Handoff per le integrazioni

I moduli applicativi sono implementati. L’ordine seguente raccoglie i passaggi che dipendono da account, accessi o decisioni del titolare. Il documento `INTEGRATION_RUNBOOK.md` contiene configurazione e prove di accettazione.

| Ordine | Il titolare mette a disposizione | SecretAI è predisposto per |
| --- | --- | --- |
| 1. Hosting | Provider/costi approvati, dominio e ambiente dedicato | Docker, PostgreSQL, migrazioni, API/worker/browser/voice, HTTPS e controlli |
| 2. AI/voce | Risorse del server approvate | Download automatico Ollama/Whisper/Piper e verifica degli strumenti; nessun account AI obbligatorio |
| 3. Google | Progetto Google Cloud e consenso calendario test | Collegamento OAuth, eventi, modifiche, sincronizzazione e conflitti |
| 4. Meta | App, configurazione Embedded Signup, account Business/professionale e approvazioni | Collegamento dalla dashboard senza consegnare token al cliente finale |
| 5. Telefonia | Numero/provider/SIP, IP autorizzati e destinazione operatore | AudioSocket/Asterisk, conversazione, interruzioni, prenotazione e trasferimento |
| 6. Gestionale | Ambiente di prova e accesso autorizzato | Registrazione dimostrazione, associazione ai servizi ed esecuzione verificata |
| 7. Stripe | Sandbox/account, Prices, piani/limiti e scelte fiscali | Checkout, Portal, rinnovi, insoluti, downgrade, cancellazione e quote |
| 8. Azienda/privacy | Dati aziendali, SMTP, policy di conservazione e validazione legale | Knowledge base, istruzioni, retention/export e gestione delle conversazioni |

Il collaudo live è ancora necessario. Non è stato attivato Stripe Tax: IVA, registrazioni e fatturazione vanno concordati prima del lancio. Non inviare password o chiavi nella chat; conservarle nell’ambiente privato o autorizzare gli account tramite i pulsanti di collegamento.
