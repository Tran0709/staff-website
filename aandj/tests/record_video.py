"""Records a narrated, end-to-end walkthrough test of the AANDJ reporting system to an MP4.

Starts its own copy of the app on a fresh demo database (your real data is not touched), drives Chromium through every
role at desktop and phone sizes, shows a caption for each step and a PASS / FAIL badge for each check, then joins the
clips with ffmpeg.

    python tests/record_video.py [output.mp4]
"""
import base64
import glob
import hashlib
import hmac
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time

WORK = os.path.join(tempfile.gettempdir(), "aandjvid")
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)
os.environ["AANDJ_DB"] = os.path.join(WORK, "video.db")
os.environ["AANDJ_NO_SCHEDULER"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import app as aandj  # noqa: E402  (creates the fresh demo DB)
from playwright.sync_api import expect, sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "AANDJ-Test-Video.mp4"))
PORT = 5055
BASE = f"http://127.0.0.1:{PORT}"
PHOTO = os.path.join(WORK, "pos_report.png")
with open(PHOTO, "wb") as f:
    f.write(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
DESKTOP = {"width": 1280, "height": 800}
MOBILE = {"width": 390, "height": 844}
results = []

server = make_server("127.0.0.1", PORT, aandj.app, threaded=True)
threading.Thread(target=server.serve_forever, daemon=True).start()

CAPTION_JS = """([text, kind, scene]) => {
  let box = document.getElementById('__cap');
  if (!box) {
    box = document.createElement('div'); box.id = '__cap';
    box.style.cssText = 'position:fixed;left:12px;right:12px;bottom:12px;z-index:99999;padding:12px 16px;border-radius:10px;' +
      'font:600 16px/1.35 system-ui,Segoe UI,sans-serif;color:#fff;box-shadow:0 6px 24px rgba(0,0,0,.35);pointer-events:none';
    document.body.appendChild(box);
  }
  box.style.background = kind === 'pass' ? '#1e7b4a' : kind === 'fail' ? '#b3261e' : 'rgba(20,24,31,.92)';
  box.innerHTML = '<div style="font:500 12px system-ui;opacity:.75;margin-bottom:3px">' + scene + '</div>' +
    (kind === 'pass' ? '✔ PASS — ' : kind === 'fail' ? '✘ FAIL — ' : '') + text;
}"""


def totp(secret):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    h = hmac.new(key, struct.pack(">Q", int(time.time() // 30)), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000:06d}"


class Run:
    def __init__(self, page, scene):
        self.page, self.scene = page, scene

    def cap(self, text, wait=2200):
        self.page.evaluate(CAPTION_JS, [text, "info", self.scene])
        self.page.wait_for_timeout(wait)

    def check(self, fn, text):
        try:
            fn()
            ok = True
        except Exception as e:  # keep recording; report at the end
            ok = False
            print("FAIL:", text, "→", str(e).splitlines()[0][:200])
        results.append((self.scene, text, ok))
        self.page.evaluate(CAPTION_JS, [text, "pass" if ok else "fail", self.scene])
        self.page.wait_for_timeout(1700)
        return ok

    def go(self, path, text=None, wait=1800):
        self.page.goto(BASE + path)
        if text:
            self.cap(text, wait)

    def type(self, sel, value):
        self.page.locator(sel).click()
        self.page.locator(sel).press_sequentially(str(value), delay=45)

    def click(self, sel, pause=700):
        loc = self.page.locator(sel).first
        loc.scroll_into_view_if_needed()
        loc.hover()
        self.page.wait_for_timeout(250)
        loc.click()
        self.page.wait_for_timeout(pause)

    def scroll(self, dy=500, steps=10):
        for _ in range(steps):
            self.page.mouse.wheel(0, dy / steps)
            self.page.wait_for_timeout(40)
        self.page.wait_for_timeout(500)

    def login(self, user, pw="aandj123"):
        self.page.goto(BASE + "/login")
        self.type("#username", user)
        self.type("#password", pw)
        self.click("button.big-submit", 900)


def title_card(browser, lines, seconds=4, size=DESKTOP):
    ctx = browser.new_context(viewport=size, record_video_dir=WORK, record_video_size=size)
    p = ctx.new_page()
    body = "".join(f"<p style='margin:10px 0;font-size:{30 if i == 0 else 19}px;font-weight:{700 if i == 0 else 400}'>{t}</p>"
                   for i, t in enumerate(lines))
    p.set_content(f"<body style='margin:0;height:100vh;display:flex;flex-direction:column;justify-content:center;align-items:center;"
                  f"background:#8a1c2b;color:#fff;font-family:system-ui,Segoe UI,sans-serif;text-align:center;padding:40px'>{body}</body>")
    p.wait_for_timeout(seconds * 1000)
    ctx.close()


def new_run(browser, scene, size, mobile=False):
    ctx = browser.new_context(viewport=size, is_mobile=mobile, has_touch=mobile, record_video_dir=WORK, record_video_size=size,
                              accept_downloads=True)
    return ctx, Run(ctx.new_page(), scene)


with sync_playwright() as pw:
    browser = pw.chromium.launch(slow_mo=40)

    title_card(browser, ["AANDJ Shop Reporting System", "Automated end-to-end test · narrated walkthrough",
                         "Fresh demo database · 5 outlets · 7 roles · desktop and phone",
                         f"Recorded {time.strftime('%d %b %Y %H:%M')}"], 5)

    # ---------------- 1. Create account (phone) ----------------
    ctx, r = new_run(browser, "1 · Create an account (phone 390px)", MOBILE, True)
    r.go("/login", "The sign-in page works on a phone. New staff can request an account.")
    r.click("#create-account")
    r.cap("The sign-up form is bilingual. Shop managers must pick their shop.")
    r.type("#name", "Wendy Lim")
    r.type("#username", "wendy_sim")
    r.type("#email", "wendy@aandj.example")
    r.page.select_option("#role", "manager")
    r.page.select_option("#shop_id", label="Simply Aesthetique")
    r.type("#password", "Wendy2026!")
    r.type("#confirm", "typo2026!")
    r.click("button.big-submit")
    r.check(lambda: expect(r.page.locator(".flash.error")).to_contain_text("don't match"), "Mismatched passwords are rejected")
    r.type("#password", "Wendy2026!")
    r.type("#confirm", "Wendy2026!")
    r.click("button.big-submit")
    r.check(lambda: expect(r.page.locator(".flash.ok")).to_contain_text("Account created"), "Account request saved")
    r.type("#username", "wendy_sim")
    r.type("#password", "Wendy2026!")
    r.click("button.big-submit")
    r.check(lambda: expect(r.page.locator(".flash.error")).to_contain_text("waiting for the GM"),
            "New account cannot sign in until the GM approves it")
    ctx.close()

    # ---------------- 2. Shop manager daily report (phone) ----------------
    ctx, r = new_run(browser, "2 · Shop manager daily report — Simply Aesthetique (phone)", MOBILE, True)
    r.login("mgr_sim")
    r.check(lambda: expect(r.page.locator("h1")).to_contain_text("Simply Aesthetique"), "Manager lands on their own shop's checklist")
    r.cap("Red badges show what is still missing today: sales, operations and KPIs.")
    r.check(lambda: r.page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1") or (_ for _ in ()).throw(AssertionError("h-scroll")),
            "No sideways scrolling at phone width")
    r.click("#go-sales")
    r.cap("Step 1 — daily sales. Net sales and average spend are calculated while typing.")
    for sel, v in [("#gross", 4200), ("#discounts", 150), ("#refunds", 50)]:
        r.page.fill(sel, "")
        r.type(sel, v)
    r.check(lambda: expect(r.page.locator("#net")).to_contain_text("4,000.00"), "Net sales = 4,200 − 150 − 50 = S$4,000")
    for sel, v in [("#cash", 500), ("#paynow", 1000), ("#card", 2000)]:
        r.page.fill(sel, "")
        r.type(sel, v)
    r.type("#transactions", 18)
    r.type("#customers", 16)
    r.cap("Payments only add up to S$3,500 — the form warns before submitting.")
    r.page.set_input_files("#pos_photo", PHOTO)
    r.page.fill("#cash_deposit", "")
    r.type("#cash_deposit", 500)
    r.type("#deposit_ref", "DBS-0001")
    r.click("button.big-submit", 1000)
    r.check(lambda: expect(r.page.locator(".flash.error")).to_contain_text("Payment modes add up to"),
            "Server rejects payments that don't match net sales")
    r.page.fill("#card", "")
    r.type("#card", 2500)
    r.page.set_input_files("#pos_photo", PHOTO)
    r.check(lambda: expect(r.page.locator("#paycheck")).to_contain_text("match"), "Payments now match net sales")
    r.click("button.big-submit", 1000)
    r.check(lambda: expect(r.page.locator(".flash.ok")).to_contain_text("Sales saved"), "Daily sales submitted with POS photo")

    r.click("#go-exp")
    r.cap("Step 2 — expenses. One line per receipt; a receipt photo is required.")
    r.type("#supplier", "Beauty Supply Co")
    r.page.select_option("#category", "Cost of goods sold")
    r.type("#amount", 320)
    r.page.fill("#gst", "")
    r.type("#gst", 26.42)
    r.page.set_input_files("#receipt", PHOTO)
    r.click("button.big-submit", 1000)
    r.check(lambda: expect(r.page.locator(".flash.ok")).to_contain_text("Expense saved"), "S$320 stock purchase saved")
    r.cap("Now a S$880 repair — above the S$500 limit, so it needs Finance approval.")
    r.type("#supplier", "LaserTech Servicing")
    r.page.select_option("#category", "Operations")
    r.type("#amount", 880)
    r.click("#paid-status label >> nth=1")
    r.type("#purpose", "Annual laser machine service")
    r.page.set_input_files("#receipt", PHOTO)
    r.click("button.big-submit", 1000)
    r.check(lambda: expect(r.page.locator(".flash.ok")).to_contain_text("sent to Finance for approval"), "S$880 routed to Finance")
    r.scroll(600)
    r.check(lambda: expect(r.page.locator("table .badge.pending")).to_have_count(1), "Pending status shown in today's expenses")

    r.go("/today")
    r.click("#go-ops")
    r.cap("Step 3 — operations: staff, hours, complaints and anything that needs the GM.")
    r.type("#staff_on_shift", 3)
    r.type("#staff_hours", 25.5)
    r.type("#complaints", "Client waited 20 min at peak")
    r.type("#gm_items", "Need approval to hire a 3rd therapist")
    r.click("button.big-submit", 1000)
    r.check(lambda: expect(r.page.locator(".flash.ok")).to_contain_text("Operations saved"), "Operations report saved")
    r.click("#go-kpi")
    r.cap("Step 4 — Simply's own KPIs: leads, consultations, room hours, rebookings.")
    for label, v in {"Leads – social media": 6, "Consultations": 4, "Packages sold": 2, "Treatment room hours used": 20,
                     "Treatment room hours available": 30, "Treatments done": 12, "Rebookings": 6}.items():
        loc = r.page.get_by_label(label, exact=False).first
        loc.scroll_into_view_if_needed()
        loc.press_sequentially(str(v), delay=40)
    r.click("button.big-submit", 1000)
    r.check(lambda: expect(r.page.locator(".check .badge.red")).to_have_count(0), "Checklist complete — every item green")

    r.go("/pnl")
    r.check(lambda: expect(r.page.locator("h1")).to_contain_text("403"), "Manager is blocked from the group P&L")
    r.go("/input/sales?shop=1")
    r.check(lambda: expect(r.page.locator("h1")).to_contain_text("403"), "Manager cannot open another shop's form")
    r.go("/input/sales?date=2026-09-15")
    r.check(lambda: expect(r.page.locator(".flash.error")).to_be_visible(), "September is locked — no edits allowed")
    r.go("/lang/zh")
    r.go("/today", "One tap on 中文 switches every screen to Chinese.", 2500)
    r.check(lambda: expect(r.page.locator("main")).to_contain_text("今日清单"), "Whole page is in Chinese")
    r.click("#go-sales", 1500)
    r.check(lambda: expect(r.page.locator("main")).to_contain_text("净销售额"), "Sales form labels in Chinese")
    r.go("/lang/en")
    ctx.close()

    # ---------------- 3. Brand & Marketing (phone) ----------------
    ctx, r = new_run(browser, "3 · Brand & Marketing — Jade (phone)", MOBILE, True)
    r.login("jade")
    r.check(lambda: expect(r.page.locator("h1")).to_contain_text("Marketing"), "Jade lands on the marketing & leads dashboard")
    r.scroll(700)
    r.go("/input/expense", "Marketing can only record Marketing spend (ads, KOL fees).")
    r.check(lambda: expect(r.page.locator("#category option")).to_have_count(2), "Only the Marketing category is offered")
    r.page.locator("#paid-status").scroll_into_view_if_needed()
    boxes = [r.page.locator("#paid-status label").nth(i).bounding_box() for i in range(2)]
    r.check(lambda: (boxes[1]["y"] > boxes[0]["y"] + 10) or (_ for _ in ()).throw(AssertionError("not stacked")),
            "Paid / Payable options are stacked in a column")
    r.type("#supplier", "Meta Ads")
    r.page.select_option("#category", "Marketing")
    r.type("#amount", 180)
    r.page.set_input_files("#receipt", PHOTO)
    r.click("button.big-submit", 1000)
    r.check(lambda: expect(r.page.locator(".flash.ok")).to_be_visible(), "Ad spend recorded")
    for p in ("/pnl", "/flash"):
        r.go(p)
    r.check(lambda: expect(r.page.locator("h1")).to_contain_text("403"), "Marketing cannot open finance dashboards")
    ctx.close()

    # ---------------- 4. Finance (desktop) ----------------
    ctx, r = new_run(browser, "4 · Finance & HR — Amanda (desktop 1280px)", DESKTOP)
    r.login("amanda")
    r.go("/approvals", "Amanda reviews the approval queue.")
    card = r.page.locator(".approval", has_text="LaserTech")
    card.scroll_into_view_if_needed()
    card.locator("button[value=approve]").hover()
    r.page.wait_for_timeout(500)
    card.locator("button[value=approve]").click()
    r.check(lambda: expect(r.page.locator(".flash.ok")).to_contain_text("approved"), "Finance approves the S$880 repair")
    r.check(lambda: expect(r.page.locator(".approval", has_text="browqueen")).to_contain_text("Waiting for the GM"),
            "S$3,500 KOL fee is above S$2,000 — only the GM can approve")
    r.go("/month-end?month=2026-10", "Month-end close for October: checklist, then reconciliation.")
    for i in range(4):
        row = r.page.locator("#checklist tr", has_text="Simply")
        row.locator("button").nth(i).click()
        r.page.wait_for_timeout(350)
    r.check(lambda: expect(r.page.locator("#checklist tr", has_text="Simply").locator("button", has_text="done")).to_have_count(4),
            "Simply's four month-end items ticked")
    r.scroll(500)
    r.cap("Reconciliation: days submitted, pending approvals, payables, cash vs deposits.")
    r.page.once("dialog", lambda d: d.accept())
    r.click("#lock-month", 1200)
    r.check(lambda: expect(r.page.locator("h1")).to_contain_text("locked"), "October locked after reconciliation")
    r.go("/staff", "Staff list: pay, CPF and commission per shop (feeds payroll).")
    r.scroll(400)
    r.go("/admin")
    r.check(lambda: expect(r.page.locator("h1")).to_contain_text("403"), "Finance cannot open GM admin settings")
    ctx.close()

    # ---------------- 5. GM (desktop) ----------------
    ctx, r = new_run(browser, "5 · GM / CEO — Joe Chen (desktop)", DESKTOP)
    r.login("joe")
    r.cap("The GM opens the daily flash: every shop today vs the same day last week.", 2600)
    r.check(lambda: expect(r.page.locator("#flash-table tr", has_text="Simply")).to_contain_text("Submitted"), "Simply shows as submitted")
    r.check(lambda: expect(r.page.locator("#flash-table tr", has_text="Cai Yuan Zi")).to_contain_text("Yet to submit"),
            "Shops that haven't reported are flagged")
    r.scroll(700)
    r.go("/alerts", "Automatic checks: late reports, sales drops, budgets, food cost, venue rent.")
    r.page.check("input[name=weekly]")
    r.click("#run-checks", 1500)
    r.check(lambda: expect(r.page.locator("#alerts")).to_contain_text("late submission"), "Late-submission alerts raised")
    r.check(lambda: expect(r.page.locator("#alerts")).to_contain_text("sales drop"), "Sales-drop (>15%) alerts raised")
    r.check(lambda: expect(r.page.locator("#alerts")).to_contain_text("over budget"), "Over-budget alert raised")
    r.go("/approvals", "The GM approves the KOL fee only they can sign off.")
    r.page.locator(".approval", has_text="browqueen").locator("button[value=approve]").click()
    r.check(lambda: expect(r.page.locator(".flash.ok")).to_contain_text("approved"), "GM approves the S$3,500 KOL fee")
    r.go("/weekly", "Weekly dashboard: sales, profit, customers, ranking, trend, people, venue, marketing.", 2600)
    r.check(lambda: expect(r.page.locator("#ranking tr")).to_have_count(6), "All 5 shops ranked")
    r.scroll(700)
    r.scroll(700)
    r.go("/pnl?month=2026-10", "Monthly P&L — per company and combined group.", 2600)
    r.check(lambda: expect(r.page.locator("#pnl")).to_contain_text("Net profit"), "P&L shows revenue down to net profit")
    r.scroll(650)
    r.check(lambda: expect(r.page.locator("#bva")).to_contain_text("Variance"), "Budget vs actual with variance")
    r.page.select_option("select[name=company]", index=1)
    r.click("text=Show", 1200)
    r.check(lambda: expect(r.page.locator("#pnl th.n")).to_have_count(2), "Filter to one company keeps its books separate")
    r.go("/scorecard?month=2026-10", "KPI scorecard — actual vs baseline, floor and target.", 2400)
    r.check(lambda: expect(r.page.locator(".scorecard .badge.green").first).to_be_visible(), "Red / amber / green status shown")
    r.scroll(900)
    r.go("/marketing", "Marketing & leads across all shops.")
    r.go("/group", "Group summary (the view Boss Dong gets).")
    r.go("/ops-log", "Operations log — complaints, equipment and items for the GM.")
    r.check(lambda: expect(r.page.locator("main")).to_contain_text("3rd therapist"), "Manager's escalation visible to the GM")
    r.go("/inbox", "Inbox: alerts, approvals, sign-up requests and the Monday dashboard e-mail.")
    r.check(lambda: expect(r.page.locator("main")).to_contain_text("AANDJ weekly dashboard"), "Weekly dashboard e-mail generated")
    r.check(lambda: expect(r.page.locator("main")).to_contain_text("New account request: Wendy Lim"), "GM notified of the sign-up")
    r.go("/admin?tab=users", "Approving Wendy's account request.")
    r.page.locator("tr", has_text="wendy_sim").locator("button.approve-user").click()
    r.check(lambda: expect(r.page.locator(".flash.ok")).to_contain_text("wendy_sim can now sign in"), "GM approves the new account")
    r.go("/admin", "Controls: receipt threshold, approval limits, deadline, 2FA requirement.")
    r.go("/admin/kpi?shop=2", "KPI fields can be added without code changes.")
    row = r.page.locator("#kpi-fields tr").last
    row.scroll_into_view_if_needed()
    row.locator("input[name=key]").press_sequentially("vip_clients", delay=40)
    row.locator("input[name=label]").press_sequentially("VIP clients served", delay=40)
    row.locator("button").click()
    r.check(lambda: expect(r.page.locator('#kpi-fields input[value="VIP clients served"]')).to_have_count(1), "New KPI field added")
    r.go("/budgets", "Monthly budgets per shop and category.")
    r.go("/audit", "Audit log — every change with before / after values; it cannot be edited.")
    r.check(lambda: expect(r.page.locator("#audit")).to_contain_text("approved expense"), "Approvals recorded in the audit log")
    r.check(lambda: expect(r.page.locator("#audit")).to_contain_text("lock month"), "Month lock recorded in the audit log")
    r.go("/export", "Export CSV for the accountant, with account codes.")
    with r.page.expect_download() as dl:
        r.page.select_option("select[name=table]", "expenses")
        r.click("text=Download CSV", 1000)
    head = open(dl.value.path(), encoding="utf-8-sig").readline()
    r.check(lambda: ("account_code" in head and "company" in head) or (_ for _ in ()).throw(AssertionError(head)),
            "CSV includes company and account code")
    r.go("/security", "Turning on two-factor login for the GM.")
    secret = r.page.locator("#totp-secret").inner_text().strip()
    r.type("#code", totp(secret))
    r.click("text=Turn on two-factor", 1000)
    r.check(lambda: expect(r.page.locator(".flash.ok")).to_contain_text("Two-factor login is on"), "Two-factor login enabled")
    r.click("text=Log out", 800)
    r.login("joe")
    r.check(lambda: expect(r.page.locator("#code")).to_be_visible(), "Sign-in now asks for the 6-digit code")
    r.type("#code", totp(secret))
    r.click("text=Verify", 1200)
    r.check(lambda: expect(r.page.locator("h1")).to_contain_text("Daily flash"), "Signed in with password + code")
    ctx.close()

    # ---------------- 6. Owner + new account (phone) ----------------
    ctx, r = new_run(browser, "6 · Owner (Boss Dong) and the newly approved account (phone)", MOBILE, True)
    r.login("dong")
    r.check(lambda: expect(r.page.locator("h1")).to_contain_text("Group summary"), "Boss Dong sees the read-only group summary")
    r.scroll(600)
    r.go("/expenses")
    r.check(lambda: expect(r.page.locator("h1")).to_contain_text("403"), "Owner cannot open transaction details")
    r.page.goto(BASE + "/login")
    r.login("wendy_sim", "Wendy2026!")
    r.check(lambda: expect(r.page.locator("h1")).to_contain_text("Simply Aesthetique"), "Wendy (approved) signs in to her shop")
    ctx.close()

    passed = sum(ok for *_, ok in results)
    failed = [t for _, t, ok in results if not ok]
    title_card(browser, [f"{passed} of {len(results)} checks passed" + ("" if not failed else f" · {len(failed)} failed"),
                         "Create account · daily input · approvals · month-end lock",
                         "Flash · weekly · P&L · scorecard · alerts · audit · export · 2FA · EN/中文"] +
               [f"FAILED: {t}" for t in failed[:5]], 6)
    browser.close()

server.shutdown()

# ---------------- join the clips into one MP4 ----------------
import imageio_ffmpeg  # noqa: E402

ff = imageio_ffmpeg.get_ffmpeg_exe()
clips = sorted(glob.glob(os.path.join(WORK, "*.webm")), key=os.path.getmtime)
args, filters = [ff, "-y"], []
for i, c in enumerate(clips):
    args += ["-i", c]
    filters.append(f"[{i}:v]scale=1280:800:force_original_aspect_ratio=decrease,pad=1280:800:(ow-iw)/2:(oh-ih)/2:color=0xf6f5f1,"
                   f"setsar=1,fps=25[v{i}]")
filters.append("".join(f"[v{i}]" for i in range(len(clips))) + f"concat=n={len(clips)}:v=1:a=0[out]")
args += ["-filter_complex", ";".join(filters), "-map", "[out]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
         "-preset", "medium", "-movflags", "+faststart", OUT]
subprocess.run(args, check=True, capture_output=True)
print(f"\n{sum(ok for *_, ok in results)}/{len(results)} checks passed → {OUT}")
for scene, text, ok in results:
    print(("PASS " if ok else "FAIL ") + f"[{scene.split(' ·')[0]}] {text}")
