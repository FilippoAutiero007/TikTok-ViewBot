# TODO - Bug Report e Miglioramenti

## CRITICI

| # | Linea | Issue |
|---|-------|-------|
| 1 | 1162 | **`result` usato prima dell'assegnazione.** Nel loop single-thread, se un'eccezione generica viene catturata prima di assegnare `result`, `log_cycle(cycle, result is True, ...)` crasha con `UnboundLocalError`. |
| 2 | 879 | **Key estratta viene scartata in `try_reconnect`.** `key = extract_key_from_html(html)` estrae una key fresca ma poi `self.key = self.field_name` la sovrascrive con il valore vecchio. Dopo il reconnect la bot usa un campo non valido. |
| 3 | 1162 | **`cycle_timer` è sempre 0.** Viene inizializzato a 0 ogni ciclo ma mai aggiornato con il valore reale del timer. CSV e grafico mostrano sempre 0. |

## ALTI

| # | Linea | Issue |
|---|-------|-------|
| 4 | 757-758 | **Race condition su `worker_counts`.** `print_dashboard` itera `worker_counts.items()` senza `STATS_LOCK`, mentre `add_sent` modifica il dict. Possibile `RuntimeError`. |
| 5 | 734-738 | **`total_sent` e `active_workers` letti senza lock** in `print_dashboard`. Data race con i thread worker. |
| 6 | 638-645 | **`matplotlib.use('Agg')` può lanciare `ValueError`** non catturata. Se il backend non è disponibile crasha. |
| 7 | 167 | **Proxy scheme duplicato.** Se l'utente passa `http://1.2.3.4:8080`, il codice costruisce `http://http://1.2.3.4:8080`. Stesso problema a linea 305 per Selenium. |
| 8 | 433, 449 | **Regex `.*?</div>` non gestisce div annidati.** Estrae contenuto incompleto/sbagliato per HTML con strutture nidificate. |
| 9 | 824-835 | **`validate_proxy` usa `requests.get` senza SSL adapter.** Inconsistenza con il resto del codebase che usa cipher specifici. |
| 10 | 568 | **Check `'views sent'` troppo fragile.** Se il testo della risposta cambia, tutte le azioni restituiscono `False` silenziosamente. |

## MEDI

| # | Linea | Issue |
|---|-------|-------|
| 11 | 22 | **`from PIL import Image` importato ma mai usato.** Dead import. |
| 12 | 486-505 | **`choose_service()` definita ma mai chiamata.** `main()` reimplementa la stessa logica inline. |
| 13 | 42-43 | **`API_URL` hardcoded all'endpoint followers.** Usato come fallback per TUTTI i servizi, sbagliato per hearts, views, ecc. |
| 14 | 69-73 | **`MAX_CYCLES`, `MAX_ERRORS` ecc. hardcoded.** Dovrebbero essere configurabili via CLI o config. |
| 15 | 711 | **`GlobalStats(target=100000)` hardcoded.** Il target 100k non si adatta al vero obiettivo dell'utente. |
| 16 | 331 | **`input()` blocca indefinitamente.** Se l'utente si allontana, il programma resta in attesa. |
| 17 | 1054-1057 | **Nessuna validazione dell'input `method`.** Se l'utente scrive "3" o "abc", defaulta a Selenium senza avviso. |
| 18 | 1100 | **`PHPSESSID` può essere stringa vuota nel pool.** `session.cookies.get('PHPSESSID', '')` può restituire `''` che viene aggiunto al pool. |
| 19 | 1162 | **`log_cycle` chiamato anche dopo eccezioni** che non fanno `continue`/`break`, con `result` potenzialmente non definito. |
| 20 | 786, 824-828 | **Proxy validation usa `requests.get` diretto** senza SSL adapter, headers custom, o rotation. |
| 21 | 754 | **ANSI escape `\033[2J\033[H`** potrebbe non funzionare su tutti i terminali (vecchi Windows cmd, IDE). |
| 22 | 339-341 | **Copia cookie Selenium incompleta.** Solo `name`, `value`, `domain` copiati. `path`, `secure`, `expiry` persi. |
| 23 | 1137-1140 | **Re-solve captcha in single-thread non ri-fetcha service list** o non ri-estrae `api_url`/`field_name` per la nuova sessione. |
| 24 | 601 | **`token, aweme_id = matches[0]` assume esattamente 2 gruppi.** Se la regex matcha diversamente, crasha con `ValueError`. |
| 25 | 870 | **`phpsessid_pool` modulo indicizza sessioni stale.** Se tutti i PHPSESSID sono scaduti, il modulo ruota tra loro senza validazione. |

## BASSI

| # | Linea | Issue |
|---|-------|-------|
| 26 | 673, 684, 690 | **Stringhe italiane hardcoded nel grafico.** `'Views totali'`, `'Inviate'` ecc. in italiano ma il resto dell'UI è in inglese. |
| 27 | 101-106 | **Debug HTML si accumulano senza cleanup.** `save_debug_html` scrive su `./debug/` su molti path di errore, riempie il disco. |
| 28 | 621-627 | **CSV sovrascritto ad ogni run.** `init_csv` con `mode='w'` distrugge i dati della sessione precedente. |
| 29 | 688 | **`ax2.bar` usa larghezza fissa `width=0.001`** in unità matplotlib (giorni). ~1.4 minuti reali. Se i cicli sono più brevi/lunghi le barre si sovrappongono. |
| 30 | 661-662 | **Chart time parsing assume stessa giornata.** Se il bot gira dopo mezzanotte i tempi vanno indietro nel grafico. |
| 31 | 1 | **`import re` e `from re import findall`.** Doppio import dello stesso modulo in stili diversi. |
| 32 | 945 | **`target=100000` non raggiungibile.** Il bot gira per time limit, non per target. La barra di progresso è fuorviante. |
| 33 | 993-997 | **`dashboard_loop` accede a `stats.active_workers` senza sincronizzazione.** |
| 34 | 98 | **`decode()` nessuna validazione input.** Stringa vuota, contenuto non-base64 produce garbage. |
| 35 | 1037 | **`max_p` senza bound check.** Un utente che scrive `999999` proverebbe a fetchare/validare quel numero di proxy. |
| 36 | 305 | **Selenium proxy assume HTTP.** `--proxy-server=http://{proxy}` forza HTTP anche per proxy SOCKS. |
| 37 | 205 | **Fallback captcha detection troppo ampio.** Matcha qualsiasi pagina che menziona "captcha" e ha un img o input. |
| 38 | 1027 | **`threads_input.isdigit()` accetta cifre Unicode** (es. Arabic-Indic). |
| 39 | 167 | **Formato proxy `ip:port` assumeto.** `socks5://`, `http://`, o `user:pass@ip:port` rompono la costruzione URL. |
| 40 | 891-892 | **Proxy logging tronca a solo scheme.** `short_proxy = self.proxy.split(':')[0]` su `http://1.2.3.4:8080` restituisce `http`. |
| 41 | 636-703 | **`generate_chart` legge CSV** che i worker thread possono stare scrivendo. Nessun file locking. |
| 42 | 938 | **`sleep(5)` dopo ogni ciclo.** Anche quando il server è veloce, aggiunge 5s di delay incondizionato. |

## RIEPILOGO

| Severità | Conteggio |
|----------|-----------|
| Critico | 3 |
| Alto | 7 |
| Medio | 15 |
| Basso | 17 |
| **Totale** | **42** |
