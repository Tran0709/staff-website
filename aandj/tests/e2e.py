"""End-to-end test of the main flows with Playwright (Chromium).

Start the app first (python app.py on a fresh demo database), then:  python tests/e2e.py [base_url]
Screenshots go to tests/screenshots/.
"""
import base64
import hashlib
import hmac
import os
import re
import struct
import sys
import time

from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000"
HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "screenshots")
os.makedirs(SHOTS, exist_ok=True)
PHOTO = os.path.join(SHOTS, "_receipt.png")
with open(PHOTO, "wb") as f:
    f.write(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
MOBILE = {"width": 390, "height": 844}
DESKTOP = {"width": 1366, "height": 900}
results = []


def step(name):
    print("✓", name)
    results.append(name)


def totp(secret):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    h = hmac.new(key, struct.pack(">Q", int(time.time() // 30)), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000:06d}"


def login(page, user, pw="aandj123"):
    page.goto(BASE + "/login")
    page.fill("#username", user)
    page.fill("#password", pw)
    page.click("button.big-submit")


def logout(page):
    page.click("text=Log out") if page.locator("text=Log out").count() else page.click("text=退出")


def shot(page, name):
    page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)


def no_hscroll(page):
    w = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert w <= 1, f"horizontal page scroll of {w}px"


with sync_playwright() as p:
    browser = p.chromium.launch()

    # ---------- 1. Shop manager on a phone ----------
    ctx = browser.new_context(viewport=MOBILE, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    login(page, "mgr_sim")
    expect(page.locator("h1")).to_contain_text("Simply Aesthetique")
    no_hscroll(page)
    shot(page, "m01_manager_today")
    step("manager signs in on mobile and lands on today's checklist")

    page.click("#go-sales")
    page.fill("#gross", "4200")
    page.fill("#discounts", "150")
    page.fill("#refunds", "50")
    page.fill("#cash", "500")
    page.fill("#paynow", "1000")
    page.fill("#card", "2000")
    page.fill("#transactions", "18")
    page.fill("#customers", "16")
    expect(page.locator("#net")).to_contain_text("4,000.00")
    expect(page.locator("#paycheck")).to_contain_text("≠")
    page.set_input_files("#pos_photo", PHOTO)
    page.fill("#cash_deposit", "500")
    page.fill("#deposit_ref", "DBS-0001")
    shot(page, "m02_sales_form")
    page.click("button.big-submit")
    expect(page.locator(".flash.error")).to_contain_text("Payment modes add up to")
    step("sales form rejects payments that don't add up to net sales")
    page.fill("#card", "2500")
    page.set_input_files("#pos_photo", PHOTO)
    expect(page.locator("#paycheck")).to_contain_text("match")
    page.click("button.big-submit")
    expect(page.locator(".flash.ok")).to_contain_text("Sales saved")
    step("manager submits daily sales with POS photo")

    page.click("#go-exp")
    page.fill("#supplier", "Beauty Supply Co")
    page.select_option("#category", "Cost of goods sold")
    page.fill("#amount", "320")
    page.fill("#gst", "26.42")
    page.click("button.big-submit")
    # receipt is required -> browser validation blocks submit; attach and retry
    page.set_input_files("#receipt", PHOTO)
    page.click("button.big-submit")
    expect(page.locator(".flash.ok")).to_contain_text("Expense saved")
    page.fill("#supplier", "LaserTech Servicing")
    page.select_option("#category", "Operations")
    page.fill("#amount", "880")
    page.set_input_files("#receipt", PHOTO)
    page.check("input[value=payable]")
    page.fill("#purpose", "Annual laser machine service")
    page.click("button.big-submit")
    expect(page.locator(".flash.ok")).to_contain_text("sent to Finance for approval")
    shot(page, "m03_expense_pending")
    step("expenses saved with receipt; S$880 routed to Finance for approval")

    page.goto(BASE + "/today")
    page.click("#go-ops")
    page.fill("#staff_on_shift", "3")
    page.fill("#staff_hours", "25.5")
    page.fill("#complaints", "Client waited 20 min")
    page.fill("#gm_items", "Need approval for a 3rd therapist")
    page.click("button.big-submit")
    expect(page.locator(".flash.ok")).to_contain_text("Operations saved")
    page.click("#go-kpi")
    labels = {"Leads – social media": "6", "Consultations": "4", "Packages sold": "2", "Treatment room hours used": "20",
              "Treatment room hours available": "30", "Treatments done": "12", "Rebookings": "6"}
    for label, v in labels.items():
        page.get_by_label(label, exact=False).first.fill(v)
    page.click("button.big-submit")
    expect(page.locator(".flash.ok")).to_contain_text("KPIs saved")
    expect(page.locator(".check .badge.red")).to_have_count(0)
    shot(page, "m04_checklist_done")
    step("operations and shop-specific KPIs submitted – checklist all green")

    r = page.goto(BASE + "/pnl")
    assert r.status == 403
    r = page.goto(BASE + "/input/sales?shop=1")
    assert r.status == 403
    page.goto(BASE + "/flash")
    assert page.locator("#flash-table tr").count() == 3, "manager should see only own shop + total row"
    step("manager is blocked from P&L and other shops; flash shows own shop only")

    page.goto(BASE + "/input/sales?date=2026-09-15")
    expect(page.locator(".flash.error")).to_be_visible()
    step("locked month (September) cannot be edited")

    page.goto(BASE + "/lang/zh")
    page.goto(BASE + "/today")
    expect(page.locator("nav")).to_contain_text("今日")
    shot(page, "m05_chinese")
    page.goto(BASE + "/lang/en")
    step("Chinese / English toggle works")
    ctx.close()

    # ---------- 2. Finance approves on desktop ----------
    ctx = browser.new_context(viewport=DESKTOP)
    page = ctx.new_page()
    login(page, "amanda")
    page.goto(BASE + "/approvals")
    card = page.locator(".approval", has_text="LaserTech")
    card.locator("button[value=approve]").click()
    expect(page.locator(".flash.ok")).to_contain_text("approved")
    expect(page.locator(".approval", has_text="browqueen")).to_contain_text("Waiting for the GM")
    shot(page, "d01_approvals_finance")
    step("Finance approves S$880; S$3,500 KOL fee waits for the GM")

    page.goto(BASE + "/month-end?month=2026-10")
    page.locator("#checklist tr", has_text="Simply").locator("button").first.click()
    expect(page.locator("#checklist tr", has_text="Simply").locator("button").first).to_contain_text("done")
    shot(page, "d02_month_end")
    step("Finance ticks month-end checklist")
    r = page.goto(BASE + "/admin")
    assert r.status == 403
    ctx.close()

    # ---------- 3. GM ----------
    ctx = browser.new_context(viewport=DESKTOP, accept_downloads=True)
    page = ctx.new_page()
    login(page, "joe")
    expect(page.locator("h1")).to_contain_text("Daily flash")
    page.goto(BASE + "/flash?date=" + time.strftime("%Y-%m-%d"))
    expect(page.locator("#flash-table tr", has_text="Simply")).to_contain_text("Submitted")
    expect(page.locator("#flash-table tr", has_text="Cai Yuan Zi")).to_contain_text("Yet to submit")
    shot(page, "d03_flash")
    step("GM daily flash: Simply submitted, others yet to submit")

    page.goto(BASE + "/alerts")
    page.check("input[name=weekly]")  # today isn't Monday, so send the weekly e-mail on demand
    page.click("text=Run checks now")
    expect(page.locator("#alerts")).to_contain_text("late submission")
    expect(page.locator("#alerts")).to_contain_text("sales drop")
    shot(page, "d04_alerts")
    step("automation raises late-submission and sales-drop alerts")

    page.goto(BASE + "/approvals")
    page.locator(".approval", has_text="browqueen").locator("button[value=approve]").click()
    expect(page.locator(".flash.ok")).to_contain_text("approved")
    step("GM approves the GM-level expense")

    for path, check, name in [("/weekly", "#ranking", "d05_weekly"), ("/pnl?month=2026-10", "#pnl", "d06_pnl"),
                              ("/scorecard?month=2026-10", ".scorecard", "d07_scorecard"), ("/marketing", "#mkt", "d08_marketing"),
                              ("/group", "#group-sales", "d09_group")]:
        page.goto(BASE + path)
        expect(page.locator(check).first).to_be_visible()
        shot(page, name)
    expect(page.locator("#group-sales")).to_contain_text("S$")
    page.goto(BASE + "/pnl?month=2026-10")
    expect(page.locator("#pnl")).to_contain_text("Net profit")
    expect(page.locator("#bva")).to_contain_text("Variance")
    page.goto(BASE + "/scorecard?month=2026-10")
    assert page.locator(".scorecard .badge.green").count() + page.locator(".scorecard .badge.red").count() > 0
    step("weekly dashboard, monthly P&L (per company + group, budget vs actual), KPI scorecard, marketing and group views render")

    with page.expect_download() as dl:
        page.goto(BASE + "/export")
        page.select_option("select[name=table]", "expenses")
        page.click("text=Download CSV")
    path = dl.value.path()
    head = open(path, encoding="utf-8-sig").readline()
    assert "account_code" in head and "company" in head, head
    step("CSV export with company and account code")

    page.goto(BASE + "/audit?tbl=daily_sales")
    expect(page.locator("#audit")).to_contain_text("submit daily sales")
    page.goto(BASE + "/audit?tbl=expenses")
    expect(page.locator("#audit")).to_contain_text("approved expense")
    shot(page, "d10_audit")
    step("audit log records submissions and approvals")

    page.goto(BASE + "/inbox")
    expect(page.locator("body")).to_contain_text("AANDJ weekly dashboard")
    expect(page.locator("body")).to_contain_text("needs the GM")
    step("GM inbox has the Monday dashboard e-mail and the manager's escalation")

    page.goto(BASE + "/admin/kpi?shop=2")
    row = page.locator("#kpi-fields tr").last
    row.locator("input[name=key]").fill("vip_clients")
    row.locator("input[name=label]").fill("VIP clients served")
    row.locator("button").click()
    expect(page.locator(".flash.ok")).to_be_visible()
    expect(page.locator('#kpi-fields input[value="VIP clients served"]')).to_have_count(1)
    page.goto(BASE + "/input/kpi?shop=2")
    expect(page.get_by_label("VIP clients served")).to_be_visible()
    step("GM adds a new KPI field without code changes")

    page.goto(BASE + "/security")
    secret = page.locator("#totp-secret").inner_text().strip()
    page.fill("#code", totp(secret))
    page.click("text=Turn on two-factor")
    expect(page.locator(".flash.ok")).to_contain_text("Two-factor login is on")
    logout(page)
    login(page, "joe")
    expect(page.locator("#code")).to_be_visible()
    page.fill("#code", totp(secret))
    page.click("text=Verify")
    expect(page.locator("h1")).to_contain_text("Daily flash")
    step("two-factor login enabled and enforced for the GM")
    ctx.close()

    # ---------- 4. Owner (read-only group view), mobile ----------
    ctx = browser.new_context(viewport=MOBILE, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    login(page, "dong")
    expect(page.locator("h1")).to_contain_text("Group summary")
    no_hscroll(page)
    shot(page, "m06_owner_group")
    assert page.goto(BASE + "/flash").status == 403
    assert page.goto(BASE + "/expenses").status == 403
    step("Boss Dong sees the read-only group summary only")
    login(page, "joe")  # 2FA now on
    login(page, "mgr_cyz")
    page.goto(BASE + "/today")
    no_hscroll(page)
    login(page, "amanda")
    for pth in ("/flash", "/weekly", "/pnl"):
        page.goto(BASE + pth)
        shot(page, "m07_" + pth.strip("/"))
    step("dashboards usable at phone width")
    ctx.close()
    browser.close()

print(f"\nAll {len(results)} checks passed.")
