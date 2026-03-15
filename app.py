from flask import Flask, jsonify, request, render_template, session, redirect, url_for
import sqlite3
import os
import json
import threading
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import urllib.request
import secrets

try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

DB_PATH = os.environ.get("DB_PATH", "pawnshop.db")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

CATEGORIES = [
    "Gold - Buying", "Gold - Selling",
    "Silver - Buying", "Silver - Selling",
    "Jewelry", "Ladies Rings", "Mens Rings", "Watches",
    "Tennis Shoes / Sneakers", "Electronics", "Musical Instruments",
    "Firearms", "Tools & Equipment", "Coins & Collectibles",
    "Luxury Bags", "Other",
]

_price_cache = {"gold": None, "silver": None, "ts": None}
_cache_lock  = threading.Lock()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS customers (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name   TEXT NOT NULL,
                phone        TEXT DEFAULT '',
                email        TEXT DEFAULT '',
                contact_pref TEXT DEFAULT 'both',
                categories   TEXT DEFAULT '[]',
                notes        TEXT DEFAULT '',
                added_date   TEXT,
                active       INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS price_history (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                date   TEXT UNIQUE,
                gold   REAL,
                silver REAL
            );
            CREATE TABLE IF NOT EXISTS settings_store (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS message_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                sent_at    TEXT,
                subject    TEXT,
                body       TEXT,
                categories TEXT,
                method     TEXT,
                sent_count INTEGER DEFAULT 0
            );
        """)

init_db()

SETTING_ENV_MAP = {
    "shop_name":      "SHOP_NAME",
    "email_from":     "EMAIL_FROM",
    "email_password": "EMAIL_PASSWORD",
    "email_smtp":     "EMAIL_SMTP",
    "email_port":     "EMAIL_PORT",
    "twilio_sid":     "TWILIO_SID",
    "twilio_token":   "TWILIO_TOKEN",
    "twilio_from":    "TWILIO_FROM",
}

def get_setting(key, default=""):
    env_key = SETTING_ENV_MAP.get(key)
    if env_key:
        val = os.environ.get(env_key)
        if val:
            return val
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT value FROM settings_store WHERE key=?", (key,)
            ).fetchone()
            return row["value"] if row else default
    except Exception:
        return default

def save_setting_db(key, value):
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings_store (key, value) VALUES (?,?)",
            (key, value)
        )

def _fetch_live():
    for url in ["https://api.metals.live/v1/spot/gold,silver",
                "https://api.metals.live/v1/spot"]:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "GoldenBallPawn/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
                prices = {}
                if isinstance(data, list):
                    for item in data:
                        prices.update(item)
                else:
                    prices = data
                gold   = prices.get("gold") or prices.get("XAU")
                silver = prices.get("silver") or prices.get("XAG")
                if gold:
                    return float(gold), float(silver) if silver else None
        except Exception:
            continue
    return None, None

def get_prices(force=False):
    global _price_cache
    with _cache_lock:
        now   = datetime.now()
        stale = (_price_cache["ts"] is None or
                 (now - _price_cache["ts"]).seconds > 300)
        if force or stale:
            gold, silver = _fetch_live()
            if gold:
                _price_cache.update({"gold": gold, "silver": silver, "ts": now})
                today = now.strftime("%Y-%m-%d")
                try:
                    with get_db() as conn:
                        conn.execute(
                            "INSERT OR REPLACE INTO price_history (date,gold,silver)"
                            " VALUES (?,?,?)", (today, gold, silver))
                except Exception:
                    pass
        return _price_cache["gold"], _price_cache["silver"]

def predict_price(history, col_index):
    vals = [r[col_index] for r in history if r[col_index] is not None][-7:]
    if len(vals) < 2:
        return None, "insufficient data"
    n   = len(vals)
    xs  = list(range(n))
    xm  = sum(xs) / n
    ym  = sum(vals) / n
    num = sum((x - xm) * (y - ym) for x, y in zip(xs, vals))
    den = sum((x - xm) ** 2 for x in xs)
    if den == 0:
        return round(vals[-1], 2), "stable"
    slope = num / den
    pred  = vals[-1] + slope
    if   slope >  0.5: trend = "rising"
    elif slope < -0.5: trend = "falling"
    else:              trend = "stable"
    return round(pred, 2), trend

def auth_required():
    if not APP_PASSWORD:
        return False
    return not session.get("authed")

@app.route("/login", methods=["GET", "POST"])
def login():
    if not APP_PASSWORD:
        return redirect(url_for("index"))
    error = ""
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["authed"] = True
            return redirect(url_for("index"))
        error = "Incorrect password"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.pop("authed", None)
    return redirect(url_for("login"))

@app.route("/")
def index():
    if auth_required():
        return redirect(url_for("login"))
    return render_template("index.html", categories=CATEGORIES)

@app.route("/api/dashboard")
def api_dashboard():
    if auth_required():
        return jsonify({"error": "unauthorized"}), 401
    gold, silver = get_prices()
    with get_db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM customers WHERE active=1"
        ).fetchone()["c"]
        hist_rows = conn.execute(
            "SELECT date, gold, silver FROM price_history"
            " ORDER BY date DESC LIMIT 30"
        ).fetchall()
    history = list(reversed([dict(r) for r in hist_rows]))
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    yest = next((r for r in history if r["date"] == yesterday), None)
    if not yest and len(history) >= 2:
        yest = history[-2]
    gold_chg = silver_chg = gold_pct = silver_pct = None
    if yest and gold and yest.get("gold"):
        gold_chg = round(gold - yest["gold"], 2)
        gold_pct = round((gold_chg / yest["gold"]) * 100, 2)
    if yest and silver and yest.get("silver"):
        silver_chg = round(silver - yest["silver"], 2)
        silver_pct = round((silver_chg / yest["silver"]) * 100, 2)
    tuples = [(r["date"], r.get("gold"), r.get("silver")) for r in history]
    gpred, gtrend = predict_price(tuples, 1)
    spred, strend = predict_price(tuples, 2)
    return jsonify({
        "gold": gold, "silver": silver,
        "gold_chg": gold_chg, "gold_pct": gold_pct,
        "silver_chg": silver_chg, "silver_pct": silver_pct,
        "ratio": round(gold / silver, 1) if gold and silver else None,
        "customer_count": count,
        "history": history,
        "gold_pred": gpred, "gold_trend": gtrend,
        "silver_pred": spred, "silver_trend": strend,
        "updated": datetime.now().strftime("%I:%M %p"),
    })

@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    if auth_required():
        return jsonify({"error": "unauthorized"}), 401
    gold, silver = get_prices(force=True)
    return jsonify({"gold": gold, "silver": silver, "ok": bool(gold)})

@app.route("/api/customers", methods=["GET"])
def api_list_customers():
    if auth_required():
        return jsonify({"error": "unauthorized"}), 401
    q = request.args.get("q", "").strip()
    with get_db() as conn:
        if q:
            like = f"%{q}%"
            rows = conn.execute(
                "SELECT * FROM customers WHERE active=1 AND"
                " (first_name LIKE ? OR phone LIKE ? OR email LIKE ?)"
                " ORDER BY first_name", (like, like, like)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM customers WHERE active=1 ORDER BY first_name"
            ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["categories"] = json.loads(d["categories"]) if d["categories"] else []
        result.append(d)
    return jsonify(result)

@app.route("/api/customers", methods=["POST"])
def api_add_customer():
    if auth_required():
        return jsonify({"error": "unauthorized"}), 401
    d = request.json
    if not d.get("first_name"):
        return jsonify({"error": "first_name required"}), 400
    with get_db() as conn:
        conn.execute(
            "INSERT INTO customers"
            " (first_name,phone,email,contact_pref,categories,notes,added_date)"
            " VALUES (?,?,?,?,?,?,?)",
            (d["first_name"], d.get("phone",""), d.get("email",""),
             d.get("contact_pref","both"), json.dumps(d.get("categories",[])),
             d.get("notes",""), datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
    return jsonify({"ok": True})

@app.route("/api/customers/<int:cid>", methods=["PUT"])
def api_update_customer(cid):
    if auth_required():
        return jsonify({"error": "unauthorized"}), 401
    d = request.json
    with get_db() as conn:
        conn.execute(
            "UPDATE customers SET first_name=?,phone=?,email=?,contact_pref=?,"
            "categories=?,notes=? WHERE id=?",
            (d["first_name"], d.get("phone",""), d.get("email",""),
             d.get("contact_pref","both"), json.dumps(d.get("categories",[])),
             d.get("notes",""), cid),
        )
    return jsonify({"ok": True})

@app.route("/api/customers/<int:cid>", methods=["DELETE"])
def api_delete_customer(cid):
    if auth_required():
        return jsonify({"error": "unauthorized"}), 401
    with get_db() as conn:
        conn.execute("DELETE FROM customers WHERE id=?", (cid,))
    return jsonify({"ok": True})

@app.route("/api/recipients", methods=["POST"])
def api_recipients():
    if auth_required():
        return jsonify({"error": "unauthorized"}), 401
    cats = request.json.get("categories", [])
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM customers WHERE active=1").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["categories"] = json.loads(d["categories"]) if d["categories"] else []
        if not cats or any(c in d["categories"] for c in cats):
            result.append({"id": d["id"], "first_name": d["first_name"],
                           "phone": d["phone"], "email": d["email"],
                           "contact_pref": d["contact_pref"]})
    return jsonify(result)

@app.route("/api/send", methods=["POST"])
def api_send():
    if auth_required():
        return jsonify({"error": "unauthorized"}), 401
    d       = request.json
    cats    = d.get("categories", [])
    body_t  = d.get("body", "").strip()
    subject = d.get("subject", "").strip()
    method  = d.get("method", "both")
    if not body_t:
        return jsonify({"error": "Message body required"}), 400
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM customers WHERE active=1").fetchall()
    customers = []
    for r in rows:
        c = dict(r)
        c["categories"] = json.loads(c["categories"]) if c["categories"] else []
        if not cats or any(cat in c["categories"] for cat in cats):
            customers.append(c)
    if not customers:
        return jsonify({"error": "No recipients match selected categories"}), 400
    gold, silver = get_prices()
    g_str = f"${gold:,.2f}"   if gold   else ""
    s_str = f"${silver:,.2f}" if silver else ""
    shop  = get_setting("shop_name", "Golden Ball Pawn")
    log = []
    ok  = 0
    for c in customers:
        body = (body_t
                .replace("{name}",   c["first_name"])
                .replace("{gold}",   g_str)
                .replace("{silver}", s_str))
        body = f"Hi {c['first_name']}! {body}\n\n- {shop}"
        pref = c["contact_pref"]
        if method in ("sms","both") and pref in ("sms","both") and c.get("phone"):
            r = _send_sms(c["phone"], body)
            log.append(f"SMS  > {c['first_name']} ({c['phone']}): {r}")
            if r == "OK": ok += 1
        if method in ("email","both") and pref in ("email","both") and c.get("email"):
            r = _send_email(c["email"], subject or f"Message from {shop}", body)
            log.append(f"Email > {c['first_name']} ({c['email']}): {r}")
            if r == "OK": ok += 1
    with get_db() as conn:
        conn.execute(
            "INSERT INTO message_log (sent_at,subject,body,categories,method,sent_count)"
            " VALUES (?,?,?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M"), subject, body_t,
             json.dumps(cats), method, ok),
        )
    return jsonify({"ok": True, "sent": ok, "total": len(customers), "log": log})

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    if auth_required():
        return jsonify({"error": "unauthorized"}), 401
    keys = ["shop_name","shop_phone","email_from","email_smtp","email_port","twilio_from"]
    return jsonify({k: get_setting(k) for k in keys})

@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    if auth_required():
        return jsonify({"error": "unauthorized"}), 401
    d = request.json
    for k, v in d.items():
        save_setting_db(k, v)
    return jsonify({"ok": True})

def _send_sms(phone, body):
    if not TWILIO_AVAILABLE:
        return "SKIPPED - install twilio"
    sid   = get_setting("twilio_sid")
    token = get_setting("twilio_token")
    from_ = get_setting("twilio_from")
    if not all([sid, token, from_]):
        return "SKIPPED - Twilio not configured"
    try:
        client = TwilioClient(sid, token)
        digits = "".join(ch for ch in phone if ch.isdigit())
        to = ("+1" + digits) if len(digits) == 10 else ("+" + digits)
        client.messages.create(body=body, from_=from_, to=to)
        return "OK"
    except Exception as e:
        return f"ERROR: {str(e)[:80]}"

def _send_email(to_addr, subject, body):
    smtp_h = get_setting("email_smtp", "smtp.gmail.com")
    smtp_p = get_setting("email_port", "587")
    from_e = get_setting("email_from")
    passwd = get_setting("email_password")
    if not all([from_e, passwd]):
        return "SKIPPED - email not configured"
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = from_e
        msg["To"]      = to_addr
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(smtp_h, int(smtp_p)) as srv:
            srv.starttls()
            srv.login(from_e, passwd)
            srv.sendmail(from_e, to_addr, msg.as_string())
        return "OK"
    except Exception as e:
        return f"ERROR: {str(e)[:80]}"

if __name__ == "__main__":
    app.run(debug=True, port=5000)
