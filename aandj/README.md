# AANDJ Shop Performance Reporting System

Every outlet's sales, costs and KPIs, reported daily into one dashboard for the GM. Built from the
requirements brief *AANDJ_Shop_Reporting_System_Brief.pdf* (3 Nov 2026).

**Stack:** Python 3.10+ · Flask · SQLite. It has no other dependencies and no paid services. Pages are rendered on the server and
work on a phone (mobile-first forms, camera upload for receipts). Charts are inline SVG.

## Run it

```bash
cd aandj
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. On first start it creates `data/aandj.db` with five outlets and about 3 months of demo
data (the "baseline").

| Username | Role | What they see |
|---|---|---|
| `joe` | GM / CEO | Everything, plus admin (budgets, KPI targets, approvals, limits, users) |
| `amanda` | Finance & HR | Finance + HR, approvals up to the GM limit, payroll, month-end lock, export |
| `nicholas` | COO | Operations dashboards, ops/KPI/sales input for any shop |
| `jade` | Brand & Marketing | Marketing & leads dashboard, marketing expenses, lead KPIs |
| `mgr_cyz`, `mgr_sim`, `mgr_brw`, `mgr_ven`, `mgr_aiw` | Shop manager | Own shop only: daily input + own flash/weekly |
| `accountant` | Accountant | Read-only finance + CSV export |
| `dong` | Owner (Boss Dong) | Read-only group summary |

The demo password for every account is `aandj123`. Change it under **Security**, or as the GM under **Admin → Users**.

**Create account:** "Create an account" on the sign-in page (`/register`). New accounts stay inactive until the GM
clicks **Approve** in Admin → Users (the GM also gets an inbox message). Nobody can sign themselves up as GM.
`python tests/signup.py` creates and approves the example account `example_manager` / `Example2026!`
(Cai Yuan Zi manager).

Useful commands:

```bash
python db.py --reset          # wipe and reload demo data
set AANDJ_NO_DEMO=1           # (PowerShell: $env:AANDJ_NO_DEMO="1") start with an empty database for go-live
python tests/e2e.py           # Playwright end-to-end test (app must be running on a fresh demo DB)
python tests/record_video.py  # narrated walkthrough test -> tests/AANDJ-Test-Video.mp4 (uses its own fresh DB)
```

Environment options: `PORT`, `HOST`, `AANDJ_SECRET` (session key, **set it in production**), `AANDJ_DB` (DB path),
`AANDJ_JOB_SECONDS` (automation interval, default 300), `AANDJ_NOW` (fake clock for testing, e.g. `2026-11-09T10:30`),
`SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_FROM` (optional e-mail delivery; without SMTP, messages
appear in each user's in-app **Inbox**).

## What's in it, mapped to the brief

| Brief | Where |
|---|---|
| Mobile input forms for sales, expenses, operations and KPIs, with receipt upload | **Today** checklist → 4 forms. Net sales and average spend are calculated as you type, the payment modes must add up to net sales, and the POS photo and receipt photo are required |
| Common sales fields (gross, discounts, refunds, net, cash/PayNow/card/platforms, transactions, customers, POS photo, cash deposit) | `input/sales` |
| Expense fields (date, shop, supplier, category, amount, GST, payment mode, receipt, approver, paid/payable) | `input/expense`, `expenses` list |
| Daily operations (staff/hours, absences, lateness, complaints, compliments, equipment, stock, items for the GM) | `input/ops`. Items for the GM are sent straight to the GM's inbox |
| Standard chart of accounts (9 categories), "Others" needs a purpose | Seeded. **Admin → Chart of accounts** to add categories or account codes, which flow into the CSV export |
| Shop-specific KPI fields for all 5 outlets; "easy to add or change" | Seeded per brief. **Admin → KPI fields** to add, rename or disable fields. Formula fields (e.g. `paid_visits / show_ups * 100`) need no code |
| 6 core tables: Shops, Daily Sales, Expenses, KPI Inputs, Staff, Baseline & Budget | `shops`, `daily_sales`, `expenses`, `kpi_fields`/`kpi_values`, `staff`, `budgets` (+ `kpi_targets`) |
| Daily flash: sales by shop, vs same day last week, shops yet to submit | **Daily flash** (also month-to-date vs budget, on-time %, open alerts) |
| Weekly dashboard: sales, profit, customers, people, venue, marketing, ranking, trends | **Weekly** (also weekday vs weekend, 8-week trend) |
| Monthly P&L per company + group, budget vs actual | **Monthly P&L** (filter by company) |
| KPI scorecard vs baseline/floor/target with red/amber/green | **KPI scorecard**. Targets are set under Admin → KPI fields & targets |
| Alerts: sales −15% vs same day last week, expenses over budget, late submissions, food cost above target, venue rent below target | `automation.py` runs every 5 minutes and on **Alerts → Run checks now**. Each alert is sent to the GM once |
| Reminders for missed deadlines + flag to GM; Monday 10am dashboard e-mail | Same job. Managers get a bilingual reminder after 11pm; the weekly summary goes to the GM, heads and Boss Dong on Mondays after 10:00 |
| Monthly deadlines: close by the 3rd, P&L by the 7th | **Month-end**: checklist (stock count, payroll, unrecorded expenses, reconciliation), cash vs deposit check, "post payroll" from the staff list. Reminders before the 3rd, an alert after it, and the P&L e-mailed to the GM and Boss Dong on the 7th |
| Role-based access; managers only their shop | `ACCESS` map in `app.py` and the shop filter on every query. Receipt photos are also restricted by shop |
| Receipts required above S$____ | **Admin → Controls**: "Receipt required above" (default 0 = always) |
| Approval matrix | Above S$500 → Finance (or GM); above S$2,000 → GM only. Both limits are editable |
| Edit history; raw data can't be deleted | Every change goes to `audit_log` with before/after values. SQLite triggers block DELETE on raw tables and any change to the log. Expenses are voided, not deleted |
| Month-end lock | **Month-end → Lock**. Locked months reject all inputs; only the GM can unlock, with a reason that is logged |
| Two-factor login, backups, no unnecessary customer data | TOTP 2FA (any authenticator app) per user, or forced for everyone in Admin. Automatic daily DB backup in `data/backups` plus a download for the GM. Forms don't collect customer personal data and carry a PDPA reminder |
| Data separated by company yet combinable | Each shop row carries its company/UEN. P&L and exports filter by company or combine for the group |
| Read-only export for the accountant | **Export** → CSV per table, by month and company, with account codes |
| Manager user guide (English and Chinese) | `docs/manager_guide_en.md`, `docs/manager_guide_zh.md`, also in-app under **Guide**. The manager screens switch EN/中文 |
| All accounts and files owned by AANDJ | Self-hosted: one folder and one SQLite file, with no third-party accounts |

## Files

- `app.py` – routes, access control, forms, 2FA, exports
- `reports.py` – flash / weekly / P&L / scorecard calculations, safe KPI formula evaluator
- `automation.py` – reminders, alerts, weekly/monthly e-mails, backups
- `db.py` – schema, triggers, chart of accounts, KPI field definitions, demo seed
- `i18n.py` – Chinese labels · `templates/`, `static/` – UI · `docs/` – manager guides · `tests/e2e.py` – browser test

## Putting it online

This is a Python server with a database file, so it can't run on Cloudflare Workers or Pages. To publish it for free with **Cloudflare Tunnel** from an always-on Windows PC, follow [deploy/cloudflare-tunnel.md](deploy/cloudflare-tunnel.md). The production entry point is `python serve.py` (Waitress, port 8000, HTTPS-only cookies, plus the reminder/alert scheduler).

## Going live checklist

1. Start on an empty database with `AANDJ_NO_DEMO=1`, `AANDJ_SECRET=<random>` and `AANDJ_ADMIN_PASSWORD=<initial password>`. This creates only the chart of accounts and the GM login `joe`. Sign in and change the password.
2. Admin → Shops: real company names, UENs and addresses (brief item 1). Admin → Users: managers' names, phones and e-mails (item 2).
3. Chart of accounts and account codes agreed with the accountant (item 5); budgets per shop (item 8); KPI targets from the signed scorecard (item 7).
4. Load the 3-month baseline (item 6): enter baseline values on the KPI targets page, and import the historical sales/expense rows into `daily_sales` / `expenses` (a CSV import screen is not built yet – see "Not implemented").
5. Turn on "Require two-factor login" and configure SMTP for e-mail.
6. Host it on a small always-on machine or VPS behind an HTTPS reverse proxy, running `python app.py` (which also starts the reminder/alert scheduler). Copy `data/backups` off the machine regularly.

## Ambiguities, assumptions and what's not implemented

**Assumptions I made, all changeable in Admin unless noted**
- **Platform.** The brief recommends Google Forms, Sheets and Looker Studio. I built a small self-hosted web app instead, because the brief also requires role-level access per shop, append-only data, month locks, approval routing and automatic alerts, which Sheets does not enforce reliably. It runs at zero licence cost, and the data stays in one SQLite file that AANDJ owns. A Google or Xero connector can be added later.
- **Receipt threshold "S$____".** The brief leaves it blank. The default is S$0, so a receipt is always required, which matches the "Receipt (required)" line in the brief.
- **Approval limits.** The brief gives none. I assumed above S$500 goes to Finance (Amanda) and above S$2,000 goes to the GM only.
- **Deadline.** 11pm, as in the brief. A day counts as late if it is still missing after 23:00, and the on-time % compares `submitted_at` with 23:59.
- **Expenses in the P&L.** Approved and pending items count; rejected and voided items don't. Revenue is the net sales from the daily submissions, which is cash-basis. No accruals or deferred revenue (for example, prepaid packages) are recognised.
- **Food cost %** is the *Cost of goods sold* category divided by net sales, month to date. The food-cost alert applies to any shop that has a `food_cost_pct` target (seeded for Cai Yuan Zi at 30%).
- **Venue rent collected vs payable** comes from two KPI fields the venue manager enters daily. The alert fires when the month-to-date ratio is below target (90% in the demo).
- **"Expenses over budget"** compares month-to-date spend with the full-month budget for each category.
- **Scorecard targets** are monthly totals. Viewing the current month mid-month shows month-to-date figures, so sales targets look red until month-end. The scorecard defaults to the previous month.
- **Companies.** Each outlet is one company. The venue and AI Wellness company names and UENs are placeholders marked "TBC" (brief items 1 and AI Wellness "to be confirmed").
- **Payroll.** The Staff list holds pay, employer CPF % (default 17%) and commission %. "Post payroll" creates one Staff expense per shop. Real CPF rates depend on age and wage ceilings and are not modelled.
- **Weekly e-mail recipients.** GM, Finance, COO, Marketing and Boss Dong.
- **Monthly P&L e-mail.** Sent on or after the 7th to the GM and Boss Dong.
- **Seeded KPI fields** follow brief page 8. Final KPIs follow the scorecard signed in Week 2, so they are editable rather than fixed.
- **E-mail.** No e-mail service is assumed, so nothing paid is used. Messages land in the in-app Inbox, and real e-mail turns on once SMTP settings are supplied (for example a Google Workspace account).

**Not implemented / out of scope for software**
- **POS and booking-system integrations** (brief item 4 needs export access first). Managers type the end-of-day figures and photograph the POS report.
- **Import screen for the 3-month baseline.** The demo seeds generated history instead. Real history needs a one-off CSV import, or entry through the forms.
- **Cloud accounting sync** (Xero / QuickBooks). A CSV export with account codes is provided instead.
- **WhatsApp or SMS reminders.** Reminders are in-app plus optional e-mail.
- **Delivery tasks that aren't software:** the 30-minute training per shop, the one-week pilot at two shops, and handover of accounts. The bilingual user guide is included.
- **Prepaid package liability accounting** for Simply and AI Wellness. Sold and redeemed values are tracked as KPIs only.
- **Mobile app or offline mode.** It is a responsive web app and needs a connection.
- **Hosting, HTTPS and an off-site backup destination.** These must be chosen by AANDJ.
