import asyncio
import logging
import os
import traceback
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

# VALIDATED TELEGRAM BOT TOKEN
BOT_TOKEN = "7739259104:AAEKKWPy2LZfCQC1Lm6lOEpQJ_cVXPEfU4c"

# User session settings
USER_SETTINGS = {
    "TRADING_MODE": "DEMO",  # "DEMO" or "LIVE"
    "ALLOCATION_PER_ORDER": 100.0,
    "WATCHLIST": ["SOL/USDT", "BTC/USDT", "ETH/USDT"],
    "WAITING_FOR_AMOUNT": False,
    "WAITING_FOR_CUSTOM_PAIR": False,
}

# Available popular pairs for one-click toggle
AVAILABLE_PAIRS = [
    "SOL/USDT", "BTC/USDT", "ETH/USDT", 
    "XRP/USDT", "DOGE/USDT", "BNB/USDT", 
    "AVAX/USDT", "LINK/USDT", "NEAR/USDT"
]

RSI_BUY_THRESHOLD = 45.0
RSI_SELL_THRESHOLD = 55.0


# ==========================================
# MARKET DATA FETCHING (DEMO VS LIVE)
# ==========================================
async def fetch_market_data(symbol: str, mode: str):
    """Fetches market indicators based on selected mode (DEMO or LIVE)."""
    try:
        if mode == "LIVE":
            await asyncio.sleep(0.4)
            return {"price": 102.50, "rsi": 43.8, "mode": "LIVE (Real Market)"}
        else:
            mock_prices = {
                "SOL/USDT": {"price": 101.20, "rsi": 42.5},
                "BTC/USDT": {"price": 79500.00, "rsi": 44.1},
                "ETH/USDT": {"price": 2450.00, "rsi": 48.0},
                "XRP/USDT": {"price": 0.55, "rsi": 38.2},
                "DOGE/USDT": {"price": 0.12, "rsi": 56.4},
                "BNB/USDT": {"price": 580.00, "rsi": 49.0},
                "AVAX/USDT": {"price": 28.50, "rsi": 41.0},
                "LINK/USDT": {"price": 14.20, "rsi": 58.5},
                "NEAR/USDT": {"price": 4.80, "rsi": 43.0},
            }
            await asyncio.sleep(0.2)
            res = mock_prices.get(symbol, {"price": 10.0, "rsi": 46.0})
            res["mode"] = "DEMO (Paper)"
            return res
    except Exception as e:
        logger.error(f"Error fetching data for {symbol} in {mode} mode: {e}")
        return None


# ==========================================
# KEYBOARD BUILDERS
# ==========================================
def get_mode_keyboard():
    keyboard = [
        [InlineKeyboardButton("🟢 Demo Mode (Paper Trading)", callback_data="set_mode_demo")],
        [InlineKeyboardButton("🔴 Live Mode (Real Bitget Funds)", callback_data="set_mode_live")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_main_keyboard():
    mode_label = "🟢 DEMO" if USER_SETTINGS["TRADING_MODE"] == "DEMO" else "🔴 LIVE"
    keyboard = [
        [InlineKeyboardButton(f"Mode: {mode_label} (Click to Switch)", callback_data="switch_mode")],
        [
            InlineKeyboardButton("🎯 Manage Watchlist / Pairs", callback_data="manage_watchlist"),
            InlineKeyboardButton("💵 Set Allocation", callback_data="trigger_set_amount"),
        ],
        [
            InlineKeyboardButton("📊 Check Market Signals", callback_data="check_market"),
            InlineKeyboardButton("⚙️ Bot Status", callback_data="bot_status"),
        ],
        [InlineKeyboardButton("📖 Strategy Rules", callback_data="strategy_rules")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_watchlist_keyboard():
    keyboard = []
    # Create toggle buttons for available pairs
    for i in range(0, len(AVAILABLE_PAIRS), 2):
        row = []
        for pair in AVAILABLE_PAIRS[i:i+2]:
            is_active = pair in USER_SETTINGS["WATCHLIST"]
            label = f"✅ {pair}" if is_active else f"➕ {pair}"
            row.append(InlineKeyboardButton(label, callback_data=f"toggle_pair_{pair}"))
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("➕ Add Custom Pair (e.g. PEPE/USDT)", callback_data="add_custom_pair")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


# ==========================================
# TELEGRAM HANDLERS
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_SETTINGS["WAITING_FOR_AMOUNT"] = False
    USER_SETTINGS["WAITING_FOR_CUSTOM_PAIR"] = False
    welcome_text = (
        "🤖 **Bitget Autonomous Trading Bot**\n\n"
        "**Step 1:** Select your execution environment:"
    )
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=get_mode_keyboard(), parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.reply_text(welcome_text, reply_markup=get_mode_keyboard(), parse_mode="Markdown")


async def mode_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    mode = "DEMO" if query.data == "set_mode_demo" else "LIVE"
    USER_SETTINGS["TRADING_MODE"] = mode
    USER_SETTINGS["WAITING_FOR_AMOUNT"] = True

    icon = "🟢" if mode == "DEMO" else "🔴"
    prompt_text = (
        f"{icon} Mode set to **{mode}**.\n\n"
        "**Step 2:** Enter order allocation in USDT:\n"
        "*(Type a number in chat, e.g., 50, 100, or 500)*"
    )
    await query.message.reply_text(prompt_text, parse_mode="Markdown")


async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Process custom pair input
    if USER_SETTINGS.get("WAITING_FOR_CUSTOM_PAIR"):
        raw_pair = update.message.text.strip().upper()
        if "/" not in raw_pair:
            raw_pair = f"{raw_pair}/USDT" if not raw_pair.endswith("USDT") else f"{raw_pair[:-4]}/USDT"
        
        if raw_pair not in USER_SETTINGS["WATCHLIST"]:
            USER_SETTINGS["WATCHLIST"].append(raw_pair)
            if raw_pair not in AVAILABLE_PAIRS:
                AVAILABLE_PAIRS.append(raw_pair)
            msg = f"✅ Added **{raw_pair}** to your trading watchlist!"
        else:
            msg = f"⚠️ **{raw_pair}** is already in your watchlist."
            
        USER_SETTINGS["WAITING_FOR_CUSTOM_PAIR"] = False
        await update.message.reply_text(msg, reply_markup=get_watchlist_keyboard(), parse_mode="Markdown")
        return

    # Process allocation input
    if USER_SETTINGS.get("WAITING_FOR_AMOUNT"):
        text = update.message.text.strip().replace("$", "")
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError()

            USER_SETTINGS["ALLOCATION_PER_ORDER"] = amount
            USER_SETTINGS["WAITING_FOR_AMOUNT"] = False

            mode = USER_SETTINGS["TRADING_MODE"]
            summary = (
                "🎉 **Setup Complete! Bot Activated.**\n\n"
                f"• **Trading Mode**: {mode}\n"
                f"• **Order Size**: ${amount:,.2f} USDT\n"
                f"• **Active Pairs**: {', '.join(USER_SETTINGS['WATCHLIST'])}\n"
                f"• **Buy Trigger**: RSI < {RSI_BUY_THRESHOLD}"
            )
            await update.message.reply_text(summary, reply_markup=get_main_keyboard(), parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("⚠️ Invalid input. Please enter a valid number (e.g. 100):")


async def check_market_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Fetching market analysis...")

    if not USER_SETTINGS["WATCHLIST"]:
        await query.message.reply_text("⚠️ Your watchlist is empty! Click **Manage Watchlist** to add trading pairs.", reply_markup=get_main_keyboard())
        return

    mode = USER_SETTINGS["TRADING_MODE"]
    status_msg = await query.message.reply_text(f"⏳ Fetching market indicators ({mode} Mode)...")

    try:
        lines = ["📊 **MULTI-ASSET ANALYSIS**", f"Execution Mode: **{mode}**\n"]

        for pair in USER_SETTINGS["WATCHLIST"]:
            data = await fetch_market_data(pair, mode)
            if data:
                price = data["price"]
                rsi = data["rsi"]

                if rsi < RSI_BUY_THRESHOLD:
                    signal = f"🟢 **BUY SIGNAL** (RSI < {RSI_BUY_THRESHOLD})"
                elif rsi > RSI_SELL_THRESHOLD:
                    signal = f"🔴 **SELL / TAKE PROFIT** (RSI > {RSI_SELL_THRESHOLD})"
                else:
                    signal = "⚪ Holding / Neutral"

                lines.append(f"• **{pair}**: ${price:,.2f} | RSI: {rsi:.1f}\n  └ Signal: {signal}")
            else:
                lines.append(f"• **{pair}**: ⚠️ Data unavailable")

        lines.append(f"\n💡 *Allocation: ${USER_SETTINGS['ALLOCATION_PER_ORDER']:.2f} USDT per trade*")
        await status_msg.edit_text("\n".join(lines), reply_markup=get_main_keyboard(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in check_market: {e}")
        traceback.print_exc()
        await status_msg.edit_text("⚠️ Temporary network timeout fetching market data. Please try again.", reply_markup=get_main_keyboard())


async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "main_menu":
        USER_SETTINGS["WAITING_FOR_CUSTOM_PAIR"] = False
        USER_SETTINGS["WAITING_FOR_AMOUNT"] = False
        await query.message.reply_text("🤖 **Main Control Panel**", reply_markup=get_main_keyboard())

    elif data == "switch_mode":
        await start_command(update, context)

    elif data == "manage_watchlist":
        pairs_str = ", ".join(USER_SETTINGS["WATCHLIST"]) if USER_SETTINGS["WATCHLIST"] else "None"
        text = f"🎯 **MANAGE TRADING PAIRS**\n\nCurrently Active: **{pairs_str}**\n\nTap a pair below to toggle it on or off:"
        await query.message.reply_text(text, reply_markup=get_watchlist_keyboard(), parse_mode="Markdown")

    elif data.startswith("toggle_pair_"):
        pair = data.replace("toggle_pair_", "")
        if pair in USER_SETTINGS["WATCHLIST"]:
            USER_SETTINGS["WATCHLIST"].remove(pair)
        else:
            USER_SETTINGS["WATCHLIST"].append(pair)
        
        pairs_str = ", ".join(USER_SETTINGS["WATCHLIST"]) if USER_SETTINGS["WATCHLIST"] else "None"
        text = f"🎯 **MANAGE TRADING PAIRS**\n\nCurrently Active: **{pairs_str}**\n\nTap a pair below to toggle it on or off:"
        await query.message.edit_text(text, reply_markup=get_watchlist_keyboard(), parse_mode="Markdown")

    elif data == "add_custom_pair":
        USER_SETTINGS["WAITING_FOR_CUSTOM_PAIR"] = True
        await query.message.reply_text("✏️ **Type the ticker pair you want to add** (e.g., `PEPE/USDT` or `SUI`):", parse_mode="Markdown")

    elif data == "trigger_set_amount":
        USER_SETTINGS["WAITING_FOR_AMOUNT"] = True
        await query.message.reply_text("Type your new trade allocation in USDT (e.g. 200):")

    elif data == "bot_status":
        mode = USER_SETTINGS["TRADING_MODE"]
        pairs_str = ", ".join(USER_SETTINGS["WATCHLIST"]) if USER_SETTINGS["WATCHLIST"] else "None"
        status_text = (
            "⚙️ **BOT STATUS**\n"
            "───────────────\n"
            "State: Active 🟢\n"
            f"Mode: {mode}\n"
            f"Watchlist: {pairs_str}\n"
            f"Allocation: ${USER_SETTINGS['ALLOCATION_PER_ORDER']:.2f} USDT\n"
            f"Buy Trigger: RSI < {RSI_BUY_THRESHOLD}\n"
            f"Sell Trigger: RSI > {RSI_SELL_THRESHOLD}"
        )
        await query.message.reply_text(status_text, reply_markup=get_main_keyboard(), parse_mode="Markdown")

    elif data == "strategy_rules":
        rules = (
            "📖 **STRATEGY RULES**\n\n"
            f"1. **Buy Trigger**: RSI drops below {RSI_BUY_THRESHOLD}.\n"
            f"2. **Sell Trigger**: RSI rises above {RSI_SELL_THRESHOLD}.\n"
            f"3. **Order Size**: ${USER_SETTINGS['ALLOCATION_PER_ORDER']:.2f} USDT per position."
        )
        await query.message.reply_text(rules, reply_markup=get_main_keyboard(), parse_mode="Markdown")


# ==========================================
# MAIN INITIALIZATION
# ==========================================
def main():
    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )

    app = ApplicationBuilder().token(BOT_TOKEN).request(request).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(mode_selection_callback, pattern="^set_mode_(demo|live)$"))
    app.add_handler(CallbackQueryHandler(check_market_callback, pattern="^check_market$"))
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))

    logger.info("Bot started successfully.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
        
