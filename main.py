import os, json, time, hmac, hashlib, base64, asyncio, re, threading
from datetime import datetime
import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram import Update
from flask import Flask

# Health server for justrunmyapp free VPS
app_flask = Flask(__name__)
@app_flask.route('/')
def home():
    return "Trader PRO v16 - OK - Running"
def run_flask():
    app_flask.run(host='0.0.0.0', port=8080)

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
"BTC/USDT": {"sym":"BTCUSDT","cg":"bitcoin","emoji":"₿"},
"ETH/USDT": {"sym":"ETHUSDT","cg":"ethereum","emoji":"♦"},
"SOL/USDT": {"sym":"SOLUSDT","cg":"solana","emoji":"◎"},
"BNB/USDT": {"sym":"BNBUSDT","cg":"binancecoin","emoji":"B"},
"XRP/USDT": {"sym":"XRPUSDT","cg":"ripple","emoji":"✕"},
"DOGE/USDT": {"sym":"DOGEUSDT","cg":"dogecoin","emoji":"Ð"},
"ADA/USDT": {"sym":"ADAUSDT","cg":"cardano","emoji":"₳"},
"AVAX/USDT": {"sym":"AVAXUSDT","cg":"avalanche-2","emoji":"🔺"},
"LINK/USDT": {"sym":"LINKUSDT","cg":"chainlink","emoji":"🔗"},
"MATIC/USDT": {"sym":"MATICUSDT","cg":"matic-network","emoji":"⬣"},
"DOT/USDT": {"sym":"DOTUSDT","cg":"polkadot","emoji":"●"},
"SHIB/USDT": {"sym":"SHIBUSDT","cg":"shiba-inu","emoji":"🐕"},
"PEPE/USDT": {"sym":"PEPEUSDT","cg":"pepe","emoji":"🐸"},
"LTC/USDT": {"sym":"LTCUSDT","cg":"litecoin","emoji":"Ł"},
"TRX/USDT": {"sym":"TRXUSDT","cg":"tron","emoji":"T"},
"UNI/USDT": {"sym":"UNIUSDT","cg":"uniswap","emoji":"🦄"},
"ETC/USDT": {"sym":"ETCUSDT","cg":"ethereum-classic","emoji":"ETC"},
"NEAR/USDT": {"sym":"NEARUSDT","cg":"near","emoji":"N"},
"APT/USDT": {"sym":"APTUSDT","cg":"aptos","emoji":"A"},
"ARB/USDT": {"sym":"ARBUSDT","cg":"arbitrum","emoji":"🔷"},
}

def load_state():
    d={"pair":"BTC/USDT","alloc":10.0,"mode":"DEMO","auto":False,"demo_bal":100.0,"real_bal":0.0,"trades":[],"start":time.time()}
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
    if data.get("code")=="00000":
        for a in data.get("data",[]):
            if a.get("coin")=="USDT":
                return float(a.get("available") or 0), None
        return 0.0, None
    return None, f"{data.get('code')}:{data.get('msg')}"

async def get_prices():
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
                return out, "CoinGecko"
    except: pass
    return {}, "Fail"

async def get_klines(cg_id):
    try:
        url=f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart?vs_currency=usd&days=1"
        async with httpx.AsyncClient(timeout=10) as c:
            r=await c.get(url)
            if r.status_code==200:
                prices=r.json().get("prices",[])
                if len(prices)>=30:
                    return [float(p[1]) for p in prices[-50:]]
    except: pass
    return []

def calc_signal(closes):
    if len(closes)<30: return "HOLD", {}
    s10=sum(closes[-10:])/10; s30=sum(closes[-30:])/30
    p10=sum(closes[-11:-1])/10; p30=sum(closes[-31:-1])/30
    info={"s10":s10,"s30":s30,"price":closes[-1]}
    if p10<=p30 and s10>p30: return "BUY", info
    if p10>=p30 and s10<p30: return "SELL", info
    return "HOLD", info

async def auto_loop(app):
    while True:
        await asyncio.sleep(60)
        s=load_state()
        if not s.get("auto"): continue
        cg=PAIRS.get(s["pair"],{}).get("cg","bitcoin")
        closes=await get_klines(cg)
        if len(closes)<30: continue
        sig,info=calc_signal(closes)
        if sig=="BUY" and s["mode"]=="DEMO" and s["demo_bal"]>=s["alloc"]:
            s["demo_bal"]-=s["alloc"]
            s["trades"].append({"type":"BUY","pair":s["pair"],"price":info["price"],"time":datetime.now().strftime("%H:%M")})
            save_state(s)
            try: await app.bot.send_message(chat_id=MY_ID, text=f"🟢 {s['pair']} BUY ${s['alloc']} @ ${info['price']:.2f}")
            except: pass

def kb(s):
    mode_icon="🔴 LIVE" if s["mode"]=="LIVE" else "🧪 DEMO"
    auto_icon="🟢 AUTO ON" if s["auto"] else "⚪ AUTO OFF"
    pair_emoji=PAIRS.get(s["pair"],{}).get("emoji","")
    if s["mode"]=="LIVE":
        bal_btn=f"💰 ${s['real_bal']:.2f}"
    else:
        bal_btn=f"💰 Demo ${s['demo_bal']:.2f}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{mode_icon} {pair_emoji} {s['pair']}", callback_data="pair")],
        [InlineKeyboardButton(f"💵 ${s['alloc']}", callback_data="alloc"), InlineKeyboardButton(f"🔄 To {'DEMO' if s['mode']=='LIVE' else 'LIVE'}", callback_data="switch")],
        [InlineKeyboardButton(auto_icon, callback_data="auto")],
        [InlineKeyboardButton(bal_btn, callback_data="bal"), InlineKeyboardButton("📊 Markets", callback_data="prices")],
        [InlineKeyboardButton("📈 Trades", callback_data="pnl")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update): return
    s=load_state()
    up=int(time.time()-s['start'])
    if s["mode"]=="DEMO":
        text=f"🤖 Trader PRO v16\n\n🧪 DEMO MODE\nPair: {PAIRS.get(s['pair'],{}).get('emoji','')} {s['pair']}\nAlloc: ${s['alloc']}\n💰 Demo: ${s['demo_bal']:.2f}\nTrades: {len(s['trades'])}\nAuto: {'🟢 ON' if s['auto'] else '⚪ OFF'}\nUptime: {up//3600}h {(up%3600)//60}m"
    else:
        text=f"🤖 Trader PRO v16\n\n🔴 LIVE MODE\nPair: {PAIRS.get(s['pair'],{}).get('emoji','')} {s['pair']}\nAlloc: ${s['alloc']}\n💰 Real: ${s['real_bal']:.2f} USDT\nTrades: {len(s['trades'])}\nAuto: {'🟢 ON' if s['auto'] else '⚪ OFF'}\nUptime: {up//3600}h {(up%3600)//60}m"
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
        if s["mode"]=="DEMO":
            text=f"🤖 Trader PRO v16\n\n🧪 DEMO MODE\nPair: {PAIRS.get(s['pair'],{}).get('emoji','')} {s['pair']}\nAlloc: ${s['alloc']}\n💰 Demo: ${s['demo_bal']:.2f}\nTrades: {len(s['trades'])}\nAuto: {'🟢 ON' if s['auto'] else '⚪ OFF'}\nUptime: {up//3600}h {(up%3600)//60}m"
        else:
            text=f"🤖 Trader PRO v16\n\n🔴 LIVE MODE\nPair: {PAIRS.get(s['pair'],{}).get('emoji','')} {s['pair']}\nAlloc: ${s['alloc']}\n💰 Real: ${s['real_bal']:.2f} USDT\nTrades: {len(s['trades'])}\nAuto: {'🟢 ON' if s['auto'] else '⚪ OFF'}\nUptime: {up//3600}h {(up%3600)//60}m"
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
        buttons.append([InlineKeyboardButton("⬅ Back", callback_data="back")])
        try: await q.edit_message_text("📊 Select Pair (20):", reply_markup=InlineKeyboardMarkup(buttons))
        except: pass
    elif d.startswith("set_"):
        label=d[4:]; s["pair"]=label; save_state(s)
        try: await q.edit_message_text(f"✅ {PAIRS[label].get('emoji','')} {label}", reply_markup=kb(s))
        except: pass
    elif d=="alloc":
        try: await q.edit_message_text("💵 Allocation:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("$5",callback_data="a_5"),InlineKeyboardButton("$10",callback_data="a_10"),InlineKeyboardButton("$25",callback_data="a_25"),InlineKeyboardButton("$50",callback_data="a_50")],[InlineKeyboardButton("⬅ Back",callback_data="back")]]))
        except: pass
    elif d.startswith("a_"):
        s["alloc"]=float(d[2:]); save_state(s)
        try: await q.edit_message_text(f"✅ ${s['alloc']}", reply_markup=kb(s))
        except: pass
    elif d=="switch":
        if s["mode"]=="DEMO":
            try: await q.edit_message_text("⚠️ Switch to LIVE?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes LIVE",callback_data="confirm_live")],[InlineKeyboardButton("❌ Stay DEMO",callback_data="back")]]))
            except: pass
        else:
            s["mode"]="DEMO"; save_state(s)
            try: await q.edit_message_text("🧪 DEMO", reply_markup=kb(s))
            except: pass
    elif d=="confirm_live":
        s["mode"]="LIVE"; save_state(s)
        bal,err=await get_real_balance()
        if bal is not None: s["real_bal"]=bal; save_state(s)
        try: await q.edit_message_text(f"🔴 LIVE ${s['real_bal']:.2f}", reply_markup=kb(s))
        except: pass
    elif d=="auto":
        s["auto"]=not s["auto"]; save_state(s)
        try: await q.edit_message_text(f"{'🟢 AUTO ON' if s['auto'] else '⚪ AUTO OFF'} {s['pair']}", reply_markup=kb(s))
        except: pass
    elif d=="bal":
        if s["mode"]=="DEMO":
            try: await q.edit_message_text(f"🧪 DEMO Balance\n\n${s['demo_bal']:.2f} USDT\nVirtual money only.\nSwitch to LIVE for real.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back",callback_data="back")]]))
            except: pass
        else:
            try: await q.edit_message_text("🔄 Fetching REAL...")
            except: pass
            bal,err=await get_real_balance()
            if err:
                try: await q.edit_message_text(f"❌ {err}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back",callback_data="back")]]))
                except: pass
            else:
                s["real_bal"]=bal; save_state(s)
                if bal<0.01:
                    msg=f"💰 LIVE ${bal:.8f}\nSpot empty! Transfer Funding->Spot in Bitget app."
                else:
                    msg=f"💰 LIVE Real ${bal:.6f} USDT\nMode LIVE only, no demo shown"
                try: await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back",callback_data="back")]]))
                except: pass
    elif d=="prices":
        try: await q.edit_message_text("📡 Loading...")
        except: pass
        prices,src=await get_prices()
        txt=f"📊 MARKETS ({src})\n{datetime.now().strftime('%H:%M:%S')}\n\n"
        for label in PAIRS.keys():
            data=prices.get(label)
            if data:
                p,chg=data
                mark="👉 " if label==s["pair"] else ""
                emoji=PAIRS[label].get("emoji","")
                arrow="🟢" if chg>=0 else "🔴"
                if p<1:
                    txt+=f"{mark}{emoji} {label}: ${p:.6f} {arrow}{chg:+.1f}%\n"
                else:
                    txt+=f"{mark}{emoji} {label}: ${p:,.2f} {arrow}{chg:+.1f}%\n"
        try: await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back",callback_data="back")]]))
        except: pass
    elif d=="pnl":
        if s["mode"]=="DEMO":
            txt=f"📈 DEMO PnL\nBalance ${s['demo_bal']:.2f} PnL {s['demo_bal']-100:+.2f} Trades {len(s['trades'])}\n"
        else:
            txt=f"📈 LIVE PnL\nReal ${s['real_bal']:.2f} Trades {len(s['trades'])}\n"
        for t in s["trades"][-5:]:
            txt+=f"{t['type']} {t['pair']} @ {t.get('price',0):.2f}\n"
        try: await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back",callback_data="back")]]))
        except: pass

async def main():
    threading.Thread(target=run_flask, daemon=True).start()
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CallbackQueryHandler(btn))
    asyncio.create_task(auto_loop(app))
    print(f"v16 PRO VPS READY - API len {len(API_KEY)}")
    await app.initialize(); await app.start(); await app.updater.start_polling(); await asyncio.Event().wait()

if __name__=="__main__": asyncio.run(main())
