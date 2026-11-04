"""Captures the screenshots used in the user guides, from a fresh demo database (live data is not touched).

    python tools/capture_screens.py <output_dir>
"""
import base64
import os
import shutil
import sys
import tempfile
import threading

OUT = os.path.abspath(sys.argv[1])
WORK = os.path.join(tempfile.gettempdir(), "aandjcap")
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)
os.makedirs(OUT, exist_ok=True)
os.environ["AANDJ_DB"] = os.path.join(WORK, "cap.db")
os.environ["AANDJ_NO_SCHEDULER"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as aandj  # noqa: E402
import automation  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

PORT = 5066
BASE = f"http://127.0.0.1:{PORT}"
PHOTO = os.path.join(WORK, "receipt.png")
with open(PHOTO, "wb") as f:
    f.write(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
DESK = {"width": 1280, "height": 860}
PHONE = {"width": 390, "height": 844}
server = make_server("127.0.0.1", PORT, aandj.app, threaded=True)
threading.Thread(target=server.serve_forever, daemon=True).start()


def session(browser, user, size, pw="aandj123"):
    ctx = browser.new_context(viewport=size, is_mobile=size is PHONE, device_scale_factor=2 if size is PHONE else 1)
    p = ctx.new_page()
    p.goto(BASE + "/login")
    if user:
        p.fill("#username", user)
        p.fill("#password", pw)
        p.click("button.big-submit")
    return ctx, p


def shot(p, name, path=None, full=False, max_h=1500, sel=None):
    if path:
        p.goto(BASE + path)
    p.wait_for_timeout(250)
    if sel:
        p.locator(sel).first.screenshot(path=os.path.join(OUT, name + ".png"))
    elif full:
        h = min(p.evaluate("document.documentElement.scrollHeight"), max_h)
        w = p.viewport_size["width"]
        p.screenshot(path=os.path.join(OUT, name + ".png"), full_page=True, clip={"x": 0, "y": 0, "width": w, "height": h})
    else:
        p.screenshot(path=os.path.join(OUT, name + ".png"))
    print("captured", name)


with sync_playwright() as pw:
    b = pw.chromium.launch()

    # ---- sign-in, create account, security (everyone) ----
    ctx, p = session(b, None, PHONE)
    shot(p, "common_login")
    p.click("#create-account")
    p.fill("#name", "Wendy Lim"); p.fill("#username", "wendy_sim"); p.select_option("#role", "manager")
    p.select_option("#shop_id", label="Simply Aesthetique")
    shot(p, "common_register", full=True)
    p.fill("#password", "Wendy2026!"); p.fill("#confirm", "Wendy2026!"); p.click("button.big-submit")
    shot(p, "common_register_done")
    ctx.close()

    # ---- shop manager (phone) ----
    ctx, p = session(b, "mgr_sim", PHONE)
    shot(p, "mgr_today", full=True)
    p.click("#go-sales")
    for k, v in [("gross", 4200), ("discounts", 150), ("refunds", 50), ("cash", 500), ("paynow", 1000), ("card", 2500),
                 ("transactions", 18), ("customers", 16), ("cash_deposit", 500), ("deposit_ref", "DBS-0001")]:
        p.fill("#" + k, str(v))
    p.set_input_files("#pos_photo", PHOTO)
    shot(p, "mgr_sales", full=True, max_h=1700)
    p.fill("#card", "2000")
    p.dispatch_event("#card", "input")
    shot(p, "mgr_sales_mismatch", sel="#paycheck")
    p.fill("#card", "2500"); p.dispatch_event("#card", "input")
    p.click("button.big-submit")
    shot(p, "mgr_sales_saved")
    p.click("#go-exp")
    p.fill("#supplier", "LaserTech Servicing"); p.select_option("#category", "Operations"); p.fill("#amount", "880")
    p.check("input[value=payable]"); p.fill("#purpose", "Annual laser machine service"); p.set_input_files("#receipt", PHOTO)
    shot(p, "mgr_expense", full=True, max_h=1700)
    p.click("button.big-submit")
    shot(p, "mgr_expense_pending", full=True, max_h=1900)
    p.goto(BASE + "/today"); p.click("#go-ops")
    p.fill("#staff_on_shift", "3"); p.fill("#staff_hours", "25.5"); p.fill("#complaints", "Client waited 20 min at peak")
    p.fill("#gm_items", "Need approval to hire a 3rd therapist")
    shot(p, "mgr_ops", full=True, max_h=1700)
    p.click("button.big-submit")
    p.click("#go-kpi")
    for label, v in {"Leads – social media": 6, "Consultations": 4, "Packages sold": 2, "Treatment room hours used": 20,
                     "Treatment room hours available": 30, "Treatments done": 12, "Rebookings": 6}.items():
        p.get_by_label(label, exact=False).first.fill(str(v))
    shot(p, "mgr_kpi", full=True, max_h=1700)
    p.click("button.big-submit")
    shot(p, "mgr_today_done", full=True)
    shot(p, "mgr_flash", "/flash", full=True)
    shot(p, "mgr_expenses", "/expenses", full=True, max_h=1200)
    p.goto(BASE + "/lang/zh")
    shot(p, "common_chinese", "/today", full=True)
    shot(p, "mgr_sales_zh", "/input/sales", full=True, max_h=1200)
    p.goto(BASE + "/lang/en")
    ctx.close()

    # run the automatic checks so alerts / inbox have content
    c = aandj.connect()
    automation.run_all(c, force_weekly=True)
    c.close()

    # ---- finance (desktop) ----
    ctx, p = session(b, "amanda", DESK)
    shot(p, "fin_approvals", "/approvals", full=True)
    shot(p, "fin_expenses", "/expenses?status=pending")
    shot(p, "fin_pnl", "/pnl?month=2026-10", full=True, max_h=1100)
    p.locator("#bva").scroll_into_view_if_needed()
    shot(p, "fin_bva", sel="#bva")
    shot(p, "fin_month_end", "/month-end?month=2026-10", full=True)
    shot(p, "fin_staff", "/staff")
    shot(p, "fin_budgets", "/budgets")
    shot(p, "fin_export", "/export")
    shot(p, "fin_audit", "/audit")
    ctx.close()

    # ---- GM (desktop) ----
    ctx, p = session(b, "joe", DESK)
    shot(p, "gm_flash", "/flash", full=True, max_h=1300)
    shot(p, "gm_alerts", "/alerts")
    shot(p, "gm_approvals", "/approvals", full=True)
    shot(p, "gm_weekly", "/weekly", full=True, max_h=1400)
    shot(p, "gm_scorecard", "/scorecard?month=2026-10", full=True, max_h=1100)
    shot(p, "gm_group", "/group", full=True)
    shot(p, "gm_admin_controls", "/admin")
    shot(p, "gm_admin_users", "/admin?tab=users")
    shot(p, "gm_admin_shops", "/admin?tab=shops")
    shot(p, "gm_admin_cats", "/admin?tab=cats")
    shot(p, "gm_admin_kpi", "/admin/kpi?shop=2")
    shot(p, "gm_inbox", "/inbox")
    shot(p, "gm_ops_log", "/ops-log")
    shot(p, "gm_marketing", "/marketing")
    shot(p, "common_security", "/security")
    ctx.close()

    # ---- COO (desktop) ----
    ctx, p = session(b, "nicholas", DESK)
    shot(p, "coo_today_selector", "/today?shop=4")
    shot(p, "coo_kpi_venue", "/input/kpi?shop=4", full=True, max_h=1200)
    shot(p, "coo_ops_log", "/ops-log")
    shot(p, "coo_weekly_people", "/weekly", full=True, max_h=1800)
    ctx.close()

    # ---- Marketing (phone + desktop) ----
    ctx, p = session(b, "jade", PHONE)
    shot(p, "mkt_dashboard_phone", "/marketing", full=True, max_h=1300)
    p.goto(BASE + "/input/expense")
    p.fill("#supplier", "KOL @browqueen"); p.select_option("#category", "Marketing"); p.fill("#amount", "450")
    p.fill("#purpose", "Instagram story x3")
    shot(p, "mkt_expense", full=True, max_h=1700)
    shot(p, "mkt_kpi", "/input/kpi?shop=3", full=True, max_h=1200)
    ctx.close()
    ctx, p = session(b, "jade", DESK)
    shot(p, "mkt_dashboard", "/marketing", full=True, max_h=1300)
    ctx.close()

    # ---- Accountant (desktop) ----
    ctx, p = session(b, "accountant", DESK)
    shot(p, "acc_pnl", "/pnl?month=2026-10", full=True, max_h=1100)
    shot(p, "acc_month_end", "/month-end?month=2026-10", full=True)
    shot(p, "acc_export", "/export")
    shot(p, "acc_scorecard", "/scorecard?month=2026-10", full=True, max_h=900)
    ctx.close()

    # ---- Owner (phone + desktop) ----
    ctx, p = session(b, "dong", PHONE)
    shot(p, "own_group_phone", full=True, max_h=1700)
    ctx.close()
    ctx, p = session(b, "dong", DESK)
    shot(p, "own_group", full=True)
    shot(p, "own_forbidden", "/flash")
    ctx.close()
    b.close()

server.shutdown()
print("done →", OUT)
