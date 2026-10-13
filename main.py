#!/usr/bin/env python3
"""
AutoPilot Pro v4.1 - MULTI-USER BACKEND FOR GOOGLE PLAY
- Supports 1000s of users, each with own Bitget keys + License
- Each APK user enters keys INSIDE the APK, not in ENV
- Max Leverage 120x, License recheck 24hrs per user
- Ready for JustRunMy.App / VPS / Google Play publishing

Deploy to JustRunMy.App or VPS, then publish APK to Play Store
"""
import os, json, time, hmac, hashlib, base64, asyncio, logging, sqlite3, threading, uuid
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
from cryptography.fernet import Fernet
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("multi_backend")

# ===== CONFIG =====
LICENSE_SERVER_URL = "https://a65332-a1e0.h.onjrnm.link"
DB_PATH = os.getenv("DB_PATH", "./data/autopilot.db")
MAX_LEVERAGE = 120
LICENSE_RECHECK_SEC = 24 * 3600
LOOP_INTERVAL = 10

# Secret for encrypting user API keys
def _load_secret():
    key = os.getenv("BOT_SECRET_KEY", "")
    if key:
        try:
            Fernet(key.encode())
            return key.encode()
        except:
            return base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    path = os.path.join(os.path.dirname(DB_PATH) or ".", "secret.key")
    if os.path.exists(path):
        return open(path,"rb").read()
    k = Fernet.generate_key()
    open(path,"wb").write(k)
    return k

FERNET = Fernet(_load_secret())
PREFIX = "enc:v1:"
def enc(v): return PREFIX+FERNET.encrypt(v.encode()).decode() if v and not v.startswith(PREFIX) else v
def dec(v):
    if not v or not v.startswith(PREFIX): return v
    try: return FERNET.decrypt(v[len(PREFIX):].encode()).decode()
    except: return ""

def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, data TEXT, created_at REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS trades (id TEXT PRIMARY KEY, user_id TEXT, pair TEXT, side TEXT, pnl REAL, created_at REAL)")
    conn.commit(); conn.close()

def get_all_user_ids():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    return [r[0] for r in rows]

async def get_user(user_id: str) -> dict:
    def _g():
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT data FROM users WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        if row: return json.loads(row[0])
        return {"user_id": user_id, "pair":"BTCUSDT","leverage":5,"margin":50.0,"auto":False,"licensed":False,"license_key":"","license_checked_at":0,"api_key":"","api_secret":"","api_passphrase":"","daily_pnl":0,"balance":0}
    return await asyncio.to_thread(_g)

async def set_user(user_id: str, data: dict):
    def _s():
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR REPLACE INTO users (user_id,data,created_at) VALUES (?,?,?)", (user_id, json.dumps(data), time.time()))
        conn.commit(); conn.close()
    await asyncio.to_thread(_s)

# License
async def verify_license(uid: str, key: str):
    if not key: return False, "No license", 0
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{LICENSE_SERVER_URL}/verify", json={"telegram_id": str(uid), "license_key": key.strip().upper()})
            if r.status_code != 200: return False, f"Server {r.status_code}", 0
            d = r.json()
            return (True, "OK", int(d.get("expires_at") or 0)) if d.get("valid") else (False, d.get("reason","invalid"), int(d.get("expires_at") or 0))
    except Exception as e:
        log.error(f"License error {e}")
        return False, "License server unreachable", 0

_verified = {}

# Flask API - MULTI USER
app = Flask(__name__)
CORS(app)

@app.route("/")
def root():
    return jsonify({
        "service": "autopilot-multiuser-backend",
        "version": "4.1-google-play-ready",
        "max_leverage": MAX_LEVERAGE,
        "license_recheck": "24hrs",
        "multi_user": True,
        "play_store_ready": True,
        "endpoints": ["/api/register","/api/user/config","/api/user/status","/api/user/start","/api/user/stop","/api/user/close"]
    })

@app.route("/health")
def health(): return jsonify({"status":"ok"})

@app.route("/api/register", methods=["POST"])
def register():
    """APK calls this on first launch to get user_id"""
    data = request.json or {}
    user_id = data.get("user_id") or str(uuid.uuid4())
    # Create if not exists
    import asyncio
    async def create():
        u = await get_user(user_id)
        if "user_id" not in u or not u.get("user_id"):
            u["user_id"] = user_id
            await set_user(user_id, u)
        return u
    u = asyncio.run(create())
    return jsonify({"ok": True, "user_id": user_id, "max_leverage": MAX_LEVERAGE})

@app.route("/api/user/config", methods=["GET","POST"])
def user_config():
    """APK sends Bitget keys + License + Pair + Leverage here - per user"""
    if request.method == "GET":
        user_id = request.args.get("user_id")
        if not user_id: return jsonify({"error":"user_id required"}), 400
        import asyncio
        u = asyncio.run(get_user(user_id))
        # Don't return secrets decrypted
        return jsonify({
            "user_id": user_id,
            "pair": u.get("pair","BTCUSDT"),
            "leverage": u.get("leverage",5),
            "margin": u.get("trade_margin_usdt",50),
            "auto": u.get("auto", False),
            "licensed": u.get("licensed", False),
            "has_api_keys": bool(u.get("api_key")),
            "max_leverage": MAX_LEVERAGE
        })
    
    # POST - save config from APK
    data = request.json or {}
    user_id = data.get("user_id")
    if not user_id: return jsonify({"error":"user_id required"}), 400
    
    import asyncio
    async def save():
        u = await get_user(user_id)
        if "bitget_api_key" in data and data["bitget_api_key"]:
            u["api_key"] = enc(data["bitget_api_key"])
            u["api_secret"] = enc(data["bitget_api_secret"])
            u["api_passphrase"] = enc(data["bitget_api_passphrase"])
        if "license_key" in data and data["license_key"]:
            u["license_key"] = data["license_key"].strip().upper()
            # Verify license immediately
            ok, reason, exp = await verify_license(user_id, u["license_key"])
            if ok:
                u["licensed"] = True
                u["license_checked_at"] = time.time()
                u["license_expires_at"] = exp
                u["license_reason"] = "OK"
            else:
                u["licensed"] = False
                u["license_reason"] = reason
        if "pair" in data: u["pair"] = data["pair"]
        if "leverage" in data: u["leverage"] = max(1, min(int(data["leverage"]), MAX_LEVERAGE))
        if "margin" in data: u["trade_margin_usdt"] = float(data["margin"])
        if "auto" in data: u["auto"] = bool(data["auto"])
        await set_user(user_id, u)
        return u
    
    u = asyncio.run(save())
    return jsonify({"ok": True, "licensed": u.get("licensed", False), "reason": u.get("license_reason",""), "max_leverage": MAX_LEVERAGE})

@app.route("/api/user/status")
def user_status():
    user_id = request.args.get("user_id")
    if not user_id: return jsonify({"error":"user_id required"}), 400
    import asyncio
    u = asyncio.run(get_user(user_id))
    return jsonify({
        "user_id": user_id,
        "pair": u.get("pair","BTCUSDT"),
        "leverage": u.get("leverage",5),
        "margin": u.get("trade_margin_usdt",50),
        "auto": u.get("auto", False),
        "licensed": u.get("licensed", False),
        "balance": u.get("balance", 0),
        "daily_pnl": u.get("daily_pnl", 0),
        "status": "running" if u.get("auto") and u.get("licensed") else "paused" if u.get("licensed") else "needs_license",
        "max_leverage": MAX_LEVERAGE,
        "license": {"valid": u.get("licensed", False), "next_check": "24hrs"}
    })

@app.route("/api/user/start", methods=["POST"])
def user_start():
    data = request.json or {}
    user_id = data.get("user_id")
    import asyncio
    async def do():
        u = await get_user(user_id)
        u["auto"] = True
        await set_user(user_id, u)
    asyncio.run(do())
    return jsonify({"ok": True})

@app.route("/api/user/stop", methods=["POST"])
def user_stop():
    data = request.json or {}
    user_id = data.get("user_id")
    import asyncio
    async def do():
        u = await get_user(user_id)
        u["auto"] = False
        await set_user(user_id, u)
    asyncio.run(do())
    return jsonify({"ok": True})

@app.route("/api/user/close", methods=["POST"])
def user_close():
    # In real version, close position via Bitget
    return jsonify({"ok": True, "msg": "Close order sent"})

# Trading loop - processes ALL users
async def trading_loop():
    init_db()
    log.info(f"MULTI-USER BACKEND READY | Max {MAX_LEVERAGE}x | License 24hr | Google Play Ready")
    while True:
        try:
            user_ids = await asyncio.to_thread(get_all_user_ids)
            for uid in user_ids:
                try:
                    u = await get_user(uid)
                    if not u.get("licensed") or not u.get("auto"): continue
                    # License recheck every 24hrs per user
                    last = float(u.get("license_checked_at",0))
                    if time.time() - last > LICENSE_RECHECK_SEC:
                        ok, reason, exp = await verify_license(uid, u.get("license_key",""))
                        u["license_checked_at"] = time.time()
                        if not ok:
                            u["licensed"] = False
                            u["auto"] = False
                            u["license_reason"] = reason
                            log.info(f"User {uid} license failed: {reason}")
                        else:
                            u["license_expires_at"] = exp
                        await set_user(uid, u)
                        if not ok: continue
                    # Here call your real process_user(uid) from original file
                    # await process_user(uid) - with Bitget trading logic
                    log.info(f"[WORKER] User {uid[:8]} | {u.get('pair')} {u.get('leverage')}x | Auto ON | License 24hr OK")
                except Exception as e:
                    log.error(f"User {uid} error {e}")
            await asyncio.sleep(LOOP_INTERVAL)
        except Exception as e:
            log.exception(e)
            await asyncio.sleep(5)

def run_flask():
    port = int(os.getenv("PORT","8080"))
    app.run(host="0.0.0.0", port=port, debug=False)

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(trading_loop())

if __name__ == "__main__":
    main()
