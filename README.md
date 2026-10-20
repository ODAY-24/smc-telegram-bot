# SMC Telegram Bot

Starter Telegram bot for public-market-data analysis using simple SMC-inspired heuristics (structure break, three-candle fair-value gap, and possible liquidity sweep). **Analysis only:** it does not submit or manage trades.

## Configure
1. Create a Telegram bot with BotFather and copy its token.
2. In your hosting provider, set `TELEGRAM_BOT_TOKEN` as a secret environment variable. Never commit the real token or an `.env` file.
3. Optional variables: `EXCHANGE_ID` (default `binance`), `DEFAULT_SYMBOL` (default `BTC/USDT`), `DEFAULT_TIMEFRAME` (default `15m`), and `OHLCV_LIMIT` (default `150`).
4. Install dependencies with `pip install -r requirements.txt` and run `python main.py`, or deploy the included `render.yaml` as a background worker.
5. In Telegram, send `/start`, then try `/analyze BTC/USDT 15m`.

## Commands
- `/start` — welcome
- `/help` — usage
- `/status` — configuration status
- `/analyze [SYMBOL] [TIMEFRAME]` — fetch public candles and analyze

Supported timeframes: 1m, 5m, 15m, 30m, 1h, 2h, 4h, 1d.

## Important
The SMC rules here are an educational prototype, not a complete or validated trading strategy. No profitability is promised. Test with public data before relying on alerts. This bot uses no exchange API keys and places no orders.
