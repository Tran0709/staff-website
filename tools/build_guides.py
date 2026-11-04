"""Builds the per-role user guides (PDF, with screenshots) from tools/capture_screens.py output.

    python tools/build_guides.py <screenshot_dir> <output_dir>
"""
import base64
import html
import os
import sys

from playwright.sync_api import sync_playwright

IMG, OUT = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
os.makedirs(OUT, exist_ok=True)
SITE = "your AANDJ address (e.g. https://reports.yourdomain.com)"

ACCOUNTS = [
    ("GM / CEO", "Joe Chen", "joe", "aandj123", "All shops", "Everything + Admin, final approvals, budgets, KPI targets, approving new accounts"),
    ("Finance & HR", "Amanda He", "amanda", "aandj123", "All shops", "Approvals up to S$2,000, P&L, staff & payroll, budgets, month-end lock, export, audit"),
    ("COO", "Nicholas Tan", "nicholas", "aandj123", "All shops", "Operations dashboards; enters sales, operations and KPIs for any shop"),
    ("Brand & Marketing", "Jade Zhao", "jade", "aandj123", "All shops", "Marketing & leads dashboard; marketing expenses; lead KPIs"),
    ("Accountant", "To be appointed", "accountant", "aandj123", "All shops", "Read-only P&L, scorecard, expenses, month-end, audit + CSV export"),
    ("Owner", "Boss Dong", "dong", "aandj123", "Group view", "Read-only group summary"),
    ("Shop manager", "Li Wei", "mgr_cyz", "aandj123", "Cai Yuan Zi", "Daily input + own shop's flash, weekly, expenses, ops log"),
    ("Shop manager", "Grace Lim", "mgr_sim", "aandj123", "Simply Aesthetique", "As above, Simply only"),
    ("Shop manager", "Mei Ling", "mgr_brw", "aandj123", "Brow Secrets", "As above, Brow Secrets only"),
    ("Shop manager", "Daniel Koh", "mgr_ven", "aandj123", "Poker Federation venue", "As above, venue only"),
    ("Shop manager", "Dr. Sun", "mgr_aiw", "aandj123", "AI Smart Wellness Centre", "As above, AI Wellness only"),
    ("Shop manager (example)", "Example Manager", "example_manager", "Example2026!", "Cai Yuan Zi", "Created through the sign-up form"),
]

os.environ.setdefault("AANDJ_DB", os.path.join(os.path.dirname(OUT), "_guide_tmp.db"))
os.environ["AANDJ_NO_SCHEDULER"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import ACCESS  # noqa: E402  (the real permission rules)

PAGES = [("Today (input)", "input_sales"), ("Daily flash", "flash"), ("Weekly", "weekly"), ("Monthly P&L", "pnl"),
         ("KPI scorecard", "scorecard"), ("Marketing", "marketing"), ("Group", "group"), ("Expenses", "expenses"),
         ("Add expense", "input_expense"), ("KPI input", "input_kpi"), ("Ops log", "ops_log"), ("Approvals", "approve"),
         ("Alerts", "alerts"), ("Month-end", "month_end"), ("Staff", "staff"), ("Budgets", "budgets"), ("Export", "export"),
         ("Audit log", "audit"), ("Admin", "admin")]
ROLE_KEYS = [("GM / CEO", "gm"), ("Finance & HR", "finance"), ("COO", "coo"), ("Brand & Marketing", "marketing"),
             ("Accountant", "accountant"), ("Owner", "owner"), ("Shop manager", "manager")]
READ_ONLY = {("accountant", "month_end"), ("accountant", "expenses")}
MATRIX = {label: ["👁" if (k, perm) in READ_ONLY else ("✓" if k in ACCESS[perm] else "–") for _, perm in PAGES] for label, k in ROLE_KEYS}

COMMON = [
    ("Signing in", [
        f"Open {SITE} on your phone or computer.",
        "Type your username and password, then tap <b>Sign in / 登录</b>.",
        "If two-factor login is on for you, enter the 6-digit code from your authenticator app.",
        "After 5 wrong passwords the account is locked for 15 minutes.",
    ], ["common_login"]),
    ("Switching language / 切换语言", [
        "Tap <b>中文</b> in the top bar to switch every screen to Chinese; tap <b>EN</b> to switch back.",
        "Your choice is remembered until you sign out.",
    ], ["common_chinese"]),
    ("Security: password and two-factor login", [
        "Open <b>Security</b> in the menu.",
        "<b>Change password</b>: enter the current one and a new one of 8+ characters.",
        "<b>Two-factor login</b>: add the key shown into Google or Microsoft Authenticator, then enter the 6-digit code it shows.",
        "Lost your phone? Ask the GM to reset two-factor login for you.",
    ], ["common_security"]),
]

ROLES = {
    "manager": {
        "title": "Shop manager", "accounts": "mgr_cyz · mgr_sim · mgr_brw · mgr_ven · mgr_aiw",
        "summary": "Every day after closing, and by 11pm, you report your shop's sales, expenses, operations and KPIs. It takes about 5 minutes on your phone. You only see your own shop.",
        "sections": [
            ("Your daily checklist", [
                "After signing in you land on <b>Today</b>, which is a 4-step checklist for today's date.",
                "A red badge means the step isn't done yet, and green means done. Tap a row to open that form.",
                "Use the date box to fill in an earlier day. Days you missed are listed under <b>Missing days</b>.",
            ], ["mgr_today"]),
            ("Step 1 – Daily sales", [
                "Enter <b>gross sales</b>, <b>discounts</b> and <b>refunds</b>. Net sales are calculated for you.",
                "Enter how customers paid: cash, PayNow, card and platforms (Grab, foodpanda…).",
                "The payments must add up to net sales. The line under the boxes turns green with ✓ when they match, and red when they don't.",
                "Enter transactions and customers; the average spend is shown.",
                "<b>Take a photo of the POS end-of-day report</b> (required), and enter the cash deposited and the deposit slip number.",
                "Tap <b>Submit</b>. You can open the same day again to correct it, and every change is recorded.",
            ], ["mgr_sales", "mgr_sales_mismatch", "mgr_sales_saved"]),
            ("Step 2 – Expenses", [
                "Add one line per receipt or invoice: supplier, category, amount (incl. GST), GST, payment mode.",
                "Choose <b>Paid</b> or <b>Payable</b> (not yet paid).",
                "A receipt or invoice photo is required. For the category <b>Others</b>, state the purpose.",
                "Above <b>S$500</b> the expense goes to Finance for approval; above <b>S$2,000</b> it goes to the GM. You'll get a message when it is approved or rejected.",
                "Today's expenses are listed below the form. Use <b>Edit</b> to correct one, or <b>void</b> to cancel it. Voided records are kept, never deleted.",
            ], ["mgr_expense", "mgr_expense_pending"]),
            ("Step 3 – Operations", [
                "Staff on shift and total hours, absences and lateness, complaints and compliments, equipment, stock or wastage problems.",
                "<b>Items needing the GM</b> are sent straight to the GM's inbox.",
                "Do not type customers' personal details (names, phone numbers, IC numbers). This is required under PDPA.",
            ], ["mgr_ops"]),
            ("Step 4 – Shop KPIs", [
                "These are the extra figures for your outlet, for example covers and wastage (Cai Yuan Zi), leads and room hours (Simply), bookings and show-ups (Brow Secrets), enquiries and rent collected (Venue), or AI checks and members (AI Wellness).",
                "Fill in what applies today and tap <b>Save</b>. When all four badges are green, you're done for the day.",
            ], ["mgr_kpi", "mgr_today_done"]),
            ("Your shop's numbers", [
                "<b>Daily flash</b> shows your sales today vs the same day last week, and month-to-date vs budget.",
                "<b>Weekly</b> shows last week's sales, profit, customers and staff hours. <b>Expenses</b> lists everything recorded for your shop.",
            ], ["mgr_flash", "mgr_expenses"]),
            ("Good to know", [
                "If you miss the 11pm deadline, you get a reminder in your <b>Inbox</b> and the GM is told.",
                "Once Finance locks a month, its figures can no longer be changed.",
                "The whole app works in Chinese. Tap 中文 at the top.",
            ], ["mgr_sales_zh"]),
        ],
    },
    "gm": {
        "title": "GM / CEO", "accounts": "joe",
        "summary": "You see every shop and every report, approve the largest expenses, and set the rules: budgets, KPI targets, approval limits, users and the chart of accounts.",
        "sections": [
            ("Daily flash – your 5-minute review", [
                "This is the first page after sign-in: sales by shop today vs the same day last week, which shops are yet to submit, the on-time rate, approvals waiting and month-to-date vs budget.",
                "Open alerts are listed at the bottom.",
            ], ["gm_flash"]),
            ("Alerts", [
                "Alerts are raised automatically:",
                "<ul><li>late submissions after 11pm</li><li>sales down more than 15% vs the same day last week</li><li>expenses over budget</li><li>food cost above target</li><li>venue rent collected below target</li><li>month-end not closed by the 3rd</li></ul>",
                "Each alert is also sent to your inbox once. Click <b>Resolve</b> when it has been dealt with.",
                "<b>Run checks now</b> runs the checks immediately. Tick the box to also send the weekly dashboard e-mail.",
            ], ["gm_alerts"]),
            ("Approvals", [
                "Expenses above S$2,000 can only be approved by you. Finance can approve those between S$500 and S$2,000.",
                "Add a note if you like, then <b>Approve</b> or <b>Reject</b>. The person who submitted it is told.",
            ], ["gm_approvals"]),
            ("Weekly dashboard", [
                "Use this for the Monday meeting. It shows sales, profit, customers, staff hours, marketing spend and the on-time rate.",
                "Below that are the shop ranking with week-on-week change and weekday vs weekend sales, an 8-week trend, and people, venue and marketing highlights.",
                "The same summary is e-mailed every Monday after 10am to you, the heads and Boss Dong.",
            ], ["gm_weekly"]),
            ("Monthly P&L and KPI scorecard", [
                "<b>Monthly P&L</b> shows each company side by side, the combined group, and budget vs actual with variances. Pick a company to see only its books.",
                "<b>KPI scorecard</b> compares each KPI with its baseline, floor and target. Green means at or better than target, amber means between the floor and the target, and red means worse than the floor.",
                "From the 7th, the previous month's P&L is e-mailed to you and Boss Dong.",
            ], ["fin_pnl", "gm_scorecard"]),
            ("Marketing, group summary and operations log", [
                "<b>Marketing</b> shows spend, KOL fees, leads, cost per lead and per customer, and sales per S$1.",
                "<b>Group</b> shows the month-to-date summary that Boss Dong sees.",
                "<b>Ops log</b> lists complaints, equipment and stock problems, and the items managers sent to you.",
            ], ["gm_marketing", "gm_group", "gm_ops_log"]),
            ("Admin – controls", [
                "<b>Admin → Controls</b> sets the following:",
                "<ul><li>the amount above which a receipt is required</li><li>the Finance and GM approval limits</li><li>the daily deadline hour</li><li>the sales-drop alert %</li><li>the public address used in e-mails</li><li>whether two-factor login is required for everyone</li></ul>",
            ], ["gm_admin_controls"]),
            ("Admin – users and new account requests", [
                "Staff can request an account from the sign-in page. The request appears here with an <b>Approve</b> button, and you also get an inbox message.",
                "Open a user to change their role, shop, password, or active status, or to reset two-factor login.",
            ], ["gm_admin_users"]),
            ("Admin – shops, chart of accounts, KPI fields and targets", [
                "<b>Shops & companies</b>: names, UENs, addresses and managers.",
                "<b>Chart of accounts</b>: expense categories and the account codes used in the export.",
                "<b>KPI fields & targets</b> (per shop): add or switch off fields with no code changes. Formula fields such as <code>paid_visits / show_ups * 100</code> are calculated automatically. You also set the baseline, floor and target for each KPI here.",
            ], ["gm_admin_shops", "gm_admin_cats", "gm_admin_kpi"]),
            ("Inbox, month-end and backups", [
                "Your <b>Inbox</b> holds alerts, approval requests, sign-up requests, items from managers and the weekly and monthly e-mails.",
                "Only you can <b>unlock</b> a locked month, and you must give a reason, which is logged.",
                "On <b>Export</b>, you can download a full database backup. A backup is also saved automatically every day.",
            ], ["gm_inbox"]),
        ],
    },
    "finance": {
        "title": "Finance & HR", "accounts": "amanda",
        "summary": "You approve expenses, keep the books clean, manage staff and payroll, set budgets, close and lock each month, and export the data for the accountant.",
        "sections": [
            ("Approvals", [
                "Expenses above S$500 come to you. You can approve or reject anything up to S$2,000; amounts above that wait for the GM.",
                "Check the receipt link before approving. The submitter is told the result.",
            ], ["fin_approvals"]),
            ("Expenses", [
                "Filter by month, shop, category and status (approved, pending, rejected, void).",
                "📎 opens the receipt. You can edit or void approved expenses; managers cannot.",
            ], ["fin_expenses"]),
            ("Monthly P&L and budget vs actual", [
                "This shows revenue down to net profit for each company, plus the combined group.",
                "Revenue is the managers' daily net sales. Expenses include approved and pending items; rejected and voided items are left out.",
                "In the budget vs actual table, green means favourable.",
            ], ["fin_pnl", "fin_bva"]),
            ("Month-end close (by the 3rd)", [
                "Tick each shop's checklist: stock count, payroll and CPF, unrecorded expenses entered, and reconciliation.",
                "Reconciliation checks: days submitted, pending approvals, payables, and cash takings vs cash deposited (the difference must be 0).",
                "<b>Post payroll from staff list</b> creates the month's Staff expense for each shop: salaries, employer CPF and commission.",
                "<b>Lock</b> the month when it is done. After that, nobody can change its figures; only the GM can unlock it.",
            ], ["fin_month_end"]),
            ("Staff and budgets", [
                "<b>Staff</b>: each person's pay, hourly rate, employer CPF %, commission % and whether they are active, per shop.",
                "<b>Budgets</b>: the monthly budget per shop for sales and each expense category, with the 3-month baseline shown for reference.",
            ], ["fin_staff", "fin_budgets"]),
            ("Export and audit log", [
                "<b>Export</b>: CSV files per table, filtered by month and company, with account codes. They open in Excel or Google Sheets, or can be imported into Xero or QuickBooks.",
                "<b>Audit log</b>: every change, with before and after values. The log itself cannot be changed.",
            ], ["fin_export", "fin_audit"]),
        ],
    },
    "coo": {
        "title": "COO", "accounts": "nicholas",
        "summary": "You follow operations across all shops and can enter sales, operations, KPIs and purchasing expenses for any shop, for example venue bookings or checks you carry out.",
        "sections": [
            ("Entering data for any shop", [
                "Open <b>Today</b> and pick the shop at the top, then use the same 4-step checklist as the shop managers (see the Shop manager guide).",
                "Example: the venue KPIs (enquiries, site visits, confirmed events, rooms let, rent collected vs payable, space hours).",
            ], ["coo_today_selector", "coo_kpi_venue"]),
            ("Operations dashboards", [
                "<b>Daily flash</b> and <b>Weekly</b> show sales, customers, staff hours, absences, lateness, complaints, compliments, and venue and marketing highlights.",
                "<b>Ops log</b> lists every day that had an issue: absences, complaints, equipment, stock, and items for the GM.",
                "<b>KPI scorecard</b> and <b>Alerts</b> are also open to you.",
            ], ["coo_weekly_people", "coo_ops_log"]),
        ],
    },
    "marketing": {
        "title": "Brand & Marketing", "accounts": "jade",
        "summary": "You record ad spend and KOL fees, enter lead figures, and follow the marketing return across all shops.",
        "sections": [
            ("Marketing & leads dashboard", [
                "For each shop: marketing spend, KOL fees, leads, cost per lead, customers, cost per customer and sales per S$1 spent.",
                "The cards below show each shop's lead KPIs, for example influencer codes, conversion rates, bookings and AI checks.",
            ], ["mkt_dashboard", "mkt_dashboard_phone"]),
            ("Recording ad / KOL spend", [
                "Open <b>Add expense</b>, pick the shop, and fill in the supplier, amount, payment mode and <b>Paid / Payable</b>. Only the Marketing category is available to you.",
                "Attach the invoice photo. Above S$500 the expense needs Finance approval, and above S$2,000 it needs the GM.",
            ], ["mkt_expense"]),
            ("Entering leads", [
                "Open <b>KPIs</b>, pick the shop and date, and fill in lead sources, influencer codes, bookings and referrals.",
            ], ["mkt_kpi"]),
        ],
    },
    "accountant": {
        "title": "Accountant", "accounts": "accountant",
        "summary": "You have read-only access to the finance data for bookkeeping, and can export it.",
        "sections": [
            ("P&L and KPI scorecard", [
                "<b>Monthly P&L</b> shows each company (with its UEN) and the combined group, with budget vs actual. Filter by company to keep each set of books separate.",
                "Check that a month shows 🔒 <b>locked</b> before you book it; a locked month can no longer change.",
            ], ["acc_pnl", "acc_scorecard"]),
            ("Month-end status", [
                "You can see each shop's checklist and the reconciliation checks. Only Finance ticks items and locks the month.",
            ], ["acc_month_end"]),
            ("Export", [
                "Choose the data (daily sales, expenses, operations, KPIs, staff, budgets, audit log), the month and the company, then click <b>Download CSV</b>.",
                "Expense exports include the account code from the chart of accounts. Every export is recorded in the audit log.",
            ], ["acc_export"]),
        ],
    },
    "owner": {
        "title": "Owner (Boss Dong)", "accounts": "dong",
        "summary": "You get the read-only group summary: how the whole group and each shop is doing this month.",
        "sections": [
            ("Group summary", [
                "Shows sales and profit month to date against budget, last month's sales, a 6-month sales trend, sales and profit by shop, and last month's KPI status (green, amber, red) for each shop.",
                "It works the same on a phone.",
                "The weekly dashboard e-mail (Mondays) and the monthly P&L and KPI scorecard (from the 7th) also arrive in your <b>Inbox</b>.",
            ], ["own_group", "own_group_phone"]),
            ("What you can't open", [
                "Detailed transactions and input forms are not part of your view; you'll see a 'no access' page.",
            ], ["own_forbidden"]),
        ],
    },
}

CSS = """
@page { size: A4; margin: 16mm 14mm 18mm; }
body { font: 10.5pt/1.5 'Segoe UI', system-ui, sans-serif; color: #1d232b; }
h1 { color: #8a1c2b; font-size: 24pt; margin: 0 0 4pt; }
h2 { color: #8a1c2b; font-size: 14pt; margin: 18pt 0 6pt; border-bottom: 1.5pt solid #e3e1da; padding-bottom: 3pt; page-break-after: avoid; }
.cover { background: #8a1c2b; color: #fff; padding: 22pt 24pt; border-radius: 10pt; margin-bottom: 14pt; }
.cover h1 { color: #fff; } .cover p { margin: 3pt 0; opacity: .92; }
.summary { background: #faf3f4; border-left: 4pt solid #8a1c2b; padding: 8pt 12pt; margin: 10pt 0; }
ol, ul { margin: 4pt 0 6pt 16pt; padding: 0; } li { margin: 2pt 0; }
.shots { display: flex; flex-wrap: wrap; gap: 10pt; align-items: flex-start; margin: 6pt 0 4pt; page-break-inside: avoid; }
.shots figure { margin: 0; } figure img { border: 1pt solid #d6d3ca; border-radius: 6pt; display: block; }
figure.desk img { width: 100%; } figure.desk { flex: 1 1 100%; } figure.phone img { width: 190pt; }
figcaption { font-size: 8.5pt; color: #66707c; margin-top: 2pt; }
table { border-collapse: collapse; width: 100%; font-size: 9pt; margin: 6pt 0; }
th, td { border: 0.75pt solid #d6d3ca; padding: 4pt 5pt; text-align: left; vertical-align: top; }
th { background: #f3efe8; }
code { background: #f3efe8; padding: 0 3pt; border-radius: 3pt; font-size: 9pt; }
.pw { font-family: Consolas, monospace; }
.note { font-size: 9pt; color: #66707c; }
.matrix td { text-align: center; } .matrix td:first-child { text-align: left; white-space: nowrap; }
"""


def img_tag(name):
    path = os.path.join(IMG, name + ".png")
    data = base64.b64encode(open(path, "rb").read()).decode()
    phone = name.startswith(("mgr_", "common_login", "common_register", "common_chinese", "mkt_expense", "mkt_kpi", "own_group_phone",
                             "mkt_dashboard_phone")) and name not in ("mgr_sales_mismatch",)
    cls = "phone" if phone else "desk"
    if name == "mgr_sales_mismatch":
        cls = "desk"
    cap = name.split("_", 1)[1].replace("_", " ").capitalize()
    return f'<figure class="{cls}"><img src="data:image/png;base64,{data}"><figcaption>{html.escape(cap)}</figcaption></figure>'


def section(title, steps, imgs):
    body = "".join(s if s.startswith("<ul>") else f"<li>{s}</li>" for s in steps)
    body = "<ol>" + body.replace("<ul>", "</ol><ul>").replace("</ul>", "</ul><ol>") + "</ol>"
    body = body.replace("<ol></ol>", "")
    return f"<h2>{html.escape(title)}</h2>{body}<div class='shots'>{''.join(img_tag(i) for i in imgs)}</div>"


def accounts_table(rows):
    tr = "".join(f"<tr><td>{r}</td><td>{n}</td><td class='pw'><b>{u}</b></td><td class='pw'>{p}</td><td>{s}</td><td>{what}</td></tr>"
                 for r, n, u, p, s, what in rows)
    return f"<table><tr><th>Role</th><th>Person</th><th>Username</th><th>Password</th><th>Shop</th><th>What they can do</th></tr>{tr}</table>"


def page(title, inner):
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>{CSS}</style></head><body>{inner}</body></html>"


def cover(title, sub):
    return (f"<div class='cover'><p style='font-size:10pt;letter-spacing:.08em'>AANDJ GROUP · SHOP REPORTING SYSTEM</p><h1>{html.escape(title)}</h1>"
            f"<p>{sub}</p></div>")


docs = {}
# ---- overview with board of all accounts ----
matrix_rows = "".join(f"<tr><td>{pg}</td>" + "".join(f"<td>{MATRIX[label][i]}</td>" for label, _ in ROLE_KEYS) + "</tr>"
                      for i, (pg, _) in enumerate(PAGES))
overview = cover("User guide – overview & accounts", "Who uses the system, how to sign in, and which guide to read") + \
    "<div class='summary'>Managers enter each day's figures on their phones, the system adds everything up automatically, and the GM reviews it and decides. Each role has its own guide, which shows exactly what that role sees.</div>" + \
    "<h2>Board of all role accounts</h2>" + accounts_table(ACCOUNTS) + \
    "<p class='note'><b>Demo accounts.</b> Change every password after the first sign-in (Security → Change password) before real use, and ask the GM to turn on two-factor login for everyone. New staff can request an account themselves (below).</p>" + \
    "<h2>Which pages each role can open</h2><table class='matrix'><tr><th>Page</th>" + "".join(f"<th>{label}</th>" for label, _ in ROLE_KEYS) + \
    f"</tr>{matrix_rows}</table><p class='note'>✓ = can open · 👁 = view only · – = no access. Shop managers only ever see their own shop.</p>" + \
    "<h2>The guides</h2><table><tr><th>Guide</th><th>For</th></tr>" + "".join(
        f"<tr><td>AANDJ-Guide-{i + 1}-{v['title'].split(' (')[0].replace(' / ', '-').replace(' & ', '-').replace(' ', '-')}.pdf</td><td>{v['summary']}</td></tr>"
        for i, v in enumerate(ROLES.values())) + "</table>" + \
    "".join(section(*s) for s in COMMON[:2]) + \
    section("Requesting a new account", [
        "On the sign-in page, tap <b>New here? Create an account</b>.",
        "Enter your name, a username, your e-mail and phone, your role, your shop (for shop managers) and a password (8+ characters, typed twice).",
        "Tap <b>Create account</b>. The GM approves it and then you can sign in. Until then, sign-in shows 'waiting for the GM's approval'.",
        "Nobody can sign themselves up as GM.",
    ], ["common_register", "common_register_done"]) + section(*COMMON[2]) + \
    "<h2>Daily and monthly deadlines</h2><table><tr><th>When</th><th>Who</th><th>What</th></tr>" \
    "<tr><td>Daily, by 11pm</td><td>Shop managers</td><td>Sales, payment modes, customers, expenses with receipt photos, operations, KPIs</td></tr>" \
    "<tr><td>Monday 10am</td><td>System</td><td>Weekly dashboard e-mail to the GM, heads and Boss Dong</td></tr>" \
    "<tr><td>By the 3rd</td><td>Managers + Finance</td><td>Stock count, payroll, unrecorded expenses, reconciliation → lock the month</td></tr>" \
    "<tr><td>By the 7th</td><td>System + Accountant</td><td>P&L per company and KPI scorecard to the GM and Boss Dong</td></tr></table>"
docs["AANDJ-Guide-0-Overview-and-Accounts"] = page("AANDJ guide – overview", overview)

for i, (key, r) in enumerate(ROLES.items()):
    mine = [a for a in ACCOUNTS if a[0].startswith(r["title"].split(" (")[0])] or [a for a in ACCOUNTS if a[2] == r["accounts"]]
    inner = cover(f"{r['title']} guide", f"Accounts: {r['accounts']}") + f"<div class='summary'>{r['summary']}</div>" + \
        "<h2>Your account</h2>" + accounts_table(mine) + "".join(section(*s) for s in r["sections"]) + \
        "".join(section(*s) for s in COMMON)
    name = f"AANDJ-Guide-{i + 1}-" + r["title"].split(" (")[0].replace(" / ", "-").replace(" & ", "-").replace(" ", "-")
    docs[name] = page(f"AANDJ guide – {r['title']}", inner)

with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page()
    for name, doc in docs.items():
        hp = os.path.join(OUT, name + ".html")
        with open(hp, "w", encoding="utf-8") as f:
            f.write(doc)
        p.goto("file:///" + hp.replace("\\", "/"))
        p.pdf(path=os.path.join(OUT, name + ".pdf"), format="A4", print_background=True, display_header_footer=True,
              header_template="<span></span>",
              footer_template="<div style='font-size:8px;color:#888;width:100%;text-align:center'>AANDJ Shop Reporting · "
                              + html.escape(name.split("-", 3)[-1].replace("-", " ")) + " · page <span class='pageNumber'></span> of <span class='totalPages'></span></div>",
              margin={"top": "16mm", "bottom": "18mm", "left": "14mm", "right": "14mm"})
        os.remove(hp)
        print("built", name + ".pdf")
    b.close()
