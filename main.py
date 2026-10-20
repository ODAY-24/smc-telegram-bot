"""SMC Telegram bot starter: analysis only; it never places trading orders."""
import asyncio
import logging
import os
import re

import ccxt
import pandas as pd
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("smc-bot")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
EXCHANGE_ID = os.getenv("EXCHANGE_ID", "binance").strip().lower()
DEFAULT_SYMBOL = os.getenv("DEFAULT_SYMBOL", "BTC/USDT").strip().upper()
DEFAULT_TIMEFRAME = os.getenv("DEFAULT_TIMEFRAME", "15m").strip()
OHLCV_LIMIT = max(60, min(int(os.getenv("OHLCV_LIMIT", "150")), 500))
TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"}
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}/[A-Z0-9]{2,20}$")


def analyze_ohlcv(rows):
    if len(rows) < 30:
        raise ValueError("Need at least 30 candles.")
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    df = df.iloc[:-1].reset_index(drop=True)  # ignore forming candle
    if len(df) < 25:
        raise ValueError("Not enough completed candles.")
    last = df.iloc[-1]
    prior = df.iloc[-21:-1]
    close, high, low = float(last.close), float(last.high), float(last.low)
    p_high, p_low = float(prior.high.max()), float(prior.low.min())
    if close > p_high:
        structure = "Bullish BOS: close broke prior 20-candle high"
    elif close < p_low:
        structure = "Bearish BOS: close broke prior 20-candle low"
    else:
        structure = "No confirmed 20-candle BOS"

    a, c = df.iloc[-3], df.iloc[-1]
    if float(a.high) < float(c.low):
        fvg = f"Bullish FVG: {float(a.high):.8g} – {float(c.low):.8g}"
    elif float(a.low) > float(c.high):
        fvg = f"Bearish FVG: {float(c.high):.8g} – {float(a.low):.8g}"
    else:
        fvg = "No fresh three-candle FVG detected"

    if high > p_high and close < p_high:
        sweep = "Possible buy-side liquidity sweep"
    elif low < p_low and close > p_low:
        sweep = "Possible sell-side liquidity sweep"
    else:
        sweep = "No obvious liquidity sweep on latest completed candle"
    return {"close": close, "structure": structure, "fvg": fvg, "sweep": sweep}


def exchange_client():
    cls = getattr(ccxt, EXCHANGE_ID, None)
    if cls is None:
        raise ValueError(f"Unknown exchange: {EXCHANGE_ID}")
    ex = cls({"enableRateLimit": True, "timeout": 15000})
    if not ex.has.get("fetchOHLCV"):
        raise ValueError("This exchange does not support OHLCV candles.")
    return ex


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "مرحباً بك في بوت SMC التجريبي.\n"
            "/analyze BTC/USDT 15m — تحليل السوق\n"
            "/status — حالة الإعدادات\n/help — المساعدة\n\n"
            "تحليل فقط؛ لا ينفّذ صفقات."
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "الاستخدام: /analyze SYMBOL TIMEFRAME\n"
            f"مثال: /analyze {DEFAULT_SYMBOL} {DEFAULT_TIMEFRAME}\n"
            "الأطر: " + ", ".join(sorted(TIMEFRAMES)) +
            "\nالتحليل تجريبي وليس توصية مالية."
        )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            f"المنصة: {EXCHANGE_ID}\nالزوج الافتراضي: {DEFAULT_SYMBOL}\n"
            f"الإطار: {DEFAULT_TIMEFRAME}\nوضع التشغيل: تحليل فقط."
        )


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    symbol = context.args[0].upper() if context.args else DEFAULT_SYMBOL
    timeframe = context.args[1].lower() if len(context.args) > 1 else DEFAULT_TIMEFRAME
    if not SYMBOL_RE.fullmatch(symbol):
        await update.message.reply_text("صيغة الزوج غير صحيحة. مثال: BTC/USDT")
        return
    if timeframe not in TIMEFRAMES:
        await update.message.reply_text("إطار غير مدعوم. استخدم /help.")
        return
    await update.message.reply_text(f"جارٍ تحليل {symbol} على {timeframe}...")
    try:
        ex = exchange_client()
        markets = await asyncio.to_thread(ex.load_markets)
        if symbol not in markets:
            await update.message.reply_text(f"الزوج {symbol} غير متاح على {EXCHANGE_ID}.")
            return
        rows = await asyncio.to_thread(ex.fetch_ohlcv, symbol, timeframe, None, OHLCV_LIMIT)
        result = analyze_ohlcv(rows)
        await update.message.reply_text(
            f"تحليل SMC مبسّط — {symbol} ({timeframe})\n\n"
            f"آخر إغلاق مكتمل: {result['close']:.8g}\n"
            f"هيكل السوق: {result['structure']}\n"
            f"اختلال سعري: {result['fvg']}\n"
            f"السيولة: {result['sweep']}\n\n"
            "قواعد أولية وليست توصية أو ضماناً للنتيجة."
        )
    except Exception:
        log.exception("Analysis failed")
        await update.message.reply_text(
            "تعذّر التحليل. تحقق من الاتصال واسم المنصة والزوج ثم أعد المحاولة. "
            "لم يتم تنفيذ أي صفقة."
        )


def main():
    if not TOKEN or TOKEN == "put_your_telegram_bot_token_here":
        raise SystemExit("أضف TELEGRAM_BOT_TOKEN في متغيرات البيئة قبل التشغيل.")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("analyze", analyze))
    log.info("Starting SMC bot in analysis-only mode")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
