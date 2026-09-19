# TikTok ViewBot

Due bot nello stesso repo:

- **Zefoy bot** (`zefoy_bot/bot.py`) — invia views/follower/like via Zefoy.com (gratis, senza login TikTok). Funziona dopo 1 captcha.
- **TikTok bot** (`main.py` + `tiktok_bot/`) — crea account e manda follow/like/view via API app TikTok. ⚠️ **Attualmente non riesce a creare account né a seguire** (vedi sotto).

## Comandi veri (il vecchio `python zefoy_bot.py` non esiste più)

```bash
pip install -r requirements.txt

# Zefoy: lista servizi (offline, sempre funziona)
python zefoy_bot/bot.py --list-services

# Zefoy: follower a un profilo (1 captcha in Chrome, poi loop da solo)
python zefoy_bot/bot.py --url https://www.tiktok.com/@trasparente0 --service 1 --method 1 --threads 3 --time 30

# TikTok: stato account locali
python main.py stats

# TikTok: prova registrazione (oggi fallisce, vedi problemi noti)
python main.py register --batch --count 1

# Test Zefoy (122 passed dopo i fix)
python -m pytest zefoy_bot/tests/test_bot.py -q
```

Servizi Zefoy: `1=Followers 2=Hearts 3=Comments 4=Views 5=Shares 6=Favorites 7=Live Stream 8=Repost`.

## ID TikTok (quale serve per cosa)

| ID | Esempio | Dove si trova | Serve per |
|---|---|---|---|
| username | `@trasparente0` | URL profilo | solo link, cambia nel tempo |
| secUid | `MS4wLjABAAAA...` | source profilo, `__UNIVERSAL_DATA_FOR_REHYDRATION__` → `secUid` | API web / info profilo |
| UID | `7318518854...` (solo numeri) | source profilo (`"id":"7...`), app → Condividi | `follow` API app (`to_user_id`) |
| aweme_id | `7412345678901234567` | URL `.../video/<ID>` | `like`/`view` video |

`parse_tiktok_url` estrae già `username` + `video_id` offline. `resolve_sec_uid` automatico invece fallisce (vedi sotto).

## Problemi noti (con evidence, non ipotesi)

1. **Registrazione via API bloccata dal WAF.** `POST passport/app/region/` → `200 0 bytes`, `passport/device/register/` → `404 internal server error`, `passport/email/register/v2/` → `200 vuoto`. Prima l'errore era `Expecting value: line 1 col 1`; dopo i fix l'errore è esplicito (`Passport ... risposta vuota (WAF/firma scartata)`). Log: `python main.py register --batch --count 1`.
2. **Firma vecchia era invalida.** `_request` non passava mai il signer; `_passport_request` generava DUE query con timestamp diversi (URL vs firma) + fallback `md5` inventato. Fix: query singola, `unix` dalla query, solo `tiktok-signer` reale, errore duro se manca (`tiktok_bot/client.py`).
3. **Account locali finti.** I 24 file in `accounts/active/` hanno `user_id='' cookies={} x_tt_token=''` ma `status='active'`. Ora `save()` rifiuta `active` senza login e `get_accounts_for_action('any')` usa solo account loggati → `for_follow: 0` (corretto, prima provava `follow(None)`).
4. **`resolve_sec_uid` murato.** `tiktok.com/@trasparente0` da datacenter risponde `Log in | TikTok` (273k chars) senza secUid. Ora rilevato e abortito subito invece di 3 retry inutili. Workaround: `view-source:` → cerca `secUid`, oppure browser con cookie salvati (da implementare).
5. **Zefoy: servizi/timer/captcha.** I servizi vanno OFF lato Zefoy senza preavviso, ogni invio ha timer 60-120s e serve 1 captcha per sessione. Non è un bug nostro: è la protezione di Zefoy.
6. **`follow` voleva secUid.** L'endpoint vuole UID numerico; ora `follow('MS4w...')` e `follow(None)` / follow anonimo sollevano `TikTokAPIError` chiaro.
7. **Test rotti.** `patch('zefoy_bot.sleep')` invece di `zefoy_bot.bot.sleep` + `CSV_FILE` mutato nel modulo sbagliato → 36 falliti. Fixati i path → `122 passed, 1 skipped`.

## Struttura

```
TikTok-ViewBot/
├── zefoy_bot/bot.py        # bot Zefoy (entry reale)
├── zefoy_bot/tests/test_bot.py
├── main.py                 # bot TikTok (register/login/run/stats/devices/config)
├── tiktok_bot/             # client, accounts, bot, utils, device, captcha, email
├── scripts/                # duplicato legacy di main.py (da rimuovere)
├── config.json             # config Zefoy
├── data/proxies.txt        # proxy
└── TODO.md                 # lista completa fix/miglioramenti
```

## Fix già applicati (verificati con test)

- Firma reale + query singola, no fallback (`client.py`)
- `extra_params` per GET, `follow` con UID + check login
- Errori WAF espliciti, `device_register` form-encoded
- Cookie via jar (niente `split(',')`), proxy validati, `close()` sessioni
- Account: filename sicuri, niente placeholder in `active/`, cooldown deterministico, `any` con limiti
- Bot: deep-copy device, ban detection su `error_code`, sessione sempre chiusa
- `resolve_sec_uid` rileva wall login, fingerprint coerente (Android↔SDK, locale↔regione↔tz)
- `main.py` crea `logs/`, `requirements` + `plyer/pysocks/tiktok-signer`, test con path giusti

Dettagli e lavoro restante in `TODO.md`.

## License

MIT
