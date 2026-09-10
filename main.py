import os, json, time, hmac, hashlib, base64, asyncio, re, threading, math
from datetime import datetime
import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram import Update
from flask import Flask

# Health server for justrunmyapp
app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "Trader PRO v17 Hybrid - OK"
def run_flask(): app_flask.run(host='0.0.0.0', port=8080)

def clean_env(p=".env"):
    try:
        with open(p,'rb') as f: d=f.read()
        for bad in [b'\xef\xbb\xbf', b'\xe2\x80\x8b', b'\xe2\x80\x8c', b'\xe2\x80\x8d']:
            d=d.replace(bad,b'')
        t=d.decode(errors='ignore')
        for line in t.splitlines():
            line=line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k,v=line.split("=",1)
            k=re.sub(r'[^\x20-\x7E]','',k).strip()
            v=v.strip().strip('"').strip("'").replace('\ufeff','').replace('\u200b','').strip()
            if k and v: os.environ[k]=v
    except: pass

for path in [".env","/data/data/com.termux/files/home/secure-bot/.env","/root/secure-bot/.env","/home/ubuntu/secure-bot/.env"]:
    clean_env(path)
try:
    from dotenv import load_dotenv; load_dotenv(override=True)
except: pass

BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
API_KEY=os.getenv("BITGET_API_KEY","").strip()
SECRET_KEY=os.getenv("BITGET_SECRET_KEY","").strip()
PASSPHRASE=os.getenv("BITGET_PASSPHRASE","").strip()

MY_ID=7679796977
STATE_FILE="bot_state.json"

PAIRS={
"BTC/USDT": {"sym":"BTCUSDT","cg":"bitcoin","emoji":"â‚¿","type":"major"},
"ETH/USDT": {"sym":"ETHUSDT","cg":"ethereum","emoji":"â™¦","type":"major"},
"SOL/USDT": {"sym":"SOLUSDT","cg":"solana","emoji":"â—Ž","type":"major"},
"BNB/USDT": {"sym":"BNBUSDT","cg":"binancecoin","emoji":"B","type":"major"},
"XRP/USDT": {"sym":"XRPUSDT","cg":"ripple","emoji":"âœ•","type":"major"},
"DOGE/USDT": {"sym":"DOGEUSDT","cg":"dogecoin","emoji":"Ã","type":"meme"},
"ADA/USDT": {"sym":"ADAUSDT","cg":"cardano","emoji":"â‚³","type":"mid"},
"AVAX/USDT": {"sym":"AVAXUSDT","cg":"avalanche-2","emoji":"ðŸ”º","type":"mid"},
"LINK/USDT": {"sym":"LINKUSDT","cg":"chainlink","emoji":"ðŸ”—","type":"mid"},
"MATIC/USDT": {"sym":"MATICUSDT","cg":"matic-network","emoji":"â¬£","type":"mid"},
"DOT/USDT": {"sym":"DOTUSDT","cg":"polkadot","emoji":"â—","type":"mid"},
"SHIB/USDT": {"sym":"SHIBUSDT","cg":"shiba-inu","emoji":"ðŸ•","type":"meme"},
"PEPE/USDT": {"sym":"PEPEUSDT","cg":"pepe","emoji":"ðŸ¸","type":"meme"},
"LTC/USDT": {"sym":"LTCUSDT","cg":"litecoin","emoji":"Å","type":"mid"},
"TRX/USDT": {"sym":"TRXUSDT","cg":"tron","emoji":"T","type":"mid"},
"UNI/USDT": {"sym":"UNIUSDT","cg":"uniswap","emoji":"ðŸ¦„","type":"mid"},
"ETC/USDT": {"sym":"ETCUSDT","cg":"ethereum-classic","emoji":"ETC","type":"mid"},
"NEAR/USDT": {"sym":"NEARUSDT","cg":"near","emoji":"N","type":"mid"},
"APT/USDT": {"sym":"APTUSDT","cg":"aptos","emoji":"A","type":"mid"},
"ARB/USDT": {"sym":"ARBUSDT","cg":"arbitrum","emoji":"ðŸ”·","type":"mid"},
}

def load_state():
    d={"pair":"BTC/USDT","alloc":10.0,"mode":"DEMO","auto":False,"demo_bal":100.0,"real_bal":0.0,"trades":[],"start":time.time(),"paused":{},"positions":{}}
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE,'r') as f:
                j=json.load(f)
                for k,v in d.items():
                    if k not in j: j[k]=v
                return j
    except: pass
    return d

def save_state(s):
    with open(STATE_FILE,'w') as f: json.dump(s,f)

async def is_allowed(u): return u.effective_user.id==MY_ID

def bitget_sign(ts, method, path, body=""):
    msg=f"{ts}{method}{path}{body}"
    return base64.b64encode(hmac.new(SECRET_KEY.encode(), msg.encode(), hashlib.sha256).digest()).decode()

async def bitget_request(path):
    if len(API_KEY)<10: return None, "API missing"
    ts=str(int(time.time()*1000))
    sign=bitget_sign(ts,"GET",path,"")
    headers={"ACCESS-KEY":API_KEY,"ACCESS-SIGN":sign,"ACCESS-TIMESTAMP":ts,"ACCESS-PASSPHRASE":PASSPHRASE,"Content-Type":"application/json"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r=await c.get(f"https://api.bitget.com{path}", headers=headers)
            if r.status_code==200:
                return r.json(), None
    except Exception as e:
        return None, str(e)
    return None, "Fail"

async def get_real_balance():
    data,err=await bitget_request("/api/v2/spot/account/assets")
    if err: return None, err
    if data and data.get("code")=="00000":
        for a in data.get("data",[]):
            if a.get("coin")=="USDT":
                return float(a.get("available") or 0), None
        return 0.0, None
    return None, f"{data.get('code')}:{data.get('msg')}" if data else "Fail"

# NEW: Bitget price source - fixes MARKETS (Fail)
async def get_prices_bitget():
    out={}
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            # Bitget ticker for all symbols
            r=await c.get("https://api.bitget.com/api/v2/spot/market/tickers")
            if r.status_code==200:
                data=r.json()
                if data.get("code")=="00000":
                    tickers={t['symbol']: t for t in data.get('data',[])}
                    for label, info in PAIRS.items():
                        sym=info['sym']
                        if sym in tickers:
                            t=tickers[sym]
                            price=float(t.get('lastPr') or t.get('last') or 0)
                            # 24h change: use change24h or calculate from open
                            chg_str=t.get('change24h') or t.get('priceChange24h') or "0"
                            try:
                                chg=float(chg_str)*100 if abs(float(chg_str))<1 else float(chg_str)
                            except:
                                chg=0.0
                            if price>0:
                                out[label]=(price, chg)
                    if out:
                        return out, "Bitget"
    except Exception as e:
        pass
    return {}, f"Bitget Fail"

async def get_prices():
    # Try Bitget first (fixes your Fail)
    prices, src = await get_prices_bitget()
    if prices:
        return prices, src
    # Fallback to CoinGecko
    try:
        ids=",".join([v["cg"] for v in PAIRS.values()])
        url=f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true"
        async with httpx.AsyncClient(timeout=12) as c:
            r=await c.get(url)
            if r.status_code==200:
                data=r.json()
                out={}
                for label, info in PAIRS.items():
                    cg=info["cg"]
                    if cg in data:
                        out[label]=(float(data[cg]["usd"]), float(data[cg].get("usd_24h_change",0)))
                if out:
                    return out, "CoinGecko"
    except: pass
    return {}, "Fail - No Price Source"

# Bitget candles for real signals
async def get_candles_bitget(symbol, limit=100):
    try:
        url=f"https://api.bitget.com/api/v2/spot/market/candles?symbol={symbol}&granularity=1min&limit={limit}"
        async with httpx.AsyncClient(timeout=10) as c:
            r=await c.get(url)
            if r.status_code==200:
                data=r.json()
                if data.get("code")=="00000":
                    # data is [[ts, open, high, low, close, vol, ...]]
                    candles=data.get('data',[])
                    closes=[]
                    for k in reversed(candles): # oldest first
                        try:
                            closes.append(float(k[4]))
                        except: pass
                    return closes
    except: pass
    return []

def calc_rsi(closes, period=14):
    if len(closes)<period+1: return 50
    gains=0; losses=0
    for i in range(1, period+1):
        diff=closes[-i] - closes[-i-1]
        if diff>=0: gains+=diff
        else: losses+=-diff
    if losses==0: return 100
    rs=gains/losses
    rsi=100 - (100/(1+rs))
    # Smooth for last candles
    for i in range(len(closes)-period-1, len(closes)-1):
        diff=closes[i+1]-closes[i]
        gain=diff if diff>0 else 0
        loss=-diff if diff<0 else 0
        gains=(gains*(period-1)+gain)/period
        losses=(losses*(period-1)+loss)/period
        if losses==0: rsi=100
        else:
            rs=gains/losses
            rsi=100 - (100/(1+rs))
    return rsi

def calc_sma(closes, period):
    if len(closes)<period: return None
    return sum(closes[-period:])/period

def calc_signal_hybrid(closes):
    if len(closes)<35: return "HOLD", {"rsi":50,"sma10":0,"sma30":0,"price":closes[-1] if closes else 0}
    sma10=calc_sma(closes,10)
    sma30=calc_sma(closes,30)
    rsi=calc_rsi(closes,14)
    price=closes[-1]
    # Previous SMA for cross detection
    prev_sma10=calc_sma(closes[:-1],10)
    prev_sma30=calc_sma(closes[:-1],30)
    info={"rsi":rsi,"sma10":sma10,"sma30":sma30,"price":price,"prev_sma10":prev_sma10,"prev_sma30":prev_sma30}
    
    # Hybrid Logic:
    # BUY: price > sma30 (uptrend) AND rsi 35-55 (dip) AND sma10 crosses above sma30 OR sma10 > sma30 and rsi <55
    buy_cond = False
    if sma10 and sma30 and prev_sma10 and prev_sma30:
        uptrend = price > sma30
        dip = 35 <= rsi <= 55
        golden_cross = prev_sma10 <= prev_sma30 and sma10 > sma30
        above = sma10 > sma30
        if uptrend and dip and (golden_cross or above):
            buy_cond=True
    
    # SELL: rsi >70 OR death cross OR price < sma30
    sell_cond=False
    if sma10 and sma30 and prev_sma10 and prev_sma30:
        death_cross = prev_sma10 >= prev_sma30 and sma10 < sma30
        overbought = rsi > 70
        below_trend = price < sma30
        if death_cross or overbought or below_trend:
            sell_cond=True

    if buy_cond: return "BUY", info
    if sell_cond: return "SELL", info
    return "HOLD", info

def get_pause_duration(pair_label, pump_pct):
    ptype=PAIRS.get(pair_label,{}).get("type","mid")
    # pump_pct positive, rug is negative pump_pct
    is_pump = pump_pct>0
    abs_pct=abs(pump_pct)
    if is_pump:
        if abs_pct>=60:
            return 4*3600 if ptype=="meme" else 3600
        elif abs_pct>=30:
            return 3600 if ptype=="meme" else 1800
        else:
            return 900 if ptype=="major" else 1800
    else: # rug/dump
        if abs_pct>=25:
            return 24*3600  # blacklist day
        elif abs_pct>=15:
            return 2*3600 if ptype=="meme" else 7200
        else:
            return 1800 if ptype=="major" else 3600

async def auto_loop(app):
    while True:
        await asyncio.sleep(60)
        s=load_state()
        if not s.get("auto"): continue
        pair_label=s["pair"]
        # Check if paused
        paused=s.get("paused",{})
        if pair_label in paused:
            if time.time() < paused[pair_label]["until"]:
                continue
            else:
                del paused[pair_label]; s["paused"]=paused; save_state(s)

        sym=PAIRS.get(pair_label,{}).get("sym","BTCUSDT")
        closes=await get_candles_bitget(sym, 100)
        if len(closes)<35:
            continue
        sig,info=calc_signal_hybrid(closes)
        
        # Detect pump/rug for pause logic
        # 5 min change
        if len(closes)>=5:
            chg5 = (closes[-1]-closes[-5])/closes[-5]*100
            if abs(chg5)>=15: # significant move
                dur=get_pause_duration(pair_label, chg5)
                # If we are NOT in position and it's a pump, pause BUY
                if chg5>0 and sig=="BUY":
                    # Skip buy, pause
                    s["paused"][pair_label]={"until":time.time()+dur,"reason":f"PUMP +{chg5:.1f}%","pct":chg5}
                    save_state(s)
                    try: await app.bot.send_message(chat_id=MY_ID, text=f"âš ï¸ {pair_label} PUMP +{chg5:.1f}% -> BUY paused {dur//60}min (avoid FOMO)")
                    except: pass
                    continue
                if chg5<-15:
                    s["paused"][pair_label]={"until":time.time()+dur,"reason":f"RUG {chg5:.1f}%","pct":chg5}
                    save_state(s)
                    try: await app.bot.send_message(chat_id=MY_ID, text=f"ðŸš¨ {pair_label} RUG {chg5:.1f}% -> paused {dur//3600:.1f}h")
                    except: pass
                    # If in position, force sell at SL
                    pos=s.get("positions",{}).get(pair_label)
                    if pos:
                        entry=pos["price"]
                        loss_pct=(closes[-1]-entry)/entry*100
                        if loss_pct<=-8:
                            # hard SL
                            try: await app.bot.send_message(chat_id=MY_ID, text=f"ðŸ›‘ HARD SL {pair_label} {loss_pct:.1f}% - SELL @ ${closes[-1]:.4f}")
                            except: pass
                            # close position logic below
                            sig="SELL"

        # Position handling
        positions=s.get("positions",{})
        pos=positions.get(pair_label)

        if sig=="BUY" and not pos:
            # Open position
            price=info["price"]
            positions[pair_label]={"price":price,"alloc":s["alloc"],"time":time.time(),"high":price,"rsi":info["rsi"]}
            s["positions"]=positions
            if s["mode"]=="DEMO":
                if s["demo_bal"]>=s["alloc"]:
                    s["demo_bal"]-=s["alloc"]
                    s["trades"].append({"type":"BUY","pair":pair_label,"price":price,"time":datetime.now().strftime("%H:%M"),"rsi":info["rsi"]})
            save_state(s)
            try: await app.bot.send_message(chat_id=MY_ID, text=f"ðŸŸ¢ BUY {pair_label} @ ${price:.4f} RSI {info['rsi']:.0f} SMA10 {info['sma10']:.2f}>{info['sma30']:.2f}")
            except: pass

        elif pos:
            entry=pos["price"]
            cur=info["price"]
            pnl_pct=(cur-entry)/entry*100
            # Update high for trailing
            if cur>pos.get("high",entry):
                pos["high"]=cur
            positions[pair_label]=pos
            s["positions"]=positions

            should_sell=False
            reason=""
            # Hard SL 8%
            if pnl_pct<=-8:
                should_sell=True; reason=f"HARD SL {pnl_pct:.1f}%"
            # TP 3% or RSI overbought or death cross
            elif sig=="SELL":
                if info["rsi"]>70:
                    reason=f"RSI {info['rsi']:.0f} overbought TP {pnl_pct:.1f}%"
                elif info["sma10"]<info["sma30"]:
                    reason=f"Death Cross TP {pnl_pct:.1f}%"
                else:
                    reason=f"Trend break {pnl_pct:.1f}%"
                # Only sell if profit or hard SL already checked
                if pnl_pct>=2.5 or pnl_pct<=-3 or info["rsi"]>75:
                    should_sell=True
            # Trailing: if up >10%, trail 5% behind high
            high=pos.get("high",entry)
            if high>entry*1.10:
                trail_price=high*0.95
                if cur<=trail_price and pnl_pct>5:
                    should_sell=True; reason=f"TRAILING {pnl_pct:.1f}% from high ${high:.4f}"

            if should_sell:
                # Close
                if s["mode"]=="DEMO":
                    proceeds=s["alloc"]*(cur/entry)
                    s["demo_bal"]+=proceeds
                    s["trades"].append({"type":"SELL","pair":pair_label,"price":cur,"time":datetime.now().strftime("%H:%M"),"pnl":pnl_pct,"reason":reason})
                del positions[pair_label]
                s["positions"]=positions
                save_state(s)
                try: await app.bot.send_message(chat_id=MY_ID, text=f"ðŸ”´ SELL {pair_label} @ ${cur:.4f} {reason} PnL {pnl_pct:+.2f}%")
                except: pass
            else:
                save_state(s)

def kb(s):
    mode_icon="ðŸ”´ LIVE" if s["mode"]=="LIVE" else "ðŸ§ª DEMO"
    auto_icon="ðŸŸ¢ AUTO ON" if s["auto"] else "âšª AUTO OFF"
    pair_emoji=PAIRS.get(s["pair"],{}).get("emoji","")
    if s["mode"]=="LIVE":
        bal_btn=f"ðŸ’° ${s['real_bal']:.2f}"
    else:
        bal_btn=f"ðŸ’° Demo ${s['demo_bal']:.2f}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{mode_icon} {pair_emoji} {s['pair']}", callback_data="pair")],
        [InlineKeyboardButton(f"ðŸ’µ ${s['alloc']}", callback_data="alloc"), InlineKeyboardButton(f"ðŸ”„ To {'DEMO' if s['mode']=='LIVE' else 'LIVE'}", callback_data="switch")],
        [InlineKeyboardButton(auto_icon, callback_data="auto")],
        [InlineKeyboardButton(bal_btn, callback_data="bal"), InlineKeyboardButton("ðŸ“Š Markets", callback_data="prices")],
        [InlineKeyboardButton("ðŸ“ˆ Trades", callback_data="pnl"), InlineKeyboardButton("â¸ Paused", callback_data="paused")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update): return
    s=load_state()
    up=int(time.time()-s['start'])
    paused_info=""
    if s.get("paused"):
        paused_info=f"\nâ¸ Paused: {len(s['paused'])} pairs"
    if s["mode"]=="DEMO":
        text=f"ðŸ¤– Trader PRO v17 Hybrid\n\nðŸ§ª DEMO MODE\nPair: {PAIRS.get(s['pair'],{}).get('emoji','')} {s['pair']}\nAlloc: ${s['alloc']}\nðŸ’° Demo: ${s['demo_bal']:.2f}{paused_info}\nTrades: {len(s['trades'])}\nPositions: {len(s.get('positions',{}))}\nAuto: {'ðŸŸ¢ ON' if s['auto'] else 'âšª OFF'}\nUptime: {up//3600}h {(up%3600)//60}m\n\nStrategy: RSI+SMA+Adaptive Pause"
    else:
        text=f"ðŸ¤– Trader PRO v17 Hybrid\n\nðŸ”´ LIVE MODE\nPair: {PAIRS.get(s['pair'],{}).get('emoji','')} {s['pair']}\nAlloc: ${s['alloc']}\nðŸ’° Real: ${s['real_bal']:.2f} USDT{paused_info}\nTrades: {len(s['trades'])}\nPositions: {len(s.get('positions',{}))}\nAuto: {'ðŸŸ¢ ON' if s['auto'] else 'âšª OFF'}\nUptime: {up//3600}h {(up%3600)//60}m"
    await update.message.reply_text(text, reply_markup=kb(s))

async def btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    try: await q.answer()
    except: pass
    if not await is_allowed(update): return
    s=load_state()
    d=q.data
    if d=="back":
        up=int(time.time()-s['start'])
        paused_info=""
        if s.get("paused"):
            paused_info=f"\nâ¸ Paused: {len(s['paused'])} pairs"
        if s["mode"]=="DEMO":
            text=f"ðŸ¤– Trader PRO v17 Hybrid\n\nðŸ§ª DEMO MODE\nPair: {PAIRS.get(s['pair'],{}).get('emoji','')} {s['pair']}\nAlloc: ${s['alloc']}\nðŸ’° Demo: ${s['demo_bal']:.2f}{paused_info}\nTrades: {len(s['trades'])}\nPositions: {len(s.get('positions',{}))}\nAuto: {'ðŸŸ¢ ON' if s['auto'] else 'âšª OFF'}\nUptime: {up//3600}h {(up%3600)//60}m"
        else:
            text=f"ðŸ¤– Trader PRO v17 Hybrid\n\nðŸ”´ LIVE MODE\nPair: {PAIRS.get(s['pair'],{}).get('emoji','')} {s['pair']}\nAlloc: ${s['alloc']}\nðŸ’° Real: ${s['real_bal']:.2f} USDT{paused_info}\nTrades: {len(s['trades'])}\nPositions: {len(s.get('positions',{}))}\nAuto: {'ðŸŸ¢ ON' if s['auto'] else 'âšª OFF'}\nUptime: {up//3600}h {(up%3600)//60}m"
        try: await q.edit_message_text(text, reply_markup=kb(s))
        except: pass
    elif d=="pair":
        buttons=[]; row=[]
        for label in PAIRS.keys():
            e=PAIRS[label].get("emoji","")
            row.append(InlineKeyboardButton(f"{e} {label}", callback_data=f"set_{label}"))
            if len(row)==2:
                buttons.append(row); row=[]
        if row: buttons.append(row)
        buttons.append([InlineKeyboardButton("â¬… Back", callback_data="back")])
        try: await q.edit_message_text("ðŸ“Š Select Pair (20):", reply_markup=InlineKeyboardMarkup(buttons))
        except: pass
    elif d.startswith("set_"):
        label=d[4:]; s["pair"]=label; save_state(s)
        try: await q.edit_message_text(f"âœ… {PAIRS[label].get('emoji','')} {label}", reply_markup=kb(s))
        except: pass
    elif d=="alloc":
        try: await q.edit_message_text(
            f"ðŸ’µ Allocation (Current ${s['alloc']})\n\nMin $1 - Max $500\nBitget allows $1 but $5+ recommended\n\nType custom amount or pick:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("$1",callback_data="a_1"),InlineKeyboardButton("$5",callback_data="a_5"),InlineKeyboardButton("$10",callback_data="a_10")],
                [InlineKeyboardButton("$25",callback_data="a_25"),InlineKeyboardButton("$50",callback_data="a_50"),InlineKeyboardButton("$100",callback_data="a_100")],
                [InlineKeyboardButton("âœï¸ Custom Amount",callback_data="custom_alloc")],
                [InlineKeyboardButton("â¬… Back",callback_data="back")]
            ]))
        except: pass
    elif d.startswith("a_"):
        try:
            s["alloc"]=float(d[2:])
            if s["alloc"]<1: s["alloc"]=1
            if s["alloc"]>500: s["alloc"]=500
            save_state(s)
            try: await q.edit_message_text(f"âœ… Allocation set to ${s['alloc']}\n\nMin Bitget is $1, but $5+ is better to see profit after fees.", reply_markup=kb(s))
            except: pass
        except: pass
    elif d=="custom_alloc":
        try:
            await q.edit_message_text(
                f"âœï¸ Type your custom amount in USDT\n\nCurrent: ${s['alloc']}\nMin: $1 | Max: $500\nExample: Send '7.5' or '12.34'\n\nJust type number and send:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬… Back",callback_data="back")]])
            )
            # set flag to await next message
            s["awaiting_alloc"]=True
            save_state(s)
        except: pass
    elif d=="switch":
        if s["mode"]=="DEMO":
            try: await q.edit_message_text("âš ï¸ Switch to LIVE?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("âœ… Yes LIVE",callback_data="confirm_live")],[InlineKeyboardButton("âŒ Stay DEMO",callback_data="back")]]))
            except: pass
        else:
            s["mode"]="DEMO"; save_state(s)
            try: await q.edit_message_text("ðŸ§ª DEMO", reply_markup=kb(s))
            except: pass
    elif d=="confirm_live":
        s["mode"]="LIVE"; save_state(s)
        bal,err=await get_real_balance()
        if bal is not None: s["real_bal"]=bal; save_state(s)
        try: await q.edit_message_text(f"ðŸ”´ LIVE ${s['real_bal']:.2f}", reply_markup=kb(s))
        except: pass
    elif d=="auto":
        s["auto"]=not s["auto"]; save_state(s)
        try: await q.edit_message_text(f"{'ðŸŸ¢ AUTO ON' if s['auto'] else 'âšª AUTO OFF'} {s['pair']}", reply_markup=kb(s))
        except: pass
    elif d=="bal":
        if s["mode"]=="DEMO":
            pos_txt=""
            for p,info in s.get("positions",{}).items():
                pos_txt+=f"\nðŸ“ {p} entry ${info['price']:.4f}"
            try: await q.edit_message_text(f"ðŸ§ª DEMO Balance\n\n${s['demo_bal']:.2f} USDT{pos_txt}\nVirtual only.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬… Back",callback_data="back")]]))
            except: pass
        else:
            try: await q.edit_message_text("ðŸ”„ Fetching REAL...")
            except: pass
            bal,err=await get_real_balance()
            if err:
                try: await q.edit_message_text(f"âŒ {err}\n\nBitget fix: Transfer Funding->Spot", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬… Back",callback_data="back")]]))
                except: pass
            else:
                s["real_bal"]=bal; save_state(s)
                if bal<0.01:
                    msg=f"ðŸ’° LIVE ${bal:.8f}\nSpot empty! Transfer Funding->Spot in Bitget app."
                else:
                    msg=f"ðŸ’° LIVE Real ${bal:.6f} USDT\nMode LIVE only"
                try: await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬… Back",callback_data="back")]]))
                except: pass
    elif d=="prices":
        try: await q.edit_message_text("ðŸ“¡ Loading Bitget...")
        except: pass
        prices,src=await get_prices()
        if not prices:
            try: await q.edit_message_text(f"âŒ MARKETS {src}\nCheck internet / Bitget API\n{datetime.now().strftime('%H:%M:%S')}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬… Back",callback_data="back")]]))
            except: pass
            return
        txt=f"ðŸ“Š MARKETS ({src})\n{datetime.now().strftime('%H:%M:%S')}\n\n"
        for label in PAIRS.keys():
            data=prices.get(label)
            if data:
                p,chg=data
                mark="ðŸ‘‰ " if label==s["pair"] else ""
                emoji=PAIRS[label].get("emoji","")
                arrow="ðŸŸ¢" if chg>=0 else "ðŸ”´"
                paused = " â¸" if label in s.get("paused",{}) else ""
                if p<1:
                    txt+=f"{mark}{emoji} {label}: ${p:.6f} {arrow}{chg:+.1f}%{paused}\n"
                else:
                    txt+=f"{mark}{emoji} {label}: ${p:,.2f} {arrow}{chg:+.1f}%{paused}\n"
        try: await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬… Back",callback_data="back")]]))
        except: pass
    elif d=="pnl":
        if s["mode"]=="DEMO":
            txt=f"ðŸ“ˆ DEMO PnL\nBalance ${s['demo_bal']:.2f} Start $100 PnL {s['demo_bal']-100:+.2f} Trades {len(s['trades'])}\n\n"
        else:
            txt=f"ðŸ“ˆ LIVE PnL\nReal ${s['real_bal']:.2f} Trades {len(s['trades'])}\n\n"
        for t in s["trades"][-8:]:
            if t['type']=="BUY":
                txt+=f"ðŸŸ¢ BUY {t['pair']} @ {t.get('price',0):.4f} RSI {t.get('rsi','?')}\n"
            else:
                txt+=f"ðŸ”´ SELL {t['pair']} {t.get('pnl',0):+.1f}% {t.get('reason','')[:20]}\n"
        # positions
        if s.get("positions"):
            txt+="\nðŸ“ Open:\n"
            for p,info in s["positions"].items():
                txt+=f"{p} @ {info['price']:.4f} alloc ${info['alloc']}\n"
        try: await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬… Back",callback_data="back")]]))
        except: pass
    elif d=="paused":
        txt="â¸ Paused Pairs (Adaptive):\n\n"
        if not s.get("paused"):
            txt+="No paused pairs"
        else:
            for pair,info in s["paused"].items():
                until=info["until"]
                left=int(until-time.time())
                if left<0: left=0
                txt+=f"{pair}: {info['reason']} - {left//60}m left\n"
        txt+="\nMEME: Pump 60m Rug 24h\nMajor: Pump 15m Rug 60m"
        try: await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("â¬… Clear All",callback_data="clear_pause")],[InlineKeyboardButton("â¬… Back",callback_data="back")]]))
        except: pass
    elif d=="clear_pause":
        s["paused"]={}; save_state(s)
        try: await q.edit_message_text("âœ… Cleared paused", reply_markup=kb(s))
        except: pass

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update): return
    s=load_state()
    if not s.get("awaiting_alloc"): return
    txt=update.message.text.strip().replace("$","").replace("USDT","").strip()
    try:
        val=float(txt)
        if val<1:
            await update.message.reply_text("âŒ Min is $1. Try again, e.g. '5'")
            return
        if val>500:
            await update.message.reply_text("âŒ Max is $500. Try lower.")
            return
        s["alloc"]=val
        s["awaiting_alloc"]=False
        save_state(s)
        await update.message.reply_text(f"âœ… Custom allocation set to ${val}\n\nBitget min $1, but $5+ recommended for visible profit.", reply_markup=kb(s))
    except:
        await update.message.reply_text("âŒ Invalid. Just send a number like '7.5' or '12'")
        s["awaiting_alloc"]=False
        save_state(s)

async def main():
    threading.Thread(target=run_flask, daemon=True).start()
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CallbackQueryHandler(btn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    asyncio.create_task(auto_loop(app))
    print(f"v17 Hybrid READY - Custom Alloc - API len {len(API_KEY)}")
    await app.initialize(); await app.start(); await app.updater.start_polling(); await asyncio.Event().wait()

if __name__=="__main__": asyncio.run(main())
