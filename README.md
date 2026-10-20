# SMC Crypto Signal Bot

A multi-user Telegram prototype for SMC-inspired **crypto spot-market signals only**. It does not place orders or require exchange API keys.

## Features
- Users enable their own alerts by sending /start; /stopalerts disables them.
- Scans the configured centralized exchange watchlist continuously (scan interval is configurable, not a scheduled signal time).
- Uses completed candles for a basic BOS + FVG/liquidity-sweep setup and proposes a reference entry, stop and 2R target.
- Tracks open signal prices and sends a notification when the target or stop is reached.
- /signals lists recent signals delivered to that user.
- SQLite stores users and signals. For Render, the included persistent disk keeps this database across deploys/restarts.

## Configuration
Set `TELEGRAM_BOT_TOKEN` as a secret environment variable in the hosting provider. Never put the real token in GitHub or send it in chat.

Optional environment variables:
- `EXCHANGE_ID` (default `binance`)
- `DEFAULT_TIMEFRAME` (default `15m`)
- `SCAN_SECONDS` (default `60`; minimum 30)
- `WATCHLIST` (comma-separated CCXT symbols, default includes major coins and selected meme coins)
- `DB_PATH` (default `/var/data/smc_bot.db` on Render)

Install with `pip install -r requirements.txt` and run `python main.py`, or deploy the included `render.yaml` as a background worker.

## Important limitations
This is an initial prototype, not a validated trading system. Its watchlist is explicit, not every coin listed on the exchange; delisted/unavailable symbols are skipped. Signals are shared market ideas delivered to users who have alerts enabled, and each user only receives updates for signals delivered to them. Price monitoring uses the exchange's latest ticker, so brief price spikes, spread, slippage and candle ordering can affect outcomes. The bot does not know whether a user actually entered a trade and does not place/manage orders. No profitability is promised; verify behavior and backtest before relying on alerts.
