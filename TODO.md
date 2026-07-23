# TODO - Bug Report e Miglioramenti

## CRITICI

| # | Riga | Issue | Severita |
|---|------|-------|----------|
| 1 | 1252 | **`sleep(5)` incondizionato dopo ogni ciclo single-thread.** Anche quando il server risponde in <1s, aggiunge 5s di delay inutile. Dovrebbe basarsi sul tempo di risposta effettivo o essere configurabile. | Critico |
| 2 | 1180 | **`time_input.isdigit()` accetta valori enormi.** Un utente che scrive `999999` imposta un time limit di ~694 giorni. Manca un bound check realistico (es. max 48 ore). | Critico |
| 3 | 1111 | **`threads_input` non ha upper bound.** Un utente che scrive `999999` creerebbe 999999 thread, causando crash di sistema. Manca un max thread (es. 50). | Critico |

## ALTI

| # | Riga | Issue | Severita |
|---|------|-------|----------|
| 4 | 200 | **Proxy HTTPS usa stesso scheme di HTTP.** Se il proxy e `socks5://1.2.3.4:1080`, both `http` e `https` usano `socks5://`. Ma se e `http://1.2.3.4:8080`, dovrebbe forzare `https://` per le richieste HTTPS? In realta i proxy HTTP funzionano anche per HTTPS via CONNECT, ma il comportamento attuale e corretto. DA VERIFICARE. | Alto |
| 5 | 425 | **`input()` per PHPSESSID blocca indefinitamente.** Se l'utente si allontana, il programma resta in attesa senza timeout. Dovrebbe avere un timeout opzionale. | Alto |
| 6 | 367 | **`input()` per solve captcha blocca indefinitamente.** Stesso problema della riga 425. Nessun timeout sull'input dell'utente. | Alto |
| 7 | 835 | **`fetch_free_proxies` usa `requests.get` senza SSL adapter.** Il resto del codebase usa `SSLAdapter` con cipher specifici, ma il fetch proxy usa la sessione default di requests senza SSL personalizzato. Inconsistenza di sicurezza. | Alto |
| 8 | 57 | **`set_window_title` potrebbe causare command injection.** Se il titolo contiene caratteri speciali del shell (come `&`, `|`, `;`), il comando OS potrebbe essere manipolato. Dovrebbe usare `subprocess` con parametri separati o validare l'input. | Alto |
| 9 | 575-583 | **`build_multipart` non escape caratteri speciali nel value.** Se il TikTok URL contiene caratteri come `\r\n`, potrebbe rompere il boundary del multipart form. Manca escaping dei valori. | Alto |
| 10 | 1224-1228 | **Re-solve captcha non aggiorna service list/api_url/field_name.** Dopo il re-solve in single-thread, il codice continua con i vecchi valori di `api_url` e `field_name`, che potrebbero non essere piu validi per la nuova sessione. | Alto |

## MEDI

| # | Riga | Issue | Severita |
|---|------|-------|----------|
| 11 | 6 | **`import tempfile` non usato.** Dead import, dovrebbe essere rimosso. | Medio |
| 12 | 512-546 | **`choose_service()` definita ma mai chiamata.** Funzione duplicata che reimplementa la logica gia presente in `main()`. Dead code. | Medio |
| 13 | 68 | **`API_URL` hardcoded all'endpoint followers.** Usato come fallback per TUTTI i servizi, ma e sbagliato per hearts, views, ecc. Dovrebbe essere dinamico in base al servizio. | Medio |
| 14 | 759 | **`GlobalStats(target=100000)` hardcoded.** Il target 100k non si adatta al vero obiettivo dell'utente. Dovrebbe essere configurabile via CLI. | Medio |
| 15 | 95-98 | **`MAX_CYCLES`, `MAX_ERRORS` hardcoded.** Dovrebbero essere configurabili via CLI o file config. | Medio |
| 16 | 672-676 | **`init_csv` con `mode='w'` sovrascrive i dati.** Ogni run distrugge i dati della sessione precedente. Dovrebbe appendere o usare un nome file con timestamp. | Medio |
| 17 | 695 | **`generate_chart` legge CSV che i worker possono stare scrivendo.** Nessun file locking, possibile corruzione dei dati se il chart viene generato durante una scrittura. | Medio |
| 18 | 803 | **ANSI escape `\033[2J\033[H` potrebbe non funzionare.** Su vecchi terminali Windows, IDE integrati, o有些 terminales non supportano questo escape. Dovrebbe avere un fallback. | Medio |
| 19 | 751 | **Chart salvato con nome fisso `stats_chart.png`.** Ogni generazione sovrascrive il grafico precedente. Dovrebbe usare un nome con timestamp o essere configurabile. | Medio |
| 20 | 238-240 | **Fallback captcha detection troppo ampio.** Anche con il regex aggiunto, matcha qualsiasi pagina che menziona "captcha" E ha un tag `<input>` o `<img>` qualunque. Potrebbe causare falsi positivi. | Medio |
| 21 | 905-910 | **`setup_session` copia cookies senza validare la sessione.** Non verifica che la sessione sia effettivamente valida dopo aver copiato i cookie. | Medio |
| 22 | 937-947 | **Import `urlparse` dentro il metodo `log`.** L'import dovrebbe essere a livello di modulo, non ripetuto ad ogni chiamata al metodo. | Medio |

## BASSI

| # | Riga | Issue | Severita |
|---|------|-------|----------|
| 23 | 709-710 | **Chart time parsing assume stessa giornata.** Se il bot gira dopo mezzanotte, i tempi vanno indietro nel grafico. Non gestisce il cambio di giorno. | Basso |
| 24 | 736 | **`ax2.bar` usa larghezza fissa `width=0.001`** in unita matplotlib (giorni). ~1.4 minuti reali. Se i cicli sono piu brevi/lunghi le barre si sovrappongono o hanno buchi. | Basso |
| 25 | 811-817 | **`load_proxies` legge il file senza file locking.** Se un altro processo sta scrivendo, potrebbe leggere dati parziali. | Basso |
| 26 | 919 | **PHPSESSID pool modulo ruota tra sessioni stale.** Se tutti i PHPSESSID sono scaduti, il modulo continua a ruotarli senza validazione. Dovrebbe marcare le sessioni scadute. | Basso |
| 27 | 25 | **`chromedriver_autoinstaller.install()` chiamato a import time.** Se fallisce, viene silenziosamente ignorato. Dovrebbe loggare un warning. | Basso |
| 28 | 844 | **`log.debug` usa `api_url.split('/')[2]` senza bound check.** Se l'URL e malformed, potrebbe lanciare IndexError. | Basso |
| 29 | 747-748 | **Chart path hardcoded.** Il grafico viene sempre salvato nella directory corrente. Dovrebbe essere nella cartella `data/` o essere configurabile. | Basso |
| 30 | 1187 | **Messaggio italiano "paste altri PHPSESSID"**混 in inglese. Il resto del codice e in inglese ma questo messaggio e in italiano. Inconsistenza di lingua. | Basso |
| 31 | 1189 | **Messaggio italiano "o INVIO per terminare"** 同上, misto italiano/inglese. | Basso |
| 32 | 1257 | **Messaggio italiano "Riepilogo"** 同上, inconsistenza lingua. | Basso |
| 33 | 1039 | **Messaggio italiano "caricati"** 同上. | Basso |
| 34 | 1044 | **Messaggio italiano "minuti"** 同上. | Basso |
| 35 | 796 | **Messaggio italiano "Workers attivi"** 同上. | Basso |
| 36 | 798 | **Messaggio italiano "Inviate", "Rimanenti"** 同上. | Basso |
| 37 | 751 | **Messaggio italiano "Grafico salvato"** 同上. | Basso |

## MIGLIORAMENTI PROPOSTI

| # | Descrizione | Priorita |
|---|-------------|----------|
| M1 | **Aggiungere argparser CLI.** Permettere di configurare tutti i parametri via command line invece che solo con input interattivo. | Alta |
| M2 | **Aggiungere file config JSON/YAML.** Per salvare le preferenze dell'utente (proxy, thread, time limit) senza doverli riscrivere ogni volta. | Alta |
| M3 | **Rimuovere `choose_service()` duplicata.** Usare la funzione esistente in main() o unificarle. | Media |
| M4 | **Rimuovere `import tempfile` inutilizzato.** Pulizia codice. | Bassa |
| M5 | **Aggiungere test per funzioni mancanti.** Mancano test per `send_action`, `search_link`, `generate_chart`, `WorkerThread`. | Media |
| M6 | **Aggiungere logging strutturato JSON.** Per facilitare il parsing automatico dei log. | Bassa |
| M7 | **Aggiungere health check proxy periodico.** Ri-validare i proxy durante l'esecuzione per rimuovere quelli che smettono di funzionare. | Alta |
| M8 | **Aggiungere rate limiting adaptive.** Ridurre automaticamente la frequenza delle richieste se il server inizia a rispondere con 429. | Media |
| M9 | **Aggiungere supporto SOCKS5/4.** Il codice attualmente gestisce solo proxy HTTP/HTTPS. | Media |
| M10 | **Aggiungere riconnessione automatica Selenium.** Se il browser si chiude inaspettatamente, riavviarlo automaticamente. | Media |
| M11 | **Aggiungere statistiche persistenti.** Salvare le statistiche in un database SQLite invece che in CSV per storico a lungo termine. | Bassa |
| M12 | **Aggiungere notifiche desktop.** Avvisare l'utente quando il bot termina o incontra errori critici usando `plyer` o simile. | Bassa |

## RIEPILOGO

| Severita | Conteggio |
|----------|-----------|
| Critico | 3 |
| Alto | 7 |
| Medio | 12 |
| Basso | 15 |
| Miglioramenti | 12 |
| **Totale** | **49** |
