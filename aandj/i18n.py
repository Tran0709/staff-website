"""English / Chinese labels.

`tr()` translates one label. `translate_html()` translates the visible text of a whole rendered page, so every
screen switches language, not only the menu. It never touches attribute values (form values, links), <option>
text without its own value (that text is what the browser submits), scripts, styles, <pre> or <textarea>.
"""
import html as _html
import re

ZH = {
    # navigation
    "Today": "今日", "Daily sales": "每日销售", "Expenses": "费用", "Expense": "费用", "Operations": "营运", "KPIs": "KPI 指标",
    "Daily flash": "每日快报", "Weekly": "周报", "Monthly P&L": "月度损益", "KPI scorecard": "KPI 记分卡", "Marketing": "市场营销",
    "Ops log": "营运日志", "Group": "集团", "Approvals": "审批", "Alerts": "警报", "Inbox": "消息", "Month-end": "月结",
    "Staff": "员工", "Budgets": "预算", "Export": "导出", "Audit log": "修改记录", "Admin": "设置", "Security": "安全", "Log out": "退出",
    "Guide": "使用指南", "Shop": "店铺", "Date": "日期", "Save": "保存", "Submit": "提交", "Month": "月份", "Show": "显示",
    "Filter": "筛选", "All": "全部", "Edit": "修改", "edit": "修改", "View": "查看", "Status": "状态", "Home": "首页",
    # input forms
    "Gross sales": "总销售额", "Discounts": "折扣", "Refunds": "退款", "Net sales": "净销售额",
    "Payment modes": "付款方式", "Cash": "现金", "Card": "刷卡", "Platforms (Grab, foodpanda, etc.)": "外卖平台（Grab、foodpanda 等）",
    "Transactions": "交易笔数", "Customers": "顾客人数", "Average spend": "平均消费", "Avg spend": "平均消费",
    "Photo of POS end-of-day report": "POS 日结单照片", "Cash deposited": "现金存款金额", "Deposit reference": "存款单号", "Notes": "备注",
    "Supplier": "供应商", "Category": "类别", "Amount (incl. GST)": "金额（含消费税）", "GST": "消费税", "Payment mode": "付款方式",
    "Receipt or invoice photo": "收据或发票照片", "Purpose": "用途", "Paid": "已付", "Payable": "应付", "paid": "已付", "payable": "应付",
    "Staff on shift": "当班员工人数", "Total staff hours": "员工总工时", "Absences": "缺勤", "Lateness": "迟到",
    "Complaints": "投诉", "Compliments": "表扬", "Equipment or supply issues": "设备或物资问题", "Stock or wastage problems": "库存或损耗问题",
    "Items needing the GM": "需要总经理处理的事项",
    "Sales saved": "销售已保存", "Operations saved": "营运已保存", "KPIs saved": "KPI 已保存", "Expense saved": "费用已保存",
    "Today's checklist": "今日清单", "Done": "已完成", "Not yet": "未完成", "Deadline": "截止时间",
    "Missing days": "未提交的日期", "Messages": "消息", "This month is locked": "本月已锁账",
    "Add expense": "添加费用", "Submitted": "已提交", "Shop-specific KPIs": "店铺专属 KPI",
    "Net = gross − discounts − refunds": "净额 = 总额 − 折扣 − 退款", "Payments must add up to net sales": "各付款方式合计须等于净销售额",
    "Keep current photo": "保留当前照片", "Expenses today": "今日费用", "required for \"Others\"": "“其他”类必填",
    "No KPI fields set up for this shop yet.": "此店铺尚未设置 KPI 字段。",
    "Please do not enter customers' personal details (PDPA).": "请勿填写顾客个人资料（PDPA）。",
    "Above S$": "超过 S$", "needs Finance approval; above S$": "需财务审批；超过 S$", "needs the GM.": "需总经理审批。",
    "approved": "已批准", "pending": "待审批", "rejected": "已驳回", "void": "已作废", "Amount": "金额", "Mode": "付款方式",
    "Receipt": "收据", "By": "提交人", "missing": "缺失", "items": "项", "total": "合计", "import": "导入",
    # dashboards
    "Sales today": "今日销售", "vs same day last week": "对比上周同日", "On time, last 7 days": "近 7 天准时率",
    "Target 100% by": "目标 100%，截止", "Approvals waiting": "待审批", "Review →": "去审批 →", "Sales by shop": "各店销售",
    "Same day last wk": "上周同日", "Change": "变化", "Yet to submit": "未提交", "yet to submit": "家未提交", "All in": "全部已交",
    "Today by shop": "今日各店销售", "Month to date vs budget": "本月累计对比预算", "Open alerts": "未处理警报",
    "All alerts →": "全部警报 →", "Weekly dashboard": "周报", "← Previous week": "← 上一周", "Next week →": "下一周 →",
    "Sales": "销售额", "Profit": "利润", "Staff hours": "员工工时", "Marketing spend": "营销支出", "On-time submissions": "准时提交率",
    "vs last week": "对比上周", "after all recorded costs": "扣除全部已记录成本", "Shop ranking": "店铺排名",
    "vs last wk": "对比上周", "Weekday": "工作日", "Weekend": "周末", "COGS %": "销货成本 %", "Staff %": "人工成本 %",
    "Group sales trend (8 weeks)": "集团销售趋势（8 周）", "This week by shop": "本周各店销售", "People": "人员",
    "Avg staff/day": "日均员工", "Sales / staff": "人均销售", "Absence days": "缺勤天数", "Venue & marketing": "场地与营销",
    "Highlights": "要点", "Line": "项目", "% of rev": "占收入 %", "Company": "公司", "All companies + group": "全部公司 + 集团",
    "Export expenses CSV": "导出费用 CSV", "Actual by company": "各公司实际", "and combined group": "及集团合并",
    "Budget vs actual": "预算对比实际", "Budget": "预算", "Actual": "实际", "Variance": "差异", "Var %": "差异 %",
    "Revenue": "收入", "Cost of goods sold": "销货成本", "Gross profit": "毛利", "Rent": "租金", "Utilities": "水电网",
    "Professional fees": "专业费用", "Systems": "系统", "Others": "其他", "Total expenses": "费用合计", "Net profit": "净利润",
    "locked": "已锁账", "open": "未锁", "Edit KPIs & targets": "修改 KPI 与目标", "KPI": "KPI", "Baseline": "基准", "Floor": "底线",
    "Target": "目标", "Green": "绿", "Amber": "黄", "Red": "红", "No target": "无目标", "↓ lower is better": "↓ 越低越好",
    "Marketing & leads": "市场营销与潜在客户", "+ Record ad / KOL spend": "+ 记录广告 / KOL 支出", "Enter leads": "填写潜在客户",
    "Spend": "支出", "of which KOL": "其中 KOL", "Leads": "潜在客户", "Cost / lead": "单个潜客成本", "Cost / customer": "单个顾客成本",
    "Sales per S$1": "每 S$1 带来销售", "Influencer codes": "网红优惠码", "Visit-to-paid conversion": "到店转付费率",
    "Check-to-paid conversion": "检测转付费率", "Group summary": "集团总览", "to date": "至今", "Sales month to date": "本月累计销售",
    "Profit month to date": "本月累计利润", "Last month sales": "上月销售", "Group sales, last 6 months": "集团近 6 个月销售",
    "By shop (month to date)": "各店（本月累计）", "Sales · profit": "销售 · 利润", "KPI status": "KPI 状态", "Read-only group view.": "集团只读视图。",
    "Operations log": "营运日志", "include quiet days": "包含无事件的日子", "Equipment / stock": "设备 / 库存",
    # approvals, alerts, inbox, month-end
    "Expense approvals": "费用审批", "Nothing waiting for approval.": "暂无待审批事项。", "Approve": "批准", "Reject": "驳回",
    "Waiting for the GM": "等待总经理审批", "Submitted by": "提交人", "needs": "需要", "approval": "审批", "receipt": "收据",
    "Run checks now": "立即检查", "also send the weekly dashboard e-mail now": "同时立即发送周报邮件", "When": "时间", "Type": "类型",
    "Alert": "警报", "Resolve": "处理", "resolved": "已处理", "No messages.": "暂无消息。", "Show everyone's messages": "显示所有人的消息",
    "Month-end close": "月结", "Checklist": "清单", "Stock count": "库存盘点", "Payroll & CPF": "薪资与公积金",
    "Unrecorded expenses entered": "已补录未记录费用", "Bank / cash reconciliation": "银行 / 现金对账", "mark done": "标记完成",
    "✓ done": "✓ 已完成", "Reconciliation checks": "对账检查", "Days submitted": "已提交天数", "Pending approvals": "待审批",
    "Payables": "应付款", "Cash takings": "现金收入", "Difference": "差额", "Post payroll from staff list": "按员工名单入账薪资",
    "Locked months": "已锁账月份", "none": "无", "Unlock": "解锁",
    # admin-ish
    "Export for bookkeeping": "导出记账数据", "Data": "数据", "Month (blank = all)": "月份（留空 = 全部）",
    "Company (blank = group)": "公司（留空 = 集团）", "All companies": "全部公司", "Download CSV": "下载 CSV",
    "Download a full database backup": "下载完整数据库备份", "Name": "姓名", "Position": "职位", "Monthly pay": "月薪", "Hourly": "时薪",
    "CPF %": "公积金 %", "Commission %": "佣金 %", "Active": "在职", "Add staff": "添加员工", "Hourly rate": "时薪",
    "Employer CPF %": "雇主公积金 %", "Monthly budgets": "月度预算", "Save budget": "保存预算", "3-month baseline sales": "3 个月基准销售",
    "Controls": "控制", "Shops & companies": "店铺与公司", "Users & access": "用户与权限", "Chart of accounts": "会计科目",
    "KPI fields & targets": "KPI 字段与目标", "Save controls": "保存控制", "Input fields": "输入字段", "Targets (scorecard)": "目标（记分卡）",
    "Two-factor login": "双重验证登录", "Change password": "修改密码", "Current password": "当前密码", "On": "已开启",
    "Turn off": "关闭", "Turn on two-factor": "开启双重验证", "Action": "操作", "User": "用户", "Record": "记录", "details": "详情",
    "Before → after": "修改前 → 修改后", "Table": "数据表", "Export CSV": "导出 CSV",
    # sign-in pages
    "Verify": "验证", "AANDJ Shop Reporting": "AANDJ 店铺报表", "Shop Reporting": "店铺报表",
    "You don't have access to this page": "您无权查看此页面", "Page not found": "页面不存在",
}

_PROTECT = re.compile(r"(<(script|style|pre|textarea)\b.*?</\2>|<option(?![^>]*\bvalue=)[^>]*>.*?</option>|<[^>]+>)", re.S | re.I)
_PHRASES = sorted((k for k in ZH if " " in k.strip() or len(k) > 12), key=len, reverse=True)

ZH.update({
    # seeded KPI field labels
    "Lunch covers": "午餐人数", "Dinner covers": "晚餐人数", "Dine-in sales": "堂食销售", "Takeaway sales": "外带销售",
    "Resident orders": "住户订单", "Delivery-app sales": "外卖平台销售", "Wastage value": "损耗金额", "Best dish": "最畅销菜品",
    "Worst dish": "最滞销菜品", "New Google reviews": "新增 Google 评价", "Google rating": "Google 评分",
    "Leads – social media": "潜客 – 社交媒体", "Leads – walk-in": "潜客 – 到店", "Leads – referral": "潜客 – 推荐",
    "Consultations": "咨询次数", "Packages sold": "售出套餐", "Prepaid packages sold (value)": "预付套餐售出（金额）",
    "Prepaid packages redeemed (value)": "预付套餐消耗（金额）", "Treatment room hours used": "护理室使用时数",
    "Treatment room hours available": "护理室可用时数", "Therapist commission": "美容师佣金", "Treatments done": "完成护理次数",
    "Rebookings": "再次预约", "Room utilisation %": "护理室使用率 %", "Rebooking rate %": "再预约率 %",
    "Leads – influencer codes": "潜客 – 网红优惠码", "Leads – other sources": "潜客 – 其他来源", "Influencer codes used": "使用的网红优惠码",
    "Bookings": "预约", "Show-ups": "到店", "Paid visits": "付费到店", "Referrals": "推荐", "Influencer share paid": "已付网红分成",
    "Show-up rate %": "到店率 %", "Visit-to-paid conversion %": "到店转付费率 %", "Enquiries": "询问", "Site visits": "实地看场",
    "Confirmed event bookings": "确认活动预订", "Rooms let": "已出租房间", "Rent collected": "已收租金", "Rent payable": "应付租金",
    "Space hours booked": "场地已订时数", "Space hours available": "场地可用时数", "Prospect pipeline value": "潜在客户管道金额",
    "Prospect pipeline notes": "潜在客户管道备注", "Rent collected vs payable %": "租金收取率 %", "Space utilisation %": "场地使用率 %",
    "AI health checks done": "AI 健康检测次数", "Paid after check": "检测后付费", "Treatment sessions": "疗程次数",
    "Memberships sold": "售出会员", "Package sales (value)": "套餐销售（金额）", "Active members": "有效会员",
    "Repeat customers": "回头客", "Customer feedback score (1–5)": "顾客评分（1–5）", "Customer feedback notes": "顾客反馈备注",
    "Check-to-paid conversion %": "检测转付费率 %",
    "PayNow": "PayNow", "Bank transfer": "银行转账", "GIRO": "GIRO 自动转账", "Platform deduction": "平台扣款", "Company card": "公司卡",
    # built-in scorecard metrics and longer hints
    "Food / product cost %": "食材 / 产品成本 %", "Staff cost %": "人工成本 %", "Rent as % of sales": "租金占销售 %",
    "Marketing cost per customer": "单个顾客营销成本", "Gross margin %": "毛利率 %",
    "Reminders, alerts, approval requests and the Monday dashboard e-mail.": "提醒、警报、审批请求和周一周报邮件。",
    "E-mail delivery is off (no SMTP server configured) – messages are shown here.": "未配置邮件服务器，消息显示在此处。",
    "Also delivered by e-mail.": "同时通过邮件发送。",
    "Green = at or better than target · Amber = between floor and target · Red = worse than floor. Monthly totals (month-to-date for the current month).":
        "绿 = 达到或优于目标 · 黄 = 介于底线和目标之间 · 红 = 低于底线。按月合计（本月为月初至今）。",
    "Revenue = net sales from daily submissions. Expenses include approved and pending items (rejected and voided excluded). Green = favourable.":
        "收入 = 每日提交的净销售额。费用包含已批准和待审批项目（不含已驳回和已作废）。绿色 = 有利。",
    "Every change is recorded with before / after values. The log itself cannot be edited or deleted.": "每次修改都会记录修改前后的值，记录本身不能修改或删除。",
    "Your account becomes active once the GM approves it.": "总经理审批后账户生效。",
})
ZH.update({
    "late submission": "逾期未交", "sales drop": "销售下滑", "month close late": "月结逾期", "over budget": "超出预算",
    "food cost": "食材成本", "venue rent": "场地租金", "alert": "警报", "reminder": "提醒", "weekly": "周报", "approval": "审批",
    "signup": "注册申请", "month_close": "月结", "gm_item": "总经理事项", "approval_result": "审批结果", "monthly_pnl": "月度损益",
    " · alert": " · 警报",
    " · reminder": " · 提醒",
    " · weekly": " · 周报",
    " · approval": " · 审批",
    " · signup": " · 注册申请",
    " · month_close": " · 月结",
    " · gm_item": " · 总经理事项",
    " · approval_result": " · 审批结果",
    " · monthly_pnl": " · 月度损益",
    "full-time": "全职", "part-time": "兼职", "Budget ": "预算 ", "items · total": "项 · 合计", " · to ": " · 发给 ",
    "Covers lunch ": "午餐人数 ", " / dinner ": " / 晚餐 ", " · delivery ": " · 外卖 ", " · wastage ": " · 损耗 ", " · rating ": " · 评分 ",
    "Leads ": "潜客 ", " · consultations ": " · 咨询 ", " · packages ": " · 套餐 ", " · room use ": " · 护理室使用率 ",
    " · rebooking ": " · 再预约率 ", "Influencer leads ": "网红潜客 ", " · bookings ": " · 预约 ", " · show-up ": " · 到店率 ",
    " · visit→paid ": " · 到店转付费 ", " · referrals ": " · 推荐 ", "Enquiries ": "询问 ", " · site visits ": " · 看场 ",
    " · events ": " · 活动 ", " · rooms let ": " · 出租房间 ", " · rent collected ": " · 已收租金 ", " · utilisation ": " · 使用率 ",
    "AI checks ": "AI 检测 ", " · check→paid ": " · 检测转付费 ", " · sessions ": " · 疗程 ", " · memberships ": " · 会员 ",
    " · repeat ": " · 回头客 ", " · marketing ": " · 营销 ", "Companies: ": "公司：", " not submitted by ": " 未在以下时间前提交：",
    ": daily sales for ": "：日报 ", " e-mailed": " 已发邮件",
})
_PHRASES = sorted((k for k in ZH if " " in k or len(k) > 12), key=len, reverse=True)


def tr(s, lang):
    return ZH.get(s, s) if lang == "zh" else s


def _text(t):
    if "&" in t:  # match labels containing &, then re-escape
        return _html.escape(_text_plain(_html.unescape(t)), quote=False)
    return _text_plain(t)


def _text_plain(t):
    s = t.strip()
    if not s:
        return t
    if s in ZH:  # whole text node is one label
        return t.replace(s, ZH[s])
    for p in _PHRASES:  # longer phrases inside mixed text, e.g. "-8.3% vs same day last week"
        if p in t:
            t = t.replace(p, ZH[p])
    return t


def translate_html(html):
    out, pos = [], 0
    for m in _PROTECT.finditer(html):
        out.append(_text(html[pos:m.start()]))
        tag = m.group(0)
        if tag.lower().startswith("<title"):
            tag = _text(tag)
        out.append(tag)
        pos = m.end()
    out.append(_text(html[pos:]))
    return "".join(out)
