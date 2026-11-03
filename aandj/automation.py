"""Scheduled jobs: late-submission reminders, alerts, Monday dashboard email, month-end reminders, backups.

Everything is idempotent (de-duplicated through the alerts / outbox tables), so the job can run every minute.
Messages go to the in-app outbox; if SMTP_* environment variables are set they are e-mailed as well.
"""
import os
import shutil
import smtplib
import sqlite3
from datetime import date, datetime, timedelta
from email.message import EmailMessage

import reports
from db import BACKUPS, DB_PATH

MONTH_CLOSE_ITEMS = [("stock_count", "Stock count"), ("payroll", "Payroll & CPF"),
                     ("unrecorded", "Unrecorded expenses entered"), ("reconciled", "Bank / cash reconciliation")]


def now():
    fake = os.environ.get("AANDJ_NOW")
    return datetime.fromisoformat(fake) if fake else datetime.now()


def setting(conn, key, default=None):
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def users_with_roles(conn, *roles):
    return conn.execute(f"SELECT * FROM users WHERE active=1 AND role IN ({','.join('?' * len(roles))})", roles).fetchall()


def send(conn, user, kind, ref, subject, body):
    """Queue a message once per (user, kind, ref)."""
    if conn.execute("SELECT 1 FROM outbox WHERE to_user=? AND kind=? AND ref=?", (user["id"], kind, ref)).fetchone():
        return False
    delivered = None
    host = os.environ.get("SMTP_HOST")
    if host and user["email"]:
        try:
            msg = EmailMessage()
            msg["Subject"], msg["From"], msg["To"] = subject, os.environ.get("SMTP_FROM", "reports@aandj.example"), user["email"]
            msg.set_content(body)
            with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=10) as s:
                s.starttls()
                if os.environ.get("SMTP_USER"):
                    s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
                s.send_message(msg)
            delivered = now().isoformat(timespec="seconds")
        except Exception as exc:  # keep the in-app copy even if e-mail fails
            body += f"\n\n[e-mail delivery failed: {exc}]"
    conn.execute("INSERT INTO outbox(created_at, to_user, to_addr, kind, ref, subject, body, delivered) VALUES (?,?,?,?,?,?,?,?)",
                 (now().isoformat(timespec="seconds"), user["id"], user["email"], kind, ref, subject, body, delivered))
    return True


def raise_alert(conn, kind, shop, ref, message):
    cur = conn.execute("INSERT OR IGNORE INTO alerts(created_at, kind, shop_id, ref, message) VALUES (?,?,?,?,?)",
                       (now().isoformat(timespec="seconds"), kind, shop["id"] if shop else None, ref, message))
    if cur.rowcount:
        for gm in users_with_roles(conn, "gm"):
            send(conn, gm, "alert", f"{kind}:{shop['code'] if shop else ''}:{ref}", f"[AANDJ alert] {message}", message)
    return cur.rowcount


def check_late(conn, n):
    deadline = int(setting(conn, "deadline_hour", "23"))
    shops = conn.execute("SELECT * FROM shops WHERE active=1").fetchall()
    for back in range(0, 8):
        day = (n - timedelta(days=back)).date()
        if n < datetime.combine(day, datetime.min.time()) + timedelta(hours=deadline):
            continue
        for s in shops:
            if conn.execute("SELECT 1 FROM daily_sales WHERE shop_id=? AND date=?", (s["id"], day.isoformat())).fetchone():
                continue
            msg = f"{s['name']}: daily sales for {day:%a %d %b} not submitted by {deadline}:00"
            raise_alert(conn, "late_submission", s, day.isoformat(), msg)
            for m in conn.execute("SELECT * FROM users WHERE role='manager' AND active=1 AND shop_id=?", (s["id"],)):
                send(conn, m, "reminder", day.isoformat(), f"Reminder: submit {day:%d %b} sales / 提醒：请提交 {day:%m-%d} 营业数据",
                     f"Hi {m['name']}, the daily report for {s['name']} on {day:%A %d %B} is missing. "
                     f"Please submit sales, payments, customers and expenses now.\n您好，{day.month}月{day.day}日 的日报尚未提交，请尽快填写。")


def check_sales_drop(conn, n):
    limit = float(setting(conn, "sales_drop_pct", "15"))
    for s in conn.execute("SELECT * FROM shops WHERE active=1").fetchall():
        for back in range(0, 7):
            day = (n - timedelta(days=back)).date()
            a = conn.execute("SELECT net FROM daily_sales WHERE shop_id=? AND date=?", (s["id"], day.isoformat())).fetchone()
            b = conn.execute("SELECT net FROM daily_sales WHERE shop_id=? AND date=?", (s["id"], (day - timedelta(days=7)).isoformat())).fetchone()
            if a and b and b["net"] and (a["net"] - b["net"]) / b["net"] * 100 < -limit:
                chg = (a["net"] - b["net"]) / b["net"] * 100
                raise_alert(conn, "sales_drop", s, day.isoformat(),
                            f"{s['name']}: sales {day:%a %d %b} S${a['net']:,.0f} are {chg:.0f}% vs same day last week (S${b['net']:,.0f})")


def check_month(conn, n):
    month = n.strftime("%Y-%m")
    d1, d2 = reports.month_bounds(month)
    for s in conn.execute("SELECT * FROM shops WHERE active=1").fetchall():
        actual = reports.expenses_by_cat(conn, s["id"], d1, d2)
        for b in conn.execute("SELECT line, amount FROM budgets WHERE shop_id=? AND month=? AND kind='budget' AND line<>'Sales'", (s["id"], month)):
            if actual.get(b["line"], 0) > b["amount"]:
                raise_alert(conn, "over_budget", s, f"{month}:{b['line']}",
                            f"{s['name']}: {b['line']} S${actual[b['line']]:,.0f} is over the {month} budget of S${b['amount']:,.0f}")
        m, _ = reports.metrics(conn, s["id"], d1, d2)
        t = conn.execute("SELECT * FROM kpi_targets WHERE shop_id=? AND metric='food_cost_pct'", (s["id"],)).fetchone()
        if t and t["target"] is not None and m["food_cost_pct"] is not None and m["food_cost_pct"] > t["target"] and m["days"] >= 3:
            raise_alert(conn, "food_cost", s, month,
                        f"{s['name']}: food cost {m['food_cost_pct']:.1f}% month-to-date is above the {t['target']:.0f}% target")
        t = conn.execute("SELECT * FROM kpi_targets WHERE shop_id=? AND metric='rent_collected_pct'", (s["id"],)).fetchone()
        v = m.get("rent_collected_pct")
        if t and t["target"] is not None and v is not None and v < t["target"]:
            raise_alert(conn, "venue_rent", s, month,
                        f"{s['name']}: rent collected is {v:.1f}% of rent payable month-to-date, below the {t['target']:.0f}% target")


def weekly_summary_text(conn, ws):
    shops = conn.execute("SELECT * FROM shops WHERE active=1 ORDER BY id").fetchall()
    w = reports.weekly(conn, shops, ws)
    lines = [f"AANDJ weekly dashboard {w['start']:%d %b} – {w['end']:%d %b %Y}", ""]
    tot = sum(r["m"]["net_sales"] for r in w["rows"])
    prof = sum(r["m"]["net_profit"] for r in w["rows"])
    lines.append(f"Group net sales S${tot:,.0f} · profit S${prof:,.0f}")
    lines.append("")
    for i, r in enumerate(w["ranked"], 1):
        g = f"{r['growth']:+.0f}%" if r["growth"] is not None else "n/a"
        lines.append(f"{i}. {r['shop']['name']}: sales S${r['m']['net_sales']:,.0f} ({g} WoW), profit S${r['m']['net_profit']:,.0f}, "
                     f"customers {r['m']['customers']}, staff hours {r['ops']['hours']:.0f}")
    lines.append("")
    lines.append(f"Open the dashboard: {setting(conn, 'app_url', '')}/weekly?week={ws.isoformat()}")
    return "\n".join(lines)


def monday_email(conn, n, force=False):
    if not force and not (n.weekday() == 0 and n.hour >= 10):
        return 0
    ws = reports.week_start(n.date()) - timedelta(days=7)
    body = weekly_summary_text(conn, ws)
    sent = 0
    for u in users_with_roles(conn, "gm", "finance", "coo", "marketing", "owner"):
        sent += send(conn, u, "weekly", ws.isoformat(), f"AANDJ weekly dashboard – week of {ws:%d %b}", body)
    return sent


def month_end(conn, n):
    prev = reports.prev_month(n.strftime("%Y-%m"))
    shops = conn.execute("SELECT * FROM shops WHERE active=1").fetchall()
    if n.day >= 1:
        for s in shops:
            done = {r["item"] for r in conn.execute("SELECT item FROM month_close WHERE month=? AND shop_id=?", (prev, s["id"]))}
            missing = [label for key, label in MONTH_CLOSE_ITEMS if key not in done]
            if missing and n.day > 3:
                raise_alert(conn, "month_close_late", s, prev, f"{s['name']}: {prev} month-end not complete by the 3rd ({', '.join(missing)})")
            elif missing:
                for u in list(conn.execute("SELECT * FROM users WHERE role='manager' AND shop_id=? AND active=1", (s["id"],))) + list(users_with_roles(conn, "finance")):
                    send(conn, u, "month_close", f"{prev}:{s['code']}", f"Month-end {prev} due by the 3rd – {s['name']}",
                         f"Please complete for {s['name']} ({prev}): {', '.join(missing)}. Deadline: the 3rd.")
    if n.day >= 7:
        d1, _ = reports.month_bounds(prev)
        cats = [r["name"] for r in conn.execute("SELECT name FROM categories ORDER BY sort")]
        p = reports.pnl(conn, shops, prev, cats)
        np = next(r for r in p["table"] if r["line"] == "Net profit")
        rev = next(r for r in p["table"] if r["line"] == "Revenue")
        body = f"Management accounts {prev}\nGroup revenue S${rev['group']:,.0f}, net profit S${np['group']:,.0f}\n\n" + "\n".join(
            f"{c['shop']['company']}: revenue S${rev['vals'][i]:,.0f}, net profit S${np['vals'][i]:,.0f}" for i, c in enumerate(p["cols"])) + \
            f"\n\nFull P&L and KPI scorecard: {setting(conn, 'app_url', '')}/pnl?month={prev}"
        for u in users_with_roles(conn, "gm", "owner"):
            send(conn, u, "monthly_pnl", prev, f"AANDJ management accounts & KPI scorecard – {prev}", body)


def backup(conn, n):
    os.makedirs(BACKUPS, exist_ok=True)
    path = os.path.join(BACKUPS, f"aandj-{n:%Y%m%d}.db")
    if os.path.exists(path):
        return path
    dest = sqlite3.connect(path)
    conn.backup(dest)
    dest.close()
    return path


def run_all(conn, force_weekly=False):
    n = now()
    check_late(conn, n)
    check_sales_drop(conn, n)
    check_month(conn, n)
    monday_email(conn, n, force=force_weekly)
    month_end(conn, n)
    conn.commit()
    backup(conn, n)
    return n
