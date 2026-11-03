"""AANDJ Shop Performance Reporting System – Flask web app."""
import base64
import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import struct
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, Response, abort, flash, g, redirect, render_template, request, send_from_directory, session, url_for)
from markupsafe import Markup, escape
from werkzeug.security import check_password_hash, generate_password_hash

import automation
import reports
from db import BACKUPS, UPLOADS, connect, ensure_db
from i18n import tr, translate_html

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024
app.secret_key = os.environ.get("AANDJ_SECRET") or hashlib.sha256(os.path.abspath(__file__).encode()).hexdigest()

ROLES = {
    "gm": "GM / CEO", "finance": "Finance & HR", "coo": "COO", "marketing": "Brand & Marketing",
    "manager": "Shop manager", "accountant": "Accountant", "owner": "Owner",
}
# What each role may open. Managers are further limited to their own shop everywhere.
ACCESS = {
    "input_sales": {"gm", "finance", "coo", "manager"},
    "input_ops": {"gm", "coo", "manager"},
    "input_kpi": {"gm", "coo", "marketing", "manager"},
    "input_expense": {"gm", "finance", "coo", "marketing", "manager"},
    "expenses": {"gm", "finance", "coo", "marketing", "manager", "accountant"},
    "approve": {"gm", "finance"},
    "flash": {"gm", "finance", "coo", "accountant", "manager"},
    "weekly": {"gm", "finance", "coo", "accountant", "manager"},
    "pnl": {"gm", "finance", "accountant"},
    "scorecard": {"gm", "finance", "coo", "accountant"},
    "marketing": {"gm", "marketing", "finance"},
    "ops_log": {"gm", "coo", "finance", "manager"},
    "group": {"gm", "finance", "owner"},
    "staff": {"gm", "finance"},
    "budgets": {"gm", "finance"},
    "month_end": {"gm", "finance", "accountant"},
    "alerts": {"gm", "finance", "coo"},
    "audit": {"gm", "finance", "accountant"},
    "export": {"gm", "finance", "accountant"},
    "admin": {"gm"},
}
PAYMENT_MODES = ["Cash", "PayNow", "Card", "Bank transfer", "GIRO", "Platform deduction", "Company card"]
ALLOWED_IMG = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf"}


# ---------------------------------------------------------------- helpers
def db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def _close(_exc):
    c = g.pop("db", None)
    if c:
        c.close()


def now():
    return automation.now()


def today():
    return now().date()


def setting(key, default=None):
    return automation.setting(db(), key, default)


def audit(action, tbl=None, record_id=None, before=None, after=None):
    u = g.get("user")
    db().execute("INSERT INTO audit_log(ts, user_id, username, action, tbl, record_id, before, after) VALUES (?,?,?,?,?,?,?,?)",
                 (now().isoformat(timespec="seconds"), u["id"] if u else None, u["username"] if u else "system", action, tbl, record_id,
                  json.dumps(dict(before), default=str) if before is not None else None,
                  json.dumps(dict(after), default=str) if after is not None else None))


def can(perm):
    u = g.get("user")
    return bool(u) and u["role"] in ACCESS[perm]


def require(perm):
    def deco(fn):
        @wraps(fn)
        def inner(*a, **kw):
            if not g.get("user"):
                return redirect(url_for("login", next=request.full_path))
            if not can(perm):
                abort(403)
            return fn(*a, **kw)
        return inner
    return deco


def visible_shops():
    u = g.user
    if u["role"] == "manager":
        return db().execute("SELECT * FROM shops WHERE id=?", (u["shop_id"],)).fetchall()
    return db().execute("SELECT * FROM shops WHERE active=1 ORDER BY id").fetchall()


def pick_shop():
    """Shop chosen via ?shop= / form, restricted to what the user may see."""
    shops = visible_shops()
    want = request.values.get("shop", type=int)
    for s in shops:
        if s["id"] == want:
            return s
    if want and g.user["role"] == "manager":
        abort(403)
    return shops[0] if shops else abort(404)


def is_locked(day):
    return db().execute("SELECT 1 FROM month_locks WHERE month=?", (str(day)[:7],)).fetchone() is not None


def parse_date(v, default=None):
    try:
        return date.fromisoformat(v) if v else (default or today())
    except ValueError:
        return default or today()


def num(name, default=0.0):
    v = (request.form.get(name) or "").replace(",", "").strip()
    if v == "":
        return default
    try:
        return float(v)
    except ValueError:
        raise ValueError(f"'{name}' must be a number")


def save_upload(field):
    f = request.files.get(field)
    if not f or not f.filename:
        return None
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_IMG:
        raise ValueError("Upload must be a photo (jpg, png, webp, heic) or PDF")
    name = f"{today():%Y%m}-{uuid.uuid4().hex[:12]}{ext}"
    f.save(os.path.join(UPLOADS, name))
    return name


def notify_users(users, kind, ref, subject, body):
    for u in users:
        automation.send(db(), u, kind, ref, subject, body)


# ---------------------------------------------------------------- TOTP two-factor login (RFC 6238)
def totp(secret, at=None, step=30):
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    counter = int((at or time.time()) // step)
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000:06d}"


def totp_ok(secret, code):
    code = (code or "").replace(" ", "")
    t = time.time()
    return any(hmac.compare_digest(totp(secret, t + d * 30), code) for d in (-1, 0, 1))


# ---------------------------------------------------------------- request hooks / template context
@app.before_request
def load_user():
    g.user = None
    uid = session.get("uid")
    if uid:
        g.user = db().execute("SELECT * FROM users WHERE id=? AND active=1", (uid,)).fetchone()
    if request.method == "POST":
        if request.form.get("_csrf") != session.get("csrf"):
            abort(400, "Form expired – please reload the page and try again.")
    if g.user and setting("require_2fa") == "1" and not g.user["totp_secret"] and request.endpoint not in (
            "security", "logout", "static", "lang"):
        return redirect(url_for("security", enrol=1))


@app.after_request
def translate_page(resp):
    if session.get("lang") == "zh" and resp.mimetype == "text/html" and not resp.direct_passthrough:
        resp.set_data(translate_html(resp.get_data(as_text=True)))
    return resp


@app.context_processor
def ctx():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    lang = session.get("lang", "en")
    return {"u": g.get("user"), "can": can, "ROLES": ROLES, "csrf": session["csrf"], "lang": lang,
            "t": lambda s: tr(s, lang), "today": today(), "now": now()}


@app.template_filter("money")
def money(v, dp=0):
    if v is None:
        return "–"
    return f"S${v:,.{dp}f}" if v >= 0 else f"-S${-v:,.{dp}f}"


@app.template_filter("pct")
def pctf(v, dp=1):
    return "–" if v is None else f"{v:.{dp}f}%"


@app.template_filter("signed")
def signed(v):
    return "–" if v is None else f"{v:+.1f}%"


@app.template_filter("val")
def valf(v, unit=""):
    if v is None:
        return "–"
    if isinstance(v, str):
        return v
    if unit == "S$":
        return money(v)
    if unit == "%":
        return f"{v:.1f}%"
    return f"{v:,.1f}" if v != int(v) else f"{int(v):,}"


@app.template_global()
def bars(items, height=160, money_fmt=True):
    """Small inline SVG bar chart: items = [(label, value)]."""
    if not items:
        return ""
    mx = max((v or 0) for _, v in items) or 1
    w = max(44, 600 // len(items))
    bw = int(w * 0.62)
    parts = [f'<svg class="chart" viewBox="0 0 {w * len(items)} {height + 34}" preserveAspectRatio="xMidYMid meet" role="img">']
    for i, (label, v) in enumerate(items):
        h = int((v or 0) / mx * height)
        x = i * w + (w - bw) // 2
        txt = money(v) if money_fmt else f"{v:,.0f}"
        parts.append(f'<rect x="{x}" y="{height - h + 14}" width="{bw}" height="{h}" rx="3"><title>{escape(label)}: {txt}</title></rect>')
        parts.append(f'<text x="{i * w + w / 2}" y="{height - h + 10}" class="v">{escape(txt)}</text>')
        parts.append(f'<text x="{i * w + w / 2}" y="{height + 30}" class="l">{escape(label)}</text>')
    parts.append("</svg>")
    return Markup("".join(parts))


# ---------------------------------------------------------------- auth
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("step") == "2fa":
            uid = session.get("pending_uid")
            u = db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None
            if u and totp_ok(u["totp_secret"], request.form.get("code")):
                session.pop("pending_uid", None)
                session["uid"] = u["id"]
                g.user = u
                audit("login (2FA)")
                db().commit()
                return redirect(request.args.get("next") or url_for("home"))
            flash("Wrong or expired code", "error")
            return render_template("login.html", step="2fa")
        u = db().execute("SELECT * FROM users WHERE username=?", (request.form.get("username", "").strip().lower(),)).fetchone()
        if not u or not check_password_hash(u["pw_hash"], request.form.get("password", "")):
            flash("Wrong username or password", "error")
            return render_template("login.html", step="pw")
        if not u["active"]:
            flash("Your account is waiting for the GM's approval / 账户待总经理审批", "error")
            return render_template("login.html", step="pw")
        session.clear()
        session["csrf"] = secrets.token_hex(16)
        if u["totp_secret"]:
            session["pending_uid"] = u["id"]
            return render_template("login.html", step="2fa")
        session["uid"] = u["id"]
        g.user = u
        audit("login")
        db().commit()
        return redirect(request.args.get("next") or url_for("home"))
    return render_template("login.html", step="pw")


SIGNUP_ROLES = ["manager", "finance", "coo", "marketing", "accountant", "owner"]  # never self-assign GM


@app.route("/register", methods=["GET", "POST"])
def register():
    """Self-service account request. The account stays inactive until the GM approves it in Admin → Users."""
    c = db()
    shops = c.execute("SELECT * FROM shops WHERE active=1 ORDER BY id").fetchall()
    if request.method == "POST":
        f = request.form
        try:
            username = f.get("username", "").strip().lower()
            name = f.get("name", "").strip()
            role = f.get("role")
            shop_id = f.get("shop_id", type=int) if role == "manager" else None
            if not name or not username:
                raise ValueError("Name and username are required")
            if not username.replace("_", "").replace(".", "").isalnum() or len(username) < 3:
                raise ValueError("Username: at least 3 letters/digits (_ and . allowed)")
            if role not in SIGNUP_ROLES:
                raise ValueError("Choose a role")
            if role == "manager" and shop_id not in [s["id"] for s in shops]:
                raise ValueError("Shop managers must choose their shop")
            if len(f.get("password", "")) < 8:
                raise ValueError("Password must be at least 8 characters")
            if f.get("password") != f.get("confirm"):
                raise ValueError("Passwords don't match")
            if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                raise ValueError("That username is taken")
            cur = c.execute("INSERT INTO users(username, name, role, shop_id, email, phone, pw_hash, active) VALUES (?,?,?,?,?,?,?,0)",
                            (username, name, role, shop_id, f.get("email", "").strip(), f.get("phone", "").strip(),
                             generate_password_hash(f["password"])))
            g.user = None
            audit("account requested", "users", cur.lastrowid, None, {"username": username, "role": role, "shop_id": shop_id})
            notify_users(automation.users_with_roles(c, "gm"), "signup", username, f"New account request: {name} ({ROLES[role]})",
                         f"{name} asked for a {ROLES[role]} account (username {username}). Approve it in Admin → Users: "
                         f"{setting('app_url')}/admin?tab=users")
            c.commit()
            flash("Account created – the GM will approve it, then you can sign in / 账户已创建，待总经理审批后即可登录", "ok")
            return redirect(url_for("login"))
        except ValueError as e:
            flash(str(e), "error")
    return render_template("register.html", shops=shops, roles=[(r, ROLES[r]) for r in SIGNUP_ROLES])


@app.route("/admin/approve-user", methods=["POST"])
@require("admin")
def approve_user():
    uid = request.form.get("id", type=int)
    before = db().execute("SELECT id, username, active FROM users WHERE id=?", (uid,)).fetchone() or abort(404)
    db().execute("UPDATE users SET active=1 WHERE id=?", (uid,))
    audit("approve account", "users", uid, before, {"active": 1})
    db().commit()
    flash(f"{before['username']} can now sign in", "ok")
    return redirect(url_for("admin", tab="users"))


@app.route("/logout", methods=["POST"])
def logout():
    lang = session.get("lang")
    session.clear()
    if lang:
        session["lang"] = lang
    return redirect(url_for("login"))


@app.route("/lang/<code>")
def lang(code):
    session["lang"] = "zh" if code == "zh" else "en"
    return redirect(request.referrer or url_for("home"))


@app.route("/security", methods=["GET", "POST"])
def security():
    if not g.user:
        return redirect(url_for("login"))
    if request.method == "POST":
        action = request.form.get("action")
        if action == "password":
            if not check_password_hash(g.user["pw_hash"], request.form.get("current", "")):
                flash("Current password is wrong", "error")
            elif len(request.form.get("new", "")) < 8:
                flash("New password must be at least 8 characters", "error")
            else:
                db().execute("UPDATE users SET pw_hash=? WHERE id=?", (generate_password_hash(request.form["new"]), g.user["id"]))
                audit("change password", "users", g.user["id"])
                db().commit()
                flash("Password changed", "ok")
        elif action == "enable":
            secret = session.get("new_totp")
            if secret and totp_ok(secret, request.form.get("code")):
                db().execute("UPDATE users SET totp_secret=? WHERE id=?", (secret, g.user["id"]))
                audit("enable 2FA", "users", g.user["id"])
                db().commit()
                session.pop("new_totp", None)
                flash("Two-factor login is on", "ok")
                return redirect(url_for("home"))
            flash("Code did not match – try again", "error")
        elif action == "disable" and setting("require_2fa") != "1":
            db().execute("UPDATE users SET totp_secret=NULL WHERE id=?", (g.user["id"],))
            audit("disable 2FA", "users", g.user["id"])
            db().commit()
            flash("Two-factor login is off", "ok")
        return redirect(url_for("security"))
    user = db().execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
    secret = None
    if not user["totp_secret"]:
        secret = session.get("new_totp") or base64.b32encode(secrets.token_bytes(10)).decode().rstrip("=")
        session["new_totp"] = secret
    uri = f"otpauth://totp/AANDJ:{user['username']}?secret={secret}&issuer=AANDJ" if secret else None
    return render_template("security.html", user=user, secret=secret, uri=uri, forced=setting("require_2fa") == "1")


@app.route("/")
def home():
    if not g.user:
        return redirect(url_for("login"))
    r = g.user["role"]
    if r == "manager":
        return redirect(url_for("manager_home"))
    if r == "owner":
        return redirect(url_for("group"))
    if r == "marketing":
        return redirect(url_for("marketing"))
    return redirect(url_for("flash_report"))


# ---------------------------------------------------------------- manager home & input forms
@app.route("/today")
@require("input_sales")
def manager_home():
    shop = pick_shop()
    day = parse_date(request.args.get("date"))
    c = db()
    status = {
        "sales": c.execute("SELECT * FROM daily_sales WHERE shop_id=? AND date=?", (shop["id"], day.isoformat())).fetchone(),
        "ops": c.execute("SELECT 1 FROM daily_ops WHERE shop_id=? AND date=?", (shop["id"], day.isoformat())).fetchone(),
        "kpi": c.execute("SELECT COUNT(*) n FROM kpi_values WHERE shop_id=? AND date=?", (shop["id"], day.isoformat())).fetchone()["n"],
        "exp": c.execute(f"SELECT COUNT(*) n, COALESCE(SUM(amount),0) amt FROM expenses WHERE shop_id=? AND date=? AND {reports.COUNTED}",
                         (shop["id"], day.isoformat())).fetchone(),
    }
    missing = []
    deadline = int(setting("deadline_hour", "23"))
    for back in range(1, 8):
        dd = day - timedelta(days=back)
        if not c.execute("SELECT 1 FROM daily_sales WHERE shop_id=? AND date=?", (shop["id"], dd.isoformat())).fetchone():
            missing.append(dd)
    msgs = c.execute("SELECT * FROM outbox WHERE to_user=? ORDER BY id DESC LIMIT 5", (g.user["id"],)).fetchall()
    return render_template("manager_home.html", shop=shop, shops=visible_shops(), day=day, status=status, missing=missing,
                           deadline=deadline, msgs=msgs, locked=is_locked(day))


@app.route("/input/sales", methods=["GET", "POST"])
@require("input_sales")
def input_sales():
    shop = pick_shop()
    day = parse_date(request.values.get("date"))
    c = db()
    existing = c.execute("SELECT * FROM daily_sales WHERE shop_id=? AND date=?", (shop["id"], day.isoformat())).fetchone()
    if request.method == "POST":
        try:
            if is_locked(day):
                raise ValueError(f"{day:%B %Y} is locked – ask Finance to unlock it")
            if day > today():
                raise ValueError("Cannot submit a future date")
            vals = {k: num(k) for k in ("gross", "discounts", "refunds", "cash", "paynow", "card", "platforms", "cash_deposit")}
            vals["transactions"] = int(num("transactions"))
            vals["customers"] = int(num("customers"))
            vals["net"] = round(vals["gross"] - vals["discounts"] - vals["refunds"], 2)
            paid = round(vals["cash"] + vals["paynow"] + vals["card"] + vals["platforms"], 2)
            if vals["gross"] <= 0:
                raise ValueError("Gross sales must be more than 0")
            if abs(paid - vals["net"]) > 1:
                raise ValueError(f"Payment modes add up to {money(paid, 2)} but net sales are {money(vals['net'], 2)}")
            photo = save_upload("pos_photo") or (existing["pos_photo"] if existing else None)
            if not photo:
                raise ValueError("Please attach a photo of the POS end-of-day report")
            vals.update(pos_photo=photo, deposit_ref=request.form.get("deposit_ref", "").strip(), notes=request.form.get("notes", "").strip())
            if existing:
                sets = ", ".join(f"{k}=?" for k in vals)
                c.execute(f"UPDATE daily_sales SET {sets} WHERE id=?", (*vals.values(), existing["id"]))
                after = c.execute("SELECT * FROM daily_sales WHERE id=?", (existing["id"],)).fetchone()
                audit("edit daily sales", "daily_sales", existing["id"], existing, after)
            else:
                cur = c.execute(f"""INSERT INTO daily_sales(shop_id, date, {', '.join(vals)}, submitted_by, submitted_at)
                                VALUES (?, ?, {', '.join('?' * len(vals))}, ?, ?)""",
                                (shop["id"], day.isoformat(), *vals.values(), g.user["id"], now().isoformat(timespec="seconds")))
                audit("submit daily sales", "daily_sales", cur.lastrowid, None, c.execute("SELECT * FROM daily_sales WHERE id=?", (cur.lastrowid,)).fetchone())
            c.commit()
            automation.check_sales_drop(c, now())
            c.commit()
            flash(tr("Sales saved", session.get("lang")), "ok")
            return redirect(url_for("manager_home", shop=shop["id"], date=day.isoformat()))
        except ValueError as e:
            flash(str(e), "error")
    return render_template("form_sales.html", shop=shop, shops=visible_shops(), day=day, row=existing, form=request.form, locked=is_locked(day))


@app.route("/input/ops", methods=["GET", "POST"])
@require("input_ops")
def input_ops():
    shop = pick_shop()
    day = parse_date(request.values.get("date"))
    c = db()
    existing = c.execute("SELECT * FROM daily_ops WHERE shop_id=? AND date=?", (shop["id"], day.isoformat())).fetchone()
    if request.method == "POST":
        try:
            if is_locked(day):
                raise ValueError(f"{day:%B %Y} is locked")
            vals = {"staff_on_shift": int(num("staff_on_shift")), "staff_hours": num("staff_hours")}
            for k in ("absences", "lateness", "complaints", "compliments", "equipment_issues", "stock_issues", "gm_items"):
                vals[k] = request.form.get(k, "").strip()
            if existing:
                c.execute(f"UPDATE daily_ops SET {', '.join(f'{k}=?' for k in vals)} WHERE id=?", (*vals.values(), existing["id"]))
                audit("edit daily operations", "daily_ops", existing["id"], existing, c.execute("SELECT * FROM daily_ops WHERE id=?", (existing["id"],)).fetchone())
            else:
                cur = c.execute(f"INSERT INTO daily_ops(shop_id, date, {', '.join(vals)}, submitted_by, submitted_at) VALUES (?,?,{','.join('?' * len(vals))},?,?)",
                                (shop["id"], day.isoformat(), *vals.values(), g.user["id"], now().isoformat(timespec="seconds")))
                audit("submit daily operations", "daily_ops", cur.lastrowid, None, vals)
            if vals["gm_items"] and (not existing or existing["gm_items"] != vals["gm_items"]):
                notify_users(automation.users_with_roles(c, "gm"), "gm_item", f"{shop['code']}:{day}:{now():%H%M%S}",
                             f"{shop['name']} needs the GM ({day:%d %b})", vals["gm_items"])
            c.commit()
            flash(tr("Operations saved", session.get("lang")), "ok")
            return redirect(url_for("manager_home", shop=shop["id"], date=day.isoformat()))
        except ValueError as e:
            flash(str(e), "error")
    return render_template("form_ops.html", shop=shop, shops=visible_shops(), day=day, row=existing, locked=is_locked(day))


@app.route("/input/kpi", methods=["GET", "POST"])
@require("input_kpi")
def input_kpi():
    shop = pick_shop()
    day = parse_date(request.values.get("date"))
    c = db()
    fields = [f for f in reports.kpi_fields(c, shop["id"]) if f["ftype"] != "formula"]
    existing = {r["field_id"]: r for r in c.execute("SELECT * FROM kpi_values WHERE shop_id=? AND date=?", (shop["id"], day.isoformat()))}
    if request.method == "POST":
        try:
            if is_locked(day):
                raise ValueError(f"{day:%B %Y} is locked")
            changed = 0
            for f in fields:
                v = request.form.get(f"f{f['id']}", "").strip()
                if f["ftype"] == "number" and v:
                    float(v.replace(",", ""))
                    v = v.replace(",", "")
                old = existing.get(f["id"])
                if old is None and v == "":
                    continue
                if old is not None and (old["value"] or "") == v:
                    continue
                if old is not None:
                    c.execute("UPDATE kpi_values SET value=?, submitted_by=?, submitted_at=? WHERE id=?",
                              (v, g.user["id"], now().isoformat(timespec="seconds"), old["id"]))
                    audit("edit KPI", "kpi_values", old["id"], {"field": f["key"], "value": old["value"]}, {"field": f["key"], "value": v})
                else:
                    cur = c.execute("INSERT INTO kpi_values(shop_id, date, field_id, value, submitted_by, submitted_at) VALUES (?,?,?,?,?,?)",
                                    (shop["id"], day.isoformat(), f["id"], v, g.user["id"], now().isoformat(timespec="seconds")))
                    audit("submit KPI", "kpi_values", cur.lastrowid, None, {"field": f["key"], "value": v})
                changed += 1
            c.commit()
            flash(f"{tr('KPIs saved', session.get('lang'))} ({changed})", "ok")
            return redirect(url_for("manager_home", shop=shop["id"], date=day.isoformat()))
        except ValueError as e:
            flash(f"Numbers only in number fields ({e})", "error")
    return render_template("form_kpi.html", shop=shop, shops=visible_shops(), day=day, fields=fields, existing=existing, locked=is_locked(day))


def approval_level(amount, category):
    if amount > float(setting("gm_approval_limit", "2000")):
        return "gm"
    if amount > float(setting("approval_limit", "500")):
        return "head"
    return None


@app.route("/input/expense", methods=["GET", "POST"])
@app.route("/expense/<int:eid>/edit", methods=["GET", "POST"])
@require("input_expense")
def input_expense(eid=None):
    c = db()
    row = None
    if eid:
        row = c.execute("SELECT * FROM expenses WHERE id=?", (eid,)).fetchone() or abort(404)
        if row["shop_id"] not in [s["id"] for s in visible_shops()]:
            abort(403)
    shop = pick_shop() if not row else c.execute("SELECT * FROM shops WHERE id=?", (row["shop_id"],)).fetchone()
    day = parse_date(request.values.get("date"), date.fromisoformat(row["date"]) if row else None)
    cats = c.execute("SELECT * FROM categories ORDER BY sort").fetchall()
    if request.method == "POST":
        try:
            if row and row["status"] in ("approved",) and row["approver_level"] not in (None, "pre-approved") and g.user["role"] not in ("gm", "finance"):
                raise ValueError("This expense is already approved – ask Finance to change it")
            if is_locked(day) or (row and is_locked(row["date"])):
                raise ValueError(f"{day:%B %Y} is locked – ask Finance to unlock it")
            if day > today():
                raise ValueError("Cannot record a future date")
            cat = request.form.get("category")
            catrow = next((x for x in cats if x["name"] == cat), None)
            if not catrow:
                raise ValueError("Choose a category")
            if g.user["role"] == "marketing" and cat != "Marketing":
                raise ValueError("Brand & Marketing can only record Marketing expenses")
            amount = num("amount")
            if amount <= 0:
                raise ValueError("Amount must be more than 0")
            gst = num("gst")
            supplier = request.form.get("supplier", "").strip()
            if not supplier:
                raise ValueError("Enter the supplier")
            purpose = request.form.get("purpose", "").strip()
            if catrow["needs_purpose"] and not purpose:
                raise ValueError("State the purpose for 'Others' expenses")
            receipt = save_upload("receipt") or (row["receipt"] if row else None)
            if not receipt and amount > float(setting("receipt_threshold", "0")):
                raise ValueError("A receipt or invoice photo is required")
            mode = request.form.get("payment_mode")
            if mode not in PAYMENT_MODES:
                raise ValueError("Choose a payment mode")
            paid = "payable" if request.form.get("paid_status") == "payable" else "paid"
            level = approval_level(amount, cat)
            if level == "head" and g.user["role"] in ("gm", "finance"):
                level, status = "head", "approved"
            elif level == "gm" and g.user["role"] == "gm":
                status = "approved"
            else:
                status = "pending" if level else "approved"
            vals = dict(shop_id=shop["id"], date=day.isoformat(), supplier=supplier, category=cat, amount=amount, gst=gst, payment_mode=mode,
                        receipt=receipt, purpose=purpose, paid_status=paid, status=status, approver_level=level)
            if status == "approved" and level:
                vals.update(approved_by=g.user["id"], approved_at=now().isoformat(timespec="seconds"))
            if row:
                c.execute(f"UPDATE expenses SET {', '.join(f'{k}=?' for k in vals)} WHERE id=?", (*vals.values(), row["id"]))
                audit("edit expense", "expenses", row["id"], row, c.execute("SELECT * FROM expenses WHERE id=?", (row["id"],)).fetchone())
                rid = row["id"]
            else:
                cur = c.execute(f"INSERT INTO expenses({', '.join(vals)}, submitted_by, created_at) VALUES ({','.join('?' * len(vals))},?,?)",
                                (*vals.values(), g.user["id"], now().isoformat(timespec="seconds")))
                rid = cur.lastrowid
                audit("submit expense", "expenses", rid, None, vals)
            if status == "pending":
                approvers = automation.users_with_roles(c, *(("gm",) if level == "gm" else ("finance", "gm")))
                notify_users(approvers, "approval", f"exp{rid}:{now():%H%M%S}", f"Approval needed: {shop['name']} {money(amount, 2)} – {supplier}",
                             f"{g.user['name']} recorded {money(amount, 2)} ({cat}) for {shop['name']} on {day:%d %b}. Purpose: {purpose or '-'}.\n"
                             f"Approve at {setting('app_url')}/approvals")
                flash(f"Saved – above the S${float(setting('approval_limit')):,.0f} limit, sent to "
                      f"{'the GM' if level == 'gm' else 'Finance'} for approval", "ok")
            else:
                flash(tr("Expense saved", session.get("lang")), "ok")
            c.commit()
            return redirect(url_for("expenses", shop=shop["id"], month=day.isoformat()[:7]) if row else
                            url_for("input_expense", shop=shop["id"], date=day.isoformat(), saved=1))
        except ValueError as e:
            flash(str(e), "error")
    recent = c.execute(f"SELECT * FROM expenses WHERE shop_id=? AND date=? ORDER BY id DESC", (shop["id"], day.isoformat())).fetchall()
    return render_template("form_expense.html", shop=shop, shops=visible_shops(), day=day, row=row, cats=cats, modes=PAYMENT_MODES,
                           recent=recent, limit=float(setting("approval_limit", "500")), gm_limit=float(setting("gm_approval_limit", "2000")),
                           receipt_threshold=float(setting("receipt_threshold", "0")), locked=is_locked(day))


@app.route("/expenses")
@require("expenses")
def expenses():
    c = db()
    month = request.args.get("month") or today().strftime("%Y-%m")
    shops = visible_shops()
    ids = [s["id"] for s in shops] or [0]
    want = request.args.get("shop", type=int)
    if want in ids:
        ids = [want]
    d1, d2 = reports.month_bounds(month)
    q = f"""SELECT e.*, s.name shop_name, s.code, u.name submitter, a.name approver FROM expenses e JOIN shops s ON s.id=e.shop_id
            LEFT JOIN users u ON u.id=e.submitted_by LEFT JOIN users a ON a.id=e.approved_by
            WHERE e.shop_id IN ({','.join('?' * len(ids))}) AND e.date>=? AND e.date<?"""
    args = [*ids, d1.isoformat(), d2.isoformat()]
    if request.args.get("status"):
        q += " AND e.status=?"
        args.append(request.args["status"])
    if request.args.get("category"):
        q += " AND e.category=?"
        args.append(request.args["category"])
    rows = c.execute(q + " ORDER BY e.date DESC, e.id DESC", args).fetchall()
    cats = c.execute("SELECT name FROM categories ORDER BY sort").fetchall()
    return render_template("expenses.html", rows=rows, shops=shops, month=month, cats=cats, total=sum(r["amount"] for r in rows if r["status"] not in ("rejected", "void")))


@app.route("/expense/<int:eid>/void", methods=["POST"])
@require("input_expense")
def void_expense(eid):
    c = db()
    row = c.execute("SELECT * FROM expenses WHERE id=?", (eid,)).fetchone() or abort(404)
    if row["shop_id"] not in [s["id"] for s in visible_shops()]:
        abort(403)
    if is_locked(row["date"]):
        flash("Month is locked", "error")
    elif row["status"] == "approved" and row["approver_level"] not in (None, "pre-approved") and g.user["role"] not in ("gm", "finance"):
        flash("Approved expenses can only be voided by Finance", "error")
    else:
        c.execute("UPDATE expenses SET status='void' WHERE id=?", (eid,))
        audit("void expense", "expenses", eid, row, {"status": "void", "reason": request.form.get("reason", "")})
        c.commit()
        flash("Expense voided (kept on record)", "ok")
    return redirect(request.referrer or url_for("expenses"))


@app.route("/approvals", methods=["GET", "POST"])
@require("approve")
def approvals():
    c = db()
    if request.method == "POST":
        eid = request.form.get("id", type=int)
        row = c.execute("SELECT * FROM expenses WHERE id=? AND status='pending'", (eid,)).fetchone()
        if not row:
            flash("Already handled", "error")
        elif row["approver_level"] == "gm" and g.user["role"] != "gm":
            flash("This amount needs the GM's approval", "error")
        else:
            new = "approved" if request.form.get("decision") == "approve" else "rejected"
            c.execute("UPDATE expenses SET status=?, approved_by=?, approved_at=? WHERE id=?",
                      (new, g.user["id"], now().isoformat(timespec="seconds"), eid))
            audit(f"{new} expense", "expenses", eid, row, {"status": new, "note": request.form.get("note", "")})
            sub = c.execute("SELECT * FROM users WHERE id=?", (row["submitted_by"],)).fetchone()
            if sub:
                automation.send(c, sub, "approval_result", f"exp{eid}", f"Expense {new}: {row['supplier']} {money(row['amount'], 2)}",
                                f"{g.user['name']} {new} your expense of {money(row['amount'], 2)} ({row['category']}). {request.form.get('note', '')}")
            c.commit()
            flash(f"Expense {new}", "ok")
        return redirect(url_for("approvals"))
    rows = c.execute("""SELECT e.*, s.name shop_name, u.name submitter FROM expenses e JOIN shops s ON s.id=e.shop_id
                        LEFT JOIN users u ON u.id=e.submitted_by WHERE e.status='pending' ORDER BY e.date""").fetchall()
    return render_template("approvals.html", rows=rows)


# ---------------------------------------------------------------- dashboards
@app.route("/flash")
@require("flash")
def flash_report():
    day = parse_date(request.args.get("date"))
    c = db()
    shops = visible_shops()
    f = reports.daily_flash(c, shops, day)
    d1 = day.replace(day=1)
    mtd = []
    for s in shops:
        st = reports.sales_totals(c, s["id"], d1, day + timedelta(days=1))
        b = c.execute("SELECT amount FROM budgets WHERE shop_id=? AND month=? AND line='Sales' AND kind='budget'", (s["id"], day.strftime("%Y-%m"))).fetchone()
        mtd.append({"shop": s, "net": st["net"], "budget": b["amount"] if b else None})
    ontime = reports.on_time_rate(c, [s["id"] for s in shops], day - timedelta(days=6), day + timedelta(days=1), setting("deadline_hour", "23"))
    alerts = c.execute(f"""SELECT a.*, s.name shop_name FROM alerts a LEFT JOIN shops s ON s.id=a.shop_id WHERE resolved=0
                           AND (a.shop_id IS NULL OR a.shop_id IN ({','.join('?' * len(shops))})) ORDER BY a.id DESC LIMIT 8""",
                       [s["id"] for s in shops]).fetchall() if can("alerts") and shops else []
    pending = c.execute("SELECT COUNT(*) n FROM expenses WHERE status='pending'").fetchone()["n"] if can("approve") else 0
    return render_template("flash.html", f=f, day=day, mtd=mtd, ontime=ontime, alerts=alerts, pending=pending,
                           deadline=int(setting("deadline_hour", "23")))


@app.route("/weekly")
@require("weekly")
def weekly():
    ws = reports.week_start(parse_date(request.args.get("week"), today() - timedelta(days=7)))
    w = reports.weekly(db(), visible_shops(), ws)
    ontime = reports.on_time_rate(db(), [s["id"] for s in visible_shops()], ws, ws + timedelta(days=7), setting("deadline_hour", "23"))
    return render_template("weekly.html", w=w, ws=ws, ontime=ontime, prev=ws - timedelta(days=7), next=ws + timedelta(days=7))


@app.route("/pnl")
@require("pnl")
def pnl():
    c = db()
    month = request.args.get("month") or reports.prev_month(today().strftime("%Y-%m"))
    shops = visible_shops()
    company = request.args.get("company")
    if company:
        shops = [s for s in shops if s["company"] == company]
    cats = [r["name"] for r in c.execute("SELECT name FROM categories ORDER BY sort")]
    p = reports.pnl(c, shops, month, cats)
    companies = sorted({s["company"] for s in visible_shops()})
    return render_template("pnl.html", p=p, month=month, companies=companies, company=company,
                           locked=is_locked(month + "-01"))


@app.route("/scorecard")
@require("scorecard")
def scorecard():
    month = request.args.get("month") or reports.prev_month(today().strftime("%Y-%m"))
    return render_template("scorecard.html", sc=reports.scorecard(db(), visible_shops(), month), month=month)


@app.route("/marketing")
@require("marketing")
def marketing():
    c = db()
    month = request.args.get("month") or today().strftime("%Y-%m")
    d1, d2 = reports.month_bounds(month)
    rows = []
    for s in visible_shops():
        m, e = reports.metrics(c, s["id"], d1, d2)
        fields = reports.kpi_fields(c, s["id"])
        lead_fields = [f for f in fields if f["key"].startswith("leads_") or f["key"] in
                       ("enquiries", "consultations", "bookings", "referrals", "influencer_share", "google_reviews", "ai_checks", "site_visits")]
        leads = sum((m.get(f["key"]) or 0) for f in fields if f["key"].startswith("leads_") or f["key"] in ("enquiries", "ai_checks"))
        spend = e.get("Marketing", 0)
        kol = c.execute(f"""SELECT COALESCE(SUM(amount),0) a FROM expenses WHERE shop_id=? AND date>=? AND date<? AND category='Marketing'
                            AND {reports.COUNTED} AND (supplier LIKE '%KOL%' OR supplier LIKE '%influencer%' OR purpose LIKE '%influencer%')""",
                        (s["id"], d1.isoformat(), d2.isoformat())).fetchone()["a"]
        rows.append({"shop": s, "m": m, "spend": spend, "kol": kol, "leads": leads, "fields": lead_fields,
                     "cpl": spend / leads if leads else None, "cpc": spend / m["customers"] if m["customers"] else None,
                     "roi": m["net_sales"] / spend if spend else None})
    return render_template("marketing.html", rows=rows, month=month)


@app.route("/ops-log")
@require("ops_log")
def ops_log():
    c = db()
    month = request.args.get("month") or today().strftime("%Y-%m")
    d1, d2 = reports.month_bounds(month)
    ids = [s["id"] for s in visible_shops()] or [0]
    rows = c.execute(f"""SELECT o.*, s.name shop_name FROM daily_ops o JOIN shops s ON s.id=o.shop_id
                         WHERE o.shop_id IN ({','.join('?' * len(ids))}) AND o.date>=? AND o.date<?
                         AND (absences<>'' OR lateness<>'' OR complaints<>'' OR compliments<>'' OR equipment_issues<>'' OR stock_issues<>'' OR gm_items<>''
                              OR ?='all')
                         ORDER BY o.date DESC, s.id""", (*ids, d1.isoformat(), d2.isoformat(), request.args.get("show", ""))).fetchall()
    return render_template("ops_log.html", rows=rows, month=month)


@app.route("/group")
@require("group")
def group():
    c = db()
    day = today()
    d1 = day.replace(day=1)
    month = day.strftime("%Y-%m")
    pm = reports.prev_month(month)
    p1, p2 = reports.month_bounds(pm)
    rows = []
    for s in visible_shops():
        m, _ = reports.metrics(c, s["id"], d1, day)
        last, _ = reports.metrics(c, s["id"], p1, p2)
        b = c.execute("SELECT amount FROM budgets WHERE shop_id=? AND month=? AND line='Sales' AND kind='budget'", (s["id"], month)).fetchone()
        rows.append({"shop": s, "mtd": m, "last": last, "budget": b["amount"] if b else None})
    trend = []
    for i in range(5, -1, -1):
        mon = reports.prev_month(month, i)
        a, b = reports.month_bounds(mon)
        trend.append((datetime.strptime(mon, "%Y-%m").strftime("%b"), sum(reports.sales_totals(c, s["id"], a, b)["net"] for s in visible_shops())))
    sc = reports.scorecard(c, visible_shops(), pm)
    return render_template("group.html", rows=rows, trend=trend, sc=sc, month=month, pm=pm, day=day)


# ---------------------------------------------------------------- admin-ish pages
@app.route("/alerts", methods=["GET", "POST"])
@require("alerts")
def alerts():
    c = db()
    if request.method == "POST":
        if request.form.get("action") == "run":
            automation.run_all(c, force_weekly=bool(request.form.get("weekly")))
            audit("run automation now")
            flash("Automation checks run", "ok")
        else:
            aid = request.form.get("id", type=int)
            c.execute("UPDATE alerts SET resolved=1 WHERE id=?", (aid,))
            audit("resolve alert", "alerts", aid)
        c.commit()
        return redirect(url_for("alerts"))
    rows = c.execute("SELECT a.*, s.name shop_name FROM alerts a LEFT JOIN shops s ON s.id=a.shop_id ORDER BY resolved, a.id DESC LIMIT 300").fetchall()
    return render_template("alerts.html", rows=rows)


@app.route("/inbox")
def inbox():
    if not g.user:
        return redirect(url_for("login"))
    c = db()
    if g.user["role"] == "gm" and request.args.get("all"):
        rows = c.execute("SELECT o.*, u.name to_name FROM outbox o LEFT JOIN users u ON u.id=o.to_user ORDER BY o.id DESC LIMIT 300").fetchall()
    else:
        rows = c.execute("SELECT o.*, u.name to_name FROM outbox o LEFT JOIN users u ON u.id=o.to_user WHERE to_user=? ORDER BY o.id DESC LIMIT 200",
                         (g.user["id"],)).fetchall()
    return render_template("inbox.html", rows=rows, smtp=bool(os.environ.get("SMTP_HOST")))


@app.route("/month-end", methods=["GET", "POST"])
@require("month_end")
def month_end():
    c = db()
    month = request.values.get("month") or reports.prev_month(today().strftime("%Y-%m"))
    shops = visible_shops()
    if request.method == "POST":
        if g.user["role"] not in ("gm", "finance"):
            abort(403)
        a = request.form.get("action")
        if a == "tick":
            sid, item = request.form.get("shop", type=int), request.form.get("item")
            if c.execute("SELECT 1 FROM month_close WHERE month=? AND shop_id=? AND item=?", (month, sid, item)).fetchone():
                c.execute("DELETE FROM month_close WHERE month=? AND shop_id=? AND item=?", (month, sid, item))
                audit("untick month-end item", "month_close", sid, None, {"month": month, "item": item})
            else:
                c.execute("INSERT INTO month_close(month, shop_id, item, done_by, done_at) VALUES (?,?,?,?,?)",
                          (month, sid, item, g.user["id"], now().isoformat(timespec="seconds")))
                audit("tick month-end item", "month_close", sid, None, {"month": month, "item": item})
        elif a == "payroll":
            if is_locked(month + "-01"):
                flash("Month is locked", "error")
                return redirect(url_for("month_end", month=month))
            d1, d2 = reports.month_bounds(month)
            last = (d2 - timedelta(days=1)).isoformat()
            n = 0
            for s in shops:
                if c.execute("SELECT 1 FROM expenses WHERE shop_id=? AND date>=? AND date<? AND supplier='Payroll' AND status<>'void'",
                             (s["id"], d1.isoformat(), d2.isoformat())).fetchone():
                    continue
                st = c.execute("SELECT * FROM staff WHERE shop_id=? AND active=1", (s["id"],)).fetchall()
                sales = reports.sales_totals(c, s["id"], d1, d2)["net"]
                pay = sum(x["monthly_pay"] * (1 + x["cpf_rate"] / 100) for x in st)
                comm = sum(sales / max(1, len(st)) * x["commission_rate"] / 100 for x in st)
                if pay + comm <= 0:
                    continue
                cur = c.execute("""INSERT INTO expenses(shop_id, date, supplier, category, amount, gst, payment_mode, receipt, purpose, paid_status,
                                   status, approver_level, approved_by, approved_at, submitted_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (s["id"], last, "Payroll", "Staff", round(pay + comm, 2), 0, "Bank transfer", None,
                                 f"Salaries + employer CPF + commission ({len(st)} staff)", "payable", "approved", "pre-approved", g.user["id"],
                                 now().isoformat(timespec="seconds"), g.user["id"], now().isoformat(timespec="seconds")))
                audit("post payroll", "expenses", cur.lastrowid, None, {"shop": s["code"], "month": month, "amount": round(pay + comm, 2)})
                n += 1
            flash(f"Payroll posted for {n} shop(s)" if n else "Payroll already posted for every shop", "ok")
        elif a == "lock":
            c.execute("INSERT OR IGNORE INTO month_locks(month, locked_by, locked_at) VALUES (?,?,?)", (month, g.user["id"], now().isoformat(timespec="seconds")))
            audit("lock month", "month_locks", None, None, {"month": month})
            flash(f"{month} locked", "ok")
        elif a == "unlock" and g.user["role"] == "gm":
            c.execute("DELETE FROM month_locks WHERE month=?", (month,))
            audit("unlock month", "month_locks", None, None, {"month": month, "reason": request.form.get("reason", "")})
            flash(f"{month} unlocked", "ok")
        c.commit()
        return redirect(url_for("month_end", month=month))
    done = {(r["shop_id"], r["item"]): r for r in c.execute(
        "SELECT m.*, u.name who FROM month_close m LEFT JOIN users u ON u.id=m.done_by WHERE month=?", (month,))}
    lock = c.execute("SELECT l.*, u.name who FROM month_locks l LEFT JOIN users u ON u.id=l.locked_by WHERE month=?", (month,)).fetchone()
    d1, d2 = reports.month_bounds(month)
    checks = []
    for s in shops:
        days_in = (min(d2, today()) - d1).days
        got = c.execute("SELECT COUNT(*) n FROM daily_sales WHERE shop_id=? AND date>=? AND date<?", (s["id"], d1.isoformat(), d2.isoformat())).fetchone()["n"]
        pend = c.execute("SELECT COUNT(*) n FROM expenses WHERE shop_id=? AND date>=? AND date<? AND status='pending'", (s["id"], d1.isoformat(), d2.isoformat())).fetchone()["n"]
        payable = c.execute("SELECT COALESCE(SUM(amount),0) a FROM expenses WHERE shop_id=? AND date>=? AND date<? AND paid_status='payable' AND status='approved'",
                            (s["id"], d1.isoformat(), d2.isoformat())).fetchone()["a"]
        dep = c.execute("SELECT COALESCE(SUM(cash),0) cash, COALESCE(SUM(cash_deposit),0) dep FROM daily_sales WHERE shop_id=? AND date>=? AND date<?",
                        (s["id"], d1.isoformat(), d2.isoformat())).fetchone()
        checks.append({"shop": s, "days": days_in, "got": got, "pending": pend, "payable": payable, "cash": dep["cash"], "dep": dep["dep"]})
    return render_template("month_end.html", month=month, shops=shops, items=automation.MONTH_CLOSE_ITEMS, done=done, lock=lock, checks=checks,
                           locks=c.execute("SELECT * FROM month_locks ORDER BY month DESC").fetchall())


@app.route("/audit")
@require("audit")
def audit_view():
    q = "SELECT * FROM audit_log"
    args = []
    if request.args.get("tbl"):
        q += " WHERE tbl=?"
        args.append(request.args["tbl"])
    rows = db().execute(q + " ORDER BY id DESC LIMIT 500", args).fetchall()
    return render_template("audit.html", rows=rows)


EXPORTS = {
    "daily_sales": "SELECT s.company, s.code shop, d.* FROM daily_sales d JOIN shops s ON s.id=d.shop_id",
    "expenses": "SELECT s.company, s.code shop, c.account_code, e.* FROM expenses e JOIN shops s ON s.id=e.shop_id LEFT JOIN categories c ON c.name=e.category",
    "daily_ops": "SELECT s.company, s.code shop, o.* FROM daily_ops o JOIN shops s ON s.id=o.shop_id",
    "kpi_values": "SELECT s.company, s.code shop, k.date, f.key, f.label, k.value, k.submitted_at FROM kpi_values k JOIN kpi_fields f ON f.id=k.field_id JOIN shops s ON s.id=k.shop_id",
    "staff": "SELECT s.company, s.code shop, t.* FROM staff t JOIN shops s ON s.id=t.shop_id",
    "budgets": "SELECT s.company, s.code shop, b.* FROM budgets b JOIN shops s ON s.id=b.shop_id",
    "audit_log": "SELECT * FROM audit_log",
}


@app.route("/export")
@require("export")
def export_page():
    return render_template("export.html", tables=EXPORTS.keys(), companies=sorted({s["company"] for s in visible_shops()}),
                           month=reports.prev_month(today().strftime("%Y-%m")))


@app.route("/export/<name>.csv")
@require("export")
def export_csv(name):
    if name not in EXPORTS:
        abort(404)
    q, args, where = EXPORTS[name], [], []
    month, company = request.args.get("month"), request.args.get("company")
    datecol = {"daily_sales": "d.date", "expenses": "e.date", "daily_ops": "o.date", "kpi_values": "k.date", "audit_log": "ts"}.get(name)
    if month and datecol:
        d1, d2 = reports.month_bounds(month)
        where.append(f"{datecol}>=? AND {datecol}<?")
        args += [d1.isoformat(), d2.isoformat()]
    if company and name != "audit_log":
        where.append("s.company=?")
        args.append(company)
    if where:
        q += " WHERE " + " AND ".join(where)
    cur = db().execute(q, args)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([d[0] for d in cur.description])
    w.writerows(cur.fetchall())
    audit("export", name, None, None, {"month": month, "company": company})
    db().commit()
    fn = f"aandj_{name}_{month or 'all'}{'_' + company.split()[0] if company else ''}.csv"
    return Response("﻿" + buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={fn}"})


@app.route("/staff", methods=["GET", "POST"])
@require("staff")
def staff():
    c = db()
    if request.method == "POST":
        try:
            sid = request.form.get("id", type=int)
            vals = dict(shop_id=int(request.form["shop_id"]), name=request.form["name"].strip(), position=request.form.get("position", "").strip(),
                        employment=request.form.get("employment", "full-time"), monthly_pay=num("monthly_pay"), hourly_rate=num("hourly_rate"),
                        cpf_rate=num("cpf_rate", 17), commission_rate=num("commission_rate"), active=1 if request.form.get("active", "1") == "1" else 0)
            if not vals["name"]:
                raise ValueError("Name is required")
            if sid:
                before = c.execute("SELECT * FROM staff WHERE id=?", (sid,)).fetchone()
                c.execute(f"UPDATE staff SET {', '.join(f'{k}=?' for k in vals)} WHERE id=?", (*vals.values(), sid))
                audit("edit staff", "staff", sid, before, vals)
            else:
                cur = c.execute(f"INSERT INTO staff({', '.join(vals)}) VALUES ({','.join('?' * len(vals))})", tuple(vals.values()))
                audit("add staff", "staff", cur.lastrowid, None, vals)
            c.commit()
            flash("Staff saved", "ok")
        except (ValueError, KeyError) as e:
            flash(str(e), "error")
        return redirect(url_for("staff"))
    rows = c.execute("SELECT t.*, s.name shop_name FROM staff t JOIN shops s ON s.id=t.shop_id ORDER BY s.id, t.active DESC, t.name").fetchall()
    return render_template("staff.html", rows=rows, shops=visible_shops(), edit=request.args.get("edit", type=int))


@app.route("/budgets", methods=["GET", "POST"])
@require("budgets")
def budgets():
    c = db()
    month = request.values.get("month") or today().strftime("%Y-%m")
    shops = visible_shops()
    lines = ["Sales"] + [r["name"] for r in c.execute("SELECT name FROM categories ORDER BY sort")]
    if request.method == "POST":
        try:
            n = 0
            for s in shops:
                for i, ln in enumerate(lines):
                    v = request.form.get(f"b_{s['id']}_{i}", "").replace(",", "").strip()
                    old = c.execute("SELECT * FROM budgets WHERE shop_id=? AND month=? AND line=? AND kind='budget'", (s["id"], month, ln)).fetchone()
                    if v == "":
                        continue
                    v = float(v)
                    if old and old["amount"] == v:
                        continue
                    c.execute("INSERT INTO budgets(shop_id, month, line, kind, amount) VALUES (?,?,?,?,?) ON CONFLICT(shop_id, month, line, kind) DO UPDATE SET amount=excluded.amount",
                              (s["id"], month, ln, "budget", v))
                    audit("set budget", "budgets", s["id"], old, {"month": month, "line": ln, "amount": v})
                    n += 1
            c.commit()
            flash(f"Budget saved ({n} changes)", "ok")
        except ValueError:
            flash("Budgets must be numbers", "error")
        return redirect(url_for("budgets", month=month))
    vals = {(r["shop_id"], r["line"]): r["amount"] for r in c.execute("SELECT * FROM budgets WHERE month=? AND kind='budget'", (month,))}
    base = {r["shop_id"]: r["amount"] for r in c.execute("SELECT * FROM budgets WHERE kind='baseline' AND line='Sales'")}
    return render_template("budgets.html", month=month, shops=shops, lines=lines, vals=vals, base=base)


@app.route("/admin", methods=["GET", "POST"])
@require("admin")
def admin():
    c = db()
    if request.method == "POST":
        a = request.form.get("action")
        try:
            if a == "settings":
                for k in ("receipt_threshold", "approval_limit", "gm_approval_limit", "deadline_hour", "sales_drop_pct"):
                    v = float(request.form[k])
                    old = setting(k)
                    if str(old) != request.form[k]:
                        c.execute("UPDATE settings SET value=? WHERE key=?", (request.form[k], k))
                        audit("change setting", "settings", None, {"key": k, "value": old}, {"key": k, "value": request.form[k]})
                for k in ("require_2fa",):
                    v = "1" if request.form.get(k) else "0"
                    if setting(k) != v:
                        c.execute("UPDATE settings SET value=? WHERE key=?", (v, k))
                        audit("change setting", "settings", None, {"key": k, "value": setting(k)}, {"key": k, "value": v})
                c.execute("UPDATE settings SET value=? WHERE key='app_url'", (request.form.get("app_url", "").rstrip("/"),))
            elif a == "shop":
                sid = request.form.get("id", type=int)
                vals = {k: request.form.get(k, "").strip() for k in ("code", "name", "name_zh", "company", "uen", "address", "kind", "manager")}
                vals["active"] = 1 if request.form.get("active") else 0
                if not vals["code"] or not vals["name"] or not vals["company"]:
                    raise ValueError("Code, name and company are required")
                if sid:
                    before = c.execute("SELECT * FROM shops WHERE id=?", (sid,)).fetchone()
                    c.execute(f"UPDATE shops SET {', '.join(f'{k}=?' for k in vals)} WHERE id=?", (*vals.values(), sid))
                    audit("edit shop", "shops", sid, before, vals)
                else:
                    cur = c.execute(f"INSERT INTO shops({', '.join(vals)}) VALUES ({','.join('?' * len(vals))})", tuple(vals.values()))
                    audit("add shop", "shops", cur.lastrowid, None, vals)
            elif a == "user":
                uid = request.form.get("id", type=int)
                role = request.form["role"]
                if role not in ROLES:
                    raise ValueError("Unknown role")
                shop_id = request.form.get("shop_id", type=int) if role == "manager" else None
                if role == "manager" and not shop_id:
                    raise ValueError("A shop manager needs a shop")
                vals = dict(username=request.form["username"].strip().lower(), name=request.form["name"].strip(), role=role, shop_id=shop_id,
                            email=request.form.get("email", "").strip(), phone=request.form.get("phone", "").strip(),
                            active=1 if request.form.get("active") else 0)
                if uid:
                    before = c.execute("SELECT id, username, name, role, shop_id, email, phone, active FROM users WHERE id=?", (uid,)).fetchone()
                    c.execute(f"UPDATE users SET {', '.join(f'{k}=?' for k in vals)} WHERE id=?", (*vals.values(), uid))
                    if request.form.get("password"):
                        c.execute("UPDATE users SET pw_hash=? WHERE id=?", (generate_password_hash(request.form["password"]), uid))
                    if request.form.get("reset_2fa"):
                        c.execute("UPDATE users SET totp_secret=NULL WHERE id=?", (uid,))
                    audit("edit user", "users", uid, before, vals)
                else:
                    if len(request.form.get("password", "")) < 8:
                        raise ValueError("New users need a password of at least 8 characters")
                    cur = c.execute(f"INSERT INTO users({', '.join(vals)}, pw_hash) VALUES ({','.join('?' * len(vals))}, ?)",
                                    (*vals.values(), generate_password_hash(request.form["password"])))
                    audit("add user", "users", cur.lastrowid, None, vals)
            elif a == "category":
                cid = request.form.get("id", type=int)
                vals = dict(name=request.form["name"].strip(), account_code=request.form.get("account_code", "").strip(),
                            includes=request.form.get("includes", "").strip(), used_for=request.form.get("used_for", "").strip(),
                            needs_purpose=1 if request.form.get("needs_purpose") else 0)
                if cid:
                    before = c.execute("SELECT * FROM categories WHERE id=?", (cid,)).fetchone()
                    if before["name"] != vals["name"]:
                        raise ValueError("Category names cannot be renamed once used (add a new one instead) – keeps the books consistent")
                    c.execute(f"UPDATE categories SET {', '.join(f'{k}=?' for k in vals)} WHERE id=?", (*vals.values(), cid))
                    audit("edit category", "categories", cid, before, vals)
                else:
                    n = c.execute("SELECT COALESCE(MAX(sort),0)+1 n FROM categories").fetchone()["n"]
                    cur = c.execute("INSERT INTO categories(name, account_code, includes, used_for, needs_purpose, sort) VALUES (?,?,?,?,?,?)",
                                    (*vals.values(), n))
                    audit("add category", "categories", cur.lastrowid, None, vals)
            c.commit()
            flash("Saved", "ok")
        except (ValueError, KeyError) as e:
            flash(str(e) or "Missing field", "error")
        except Exception as e:  # e.g. unique constraint
            flash(f"Could not save: {e}", "error")
        return redirect(url_for("admin", tab=request.form.get("tab", "")))
    return render_template("admin.html", settings={r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")},
                           shops=c.execute("SELECT * FROM shops ORDER BY id").fetchall(),
                           users=c.execute("SELECT u.*, s.code shop_code FROM users u LEFT JOIN shops s ON s.id=u.shop_id ORDER BY u.id").fetchall(),
                           cats=c.execute("SELECT * FROM categories ORDER BY sort").fetchall(), tab=request.args.get("tab", "settings"))


@app.route("/admin/kpi", methods=["GET", "POST"])
@require("admin")
def admin_kpi():
    c = db()
    shop = pick_shop()
    if request.method == "POST":
        a = request.form.get("action")
        try:
            if a == "field":
                fid = request.form.get("id", type=int)
                key = request.form["key"].strip().lower().replace(" ", "_")
                if not key.isidentifier():
                    raise ValueError("Key must be letters, digits and _ only")
                ftype = request.form.get("ftype", "number")
                agg = "formula" if ftype == "formula" else request.form.get("agg", "sum")
                formula = request.form.get("formula", "").strip() or None
                if ftype == "formula":
                    keys = [f["key"] for f in reports.kpi_fields(c, shop["id"], False) if f["ftype"] != "formula"]
                    reports.validate_formula(formula or "", keys)
                vals = dict(key=key, label=request.form["label"].strip(), ftype=ftype, agg=agg, formula=formula,
                            unit=request.form.get("unit", "").strip(), sort=request.form.get("sort", type=int) or 0,
                            active=1 if request.form.get("active") else 0)
                if fid:
                    before = c.execute("SELECT * FROM kpi_fields WHERE id=?", (fid,)).fetchone()
                    c.execute(f"UPDATE kpi_fields SET {', '.join(f'{k}=?' for k in vals)} WHERE id=?", (*vals.values(), fid))
                    audit("edit KPI field", "kpi_fields", fid, before, vals)
                else:
                    cur = c.execute(f"INSERT INTO kpi_fields(shop_id, {', '.join(vals)}) VALUES (?, {','.join('?' * len(vals))})", (shop["id"], *vals.values()))
                    audit("add KPI field", "kpi_fields", cur.lastrowid, None, vals)
            elif a == "target":
                metric = request.form["metric"]
                f = lambda k: float(request.form[k]) if request.form.get(k, "").strip() != "" else None
                vals = (shop["id"], metric, f("baseline"), f("floor"), f("target"), request.form.get("direction", "up"))
                before = c.execute("SELECT * FROM kpi_targets WHERE shop_id=? AND metric=?", (shop["id"], metric)).fetchone()
                if request.form.get("remove") and before:
                    c.execute("DELETE FROM kpi_targets WHERE id=?", (before["id"],))
                    audit("remove KPI target", "kpi_targets", before["id"], before, None)
                else:
                    c.execute("""INSERT INTO kpi_targets(shop_id, metric, baseline, floor, target, direction) VALUES (?,?,?,?,?,?)
                                 ON CONFLICT(shop_id, metric) DO UPDATE SET baseline=excluded.baseline, floor=excluded.floor,
                                 target=excluded.target, direction=excluded.direction""", vals)
                    audit("set KPI target", "kpi_targets", None, before, dict(zip(("shop", "metric", "baseline", "floor", "target", "direction"), vals)))
            c.commit()
            flash("Saved", "ok")
        except (ValueError, KeyError, SyntaxError) as e:
            flash(f"Not saved: {e}", "error")
        except Exception as e:
            flash(f"Could not save: {e}", "error")
        return redirect(url_for("admin_kpi", shop=shop["id"]))
    fields = reports.kpi_fields(c, shop["id"], False)
    targets = c.execute("SELECT * FROM kpi_targets WHERE shop_id=? ORDER BY id", (shop["id"],)).fetchall()
    metric_opts = [(k, v[0]) for k, v in reports.BUILTIN_METRICS.items()] + [(f["key"], f["label"]) for f in fields if f["ftype"] != "text"]
    return render_template("admin_kpi.html", shop=shop, shops=visible_shops(), fields=fields, targets=targets, metric_opts=metric_opts,
                           labels=dict(metric_opts))


@app.route("/uploads/<path:name>")
def uploads(name):
    if not g.user:
        abort(403)
    if g.user["role"] == "manager":
        c = db()
        own = c.execute("SELECT 1 FROM daily_sales WHERE pos_photo=? AND shop_id=? UNION SELECT 1 FROM expenses WHERE receipt=? AND shop_id=?",
                        (name, g.user["shop_id"], name, g.user["shop_id"])).fetchone()
        if not own:
            abort(403)
    elif g.user["role"] == "owner":
        abort(403)
    return send_from_directory(UPLOADS, name)


@app.route("/backup")
@require("admin")
def backup():
    path = automation.backup(db(), now())
    audit("download backup")
    db().commit()
    return send_from_directory(BACKUPS, os.path.basename(path), as_attachment=True)


@app.route("/guide")
def guide():
    lang_ = request.args.get("lang") or session.get("lang", "en")
    fn = "manager_guide_zh.md" if lang_ == "zh" else "manager_guide_en.md"
    with open(os.path.join(os.path.dirname(__file__), "docs", fn), encoding="utf-8") as f:
        return render_template("guide.html", text=f.read(), lang_=lang_)


@app.errorhandler(403)
def forbidden(_e):
    return render_template("error.html", code=403, msg="You don't have access to this page / 您无权查看此页面"), 403


@app.errorhandler(404)
def notfound(_e):
    return render_template("error.html", code=404, msg="Page not found"), 404


@app.errorhandler(400)
def badreq(e):
    return render_template("error.html", code=400, msg=getattr(e, "description", "Bad request")), 400


# ---------------------------------------------------------------- background scheduler
def _scheduler():
    while True:
        try:
            c = connect()
            automation.run_all(c)
            c.close()
        except Exception as exc:
            app.logger.warning("automation failed: %s", exc)
        time.sleep(int(os.environ.get("AANDJ_JOB_SECONDS", "300")))


def start_scheduler():
    if os.environ.get("AANDJ_NO_SCHEDULER") != "1":
        threading.Thread(target=_scheduler, daemon=True).start()


ensure_db()

if __name__ == "__main__":
    start_scheduler()
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")), debug=False)
