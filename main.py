"""Multi-user SMC crypto signal bot. Signals only; never places orders."""
import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timezone
from dotenv import load_dotenv
import ccxt
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
EXCHANGE_ID = os.getenv("EXCHANGE_ID", "binance").strip().lower()
TIMEFRAME = os.getenv("DEFAULT_TIMEFRAME", "15m").strip()
SCAN_SECONDS = max(30, int(os.getenv("SCAN_SECONDS", "60")))
DB_PATH = os.getenv("DB_PATH", "/var/data/smc_bot.db")
WATCHLIST = [s.strip().upper() for s in os.getenv(
    "WATCHLIST",
    "BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT,XRP/USDT,DOGE/USDT,ADA/USDT,AVAX/USDT,"
    "LINK/USDT,SHIB/USDT,PEPE/USDT,BONK/USDT,WIF/USDT,FLOKI/USDT"
).split(",") if s.strip()]
LIMIT = 100
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("smc-bot")
_exchange = None
_exchange_lock = asyncio.Lock()


def connect_db():
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""CREATE TABLE IF NOT EXISTS users (
        chat_id INTEGER PRIMARY KEY, joined_at TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
        direction TEXT NOT NULL, entry REAL NOT NULL, stop REAL NOT NULL, target REAL NOT NULL,
        status TEXT NOT NULL, candle_ts INTEGER NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(symbol, timeframe, candle_ts, direction))""")
    con.execute("""CREATE TABLE IF NOT EXISTS recipients (
        signal_id INTEGER NOT NULL, chat_id INTEGER NOT NULL,
        PRIMARY KEY(signal_id, chat_id))""")
    con.commit()
    return con


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def analyze(rows):
    # Only completed candles are considered; last row is usually still forming.
    if len(rows) < 35:
        return None
    candles = rows[:-1]
    prior = candles[-21:-1]
    last = candles[-1]
    previous = candles[-2]
    close = float(last[4])
    high, low = float(last[2]), float(last[3])
    prior_high = max(float(c[2]) for c in prior)
    prior_low = min(float(c[3]) for c in prior)
    recent_lows = [float(c[3]) for c in candles[-8:]]
    recent_highs = [float(c[2]) for c in candles[-8:]]
    a, c = candles[-3], candles[-1]
    bull_fvg = float(a[2]) < float(c[3])
    bear_fvg = float(a[3]) > float(c[2])
    bull_sweep = low < prior_low and close > prior_low
    bear_sweep = high > prior_high and close < prior_high
    bull_bos = close > prior_high
    bear_bos = close < prior_low

    # Conservative prototype: require a structure break plus an FVG or sweep.
    if bull_bos and (bull_fvg or bull_sweep):
        entry = close
        stop = min(recent_lows)
        risk = entry - stop
        if risk <= 0 or risk / entry > 0.08:
            return None
        return {"direction": "LONG", "entry": entry, "stop": stop,
                "target": entry + 2 * risk, "ts": int(last[0])}
    if bear_bos and (bear_fvg or bear_sweep):
        entry = close
        stop = max(recent_highs)
        risk = stop - entry
        if risk <= 0 or risk / entry > 0.08:
            return None
        return {"direction": "SHORT", "entry": entry, "stop": stop,
                "target": entry - 2 * risk, "ts": int(last[0])}
    return None


async def get_exchange():
    global _exchange
    async with _exchange_lock:
        if _exchange is None:
            cls = getattr(ccxt, EXCHANGE_ID, None)
            if cls is None:
                raise ValueError("Unknown exchange configured")
            _exchange = cls({"enableRateLimit": True, "timeout": 20000})
            await asyncio.to_thread(_exchange.load_markets)
        return _exchange


def fmt(value):
    return f"{value:.8g}"


async def send_to_recipients(app, signal_id, message):
    con = connect_db()
    ids = [r[0] for r in con.execute(
        "SELECT chat_id FROM recipients WHERE signal_id=?", (signal_id,)).fetchall()]
    con.close()
    for chat_id in ids:
        try:
            await app.bot.send_message(chat_id=chat_id, text=message)
        except Exception:
            log.exception("Could not notify chat %s", chat_id)


async def scan_once(app):
    ex = await get_exchange()
    con = connect_db()
    users = [r[0] for r in con.execute("SELECT chat_id FROM users").fetchall()]
    if not users:
        con.close()
        return
    for symbol in WATCHLIST:
        try:
            if symbol not in ex.markets:
                continue
            rows = await asyncio.to_thread(ex.fetch_ohlcv, symbol, TIMEFRAME, None, LIMIT)
            setup = analyze(rows)
            if not setup:
                continue
            created = utc_now()
            try:
                cur = con.execute(
                    """INSERT INTO signals(symbol,timeframe,direction,entry,stop,target,status,candle_ts,created_at)
                    VALUES(?,?,?,?,?,?, 'OPEN',?,?)""",
                    (symbol, TIMEFRAME, setup["direction"], setup["entry"], setup["stop"],
                     setup["target"], setup["ts"], created))
                signal_id = cur.lastrowid
            except sqlite3.IntegrityError:
                continue
            con.executemany("INSERT OR IGNORE INTO recipients(signal_id,chat_id) VALUES(?,?)",
                            [(signal_id, chat_id) for chat_id in users])
            con.commit()
            message = (
                f"📊 إشارة SMC جديدة — {symbol}\n"
                f"الاتجاه: {setup['direction']} (إشارة فقط)\n"
                f"الإطار: {TIMEFRAME}\nالدخول المرجعي: {fmt(setup['entry'])}\n"
                f"وقف الخسارة: {fmt(setup['stop'])}\nالهدف (2R): {fmt(setup['target'])}\n"
                f"السبب: كسر هيكل مع FVG أو سحب سيولة\nوقت الإشارة: {created}\n\n"
                "راقب التنفيذ يدويًا؛ النتائج غير مضمونة."
            )
            await send_to_recipients(app, signal_id, message)
        except Exception:
            log.exception("Scan failed for %s", symbol)
    con.close()


async def monitor_once(app):
    con = connect_db()
    active = con.execute(
        "SELECT id,symbol,direction,entry,stop,target FROM signals WHERE status='OPEN'"
    ).fetchall()
    con.close()
    if not active:
        return
    ex = await get_exchange()
    for signal_id, symbol, direction, entry, stop, target in active:
        try:
            ticker = await asyncio.to_thread(ex.fetch_ticker, symbol)
            price = float(ticker.get("last") or 0)
            if price <= 0:
                continue
            status = None
            if direction == "LONG":
                if price <= stop:
                    status = "STOP"
                elif price >= target:
                    status = "TARGET"
            else:
                if price >= stop:
                    status = "STOP"
                elif price <= target:
                    status = "TARGET"
            if status:
                con = connect_db()
                cur = con.execute(
                    "UPDATE signals SET status=? WHERE id=? AND status='OPEN'",
                    (status, signal_id))
                con.commit()
                con.close()
                if cur.rowcount:
                    label = "تحقق الهدف" if status == "TARGET" else "وصل السعر إلى وقف الخسارة"
                    await send_to_recipients(
                        app, signal_id,
                        f"🔔 تحديث الإشارة — {symbol}\n{label}\n"
                        f"السعر المرصود: {fmt(price)}\nالاتجاه: {direction}\n"
                        "هذه متابعة سعرية للإشارة وليست سجل تنفيذ فعلي."
                    )
        except Exception:
            log.exception("Monitor failed for %s", symbol)


async def background_loop(app):
    await asyncio.sleep(3)
    while True:
        try:
            await scan_once(app)
            await monitor_once(app)
        except Exception:
            log.exception("Background cycle failed")
        await asyncio.sleep(SCAN_SECONDS)


async def post_init(app):
    app.bot_data["scanner_task"] = asyncio.create_task(background_loop(app))
    log.info("SMC scanner started: %d symbols", len(WATCHLIST))


async def post_shutdown(app):
    task = app.bot_data.get("scanner_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.effective_user:
        return
    con = connect_db()
    con.execute("INSERT OR IGNORE INTO users(chat_id,joined_at) VALUES(?,?)",
                (update.effective_chat.id, utc_now()))
    con.commit()
    con.close()
    await update.effective_message.reply_text(
        "أهلًا بك في بوت إشارات SMC للعملات الرقمية والميم كوين.\n"
        "تم تفعيل استقبال الإشارات والتحديثات لهذا الحساب.\n\n"
        "/signals — إشاراتك المفتوحة\n/stopalerts — إيقاف التنبيهات\n"
        "/start — إعادة تفعيل التنبيهات\n/help — المساعدة\n\n"
        "إشارات فقط؛ لا ينفّذ البوت صفقات. لا توجد ضمانات للربح."
    )


async def stopalerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat:
        return
    con = connect_db()
    con.execute("DELETE FROM users WHERE chat_id=?", (update.effective_chat.id,))
    con.execute("DELETE FROM recipients WHERE chat_id=?", (update.effective_chat.id,))
    con.commit()
    con.close()
    await update.effective_message.reply_text(
        "تم إيقاف التنبيهات لهذا الحساب. أرسل /start لإعادة تفعيلها."
    )


async def signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat:
        return
    con = connect_db()
    rows = con.execute(
        """SELECT s.symbol,s.direction,s.entry,s.stop,s.target,s.status,s.created_at
        FROM signals s JOIN recipients r ON r.signal_id=s.id
        WHERE r.chat_id=? ORDER BY s.id DESC LIMIT 15""",
        (update.effective_chat.id,)).fetchall()
    con.close()
    if not rows:
        await update.effective_message.reply_text("لا توجد إشارات مسجلة لهذا الحساب حتى الآن.")
        return
    lines = ["آخر إشاراتك:"]
    for symbol, direction, entry, stop, target, status, created in rows:
        lines.append(f"{symbol} {direction} | {status}\nدخول {fmt(entry)} · وقف {fmt(stop)} · هدف {fmt(target)}\n{created}")
    await update.effective_message.reply_text("\n\n".join(lines))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "/start — تفعيل التنبيهات\n/signals — آخر إشاراتك\n"
        "/stopalerts — إيقاف التنبيهات\n\n"
        f"المنصة: {EXCHANGE_ID} | الإطار: {TIMEFRAME}\n"
        "الرموز التي تتم مراقبتها تضبط عبر WATCHLIST. التحليل تجريبي وقد يعطي إشارات خاطئة."
    )


def main():load_dotenv()
    if not TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN as a secret environment variable.")
    app = (Application.builder().token(TOKEN).post_init(post_init)
           .post_shutdown(post_shutdown).build())
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("signals", signals))
    app.add_handler(CommandHandler("stopalerts", stopalerts))
    log.info("Starting signal-only multi-user SMC bot")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
