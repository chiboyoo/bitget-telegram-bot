import asyncio
import base64
import hashlib
import hmac
import logging
import time
import httpx
import pandas as pd
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

# ==========================================
# CONFIGURATION & LOGGING
# ==========================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = "7739259104:AAEKKWPy2LZfCQC1Lm6lOEpQJ_cVXPEfU4c"

# Bitget Live API Credentials
LIVE_API_KEY = "bg_203aa8f162f1ab5302705d5711745dcc"
LIVE_SECRET_KEY = (
    "1ea94d15af0aa29174e3b712fbd6f97e5136fe344f8c1fadb5454497873b50df"
)
# REQUIRED FOR LIVE BALANCE: Enter the Passphrase you created on Bitget for this API Key
LIVE_PASSPHRASE = "224422"

USER_SETTINGS = {
    "TRADING_MODE": "DEMO",
    "ALLOCATION_PER_ORDER": 100.0,
    "WATCHLIST": ["SOL/USDT", "BTC/USDT", "ETH/USDT"],
    "WAITING_FOR_AMOUNT": False,
    "WAITING_FOR_CUSTOM_PAIR": False,
    "DEMO_BALANCE": 1000.00,
    "REALIZED_PNL": 0.00,
    "OPEN_POSITIONS": {},
}

AVAILABLE_PAIRS = [
    "SOL/USDT",
    "BTC/USDT",
    "ETH/USDT",
    "XRP/USDT",
    "DOGE/USDT",
    "BNB/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "NEAR/USDT",
]

RSI_BUY_THRESHOLD = 45.0
RSI_SELL_THRESHOLD = 55.0


# ==========================================
# BITGET API HELPERS
# ==========================================
def generate_signature(
    timestamp: str, method: str, request_path: str, body: str, secret_key: str
) -> str:
    """Generates HMAC-SHA256 signature for Bitget V2 API."""
    message = f"{timestamp}{method.upper()}{request_path}{body}"
    mac = hmac.new(
        secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    )
    return base64.b64encode(mac.digest()).decode("utf-8")


async def fetch_real_balance():
    """Fetches real available USDT spot balance from Bitget."""
    if (
        not LIVE_PASSPHRASE
        or LIVE_PASSPHRASE == "YOUR_BITGET_PASSPHRASE_HERE"
    ):
        logger.error(
            "Bitget Passphrase missing! Please update LIVE_PASSPHRASE in main.py"
        )
        return None

    request_path = "/api/v2/spot/account/assets"
    timestamp = str(int(time.time() * 1000))
    signature = generate_signature(
        timestamp, "GET", request_path, "", LIVE_SECRET_KEY
    )

    headers = {
        "ACCESS-KEY": LIVE_API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": LIVE_PASSPHRASE,
        "Content-Type": "application/json",
        "locale": "en-US",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(
                f"https://api.bitget.com{request_path}", headers=headers
            )
            data = res.json()
            if data.get("code") == "00000" and data.get("data"):
                for asset in data["data"]:
                    if asset.get("coin") == "USDT":
                        return float(asset.get("available", 0.0))
                return 0.0
            else:
                logger.error(f"Bitget Balance Response Error: {data}")
                return None
    except Exception as e:
        logger.error(f"Error fetching Bitget balance: {e}")
        return None


async def fetch_market_data(symbol: str):
    """Fetches price ticker and calculates 15m RSI using public Bitget REST endpoints."""
    try:
        clean_symbol = symbol.replace("/", "").upper()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            # 1. Fetch Real-time Spot Ticker
            ticker_url = f"https://api.bitget.com/api/v2/spot/market/tickers?symbol={clean_symbol}"
            ticker_res = await client.get(ticker_url)
            ticker_data = ticker_res.json()

            if (
                ticker_data.get("code") != "00000"
                or not ticker_data.get("data")
            ):
                logger.error(
                    f"Ticker API error for {clean_symbol}: {ticker_data}"
                )
                return None

            live_price = float(ticker_data["data"][0]["lastPr"])

            # 2. Fetch Candlesticks (15m Granularity)
            kline_url = f"https://api.bitget.com/api/v2/spot/market/candles?symbol={clean_symbol}&granularity=15m&limit=30"
            kline_res = await client.get(kline_url)
            kline_data = kline_res.json()

            if kline_data.get("code") == "00000" and kline_data.get("data"):
                closes = [float(candle[4]) for candle in kline_data["data"]]
                closes.reverse()

                df = pd.DataFrame({"close": closes})
                delta = df["close"].diff()
                gain = delta.clip(lower=0)
                loss = -1 * delta.clip(upper=0)
                avg_gain = gain.rolling(window=14).mean()
                avg_loss = loss.rolling(window=14).mean()

                rs = avg_gain / avg_loss
                rsi_series = 100 - (100 / (1 + rs))
                current_rsi = float(rsi_series.iloc[-1])
            else:
                current_rsi = 50.0

            return {"price": live_price, "rsi": round(current_rsi, 1)}

    except Exception as e:
        logger.error(f"Bitget Market Data Error for {symbol}: {e}")
        return None


# ==========================================
# KEYBOARD BUILDERS
# ==========================================
def get_mode_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(
                "🟢 Demo Mode (Paper Trading)", callback_data="set_mode_demo"
            )
        ],
        [
            InlineKeyboardButton(
                "🔴 Live Mode (Real Bitget Funds)", callback_data="set_mode_live"
            )
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_main_keyboard():
    mode_label = (
        "🟢 DEMO" if USER_SETTINGS["TRADING_MODE"] == "DEMO" else "🔴 LIVE"
    )
    keyboard = [
        [
            InlineKeyboardButton(
                f"Mode: {mode_label} (Click to Switch)",
                callback_data="switch_mode",
            )
        ],
        [
            InlineKeyboardButton(
                "🎯 Watchlist", callback_data="manage_watchlist"
            ),
            InlineKeyboardButton(
                "💵 Allocation", callback_data="trigger_set_amount"
            ),
        ],
        [
            InlineKeyboardButton(
                "📊 Market Signals", callback_data="check_market"
            ),
            InlineKeyboardButton(
                "📈 Check Profit / PnL", callback_data="check_pnl"
            ),
        ],
        [
            InlineKeyboardButton(
                "💰 Check Balance", callback_data="check_balance"
            ),
            InlineKeyboardButton("⚙️ Bot Status", callback_data="bot_status"),
        ],
        [
            InlineKeyboardButton(
                "📖 Strategy Rules", callback_data="strategy_rules"
            )
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_watchlist_keyboard():
    keyboard = []
    for i in range(0, len(AVAILABLE_PAIRS), 2):
        row = []
        for pair in AVAILABLE_PAIRS[i : i + 2]:
            is_active = pair in USER_SETTINGS["WATCHLIST"]
            label = f"✅ {pair}" if is_active else f"➕ {pair}"
            row.append(
                InlineKeyboardButton(label, callback_data=f"toggle_pair_{pair}")
            )
        keyboard.append(row)

    keyboard.append(
        [
            InlineKeyboardButton(
                "➕ Add Custom Pair", callback_data="add_custom_pair"
            )
        ]
    )
    keyboard.append(
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
    )
    return InlineKeyboardMarkup(keyboard)


# ==========================================
# TELEGRAM HANDLERS
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_SETTINGS["WAITING_FOR_AMOUNT"] = False
    USER_SETTINGS["WAITING_FOR_CUSTOM_PAIR"] = False
    text = "🤖 **Bitget Autonomous Trading Bot**\n\nChoose execution mode to begin:"
    if update.message:
        await update.message.reply_text(
            text, reply_markup=get_mode_keyboard(), parse_mode="Markdown"
        )
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            text, reply_markup=get_mode_keyboard(), parse_mode="Markdown"
        )


async def mode_selection_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    mode = "DEMO" if query.data == "set_mode_demo" else "LIVE"
    USER_SETTINGS["TRADING_MODE"] = mode
    USER_SETTINGS["WAITING_FOR_AMOUNT"] = True

    icon = "🟢" if mode == "DEMO" else "🔴"
    prompt = (
        f"{icon} Mode set to **{mode}**.\n\n"
        "**Enter trade allocation amount in USDT per order (e.g. 100):**"
    )
    await query.message.reply_text(prompt, parse_mode="Markdown")


async def text_input_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if USER_SETTINGS.get("WAITING_FOR_CUSTOM_PAIR"):
        raw_pair = update.message.text.strip().upper()
        if "/" not in raw_pair:
            raw_pair = (
                f"{raw_pair}/USDT"
                if not raw_pair.endswith("USDT")
                else f"{raw_pair[:-4]}/USDT"
            )

        if raw_pair not in USER_SETTINGS["WATCHLIST"]:
            USER_SETTINGS["WATCHLIST"].append(raw_pair)
            if raw_pair not in AVAILABLE_PAIRS:
                AVAILABLE_PAIRS.append(raw_pair)
            msg = f"✅ Added **{raw_pair}** to watchlist!"
        else:
            msg = f"⚠️ **{raw_pair}** is already in watchlist."

        USER_SETTINGS["WAITING_FOR_CUSTOM_PAIR"] = False
        await update.message.reply_text(
            msg, reply_markup=get_watchlist_keyboard(), parse_mode="Markdown"
        )
        return

    if USER_SETTINGS.get("WAITING_FOR_AMOUNT"):
        text = update.message.text.strip().replace("$", "")
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError()

            USER_SETTINGS["ALLOCATION_PER_ORDER"] = amount
            USER_SETTINGS["WAITING_FOR_AMOUNT"] = False

            summary = (
                "🎉 **Setup Complete!**\n\n"
                f"• Execution Mode: **{USER_SETTINGS['TRADING_MODE']}**\n"
                f"• Allocation: **${amount:,.2f} USDT**\n"
                f"• Active Watchlist: {', '.join(USER_SETTINGS['WATCHLIST'])}"
            )
            await update.message.reply_text(
                summary, reply_markup=get_main_keyboard(), parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("⚠️ Enter a valid number (e.g. 100):")


async def check_balance_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer("Checking account balance...")

    mode = USER_SETTINGS["TRADING_MODE"]

    if mode == "DEMO":
        bal = USER_SETTINGS["DEMO_BALANCE"]
        msg = (
            "💰 **ACCOUNT BALANCE (DEMO MODE)**\n"
            "───────────────\n"
            f"• Available Paper Balance: **${bal:,.2f} USDT**\n"
            f"• Realized PnL: **${USER_SETTINGS['REALIZED_PNL']:+.2f} USDT**"
        )
    else:
        live_bal = await fetch_real_balance()
        if live_bal is not None:
            msg = (
                "💰 **BITGET LIVE ACCOUNT BALANCE**\n"
                "───────────────\n"
                f"• Available Spot USDT: **${live_bal:,.2f} USDT**\n"
                "• Status: **Connected to Bitget API**"
            )
        else:
            msg = (
                "💰 **ACCOUNT BALANCE (LIVE MODE)**\n"
                "───────────────\n"
                "⚠️ **Failed to retrieve Bitget balance.**\n\n"
                "Ensure you set `LIVE_PASSPHRASE` in `main.py` to the passphrase created for your API Key."
            )

    await query.message.reply_text(
        msg, reply_markup=get_main_keyboard(), parse_mode="Markdown"
    )


async def check_pnl_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer("Calculating PnL...")

    mode = USER_SETTINGS["TRADING_MODE"]
    positions = USER_SETTINGS["OPEN_POSITIONS"]

    total_unrealized_pnl = 0.0
    pnl_lines = [
        "📈 **PROFIT & LOSS (PnL) REPORT**",
        f"Mode: **{mode}**\n",
    ]

    if not positions:
        pnl_lines.append("ℹ️ No active open positions.")
    else:
        for pair, pos in positions.items():
            m_data = await fetch_market_data(pair)
            if m_data:
                curr_price = m_data["price"]
                entry_price = pos["entry_price"]
                alloc = pos["amount"]

                pnl_pct = ((curr_price - entry_price) / entry_price) * 100
                pnl_usdt = (pnl_pct / 100) * alloc
                total_unrealized_pnl += pnl_usdt

                icon = "🟢" if pnl_usdt >= 0 else "🔴"
                pnl_lines.append(
                    f"• **{pair}**: {icon} **{pnl_pct:+.2f}%** (${pnl_usdt:+.2f} USDT)\n"
                    f"  └ Entry: ${entry_price:,.2f} | Current: ${curr_price:,.2f}"
                )

    total_icon = "🚀" if total_unrealized_pnl >= 0 else "🔻"
    pnl_lines.append(
        f"\n{total_icon} **Unrealized PnL**: **${total_unrealized_pnl:+.2f} USDT**"
    )
    pnl_lines.append(
        f"💰 **Realized PnL**: **${USER_SETTINGS['REALIZED_PNL']:+.2f} USDT**"
    )

    await query.message.reply_text(
        "\n".join(pnl_lines),
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown",
    )


async def check_market_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer("Fetching live market signals...")

    if not USER_SETTINGS["WATCHLIST"]:
        await query.message.reply_text(
            "⚠️ Watchlist is empty!", reply_markup=get_main_keyboard()
        )
        return

    mode = USER_SETTINGS["TRADING_MODE"]
    status_msg = await query.message.reply_text(
        f"⏳ Fetching live market data ({mode} Mode)..."
    )

    lines = ["📊 **LIVE MARKET ANALYSIS**\n"]
    for pair in USER_SETTINGS["WATCHLIST"]:
        data = await fetch_market_data(pair)
        if data:
            rsi = data["rsi"]
            signal = (
                "🟢 BUY"
                if rsi < RSI_BUY_THRESHOLD
                else ("🔴 SELL" if rsi > RSI_SELL_THRESHOLD else "⚪ Hold")
            )
            lines.append(
                f"• **{pair}**: ${data['price']:,.2f} | RSI: {rsi:.1f} ({signal})"
            )
        else:
            lines.append(f"• **{pair}**: ⚠️ Bitget API Error")

    await status_msg.edit_text(
        "\n".join(lines),
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown",
    )


async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main_menu":
        await query.message.reply_text(
            "🤖 **Main Control Panel**", reply_markup=get_main_keyboard()
        )

    elif data == "switch_mode":
        await start_command(update, context)

    elif data == "manage_watchlist":
        pairs_str = (
            ", ".join(USER_SETTINGS["WATCHLIST"])
            if USER_SETTINGS["WATCHLIST"]
            else "None"
        )
        await query.message.reply_text(
            f"🎯 **WATCHLIST MANAGEMENT**\nActive Pairs: **{pairs_str}**",
            reply_markup=get_watchlist_keyboard(),
            parse_mode="Markdown",
        )

    elif data.startswith("toggle_pair_"):
        pair = data.replace("toggle_pair_", "")
        if pair in USER_SETTINGS["WATCHLIST"]:
            USER_SETTINGS["WATCHLIST"].remove(pair)
        else:
            USER_SETTINGS["WATCHLIST"].append(pair)
        pairs_str = (
            ", ".join(USER_SETTINGS["WATCHLIST"])
            if USER_SETTINGS["WATCHLIST"]
            else "None"
        )
        await query.message.edit_text(
            f"🎯 **WATCHLIST MANAGEMENT**\nActive Pairs: **{pairs_str}**",
            reply_markup=get_watchlist_keyboard(),
            parse_mode="Markdown",
        )

    elif data == "add_custom_pair":
        USER_SETTINGS["WAITING_FOR_CUSTOM_PAIR"] = True
        await query.message.reply_text(
            "✏️ Enter custom pair ticker (e.g. `PEPE/USDT` or `SOL`):",
            parse_mode="Markdown",
        )

    elif data == "trigger_set_amount":
        USER_SETTINGS["WAITING_FOR_AMOUNT"] = True
        await query.message.reply_text("Enter allocation size in USDT:")

    elif data == "bot_status":
        status_text = (
            "⚙️ **BOT STATUS REPORT**\n"
            "───────────────\n"
            f"• Mode: **{USER_SETTINGS['TRADING_MODE']}**\n"
            f"• Trade Allocation: **${USER_SETTINGS['ALLOCATION_PER_ORDER']:.2f} USDT**\n"
            f"• Active Watchlist: {', '.join(USER_SETTINGS['WATCHLIST'])}"
        )
        await query.message.reply_text(
            status_text, reply_markup=get_main_keyboard(), parse_mode="Markdown"
        )

    elif data == "strategy_rules":
        rules = (
            "📖 **STRATEGY RULES**\n"
            "───────────────\n"
            f"1. **Buy Trigger**: RSI (15m) < **{RSI_BUY_THRESHOLD}**\n"
            f"2. **Sell Trigger**: RSI (15m) > **{RSI_SELL_THRESHOLD}**\n"
            "3. **Position Sizing**: Fixed USDT allocation per trade."
        )
        await query.message.reply_text(
            rules, reply_markup=get_main_keyboard(), parse_mode="Markdown"
        )


# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
    app = ApplicationBuilder().token(BOT_TOKEN).request(request).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(
        CallbackQueryHandler(
            mode_selection_callback, pattern="^set_mode_(demo|live)$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(check_pnl_callback, pattern="^check_pnl$")
    )
    app.add_handler(
        CallbackQueryHandler(check_balance_callback, pattern="^check_balance$")
    )
    app.add_handler(
        CallbackQueryHandler(check_market_callback, pattern="^check_market$")
    )
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler)
    )

    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
        
