# TODO - Bug Report e Miglioramenti (v2)

## CRITICI (Bugs che causano crash o funzionamento errato)

| # | Riga | Issue | Severita |
|---|------|-------|----------|
| 1 | 1508-1509 | **`MAX_CYCLES`/`MAX_ERRORS` in `main()` sono locali, non aggiornano i globali.** La riga `MAX_CYCLES = CONFIG['max_cycles']` in `main()` crea una variabile locale, ma il codice nei cicli (riga 1340, 1691) usa ancora i valori globali originali. `--max-cycles` dall'CLI non funziona. | Critico |
| 2 | 1018-1025 | **`init_csv` scrive header ogni volta che viene chiamata.** Se il file esiste, apre in append mode e scrive un nuovo header row, corrompendo il CSV con header multipli. | Critico |
| 3 | 1148-1175 | **`print_dashboard` tiene `STATS_LOCK` durante stampa schermo.** Se un worker chiama `add_sent()` mentre il dashboard tiene il lock, il worker si blocca. Possibile deadlock se il print è lento. | Critico |
| 4 | 1293-1302 | **`try_reconnect` incrementa `self.reconnects` due volte per iterazione.** Prima a riga 1293 (`+= 1`), poi dentro il while a riga 1302 (`+= 1`). Un pool di 3 PHPSESSID salta sessioni. | Critico |
| 5 | 1602-1606 | **`key` da CLI non viene usata nel loop.** Dopo `solve_with_cookie()` con `--phpsessid`, `key` viene estratta a riga 1602 ma non assegnata alla variabile `key` del loop (è un'assegnazione locale). Il loop usa `key=None`. | Critico |

## ALTI (Bug che causano comportamento errato)

| # | Riga | Issue | Severita |
|---|------|-------|----------|
| 6 | 1078 | **Label grafico hardcoded "Total views sent".** Anche quando il servizio è Comments, Hearts, o Favorites, l'etichetta dice sempre "Total views sent". | Alto |
| 7 | 1404 | **Proxy rotation non funziona.** `proxy_list[i % len(proxy_list)]` assegna sempre lo stesso proxy allo stesso worker (indice fisso). Non c'è rotazione durante l'esecuzione. | Alto |
| 8 | 1615-1618 | **Se `key` è None dopo re-solve, il loop non si ferma.** La variabile `key` del loop è `None` ma il ciclo continua, causando crash in `search_link`. | Alto |
| 9 | 1349 | **`cycle_start` non inizializzato prima del primo sleep.** Se il primo ciclo lancia un'eccezione non-`RuntimeError` prima di arrivare a `cycle_start = time()`, il `sleep_delay` a riga 1392 usa `cycle_start` non definito. | Alto |
| 10 | 940-1008 | **`search_link` non valida il contenuto decodificato.** Se la risposta decodificata non ha il form atteso, continua a loop infinito con "No timer and no form found". Dovrebbe avere un max retry per questo caso. | Alto |
| 11 | 930-934 | **`send_action` success check incomplete.** Mancano: `'comment hearts sent'`, `'live stream sent'`, `'repost sent'`. Solo alcune frasi sono controllate. | Alto |
| 12 | 786-815 | **`check_service_status` potrebbe non rilevare correttamente servizi disabilitati.** Se zefoy aggiunge nuovi pattern HTML per "disabled" (es. `opacity:0.5`, `pointer-events:none`), il detection fallisce silenziosamente. | Alto |

## MEDI (Bug minori o miglioramenti importanti)

| # | Riga | Issue | Severita |
|---|------|-------|----------|
| 13 | — | **Nessun graceful shutdown.** Ctrl+C killa il processo senza salvare stats, chiudere sessioni, o generare il grafico. Manca un signal handler. | Medio |
| 14 | 1328 | **`WorkerThread.log` importa `urlparse` ad ogni chiamata.** L'import è già a livello di modulo (riga 23). Import ripetuti sono inutili. | Medio |
| 15 | 1242-1253 | **`validate_proxy` non chiude la sessione.** Ogni validazione proxy crea una `requests.Session()` che non viene chiusa, causando leak di connessioni. | Medio |
| 16 | 90-119 | **`input_with_timeout` su Windows non gestisce Unicode.** `msvcrt.getwche()` non gestisce caratteri speciali (accenti, CJK). Potrebbe crashare su input con caratteri non-ASCII. | Medio |
| 17 | 342 | **`SqliteStats.log_cycle` passa `elapsed` come stringa.** `f'{elapsed:.1f}'` produce una stringa, ma la colonna `elapsed_sec` è `REAL`. Funziona ma è incoerente. | Medio |
| 18 | 1413 | **`dashboard_loop` thread non è joinato.** Dopo `stats.set_active(0)`, il thread potrebbe non aver terminato ancora. | Medio |
| 19 | — | **Nessun SIGINT handler.** Se il bot è in multi-thread, Ctrl+C non ferma i worker in modo pulito. | Medio |
| 20 | 1016-1025 | **`init_csv` dovrebbe verificare se il file CSV è valido.** Se il file esiste ma è corrotto (es. scritto male), il bot continua a fare append su dati corrotti. | Medio |

## BASSI (Bug cosmnetici o miglioramenti minori)

| # | Riga | Issue | Severita |
|---|------|-------|----------|
| 21 | 1362 | **Window title dice "Views Generated" anche per altri servizi.** Dovrebbe usare il nome del servizio. | Basso |
| 22 | 1530-1539 | **Menu servizi mostra tutti i servizi anche se sono OFF su zefoy.** Dovrebbe mostrare solo quelli disponibili, o almeno evidenziare meglio che "non funzionano". | Basso |
| 23 | — | **`config.json` non ha sezione per ogni servizio.** Ogni servizio potrebbe avere parametri diversi (max cycles, target, ecc). | Basso |
| 24 | — | **Nessun log delle statistiche finali in SQLite.** Manca un riepilogo della sessione nel database. | Basso |
| 25 | 1392-1393 | **`sleep_delay` dopo errore include il tempo di errore.** Se un errore dura 30s, il delay è `max(1, 5 - 30) = 1` invece di 5. Dovrebbe resettare. | Basso |
| 26 | — | **Manca `requirements.txt`** con dipendenze opzionali (matplotlib, plyer, pysocks). | Basso |
| 27 | — | **Manca `--dry-run` flag** per testare la configurazione senza eseguire il bot. | Basso |

## MIGLIORAMENTI PROPOSTI

| # | Descrizione | Priorita |
|---|-------------|----------|
| M1 | **Aggiungere `--service-name` flag** per auto-select per nome (es. `--service-name "Comments Hearts"`) | Media |
| M2 | **Aggiungere `--verbose` / `--quiet` flags** per controllo livello log | Media |
| M3 | **Aggiungere health check periodico delle sessioni PHPSESSID** ogni N cicli | Media |
| M4 | **Aggiungere `--export-stats` flag** per exportare statistiche in JSON/CSV | Bassa |
| M5 | **Aggiungere grafico live** con matplotlib animation (opzionale) | Bassa |
| M6 | **Aggiungere `--no-chart` flag** per skip generazione grafico | Bassa |
| M7 | **Aggiungere `--log-level` flag** per controllo debug output | Bassa |
| M8 | **Aggiungere supporto per `tiktok.com/@user/video/ID` URL** (formatti diversi) | Media |
| M9 | **Aggiungere `--rotate-service` flag** per ruotare automaticamente tra servizi disponibili | Bassa |
| M10 | **Aggiungere `--session-file` flag** per salvare/caricare sessioni PHPSESSID da file | Media |

## ANALISI: Perché Likes e Followers NON funzionano

Dall'HTML della pagina zefoy.com (`debug/service_list.html`):

```
Followers: <button disabled class="btn btn-primary rounded-0 t-followers-button">
           <small class="badge badge-round badge-danger">soon will be update</small>

Hearts:    <button disabled class="btn btn-primary rounded-0 t-hearts-button">
           <small class="badge badge-round badge-danger">soon will be update</small>

Views:     <button disabled class="btn btn-primary rounded-0 t-views-button">
           <small class="badge badge-round badge-danger">soon will be update</small>
```

**Tutti e tre i bottoni sono `disabled`** — zefoy.com ha disattivato questi servizi lato server. Il bot li detecta correttamente come OFF e NON li mostra come disponibili.

**Servizi attualmente funzionanti su zefoy:**
- Comments Hearts (`t-chearts-button`) - ON, aggiornato 2 settimane fa
- Favorites (`t-favorites-button`) - ON, aggiornato 2 settimane fa

**Servizi non funzionanti (disabilitati da zefoy):**
- Followers - OFF ("soon will be update")
- Hearts - OFF ("soon will be update")  
- Views - OFF ("soon will be update")
- Shares - OFF ("soon will be update")
- Live Stream - OFF ("soon will be update")
- Repost - OFF ("soon will be update")

**Questo non è un bug del bot.** Il bot funziona correttamente — il problema è che zefoy.com ha disabilitato questi servizi. L'utente dovrebbe usare Comments Hearts (#3) o Favorites (#6).

## RIEPILOGO

| Severita | Totale | Da Fixare |
|----------|--------|-----------|
| Critico | 5 | 5 |
| Alto | 7 | 7 |
| Medio | 8 | 8 |
| Basso | 7 | 7 |
| Miglioramenti | 10 | 10 |
| **Totale** | **37** | **37** |
