"""Report calculations: daily flash, weekly dashboard, monthly P&L, KPI scorecard."""
import ast
import operator
from datetime import date, timedelta

COUNTED = "status NOT IN ('rejected', 'void')"

BUILTIN_METRICS = {
    "net_sales": ("Net sales", "S$", "up"),
    "customers": ("Customers", "", "up"),
    "avg_spend": ("Average spend", "S$", "up"),
    "gross_margin_pct": ("Gross margin %", "%", "up"),
    "food_cost_pct": ("Food / product cost %", "%", "down"),
    "staff_cost_pct": ("Staff cost %", "%", "down"),
    "rent_pct": ("Rent as % of sales", "%", "down"),
    "marketing_per_customer": ("Marketing cost per customer", "S$", "down"),
    "net_profit": ("Net profit", "S$", "up"),
}


def d(s):
    return date.fromisoformat(s) if isinstance(s, str) else s


def month_bounds(month):
    y, m = map(int, month.split("-"))
    first = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return first, nxt  # [first, nxt)


def prev_month(month, n=1):
    y, m = map(int, month.split("-"))
    m -= n
    while m < 1:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


def week_start(day):
    return day - timedelta(days=day.weekday())


# ---------- safe formula evaluation for KPI fields ----------
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def eval_formula(expr, values):
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            a, b = ev(node.left), ev(node.right)
            if a is None or b is None:
                return None
            if isinstance(node.op, ast.Div) and b == 0:
                return None
            return _OPS[type(node.op)](a, b)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            v = ev(node.operand)
            return None if v is None else -v
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name):
            v = values.get(node.id)
            return v if isinstance(v, (int, float)) else None
        raise ValueError("Only + - * / numbers and field keys are allowed")
    return ev(ast.parse(expr, mode="eval"))


def validate_formula(expr, keys):
    tree = ast.parse(expr, mode="eval")
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id not in keys:
            raise ValueError(f"Unknown field key '{n.id}'")
    eval_formula(expr, {k: 1 for k in keys})


# ---------- base aggregates ----------
def sales_totals(conn, shop_id, d1, d2):
    r = conn.execute("""SELECT COALESCE(SUM(net),0) net, COALESCE(SUM(gross),0) gross, COALESCE(SUM(customers),0) customers,
                        COALESCE(SUM(transactions),0) tx, COUNT(*) days FROM daily_sales WHERE shop_id=? AND date>=? AND date<?""",
                     (shop_id, d1.isoformat(), d2.isoformat())).fetchone()
    return dict(r)


def expenses_by_cat(conn, shop_id, d1, d2):
    rows = conn.execute(f"""SELECT category, SUM(amount) amt FROM expenses WHERE shop_id=? AND date>=? AND date<? AND {COUNTED}
                            GROUP BY category""", (shop_id, d1.isoformat(), d2.isoformat())).fetchall()
    return {r["category"]: r["amt"] for r in rows}


def kpi_fields(conn, shop_id, active_only=True):
    q = "SELECT * FROM kpi_fields WHERE shop_id=?" + (" AND active=1" if active_only else "") + " ORDER BY sort, id"
    return conn.execute(q, (shop_id,)).fetchall()


def kpi_period(conn, shop_id, d1, d2):
    """Aggregate KPI inputs over [d1, d2). Returns {key: value}."""
    fields = kpi_fields(conn, shop_id)
    out = {}
    for f in fields:
        if f["ftype"] == "formula":
            continue
        rows = conn.execute("SELECT value FROM kpi_values WHERE field_id=? AND date>=? AND date<? ORDER BY date",
                            (f["id"], d1.isoformat(), d2.isoformat())).fetchall()
        vals = [r["value"] for r in rows if r["value"] not in (None, "")]
        if not vals:
            out[f["key"]] = None
            continue
        if f["ftype"] == "text" or f["agg"] == "last":
            v = vals[-1]
            try:
                out[f["key"]] = float(v) if f["ftype"] != "text" else v
            except ValueError:
                out[f["key"]] = v
            continue
        nums = []
        for v in vals:
            try:
                nums.append(float(v))
            except ValueError:
                pass
        out[f["key"]] = (sum(nums) / len(nums) if f["agg"] == "avg" else sum(nums)) if nums else None
    for f in fields:
        if f["ftype"] == "formula" and f["formula"]:
            try:
                out[f["key"]] = eval_formula(f["formula"], out)
            except Exception:
                out[f["key"]] = None
    return out


def pct(a, b):
    return (a / b * 100) if b else None


def metrics(conn, shop_id, d1, d2):
    s = sales_totals(conn, shop_id, d1, d2)
    e = expenses_by_cat(conn, shop_id, d1, d2)
    total_exp = sum(e.values())
    net = s["net"]
    m = {
        "net_sales": net, "customers": s["customers"], "avg_spend": (net / s["customers"]) if s["customers"] else None,
        "gross_margin_pct": pct(net - e.get("Cost of goods sold", 0), net),
        "food_cost_pct": pct(e.get("Cost of goods sold", 0), net),
        "staff_cost_pct": pct(e.get("Staff", 0), net),
        "rent_pct": pct(e.get("Rent", 0), net),
        "marketing_per_customer": (e.get("Marketing", 0) / s["customers"]) if s["customers"] else None,
        "net_profit": net - total_exp,
        "total_expenses": total_exp, "days": s["days"],
    }
    m.update({k: v for k, v in kpi_period(conn, shop_id, d1, d2).items()})
    return m, e


def rag(value, t):
    """Red / amber / green against floor and target. Returns (status, note)."""
    if value is None or not isinstance(value, (int, float)) or t is None:
        return "na"
    up = t["direction"] == "up"
    target, floor = t["target"], t["floor"]
    if target is None and floor is None:
        return "na"
    better = (lambda a, b: a >= b) if up else (lambda a, b: a <= b)
    if target is not None and better(value, target):
        return "green"
    if floor is not None and better(value, floor):
        return "amber"
    if floor is None:
        return "amber"
    return "red"


# ---------- reports ----------
def daily_flash(conn, shops, day):
    last_week = day - timedelta(days=7)
    rows = []
    for s in shops:
        today = conn.execute("SELECT * FROM daily_sales WHERE shop_id=? AND date=?", (s["id"], day.isoformat())).fetchone()
        lw = conn.execute("SELECT net, customers FROM daily_sales WHERE shop_id=? AND date=?", (s["id"], last_week.isoformat())).fetchone()
        net = today["net"] if today else None
        lw_net = lw["net"] if lw else None
        rows.append({"shop": s, "row": today, "net": net, "customers": today["customers"] if today else None,
                     "lw_net": lw_net, "change": ((net - lw_net) / lw_net * 100) if (net is not None and lw_net) else None,
                     "submitted": today is not None})
    tot = sum(r["net"] or 0 for r in rows)
    lw_tot = sum(r["lw_net"] or 0 for r in rows if r["net"] is not None)
    return {"rows": rows, "total": tot, "lw_total": lw_tot,
            "change": ((tot - lw_tot) / lw_tot * 100) if lw_tot else None,
            "missing": [r["shop"] for r in rows if not r["submitted"]]}


def on_time_rate(conn, shop_ids, d1, d2, deadline_hour):
    if not shop_ids:
        return None
    q = f"SELECT date, submitted_at FROM daily_sales WHERE shop_id IN ({','.join('?' * len(shop_ids))}) AND date>=? AND date<?"
    rows = conn.execute(q, (*shop_ids, d1.isoformat(), d2.isoformat())).fetchall()
    expected = len(shop_ids) * (d2 - d1).days
    ok = 0
    for r in rows:
        deadline = f"{r['date']}T{int(deadline_hour):02d}:59:59"
        if r["submitted_at"] <= deadline:
            ok += 1
    return pct(ok, expected) if expected else None


def weekly(conn, shops, ws):
    we = ws + timedelta(days=7)
    pws = ws - timedelta(days=7)
    rows = []
    for s in shops:
        m, e = metrics(conn, s["id"], ws, we)
        pm, _ = metrics(conn, s["id"], pws, ws)
        ops = conn.execute("""SELECT COALESCE(SUM(staff_hours),0) hours, COALESCE(AVG(staff_on_shift),0) heads,
                              SUM(CASE WHEN absences<>'' THEN 1 ELSE 0 END) absences,
                              SUM(CASE WHEN lateness<>'' THEN 1 ELSE 0 END) late,
                              SUM(CASE WHEN complaints<>'' THEN 1 ELSE 0 END) complaints,
                              SUM(CASE WHEN compliments<>'' THEN 1 ELSE 0 END) compliments
                              FROM daily_ops WHERE shop_id=? AND date>=? AND date<?""",
                           (s["id"], ws.isoformat(), we.isoformat())).fetchone()
        wk = conn.execute("""SELECT SUM(CASE WHEN strftime('%w', date) IN ('0','6') THEN net ELSE 0 END) wkend,
                             SUM(CASE WHEN strftime('%w', date) NOT IN ('0','6') THEN net ELSE 0 END) wkday
                             FROM daily_sales WHERE shop_id=? AND date>=? AND date<?""", (s["id"], ws.isoformat(), we.isoformat())).fetchone()
        rows.append({"shop": s, "m": m, "prev": pm, "exp": e, "ops": dict(ops), "wkend": wk["wkend"] or 0, "wkday": wk["wkday"] or 0,
                     "growth": ((m["net_sales"] - pm["net_sales"]) / pm["net_sales"] * 100) if pm["net_sales"] else None,
                     "sales_per_head": (m["net_sales"] / ops["heads"]) if ops["heads"] else None})
    ranked = sorted(rows, key=lambda r: r["net_sales"] if "net_sales" in r else r["m"]["net_sales"], reverse=True)
    trend = []
    for i in range(7, -1, -1):
        a = ws - timedelta(days=7 * i)
        b = a + timedelta(days=7)
        vals = {}
        for s in shops:
            vals[s["code"]] = sales_totals(conn, s["id"], a, b)["net"]
        trend.append({"week": a, "vals": vals, "total": sum(vals.values())})
    return {"rows": rows, "ranked": ranked, "trend": trend, "start": ws, "end": we - timedelta(days=1)}


def pnl(conn, shops, month, categories):
    d1, d2 = month_bounds(month)
    cols = []
    for s in shops:
        e = expenses_by_cat(conn, s["id"], d1, d2)
        st = sales_totals(conn, s["id"], d1, d2)
        budget = {r["line"]: r["amount"] for r in conn.execute(
            "SELECT line, amount FROM budgets WHERE shop_id=? AND month=? AND kind='budget'", (s["id"], month))}
        cols.append({"shop": s, "sales": st["net"], "exp": e, "budget": budget})

    def line(col, name):
        if name == "Revenue":
            return col["sales"]
        if name == "Gross profit":
            return col["sales"] - col["exp"].get("Cost of goods sold", 0)
        if name == "Total expenses":
            return sum(col["exp"].values())
        if name == "Net profit":
            return col["sales"] - sum(col["exp"].values())
        return col["exp"].get(name, 0)

    def bline(col, name):
        b = col["budget"]
        if not b:
            return None
        if name == "Revenue":
            return b.get("Sales")
        if name == "Gross profit":
            return b.get("Sales", 0) - b.get("Cost of goods sold", 0)
        costs = sum(v for k, v in b.items() if k != "Sales")
        if name == "Total expenses":
            return costs
        if name == "Net profit":
            return b.get("Sales", 0) - costs
        return b.get(name)

    lines = ["Revenue", "Cost of goods sold", "Gross profit"] + [c for c in categories if c != "Cost of goods sold"] + ["Total expenses", "Net profit"]
    table = []
    for ln in lines:
        vals = [line(c, ln) for c in cols]
        buds = [bline(c, ln) for c in cols]
        table.append({"line": ln, "vals": vals, "group": sum(vals), "budgets": buds,
                      "group_budget": sum(b for b in buds if b is not None) if any(b is not None for b in buds) else None,
                      "bold": ln in ("Revenue", "Gross profit", "Net profit")})
    return {"cols": cols, "table": table, "month": month}


def scorecard(conn, shops, month):
    d1, d2 = month_bounds(month)
    out = []
    for s in shops:
        m, _ = metrics(conn, s["id"], d1, d2)
        fields = {f["key"]: f for f in kpi_fields(conn, s["id"])}
        targets = conn.execute("SELECT * FROM kpi_targets WHERE shop_id=? ORDER BY id", (s["id"],)).fetchall()
        items = []
        for t in targets:
            label, unit = (BUILTIN_METRICS[t["metric"]][:2] if t["metric"] in BUILTIN_METRICS
                           else ((fields[t["metric"]]["label"], fields[t["metric"]]["unit"]) if t["metric"] in fields else (t["metric"], "")))
            v = m.get(t["metric"])
            items.append({"metric": t["metric"], "label": label, "unit": unit or "", "value": v, "t": t, "status": rag(v, t)})
        out.append({"shop": s, "rows": items,
                    "counts": {k: sum(1 for i in items if i["status"] == k) for k in ("green", "amber", "red")}})
    return out
