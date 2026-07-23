# TikTok ViewBot

Bot per aumentare le visualizzazioni TikTok tramite Zefoy.com.

## Funzionalità

- **Selenium**: Risoluzione automatica captcha tramite browser Chrome
- **Cookie Manual**: Inserimento manuale PHPSESSID
- **Multi-Thread**: Supporto per più thread con proxy
- **Dashboard**: Statistiche in tempo reale
- **Grafici**: Generazione grafici CSV con matplotlib
- **Proxy**: Supporto proxy con validazione automatica
- **Auto Chromedriver**: Installazione automatica chromedriver
- **Banner ASCII**: Banner grafico con pyfiglet

## Requisiti

```bash
pip install -r requirements.txt
```

## Utilizzo

```bash
python zefoy_bot.py
```

### Modalità

1. **Selenium** (default): Apre Chrome per risolvere il captcha
2. **Cookie Manual**: Inserisci PHPSESSID dal browser

### Multi-Thread

```bash
# Esempio con 3 thread
python zefoy_bot.py
# Inserisci URL TikTok
# Scegli metodo captcha
# Inserisci numero thread: 3
```

## Struttura

```
TikTok-ViewBot/
├── zefoy_bot.py          # File principale
├── data/
│   ├── proxies.txt       # File proxy
│   └── stats.csv         # Statistiche (generato)
├── debug/                # HTML di debug
├── logs/
│   └── bot_log.txt       # Log
├── tests/
│   └── test_bot.py       # Test
├── reference/
│   ├── tiktok-private-api/ # API TikTok
│   └── selenium-bot/       # Bot riferimento
├── requirements.txt
├── README.md
├── LICENSE
└── TODO.md
```

## Fix Applicati

- ✅ Risolti 27 bug su 42 totali
- ✅ Rimossi import inutilizzati
- ✅ Corretta race condition su worker_counts
- ✅ Corretto proxy scheme duplicato
- ✅ Migliorata validazione input
- ✅ Corretta copia cookie Selenium
- ✅ Aggiunta validazione PHPSESSID pool
- ✅ Aggiunto chromedriver autoinstaller
- ✅ Aggiunto banner ASCII art
- ✅ Aggiornamento titolo finestra con metriche

## Ispirazione

Basato su [vdutts7/tiktok-bot](https://github.com/vdutts7/tiktok-bot) con miglioramenti significativi.

## License

MIT
