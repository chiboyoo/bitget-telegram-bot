import asyncio
import logging
import os
import traceback
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

# User session settings & balances
USER_SETTINGS = {
    "TRADING_MODE": "DEMO",
    "ALLOCATION_PER_ORDER": 100.0,
    "WATCHLIST": ["SOL/USDT", "BTC/USDT", "ETH/USDT"],
    "WAITING_FOR_AMOUNT": False,
    "WAITING_FOR_CUSTOM_PAIR": False,
    "BALANCE": 1000.00,  # Starting paper balance (USDT)
    "REALIZED_PNL": 0.00,
    "OPEN_POSITIONS": {
        "SOL/USDT": {"amount": 100.0, "entry_price": 98.50},
        "BTC/USDT": {"amount": 100.0, "entry_price": 78200.00},
    },
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
# MARKET DATA FETCHING
# ==========================================
async def fetch_market_data(symbol: str, mode: str):
    """Fetches real live ticker prices and calculates real-time RSI from Bitget API."""
    try:
        # Format symbol for Bitget API (e.g. SOL/USDT -> SOLUSDT)
        clean_symbol = symbol.replace("/", "")

        async with httpx.AsyncClient(timeout=10.0) as client:
            # 1. Fetch Real-Time Ticker Price
            ticker_url = f"https://api.bitget.com/api/v2/spot/market/tickers?symbol={clean_symbol}"
            ticker_res = await client.get(ticker_url)
            ticker_data = ticker_res.json()

            if (
                ticker_data.get("code") != "00000"
                or not ticker_data.get("data")
            ):
                return None

            live_price = float(ticker_data["data"][0]["lastPr"])

            # 2. Fetch Recent 15m Candlestick Data for RSI
            kline_url = f"https://api.bitget.com/api/v2/spot/market/candles?symbol={clean_symbol}&granularity=15m&limit=30"
            kline_res = await client.get(kline_url)
            kline_data = kline_res.json()

            if kline_data.get("code") == "00000" and kline_data.get("data"):
                closes = [float(candle[4]) for candle in kline_data["data"]]
                closes.reverse()  # Chronological order

                # Calculate 14-period RSI
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
        logger.error(f"Bitget API Error for {symbol}: {e}")
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
                InlineKeyboardButton(
                    label, callback_data=f"toggle_pair_{pair}"
                )
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
        [
            InlineKeyboardButton(
                "🔙 Back to Main Menu", callback_data="main_menu"
            )
        ]
    )
    return InlineKeyboardMarkup(keyboard)


# ==========================================
# TELEGRAM HANDLERS
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_SETTINGS["WAITING_FOR_AMOUNT"] = False
    USER_SETTINGS["WAITING_FOR_CUSTOM_PAIR"] = False
    welcome_text = (
        "🤖 **Bitget Autonomous Trading Bot**\n\n"
        "**Step 1:** Select execution mode:"
    )
    if update.message:
        await update.message.reply_text(
            welcome_text,
            reply_markup=get_mode_keyboard(),
            parse_mode="Markdown",
        )
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            welcome_text,
            reply_markup=get_mode_keyboard(),
            parse_mode="Markdown",
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
    prompt_text = (
        f"{icon} Mode set to **{mode}**.\n\n"
        "**Step 2:** Enter trade size in USDT (e.g. 100):"
    )
    await query.message.reply_text(prompt_text, parse_mode="Markdown")


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
                f"• Mode: {USER_SETTINGS['TRADING_MODE']}\n"
                f"• Allocation: ${amount:,.2f} USDT\n"
                f"• Pairs: {', '.join(USER_SETTINGS['WATCHLIST'])}"
            )
            await update.message.reply_text(
                summary,
                reply_markup=get_main_keyboard(),
                parse_mode="Markdown",
            )
        except ValueError:
            await update.message.reply_text(
                "⚠️ Enter a valid number (e.g. 100):"
            )


async def check_pnl_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer("Calculating PnL...")

    mode = USER_SETTINGS["TRADING_MODE"]
    positions = USER_SETTINGS["OPEN_POSITIONS"]

    total_unrealized_pnl = 0.0
    pnl_lines = ["📈 **PROFIT & LOSS (PnL) REPORT**", f"Mode: **{mode}**\n"]

    if not positions:
        pnl_lines.append("ℹ️ No active open positions.")
    else:
        for pair, pos in positions.items():
            m_data = await fetch_market_data(pair, mode)
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
        f"💰 **Realized Profit**: **${USER_SETTINGS['REALIZED_PNL']:+.2f} USDT**"
    )

    await query.message.reply_text(
        "\n".join(pnl_lines),
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown",
    )


async def check_balance_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer("Checking account balance...")

    mode = USER_SETTINGS["TRADING_MODE"]
    bal = USER_SETTINGS["BALANCE"]
    realized = USER_SETTINGS["REALIZED_PNL"]

    msg = (
        "💰 **ACCOUNT BALANCE**\n"
        "───────────────\n"
        f"• Environment: **{mode}**\n"
        f"• Available USDT: **${bal:,.2f} USDT**\n"
        f"• Realized Earnings: **${realized:+.2f} USDT**\n"
        f"• Total Equity: **${(bal + realized):,.2f} USDT**"
    )
    await query.message.reply_text(
        msg, reply_markup=get_main_keyboard(), parse_mode="Markdown"
    )


async def check_market_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer("Fetching signals...")

    if not USER_SETTINGS["WATCHLIST"]:
        await query.message.reply_text(
            "⚠️ Watchlist is empty!", reply_markup=get_main_keyboard()
        )
        return

    mode = USER_SETTINGS["TRADING_MODE"]
    status_msg = await query.message.reply_text(
        f"⏳ Fetching indicators ({mode} Mode)..."
    )

    try:
        lines = ["📊 **MARKET ANALYSIS**\n"]
        for pair in USER_SETTINGS["WATCHLIST"]:
            data = await fetch_market_data(pair, mode)
            if data:
                rsi = data["rsi"]
                signal = (
                    "🟢 BUY"
                    if rsi < RSI_BUY_THRESHOLD
                    else (
                        "🔴 SELL"
                        if rsi > RSI_SELL_THRESHOLD
                        else "⚪ Hold"
                    )
                )
                lines.append(
                    f"• **{pair}**: ${data['price']:,.2f} | RSI: {rsi:.1f} ({signal})"
                )
            else:
                lines.append(f"• **{pair}**: ⚠️ Error")

        await status_msg.edit_text(
            "\n".join(lines),
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Error in check_market: {e}")
        await status_msg.edit_text(
            "⚠️ Network timeout fetching data.",
            reply_markup=get_main_keyboard(),
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
            f"🎯 **WATCHLIST**\nActive: **{pairs_str}**",
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
            f"🎯 **WATCHLIST**\nActive: **{pairs_str}**",
            reply_markup=get_watchlist_keyboard(),
            parse_mode="Markdown",
        )

    elif data == "add_custom_pair":
        USER_SETTINGS["WAITING_FOR_CUSTOM_PAIR"] = True
        await query.message.reply_text(
            "✏️ Enter pair ticker (e.g., `PEPE/USDT`):", parse_mode="Markdown"
        )

    elif data == "trigger_set_amount":
        USER_SETTINGS["WAITING_FOR_AMOUNT"] = True
        await query.message.reply_text("Enter allocation amount in USDT:")

    elif data == "bot_status":
        status_text = (
            "⚙️ **BOT STATUS**\n"
            f"Mode: {USER_SETTINGS['TRADING_MODE']}\n"
            f"Allocation: ${USER_SETTINGS['ALLOCATION_PER_ORDER']:.2f} USDT\n"
            f"Watchlist: {', '.join(USER_SETTINGS['WATCHLIST']) if USER_SETTINGS['WATCHLIST'] else 'None'}"
        )
        await query.message.reply_text(
            status_text,
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown",
        )

    elif data == "strategy_rules":
        rules = (
            f"📖 **RULES**\n1. Buy: RSI < {RSI_BUY_THRESHOLD}\n2. Sell: RSI >"
            f" {RSI_SELL_THRESHOLD}"
        )
        await query.message.reply_text(
            rules, reply_markup=get_main_keyboard(), parse_mode="Markdown"
        )


# ==========================================
# MAIN INITIALIZATION
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
        CallbackQueryHandler(
            check_balance_callback, pattern="^check_balance$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(check_market_callback, pattern="^check_market$")
    )
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler)
    )

    logger.info("Bot started successfully.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
                
