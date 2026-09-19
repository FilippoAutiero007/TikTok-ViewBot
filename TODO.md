# TODO — analisi completa codice + fix/miglioramenti

Legenda: ✅ fatto e verificato con test · ⬜ da fare. Riferimenti `file:riga` sul codice attuale.

## A. Firma e richieste API (`tiktok_bot/client.py`) — priorità massima

- [x] ✅ Query singola per URL+firma, `unix` condiviso, solo signer reale, niente fallback (`_generate_query`, `_sign_request_tiktoksigner`, `_build_headers`, `_request`, `_passport_request`)
- [x] ✅ `get_user_info/videos/search_user` usavano `params=` inesistente → ora `extra_params=` + `sec_user_id` nell'URL
- [x] ✅ `follow/unfollow` richiedono UID numerico (rifiutano `MS4w...`/`None`) + `_require_login`
- [x] ✅ `_passport_request` valida status/body vuoto/Content-Type (errori WAF espliciti invece di `Expecting value char 0`)
- [x] ✅ `device_register` form-encoded invece di `json.dumps`
- [x] ✅ Cookie via jar (niente `split(',')` su `Expires=Wed,`), niente `session.timeout` fantasma, proxy validati, `close()` + context manager
- [ ] ⬜ `_handle_response`: gestire `2000` come successo come fa `_handle_login_response`, seguire/segnalare redirect 301/302 invece di `{'status_code':0}`
- [ ] ⬜ `_request` GET: verificare che `extra_params` firmati coincidano con quelli nell'URL anche per `sec_user_id/count/cursor`
- [ ] ⬜ Retry captcha su sessione condivisa (oggi `TikTokCaptchaSolver` usa sessione propria, il retry non eredita cookie/token)

## B. Account (`tiktok_bot/accounts.py`)

- [x] ✅ Filename sicuri (niente `.json` vuoto), scrittura atomica, `mark_banned` rimuove tutte le varianti
- [x] ✅ `save()` rifiuta `active` senza login; `is_logged_in`
- [x] ✅ Cooldown deterministico per account (niente `random` a ogni accesso)
- [x] ✅ `get_accounts_for_action`: solo loggati + cooldown; `any` applica tutti i limiti; warmup solo per follow/like (view subito)
- [ ] ⬜ `_load_accounts`: salta file corrotti con warning invece di crash; distingue `pending/` da `active/`
- [ ] ⬜ `register_batch/login_account`: riusa device salvato + stesso proxy per email provider (oggi device fresco e IP mismatch)

## C. Bot (`tiktok_bot/bot.py`)

- [x] ✅ `with TikTokClient` (niente leak FD), `deepcopy(device)`, `_is_auth_error` su `error_code` per entrambi i rami
- [x] ✅ Usa `target_user_id` numerico quando disponibile
- [ ] ⬜ `_create_accounts_batch`: non salvare `pending` in `active/`; chiama `register_account` e salva solo verificati
- [ ] ⬜ `record_action` thread-safe (lock per account, niente race su `actions_count`/`save()` concorrente)
- [ ] ⬜ Signal handler senza `sys.exit()` dentro il segnale (solo flag stop + join)

## D. Utils/device/email/captcha

- [x] ✅ `resolve_sec_uid` rileva wall login/captcha e abortisce con log chiaro
- [x] ✅ Fingerprint coerente (`ANDROID_SDK_MAP`, `LOCALE_REGION_TZ`)
- [ ] ⬜ `resolve_sec_uid` via Playwright con cookie salvati (1 login manuale → niente wall) + rotazione proxy/UA
- [ ] ⬜ `resolve_video_id`: GET con proxy invece di HEAD (short URL `vm.tiktok.com` richiedono JS/redirect)
- [ ] ⬜ `captcha_solver`: riusa stessi params per `session_id`, cifra come da protocollo (niente `key/nonce` random), `matchTemplate(puzzle,piece)` non invertito, traiettoria umana
- [ ] ⬜ `email_providers/temp_email`: pattern contestuali invece di `(\d{6})` greedy, niente OTP in log, `sender_filter` fissato
- [ ] ⬜ `account_creator`: `try/finally driver.quit()`, driver cached (niente `ChromeDriverManager().install()` per account), screenshot fuori dalla CWD, stealth completo

## E. Zefoy (`zefoy_bot/`)

- [x] ✅ Test con path giusti (`zefoy_bot.bot.*`, `botmod.CSV_FILE`) → `122 passed, 1 skipped`
- [x] ✅ `__init__.py` riesporta API pubblica
- [ ] ⬜ Menu stampato generato da `SERVICES` (oggi dice `1=Views` ma `SERVICES[1]=Followers`)
- [ ] ⬜ Max-reconnect dopo `Session expired` (oggi `continue` infinito se Zefoy è down)
- [ ] ⬜ Rotazione proxy reale per worker (oggi indice fisso)
- [ ] ⬜ `send_action/search_link`: decodificare PRIMA di cercare timer; match esatti invece di substring (`'success'`, `'comments'`)
- [ ] ⬜ Signal handler + `executor.shutdown(cancel_futures=True)` + chiusura driver/sessioni
- [ ] ⬜ `__all__` esplicito in `bot.py` (oggi `import *` esporta anche `os/sys/requests/sleep`)

## F. Entry-point/config/docs

- [x] ✅ `main.py` crea `logs/` prima del `FileHandler`
- [x] ✅ `requirements.txt` + `plyer/pysocks/tiktok-signer`
- [x] ✅ README riscritto (comandi veri, ID, problemi con evidence, struttura)
- [ ] ⬜ Unificare `config.json` vs `config_bot.json` (`cmd_config` oggi non tocca il bot)
- [ ] ⬜ Eliminare `scripts/main.py` duplicato (manca `cmd_create_real`)
- [ ] ⬜ Validazione `argparse` (`--count/--threads/--time > 0`) e validazione tipi/range in `load_config`
- [ ] ⬜ `scripts/proxy_parallel.py`: chiudi sessione, niente `cancel()` inefficace, scrittura atomica `proxies.txt`
- [ ] ⬜ `.gitignore`: non committare `logs/*.log`, screenshot `*.png`, script `debug_*/inspect_*` di lavoro

## G. Prova finale `@trasparente0` (bloccata lato server, non dal codice)

- [x] ✅ `register --count 1` → errori WAF espliciti (non più crash oscuro)
- [x] ✅ `stats` → 24 account, 0 loggati, `for_follow: 0` (corretto)
- [ ] ⬜ Ottenere UID numerico manuale (view-source → `"id":"7...`) o via browser loggato
- [ ] ⬜ `create-real` via browser → account verificato → `run --target ... --follows 1`
- [ ] ⬜ Alternativa Zefoy: `zefoy_bot/bot.py --url ... --service 1 --method 1` (1 captcha manuale, poi loop; dipende da servizi ON e timer 60-120s)
