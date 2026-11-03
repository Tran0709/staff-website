"""Database schema, connection helpers and demo seed data for the AANDJ reporting system."""
import json
import os
import random
import sqlite3
from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("AANDJ_DB", os.path.join(BASE, "data", "aandj.db"))
UPLOADS = os.path.join(BASE, "data", "uploads")
BACKUPS = os.path.join(BASE, "data", "backups")

SCHEMA = """
CREATE TABLE IF NOT EXISTS shops (
  id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, name_zh TEXT,
  company TEXT NOT NULL, uen TEXT, address TEXT, kind TEXT NOT NULL, manager TEXT,
  active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL,
  shop_id INTEGER REFERENCES shops(id), email TEXT, phone TEXT, pw_hash TEXT NOT NULL,
  totp_secret TEXT, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, account_code TEXT, includes TEXT, used_for TEXT,
  needs_purpose INTEGER NOT NULL DEFAULT 0, sort INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS daily_sales (
  id INTEGER PRIMARY KEY, shop_id INTEGER NOT NULL REFERENCES shops(id), date TEXT NOT NULL,
  gross REAL NOT NULL, discounts REAL NOT NULL DEFAULT 0, refunds REAL NOT NULL DEFAULT 0, net REAL NOT NULL,
  cash REAL NOT NULL DEFAULT 0, paynow REAL NOT NULL DEFAULT 0, card REAL NOT NULL DEFAULT 0,
  platforms REAL NOT NULL DEFAULT 0, transactions INTEGER NOT NULL DEFAULT 0, customers INTEGER NOT NULL DEFAULT 0,
  pos_photo TEXT, cash_deposit REAL NOT NULL DEFAULT 0, deposit_ref TEXT, notes TEXT,
  submitted_by INTEGER, submitted_at TEXT NOT NULL, UNIQUE(shop_id, date));
CREATE TABLE IF NOT EXISTS expenses (
  id INTEGER PRIMARY KEY, shop_id INTEGER NOT NULL REFERENCES shops(id), date TEXT NOT NULL,
  supplier TEXT NOT NULL, category TEXT NOT NULL, amount REAL NOT NULL, gst REAL NOT NULL DEFAULT 0,
  payment_mode TEXT NOT NULL, receipt TEXT, purpose TEXT, paid_status TEXT NOT NULL DEFAULT 'paid',
  status TEXT NOT NULL DEFAULT 'approved', approver_level TEXT, approved_by INTEGER, approved_at TEXT,
  submitted_by INTEGER, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS daily_ops (
  id INTEGER PRIMARY KEY, shop_id INTEGER NOT NULL REFERENCES shops(id), date TEXT NOT NULL,
  staff_on_shift INTEGER NOT NULL DEFAULT 0, staff_hours REAL NOT NULL DEFAULT 0, absences TEXT,
  lateness TEXT, complaints TEXT, compliments TEXT, equipment_issues TEXT, stock_issues TEXT, gm_items TEXT,
  submitted_by INTEGER, submitted_at TEXT NOT NULL, UNIQUE(shop_id, date));
CREATE TABLE IF NOT EXISTS kpi_fields (
  id INTEGER PRIMARY KEY, shop_id INTEGER NOT NULL REFERENCES shops(id), key TEXT NOT NULL, label TEXT NOT NULL,
  ftype TEXT NOT NULL DEFAULT 'number', agg TEXT NOT NULL DEFAULT 'sum', formula TEXT, unit TEXT,
  sort INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, UNIQUE(shop_id, key));
CREATE TABLE IF NOT EXISTS kpi_values (
  id INTEGER PRIMARY KEY, shop_id INTEGER NOT NULL, date TEXT NOT NULL, field_id INTEGER NOT NULL REFERENCES kpi_fields(id),
  value TEXT, submitted_by INTEGER, submitted_at TEXT NOT NULL, UNIQUE(shop_id, date, field_id));
CREATE TABLE IF NOT EXISTS kpi_targets (
  id INTEGER PRIMARY KEY, shop_id INTEGER NOT NULL REFERENCES shops(id), metric TEXT NOT NULL,
  baseline REAL, floor REAL, target REAL, direction TEXT NOT NULL DEFAULT 'up', UNIQUE(shop_id, metric));
CREATE TABLE IF NOT EXISTS staff (
  id INTEGER PRIMARY KEY, shop_id INTEGER NOT NULL REFERENCES shops(id), name TEXT NOT NULL, position TEXT,
  employment TEXT NOT NULL DEFAULT 'full-time', monthly_pay REAL NOT NULL DEFAULT 0, hourly_rate REAL NOT NULL DEFAULT 0,
  cpf_rate REAL NOT NULL DEFAULT 17, commission_rate REAL NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS budgets (
  id INTEGER PRIMARY KEY, shop_id INTEGER NOT NULL REFERENCES shops(id), month TEXT NOT NULL, line TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'budget', amount REAL NOT NULL, UNIQUE(shop_id, month, line, kind));
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS month_locks (month TEXT PRIMARY KEY, locked_by INTEGER, locked_at TEXT);
CREATE TABLE IF NOT EXISTS month_close (
  month TEXT NOT NULL, shop_id INTEGER NOT NULL, item TEXT NOT NULL, done_by INTEGER, done_at TEXT,
  PRIMARY KEY(month, shop_id, item));
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, user_id INTEGER, username TEXT, action TEXT NOT NULL,
  tbl TEXT, record_id INTEGER, before TEXT, after TEXT);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, kind TEXT NOT NULL, shop_id INTEGER, ref TEXT NOT NULL,
  message TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0, UNIQUE(kind, shop_id, ref));
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, to_user INTEGER, to_addr TEXT, kind TEXT NOT NULL,
  ref TEXT, subject TEXT NOT NULL, body TEXT NOT NULL, delivered TEXT);
CREATE TRIGGER IF NOT EXISTS no_delete_sales BEFORE DELETE ON daily_sales BEGIN SELECT RAISE(ABORT, 'raw data cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_exp BEFORE DELETE ON expenses BEGIN SELECT RAISE(ABORT, 'raw data cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_ops BEFORE DELETE ON daily_ops BEGIN SELECT RAISE(ABORT, 'raw data cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_kpi BEFORE DELETE ON kpi_values BEGIN SELECT RAISE(ABORT, 'raw data cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_audit BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_audit BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
"""

CATEGORIES = [
    ("Cost of goods sold", "5000", "Ingredients, beauty consumables, retail stock", "Food cost %, gross margin", 0),
    ("Staff", "6000", "Salaries, CPF, commissions, bonuses, part-timers", "Staff cost %, sales per employee", 0),
    ("Rent", "6100", "Rent, management and service charges", "Rent as % of sales", 0),
    ("Utilities", "6200", "Electricity, water, gas, internet, phone", "Fixed costs", 0),
    ("Marketing", "6300", "Ads, KOL fees, printing, promotions", "Cost per customer, marketing return", 0),
    ("Operations", "6400", "Cleaning, repairs, small tools, delivery-platform commission", "Operating efficiency", 0),
    ("Professional fees", "6500", "Accounting, legal, recruitment agencies, licences", "Overheads", 0),
    ("Systems", "6600", "POS, booking systems, software subscriptions", "Overheads", 0),
    ("Others", "6900", "Purpose must be stated", "Approval needed above the limit", 1),
]

SHOPS = [
    ("CYZ", "Cai Yuan Zi", "菜园子", "Cai Yuan Zi Pte. Ltd.", "TBC (Week 1)", "118 Killiney Rd #01-02", "restaurant"),
    ("SIM", "Simply Aesthetique", "Simply 美学", "Simply Aesthetique Pte. Ltd.", "TBC (Week 1)", "Capitol Piazza #B1-28", "beauty"),
    ("BRW", "Brow Secrets", "眉秘", "Brow Secrets Pte. Ltd.", "TBC (Week 1)", "360 Orchard Rd #02-13", "brow"),
    ("VEN", "Poker Federation venue", "扑克联合会场地", "Poker Federation venue (company TBC)", "TBC (Week 1)", "Orchard Towers #02-43", "venue"),
    ("AIW", "AI Smart Wellness Centre", "AI 智能健康中心", "AI Smart Wellness Centre (company TBC)", "TBC (Week 1)", "Unit #01-32 (address TBC)", "wellness"),
]

# (key, label, ftype, agg, formula, unit)
KPI_FIELDS = {
    "CYZ": [
        ("lunch_covers", "Lunch covers", "number", "sum", None, ""),
        ("dinner_covers", "Dinner covers", "number", "sum", None, ""),
        ("dine_in_sales", "Dine-in sales", "number", "sum", None, "S$"),
        ("takeaway_sales", "Takeaway sales", "number", "sum", None, "S$"),
        ("resident_orders", "Resident orders", "number", "sum", None, ""),
        ("delivery_sales", "Delivery-app sales", "number", "sum", None, "S$"),
        ("wastage", "Wastage value", "number", "sum", None, "S$"),
        ("best_dish", "Best dish", "text", "last", None, ""),
        ("worst_dish", "Worst dish", "text", "last", None, ""),
        ("google_reviews", "New Google reviews", "number", "sum", None, ""),
        ("google_rating", "Google rating", "number", "last", None, "★"),
    ],
    "SIM": [
        ("leads_social", "Leads – social media", "number", "sum", None, ""),
        ("leads_walkin", "Leads – walk-in", "number", "sum", None, ""),
        ("leads_referral", "Leads – referral", "number", "sum", None, ""),
        ("consultations", "Consultations", "number", "sum", None, ""),
        ("packages_sold", "Packages sold", "number", "sum", None, ""),
        ("prepaid_sold", "Prepaid packages sold (value)", "number", "sum", None, "S$"),
        ("prepaid_redeemed", "Prepaid packages redeemed (value)", "number", "sum", None, "S$"),
        ("room_hours_used", "Treatment room hours used", "number", "sum", None, "h"),
        ("room_hours_avail", "Treatment room hours available", "number", "sum", None, "h"),
        ("therapist_commission", "Therapist commission", "number", "sum", None, "S$"),
        ("treatments", "Treatments done", "number", "sum", None, ""),
        ("rebookings", "Rebookings", "number", "sum", None, ""),
        ("room_utilisation", "Room utilisation %", "formula", "formula", "room_hours_used / room_hours_avail * 100", "%"),
        ("rebooking_rate", "Rebooking rate %", "formula", "formula", "rebookings / treatments * 100", "%"),
    ],
    "BRW": [
        ("leads_influencer", "Leads – influencer codes", "number", "sum", None, ""),
        ("leads_other", "Leads – other sources", "number", "sum", None, ""),
        ("influencer_codes", "Influencer codes used", "text", "last", None, ""),
        ("bookings", "Bookings", "number", "sum", None, ""),
        ("show_ups", "Show-ups", "number", "sum", None, ""),
        ("paid_visits", "Paid visits", "number", "sum", None, ""),
        ("referrals", "Referrals", "number", "sum", None, ""),
        ("influencer_share", "Influencer share paid", "number", "sum", None, "S$"),
        ("google_reviews", "New Google reviews", "number", "sum", None, ""),
        ("show_up_rate", "Show-up rate %", "formula", "formula", "show_ups / bookings * 100", "%"),
        ("visit_to_paid", "Visit-to-paid conversion %", "formula", "formula", "paid_visits / show_ups * 100", "%"),
    ],
    "VEN": [
        ("enquiries", "Enquiries", "number", "sum", None, ""),
        ("site_visits", "Site visits", "number", "sum", None, ""),
        ("event_bookings", "Confirmed event bookings", "number", "sum", None, ""),
        ("rooms_let", "Rooms let", "number", "sum", None, ""),
        ("rent_collected", "Rent collected", "number", "sum", None, "S$"),
        ("rent_payable", "Rent payable", "number", "sum", None, "S$"),
        ("hours_booked", "Space hours booked", "number", "sum", None, "h"),
        ("hours_avail", "Space hours available", "number", "sum", None, "h"),
        ("pipeline_value", "Prospect pipeline value", "number", "last", None, "S$"),
        ("prospects", "Prospect pipeline notes", "text", "last", None, ""),
        ("rent_collected_pct", "Rent collected vs payable %", "formula", "formula", "rent_collected / rent_payable * 100", "%"),
        ("space_utilisation", "Space utilisation %", "formula", "formula", "hours_booked / hours_avail * 100", "%"),
    ],
    "AIW": [
        ("ai_checks", "AI health checks done", "number", "sum", None, ""),
        ("paid_after_check", "Paid after check", "number", "sum", None, ""),
        ("treatment_sessions", "Treatment sessions", "number", "sum", None, ""),
        ("memberships_sold", "Memberships sold", "number", "sum", None, ""),
        ("package_sales", "Package sales (value)", "number", "sum", None, "S$"),
        ("members_total", "Active members", "number", "last", None, ""),
        ("repeat_customers", "Repeat customers", "number", "sum", None, ""),
        ("feedback_score", "Customer feedback score (1–5)", "number", "avg", None, ""),
        ("feedback_notes", "Customer feedback notes", "text", "last", None, ""),
        ("check_to_paid", "Check-to-paid conversion %", "formula", "formula", "paid_after_check / ai_checks * 100", "%"),
    ],
}

DEFAULT_SETTINGS = {
    "receipt_threshold": "0",      # receipt photo required for any expense above this (brief: "S$____" – to confirm)
    "approval_limit": "500",       # above this → head (Finance) approval
    "gm_approval_limit": "2000",   # above this → GM approval
    "deadline_hour": "23",         # daily submission deadline (11pm)
    "require_2fa": "0",            # force every user to enrol two-factor login
    "sales_drop_pct": "15",        # alert when sales fall more than this vs same day last week
    "app_url": "http://127.0.0.1:5000",
}

DEMO_PASSWORD = "aandj123"


def connect(path=None):
    conn = sqlite3.connect(path or DB_PATH, detect_types=0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    conn.commit()


def _placeholder_png(path):
    import base64
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    with open(path, "wb") as f:
        f.write(png)


def seed(conn, today=None, days=95):
    """Load master data plus ~3 months of demo transactions (the 'baseline')."""
    rnd = random.Random(7)
    today = today or date.today()
    now = datetime.now().isoformat(timespec="seconds")
    os.makedirs(UPLOADS, exist_ok=True)
    _placeholder_png(os.path.join(UPLOADS, "seed_receipt.png"))

    for i, c in enumerate(CATEGORIES):
        conn.execute("INSERT INTO categories(name, account_code, includes, used_for, needs_purpose, sort) VALUES (?,?,?,?,?,?)",
                     (*c, i))
    shop_ids = {}
    managers = {"CYZ": "Li Wei", "SIM": "Grace Lim", "BRW": "Mei Ling", "VEN": "Daniel Koh", "AIW": "Dr. Sun"}
    for code, name, zh, company, uen, addr, kind in SHOPS:
        cur = conn.execute("INSERT INTO shops(code, name, name_zh, company, uen, address, kind, manager) VALUES (?,?,?,?,?,?,?,?)",
                           (code, name, zh, company, uen, addr, kind, managers[code]))
        shop_ids[code] = cur.lastrowid

    pw = generate_password_hash(DEMO_PASSWORD)
    users = [
        ("joe", "Joe Chen", "gm", None, "joe@aandj.example"),
        ("amanda", "Amanda He", "finance", None, "amanda@aandj.example"),
        ("nicholas", "Nicholas Tan", "coo", None, "nicholas@aandj.example"),
        ("jade", "Jade Zhao", "marketing", None, "jade@aandj.example"),
        ("accountant", "Accountant (to be appointed)", "accountant", None, "accounts@aandj.example"),
        ("dong", "Boss Dong", "owner", None, "dong@aandj.example"),
    ] + [(f"mgr_{c.lower()}", managers[c], "manager", shop_ids[c], f"{c.lower()}@aandj.example") for c in shop_ids]
    for u in users:
        conn.execute("INSERT INTO users(username, name, role, shop_id, email, pw_hash) VALUES (?,?,?,?,?,?)", (*u, pw))

    for code, fields in KPI_FIELDS.items():
        for i, (key, label, ftype, agg, formula, unit) in enumerate(fields):
            conn.execute("INSERT INTO kpi_fields(shop_id, key, label, ftype, agg, formula, unit, sort) VALUES (?,?,?,?,?,?,?,?)",
                         (shop_ids[code], key, label, ftype, agg, formula, unit, i))

    # Sales profile per shop: (base daily net, weekend factor, cogs %, avg ticket, closed weekday)
    profile = {
        "CYZ": (5200, 1.35, 0.31, 42, None),
        "SIM": (3800, 1.2, 0.10, 260, None),
        "BRW": (2100, 1.25, 0.08, 180, None),
        "VEN": (1500, 1.6, 0.03, 300, None),
        "AIW": (1200, 1.3, 0.12, 120, None),
    }
    rent = {"CYZ": 14000, "SIM": 11000, "BRW": 7500, "VEN": 9000, "AIW": 8000}
    staff_seed = {
        "CYZ": [("Chef Zhang", "Head chef", 5200), ("Ah Hock", "Cook", 3200), ("Siti", "Service", 2600), ("Kumar", "Service", 2500)],
        "SIM": [("Grace Lim", "Manager", 4800), ("Joyce", "Therapist", 3000), ("Wen", "Therapist", 2900)],
        "BRW": [("Mei Ling", "Manager / artist", 4200), ("Anna", "Brow artist", 3000)],
        "VEN": [("Daniel Koh", "Venue manager", 4500), ("Ravi", "Event crew", 2400)],
        "AIW": [("Dr. Sun", "Centre lead", 5500), ("Lily", "Wellness therapist", 2800)],
    }
    for code, rows in staff_seed.items():
        for name, pos, pay in rows:
            conn.execute("INSERT INTO staff(shop_id, name, position, monthly_pay, commission_rate) VALUES (?,?,?,?,?)",
                         (shop_ids[code], name, pos, pay, 5 if code in ("SIM", "BRW") and pos != "Manager" else 0))

    start = today - timedelta(days=days)
    sup = {"CYZ": "Sheng Siong Wholesale", "SIM": "Beauty Supply Co", "BRW": "Brow Pro Supplies", "VEN": "Drinks Depot", "AIW": "Wellness Consumables"}
    fields_by_shop = {code: {r["key"]: r["id"] for r in conn.execute("SELECT id, key FROM kpi_fields WHERE shop_id=?", (sid,))}
                      for code, sid in shop_ids.items()}
    monthly = {}
    d = start
    while d < today:
        for code, sid in shop_ids.items():
            base, wkend, cogs, ticket, closed = profile[code]
            # Missing / late submissions to show reminders: yesterday not submitted for VEN and AIW
            if d == today - timedelta(days=1) and code in ("VEN", "AIW"):
                continue
            if closed is not None and d.weekday() == closed:
                continue
            factor = wkend if d.weekday() >= 5 else 1.0
            trend = 1 + 0.002 * (d - start).days
            net = round(base * factor * trend * rnd.uniform(0.82, 1.15), 2)
            # A visible sales dip for CYZ yesterday (> 15% vs same day last week)
            if code == "CYZ" and d == today - timedelta(days=1):
                net = round(base * factor * 0.6, 2)
            disc = round(net * 0.04, 2)
            refunds = round(net * 0.005, 2)
            gross = round(net + disc + refunds, 2)
            plat = round(net * (0.18 if code == "CYZ" else 0), 2)
            card = round((net - plat) * 0.55, 2)
            paynow = round((net - plat) * 0.3, 2)
            cash = round(net - plat - card - paynow, 2)
            cust = max(1, int(net / ticket))
            submitted = datetime.combine(d, datetime.min.time()) + timedelta(hours=22, minutes=rnd.randint(0, 50))
            if rnd.random() < 0.04:
                submitted += timedelta(hours=10)  # occasional late submission
            conn.execute("""INSERT INTO daily_sales(shop_id, date, gross, discounts, refunds, net, cash, paynow, card, platforms,
                         transactions, customers, pos_photo, cash_deposit, deposit_ref, submitted_by, submitted_at)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (sid, d.isoformat(), gross, disc, refunds, net, cash, paynow, card, plat, cust + rnd.randint(0, 5), cust,
                          "seed_receipt.png", cash, f"DEP{d:%m%d}{code}", None, submitted.isoformat(timespec="seconds")))
            # daily COGS purchase
            conn.execute("""INSERT INTO expenses(shop_id, date, supplier, category, amount, gst, payment_mode, receipt, paid_status,
                         status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                         (sid, d.isoformat(), sup[code], "Cost of goods sold", round(net * cogs * rnd.uniform(0.9, 1.15), 2), 0,
                          "Bank transfer", "seed_receipt.png", "payable" if rnd.random() < 0.3 else "paid", "approved", now))
            if code == "CYZ" and d.weekday() == 2:
                conn.execute("""INSERT INTO expenses(shop_id, date, supplier, category, amount, gst, payment_mode, receipt, paid_status,
                             status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                             (sid, d.isoformat(), "GrabFood / foodpanda", "Operations", round(plat * 6, 2), 0, "Platform deduction",
                              "seed_receipt.png", "paid", "approved", now))
            if d.weekday() == 0:
                conn.execute("""INSERT INTO expenses(shop_id, date, supplier, category, amount, gst, payment_mode, receipt, paid_status,
                             status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                             (sid, d.isoformat(), "Meta Ads", "Marketing", round(rnd.uniform(150, 450), 2), 0, "Card",
                              "seed_receipt.png", "paid", "approved", now))
            # daily ops
            staff_n = len(staff_seed[code])
            conn.execute("""INSERT INTO daily_ops(shop_id, date, staff_on_shift, staff_hours, absences, lateness, complaints, compliments,
                         equipment_issues, stock_issues, gm_items, submitted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (sid, d.isoformat(), staff_n, staff_n * 8.5, "" if rnd.random() > 0.08 else "1 staff on MC",
                          "" if rnd.random() > 0.1 else "1 staff 15 min late",
                          "" if rnd.random() > 0.07 else "Long wait time at peak", "" if rnd.random() > 0.3 else "Customer praised service",
                          "" if rnd.random() > 0.04 else "Aircon leaking", "" if rnd.random() > 0.05 else "Short of supplies",
                          "", submitted.isoformat(timespec="seconds")))
            # KPI values
            f = fields_by_shop[code]
            vals = {}
            if code == "CYZ":
                vals = {"lunch_covers": int(cust * 0.42), "dinner_covers": int(cust * 0.58), "dine_in_sales": round(net * 0.62, 2),
                        "takeaway_sales": round(net * 0.12, 2), "resident_orders": rnd.randint(2, 9), "delivery_sales": plat,
                        "wastage": round(rnd.uniform(40, 140), 2), "best_dish": rnd.choice(["Chairman's fish head", "Hunan pork belly"]),
                        "worst_dish": rnd.choice(["Cold tofu", "Bitter gourd"]), "google_reviews": rnd.randint(0, 4),
                        "google_rating": round(rnd.uniform(4.3, 4.6), 1)}
            elif code == "SIM":
                tr = cust + rnd.randint(2, 6)
                vals = {"leads_social": rnd.randint(2, 8), "leads_walkin": rnd.randint(0, 3), "leads_referral": rnd.randint(0, 2),
                        "consultations": rnd.randint(2, 6), "packages_sold": rnd.randint(0, 3), "prepaid_sold": round(rnd.uniform(0, 3000), 2),
                        "prepaid_redeemed": round(rnd.uniform(500, 2200), 2), "room_hours_used": rnd.randint(14, 26),
                        "room_hours_avail": 30, "therapist_commission": round(net * 0.05, 2), "treatments": tr,
                        "rebookings": int(tr * rnd.uniform(0.35, 0.6))}
            elif code == "BRW":
                b = rnd.randint(8, 16)
                s = int(b * rnd.uniform(0.75, 0.95))
                vals = {"leads_influencer": rnd.randint(2, 9), "leads_other": rnd.randint(1, 5), "influencer_codes": "JADE10, MEIBROW",
                        "bookings": b, "show_ups": s, "paid_visits": int(s * rnd.uniform(0.6, 0.9)), "referrals": rnd.randint(0, 3),
                        "influencer_share": round(net * 0.06, 2), "google_reviews": rnd.randint(0, 3)}
            elif code == "VEN":
                vals = {"enquiries": rnd.randint(1, 6), "site_visits": rnd.randint(0, 3), "event_bookings": rnd.randint(0, 2),
                        "rooms_let": rnd.randint(1, 4), "rent_collected": round(rnd.uniform(150, 420), 2), "rent_payable": 400,
                        "hours_booked": rnd.randint(4, 12), "hours_avail": 14, "pipeline_value": 18000 + rnd.randint(0, 6000),
                        "prospects": "Corporate poker night (Dec), charity tournament"}
            elif code == "AIW":
                ch = rnd.randint(6, 15)
                vals = {"ai_checks": ch, "paid_after_check": int(ch * rnd.uniform(0.25, 0.5)), "treatment_sessions": rnd.randint(5, 12),
                        "memberships_sold": rnd.randint(0, 2), "package_sales": round(rnd.uniform(0, 1500), 2),
                        "members_total": 40 + (d - start).days // 3, "repeat_customers": rnd.randint(2, 7),
                        "feedback_score": round(rnd.uniform(4.0, 4.9), 1), "feedback_notes": "Clear explanations"}
            for k, v in vals.items():
                conn.execute("INSERT INTO kpi_values(shop_id, date, field_id, value, submitted_at) VALUES (?,?,?,?,?)",
                             (sid, d.isoformat(), f[k], str(v), submitted.isoformat(timespec="seconds")))
            monthly.setdefault((code, d.strftime("%Y-%m")), 0)
            monthly[(code, d.strftime("%Y-%m"))] += net
        # Monthly fixed costs on the 1st / 5th / last day
        if d.day == 1:
            for code, sid in shop_ids.items():
                for supplier, cat, amt in [("Landlord", "Rent", rent[code]), ("Square / Lightspeed", "Systems", 180),
                                           ("Accounting firm", "Professional fees", 600)]:
                    conn.execute("""INSERT INTO expenses(shop_id, date, supplier, category, amount, gst, payment_mode, receipt,
                                 paid_status, status, approver_level, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                                 (sid, d.isoformat(), supplier, cat, amt, round(amt * 0.09, 2), "GIRO", "seed_receipt.png", "paid",
                                  "approved", "pre-approved", now))
        if d.day == 5:
            for code, sid in shop_ids.items():
                conn.execute("""INSERT INTO expenses(shop_id, date, supplier, category, amount, gst, payment_mode, receipt, paid_status,
                             status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                             (sid, d.isoformat(), "SP Group", "Utilities", round(rnd.uniform(700, 1800) if code == "CYZ" else rnd.uniform(250, 600), 2),
                              0, "GIRO", "seed_receipt.png", "paid", "approved", now))
        if (d + timedelta(days=1)).day == 1:  # month-end payroll
            for code, sid in shop_ids.items():
                pay = sum(p for _, _, p in staff_seed[code])
                conn.execute("""INSERT INTO expenses(shop_id, date, supplier, category, amount, gst, payment_mode, receipt, purpose,
                             paid_status, status, approver_level, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                             (sid, d.isoformat(), "Payroll", "Staff", round(pay * 1.17, 2), 0, "Bank transfer", "seed_receipt.png",
                              "Salaries + employer CPF", "paid", "approved", "pre-approved", now))
        d += timedelta(days=1)

    # A couple of pending approvals
    conn.execute("""INSERT INTO expenses(shop_id, date, supplier, category, amount, gst, payment_mode, receipt, purpose, paid_status,
                 status, approver_level, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (shop_ids["CYZ"], (today - timedelta(days=1)).isoformat(), "CoolAir Services", "Operations", 1250, 112.5, "Bank transfer",
                  "seed_receipt.png", "Replace kitchen exhaust motor", "payable", "pending", "head", now))
    conn.execute("""INSERT INTO expenses(shop_id, date, supplier, category, amount, gst, payment_mode, receipt, purpose, paid_status,
                 status, approver_level, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (shop_ids["BRW"], (today - timedelta(days=2)).isoformat(), "KOL @browqueen", "Marketing", 3500, 0, "Bank transfer",
                  "seed_receipt.png", "December influencer campaign", "payable", "pending", "gm", now))

    # Baseline (3-month average) and budgets for the current and neighbouring months
    months = sorted({m for (_, m) in monthly})
    cats = [c[0] for c in CATEGORIES]
    for code, sid in shop_ids.items():
        full = [monthly[(code, m)] for m in months if (code, m) in monthly][1:-1] or [monthly[(code, m)] for m in months if (code, m) in monthly]
        base_sales = sum(full) / len(full)
        m0 = today.replace(day=1)
        for offset in (-2, -1, 0, 1):
            y, mo = m0.year, m0.month + offset
            while mo < 1:
                y, mo = y - 1, mo + 12
            while mo > 12:
                y, mo = y + 1, mo - 12
            mon = f"{y:04d}-{mo:02d}"
            sales_budget = round(base_sales * 1.08, -2)
            lines = {"Sales": sales_budget, "Cost of goods sold": round(sales_budget * profile[code][2], -1),
                     "Staff": round(sum(p for _, _, p in staff_seed[code]) * 1.17, -1), "Rent": rent[code], "Utilities": 1500 if code == "CYZ" else 500,
                     "Marketing": 1600 if code in ("SIM", "BRW") else 1200, "Operations": 1500 if code == "CYZ" else 300,
                     "Professional fees": 600, "Systems": 200, "Others": 200}
            for line, amt in lines.items():
                conn.execute("INSERT INTO budgets(shop_id, month, line, kind, amount) VALUES (?,?,?,?,?)", (sid, mon, line, "budget", amt))
        conn.execute("INSERT INTO budgets(shop_id, month, line, kind, amount) VALUES (?,?,?,?,?)", (sid, "baseline", "Sales", "baseline", round(base_sales, 2)))

        targets = [("net_sales", round(base_sales, -2), round(base_sales * 0.9, -2), round(base_sales * 1.08, -2), "up"),
                   ("customers", None, None, None, "up"),
                   ("gross_margin_pct", None, None, None, "up"),
                   ("staff_cost_pct", None, None, None, "down"),
                   ("net_profit", None, 0, None, "up")]
        for metric, b, fl, tg, dirn in targets:
            conn.execute("INSERT INTO kpi_targets(shop_id, metric, baseline, floor, target, direction) VALUES (?,?,?,?,?,?)",
                         (sid, metric, b, fl, tg, dirn))
    t = lambda code, metric, b, fl, tg, dirn="up": conn.execute(
        "INSERT OR REPLACE INTO kpi_targets(shop_id, metric, baseline, floor, target, direction) VALUES (?,?,?,?,?,?)",
        (shop_ids[code], metric, b, fl, tg, dirn))
    t("CYZ", "food_cost_pct", 31, 34, 30, "down")
    t("CYZ", "customers", 3600, 3300, 4000)
    t("CYZ", "google_rating", 4.4, 4.2, 4.6)
    t("SIM", "room_utilisation", 65, 55, 75)
    t("SIM", "rebooking_rate", 45, 40, 55)
    t("BRW", "show_up_rate", 85, 80, 90)
    t("BRW", "visit_to_paid", 72, 65, 80)
    t("VEN", "rent_collected_pct", 70, 65, 90)
    t("VEN", "space_utilisation", 55, 45, 65)
    t("AIW", "check_to_paid", 35, 30, 45)
    t("AIW", "ai_checks", 300, 250, 350)

    # Previous-previous month already reconciled and locked
    m0 = today.replace(day=1)
    prev2 = (m0 - timedelta(days=1)).replace(day=1) - timedelta(days=1)
    conn.execute("INSERT INTO month_locks(month, locked_by, locked_at) VALUES (?,?,?)", (prev2.strftime("%Y-%m"), 2, now))
    conn.execute("INSERT INTO audit_log(ts, username, action, tbl, after) VALUES (?,?,?,?,?)",
                 (now, "system", "seed", None, json.dumps({"note": "demo data loaded", "from": start.isoformat()})))
    conn.commit()


def ensure_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(UPLOADS, exist_ok=True)
    os.makedirs(BACKUPS, exist_ok=True)
    fresh = not os.path.exists(DB_PATH)
    conn = connect()
    init_db(conn)
    if fresh and os.environ.get("AANDJ_NO_DEMO") != "1":
        seed(conn)
    elif fresh:  # go-live: chart of accounts + one GM account, everything else entered in Admin
        for i, c in enumerate(CATEGORIES):
            conn.execute("INSERT INTO categories(name, account_code, includes, used_for, needs_purpose, sort) VALUES (?,?,?,?,?,?)", (*c, i))
        conn.execute("INSERT INTO users(username, name, role, email, pw_hash) VALUES (?,?,?,?,?)",
                     ("joe", "Joe Chen", "gm", "", generate_password_hash(os.environ.get("AANDJ_ADMIN_PASSWORD", DEMO_PASSWORD))))
        conn.commit()
    conn.close()


if __name__ == "__main__":
    import sys
    if "--reset" in sys.argv and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    ensure_db()
    print("Database ready at", DB_PATH)
