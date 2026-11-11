#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fulfill_plan.py — 仓捷运 · 履约一键出单（待发清单 / 拣货 / 质检打包 / 库存警戒线 / 物流比价 / 异常预案）

它解决发货每天最要命的三件事：
    1. 哪单快超 48 小时了           → 按付款时间算倒计时，超时单排最前
    2. 这单该拣什么、怎么包、拍什么 → 按品类必查项 + 8 步打包 + 一镜到底留证
    3. 缺货了 / 破损了 / 卡在途中了 → 按异常代码直接给动作、SLA、话术

边界（和 design_brief / content_plan / service_reply 一个原则）：
    本脚本**不编造单号、地址、库存、轨迹**。输入里没有的一律留【】占位或标「占位」。
    库存只有你填了 sold_7d 才推算可售天数，没填就报占位——不猜销量。

用法：
    # 1) 出今日履约单（最常用）
    python fulfill_plan.py --input orders.json --out fulfill_plan.md

    # 2) 单件试算：某个 SKU 该用什么物流、多少钱
    python fulfill_plan.py --sku "二手 Switch OLED 掌机" --weight 1.2 \
        --amount 1799 --province 广东

    # 3) 发货文案自查（详情页/私聊里那些时效承诺，发之前过一遍）
    python fulfill_plan.py --check "现货秒发 当天发货 签收即视为验收无误"

依赖：仅标准库。规则读 fulfill_rules.json，品类必查项与违规词表复用 design_rules.json。
"""

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta

import design_brief as db

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, "fulfill_rules.json")
TEMPLATE_HINT = "orders.template.json"

R = {}
PH = "【%s】"
NOW = None


# ---------------------------------------------------------------- 基础

def load_rules():
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def num(v):
    """转 float，转不了返回 None（不瞎猜）。"""
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("¥", "").strip())
    except (TypeError, ValueError):
        return None


def money(v):
    return db.money(v)


def moneyx(v):
    """运费要带小数：续重 ¥2.5 显示成 ¥2 会把比价算错。"""
    if v is None:
        return "¥—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "¥—"
    if abs(f - round(f)) > 1e-9:
        return "¥%s" % format(f, ",.2f").rstrip("0").rstrip(".")
    return "¥%s" % format(f, ",.0f")


def zh_clean(s):
    """去掉中文之间的多余空格。"""
    s = re.sub(r"(?<=[\u4e00-\u9fa5]) +(?=[\u4e00-\u9fa5])", "", s)
    s = re.sub(r"(?<=[\u4e00-\u9fa5]) +(?=【)", "", s)
    s = re.sub(r"(?<=】) +(?=[\u4e00-\u9fa5])", "", s)
    return s.strip()


def parse_dt(s):
    """尽量解析时间，失败返回 None（不用当前时间冒充）。"""
    if not s:
        return None
    s = str(s).strip().replace("/", "-").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%m-%d %H:%M", "%m-%d"):
        try:
            d = datetime.strptime(s, fmt)
            if fmt.startswith("%m"):
                d = d.replace(year=NOW.year)
            return d
        except ValueError:
            continue
    return None


def fmt_dt(d):
    if d is None:
        return "—"
    return d.strftime("%m-%d %H:%M")


def hours_between(a, b):
    return (b - a).total_seconds() / 3600.0


def cat_of(*texts):
    return db.pick_category(*texts)


# ---------------------------------------------------------------- 订单

def order_hours_left(o):
    """返回 (剩余小时, 已过小时, 是否超时)。付款时间不明则全 None。"""
    paid = parse_dt(o.get("paid_at"))
    if paid is None:
        return None, None, None
    limit = R["sla"]["ship_within_hours"]
    deadline = paid + timedelta(hours=limit)
    left = hours_between(NOW, deadline)
    return left, hours_between(paid, NOW), left < 0


def risk_of(left, shipped):
    if shipped:
        return "✅ 已交寄"
    if left is None:
        return "⚪ 付款时间未填"
    if left < 0:
        h = int(-left)
        return "🔴 已超时 %s" % ("<1 h" if h == 0 else "%d h" % h)
    if left <= R["sla"]["warn_hours_left"]:
        return "🟠 剩 %d h" % int(left)
    if left <= R["sla"]["urge_hours_left"]:
        return "🟡 剩 %d h" % int(left)
    return "🟢 剩 %d h" % int(left)


def orders_table(orders):
    rows = []
    for o in orders:
        left, passed, overdue = order_hours_left(o)
        shipped = bool(o.get("tracking") or o.get("shipped_at"))
        rows.append({
            "o": o, "left": left, "passed": passed,
            "overdue": overdue, "shipped": shipped,
            "risk": risk_of(left, shipped),
            "sort": (1 if shipped else 0, left if left is not None else 9999),
        })
    rows.sort(key=lambda r: r["sort"])
    return rows


def block_orders(rows, orders):
    out = ["## 一、今日待发清单", ""]
    if not orders:
        out.append("> 今天没有待发订单。把 `orders.json` 里的 orders 填上再跑。")
        out.append("")
        return out

    overdue = sum(1 for r in rows if r["overdue"])
    unshipped = sum(1 for r in rows if not r["shipped"])
    limit = R["sla"]["ship_within_hours"]
    out.append("> 口径：倒计时 = 付款时间 + **%d 小时**（承诺的是「发出」，不是「到达」）。"
               "共 %d 单，未交寄 %d 单，已超时 **%d** 单。"
               % (limit, len(orders), unshipped, overdue))
    out.append("")
    if overdue:
        out.append("> 🔴 **超时单先处理**：先给买家一句说明 + 补偿方案，再安排发货。等买家来问，性质就变了。")
        out.append("")

    out.append("| 订单号 | SKU | 数量 | 付款时间 | 已过 | 状态 | 收件地 |")
    out.append("|---|---|---|---|---|---|---|")
    for r in rows:
        o = r["o"]
        passed = "—" if r["passed"] is None else "%d h" % int(r["passed"])
        addr = zh_clean(" ".join(x for x in [o.get("province"), o.get("city")] if x)) or PH % "省 市"
        out.append("| %s | %s | %s | %s | %s | %s | %s |"
                   % (o.get("order_id") or PH % "订单号",
                      o.get("sku") or PH % "SKU",
                      o.get("qty") or 1,
                      fmt_dt(parse_dt(o.get("paid_at"))),
                      passed, r["risk"], addr))
    out.append("")

    # 今日动作建议
    out.append("**今天必须做的三件事**")
    if overdue:
        out.append("1. 🔴 先把 %d 个超时单的说明发出去：主动说明 + 给补偿方案（小额红包 / 包邮 / 赠品），"
                   "别等买家来问" % overdue)
    else:
        out.append("1. 无超时单，按付款顺序交寄即可")
    hold = [r for r in rows if r["left"] is not None and 0 <= r["left"] <= R["sla"]["warn_hours_left"]]
    if hold:
        out.append("2. 🟠 有 %d 单进入 12 小时红线，今天必须出门" % len(hold))
    else:
        out.append("2. 无 12 小时红线单")
    out.append("3. 每个包裹都要一镜到底录像（全貌→序列号→装箱→封箱贴单），不剪辑")
    out.append("")
    return out


# ---------------------------------------------------------------- 拣货

def demand_by_sku(orders):
    d = {}
    for o in orders:
        if o.get("tracking") or o.get("shipped_at"):
            continue
        sku = o.get("sku") or PH % "SKU"
        d[sku] = d.get(sku, 0) + int(num(o.get("qty")) or 1)
    return d


def stock_map(stock):
    m = {}
    for s in stock:
        sku = s.get("sku")
        if sku:
            m[sku] = s
    return m


def block_pick(orders, stock):
    out = ["## 二、拣货单", ""]
    demand = demand_by_sku(orders)
    if not demand:
        out.append("> 没有待拣订单。")
        out.append("")
        return out, demand

    sm = stock_map(stock)
    out.append("> 只统计**未交寄**订单。库位空着就先去贴库位标签——找货时间是发货里最大的隐性成本。")
    out.append("")
    out.append("| SKU | 需拣 | 库位 | 在手库存 | 拣完剩 | 判定 |")
    out.append("|---|---|---|---|---|---|")
    shortages = []
    for sku, qty in sorted(demand.items(), key=lambda kv: -kv[1]):
        s = sm.get(sku, {})
        on_hand = num(s.get("on_hand"))
        loc = s.get("loc") or PH % "库位"
        if on_hand is None:
            rest, verdict = "—", "⚪ 库存未填"
        else:
            rest = on_hand - qty
            if rest < 0:
                verdict = "🔴 缺 %d 件" % int(-rest)
                shortages.append((sku, int(-rest)))
            elif rest < (num(s.get("safety")) or 0):
                verdict = "🟠 低于警戒线"
            else:
                verdict = "✅ 可发"
        out.append("| %s | %d | %s | %s | %s | %s |"
                   % (sku, qty, loc,
                      "—" if on_hand is None else "%d" % on_hand,
                      rest if isinstance(rest, str) else "%d" % rest,
                      verdict))
    out.append("")
    if shortages:
        out.append("> 🔴 **超卖预警**：%s。先停售这些 SKU，再按异常预案 **OOS** 处理——"
                   "继续接单只会多几个差评。"
                   % "、".join("%s 缺 %d 件" % (k, v) for k, v in shortages))
        out.append("")
    return out, demand


# ---------------------------------------------------------------- 质检打包

def block_qc(orders, demand):
    out = ["## 三、质检打包核对表", ""]
    if not demand:
        out.append("> 无待发商品。")
        out.append("")
        return out

    out.append("> 每一项都要打勾再封箱。**先拍照录像再封箱**，封完再拆就说不清了。")
    out.append("")
    out.append("**通用打包 8 步（每个包裹都过一遍）**")
    out.append("")
    out.append("| # | 动作 | 标准 | 为什么 |")
    out.append("|---|---|---|---|")
    for s in R["packing_base"]:
        out.append("| %d | %s | %s | %s |" % (s["no"], s["name"], s["spec"], s["why"]))
    out.append("")

    for sku, qty in sorted(demand.items(), key=lambda kv: -kv[1]):
        cat_name, cat_rule = cat_of(sku)
        must = cat_rule.get("must_state", [])
        out.append("### %s　×%d　（品类：%s）" % (sku, qty, cat_name))
        out.append("")
        out.append("**本品类必须核对（缺一条就等着退货）**")
        for m in must:
            out.append("- [ ] %s" % m)
        out.append("")
        risks = cat_rule.get("risks", [])
        if risks:
            out.append("**本品类高发纠纷**：%s" % "；".join(risks))
            out.append("")
    return out


# ---------------------------------------------------------------- 库存

def block_stock(stock, demand):
    out = ["## 四、库存警戒线表", ""]
    if not stock:
        out.append("> 库存表为空。填 `stock` 字段（sku / on_hand / safety / in_transit / sold_7d）后重跑。")
        out.append("")
        return out

    cfg = R["stock_alert"]
    out.append("> 可售天数 = 在手库存 ÷ 近 7 日日均销量。**没填 sold_7d 就不推算**，标「占位」——"
               "凭感觉估销量，警戒线就是假的。")
    out.append("")
    out.append("| SKU | 在手 | 警戒线 | 在途 | 到货预计 | 近7日销 | 可售天数 | 判定 | 动作 |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    alerts = []
    for s in stock:
        sku = s.get("sku") or PH % "SKU"
        on_hand = num(s.get("on_hand"))
        safety = num(s.get("safety"))
        transit = num(s.get("in_transit"))
        sold7 = num(s.get("sold_7d"))
        eta = s.get("eta_days")
        need = demand.get(sku, 0)

        if sold7 and on_hand is not None:
            days = on_hand / (sold7 / 7.0)
            days_txt = "%.1f 天" % days
            if days <= cfg["days_danger"]:
                verdict, action = "🔴 危险", "立即补货 / 停售"
            elif days <= cfg["days_warn"]:
                verdict, action = "🟠 偏低", "今天下补货单"
            elif days <= cfg["days_watch"]:
                verdict, action = "🟡 关注", "排进本周补货"
            else:
                verdict, action = "🟢 充足", "正常"
            if need and on_hand is not None and on_hand < need:
                verdict, action = "🔴 不够发", "停售 + 走 OOS 预案"
        else:
            days_txt = PH % "可售天数（缺 sold_7d）"
            if on_hand is not None and safety is not None:
                verdict = "🟠 低于警戒线" if on_hand < safety else "⚪ 缺销量数据"
            else:
                verdict = "⚪ 数据不全"
            action = "补 sold_7d 后重算"

        if verdict.startswith("🔴") or verdict.startswith("🟠"):
            alerts.append(sku)
        out.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                   % (sku,
                      "—" if on_hand is None else "%d" % on_hand,
                      "—" if safety is None else "%d" % safety,
                      "—" if transit is None else "%d" % transit,
                      ("%s 天" % eta) if eta not in (None, "") else "—",
                      "—" if sold7 is None else "%d" % sold7,
                      days_txt, verdict, action))
    out.append("")
    if alerts:
        out.append("> 需要动的 SKU：**%s**。补货单今天下，别等卖完再找货。"
                   % "、".join(alerts))
        out.append("")
    return out


# ---------------------------------------------------------------- 物流

def is_remote(province):
    if not province:
        return False
    return any(r in province for r in R["remote_regions"])


def fragile(sku):
    return any(k in (sku or "") for k in R["fragile_keywords"])


def cost_of(carrier, weight):
    w = weight if weight and weight > 0 else None
    if w is None:
        return None
    extra_kg = max(0, math.ceil(w - 1))
    return carrier["first"] + extra_kg * carrier["extra"]


def pick_carrier(province, sku, weight, amount, note):
    cfg = R["pick_logistics"]
    carriers = {c["name"]: c for c in R["logistics"]}
    reason = []

    if is_remote(province):
        return carriers["邮政 EMS"], "收件地在偏远地区（%s），通达系常不派送" % province
    if amount is not None and amount >= cfg["high_value"]:
        reason.append("订单额 %s ≥ %s，走可保价的顺丰" % (money(amount), money(cfg["high_value"])))
    if fragile(sku):
        reason.append("品类含易碎关键词（屏/玻璃/镜头等）")
    if any(k in (note or "") for k in cfg["urgent_keywords"]):
        reason.append("买家留言有时效要求")
    if reason:
        return carriers["顺丰标快"], "；".join(reason)
    if weight is not None and weight >= cfg["heavy_kg"]:
        return carriers["德邦快递"], "重量 %.1fkg ≥ %skg，大件按德邦计费更省" % (weight, cfg["heavy_kg"])

    # 常规件取最便宜
    ok = [c for c in R["logistics"] if c["name"] not in ("顺丰特快", "顺丰标快", "德邦快递", "邮政 EMS")]
    cheapest = min(ok, key=lambda c: (c["first"], c["extra"]))
    return cheapest, "常规件取最低价承运商"


def block_logistics(orders, stock):
    out = ["## 五、物流方案与比价", ""]
    if not orders:
        out.append("> 无订单。")
        out.append("")
        return out

    sm = stock_map(stock)
    out.append("> ⚠️ 下表运费为**参考价**（首重 1kg 口径），实际以当地网点报价为准。"
               "别拿这张表去跟买家承诺运费。")
    out.append("")
    out.append("| 订单号 | 品类 | 重量 | 收件地 | 建议承运 | 参考运费 | 时效 | 理由 |")
    out.append("|---|---|---|---|---|---|---|---|")
    total = 0.0
    unknown = 0
    for o in orders:
        if o.get("tracking") or o.get("shipped_at"):
            continue
        sku = o.get("sku") or ""
        cat_name, _ = cat_of(sku)
        w = num(o.get("weight_kg"))
        c, why = pick_carrier(o.get("province"), sku, w, num(o.get("amount")), o.get("note"))
        cost = cost_of(c, w)
        if cost is None:
            unknown += 1
        else:
            total += cost
        out.append("| %s | %s | %s | %s | **%s** | %s | %s | %s |"
                   % (o.get("order_id") or PH % "订单号",
                      cat_name,
                      "%.2f kg" % w if w else PH % "重量",
                      zh_clean(o.get("province") or "") or PH % "省",
                      c["name"],
                      moneyx(cost) if cost is not None else PH % "运费",
                      c["eta"],
                      why))
    out.append("")
    if unknown:
        out.append("> ⚪ **%d 单缺重量**，运费未计入合计。重量必须称——估重估低了，运费自己吞。"
                   % unknown)
    out.append("> 未交寄订单运费合计（按已填重量）：**%s**" % moneyx(total))
    out.append("")

    # 比价表
    out.append("**常用承运商参考价（1kg 首重 / 续重）**")
    out.append("")
    out.append("| 承运 | 首重 | 续重/kg | 时效 | 适合 | 备注 |")
    out.append("|---|---|---|---|---|---|")
    for c in R["logistics"]:
        out.append("| %s | %s | %s | %s | %s | %s |"
                   % (c["name"], moneyx(c["first"]), moneyx(c["extra"]), c["eta"], c["best"], c["note"]))
    out.append("")
    return out


# ---------------------------------------------------------------- 异常预案

def block_exceptions(orders, demand, stock):
    out = ["## 六、异常处理预案", ""]
    out.append("> 按**触发条件**查表，别临场想。每条都给了首响时限、动作顺序、可发话术、责任角色。")
    out.append("")

    # 当前命中提示
    hits = []
    sm = stock_map(stock)
    for sku, qty in demand.items():
        s = sm.get(sku, {})
        on_hand = num(s.get("on_hand"))
        if on_hand is not None and on_hand < qty:
            hits.append("**OOS 缺货**：%s 需 %d 件，在手 %d 件" % (sku, qty, on_hand))
    for o in orders:
        left, _, overdue = order_hours_left(o)
        if overdue and not (o.get("tracking") or o.get("shipped_at")):
            hits.append("**超时**：%s 已超 %d 小时未交寄" % (o.get("order_id") or "?", int(-left)))
        if not o.get("province") or not o.get("city"):
            hits.append("**ADDR 地址不详**：%s 缺省/市" % (o.get("order_id") or "?"))
    if hits:
        out.append("### 本次扫描命中")
        for h in hits:
            out.append("- %s" % h)
        out.append("")

    for e in R["exceptions"]:
        out.append("### [%s] %s" % (e["code"], e["name"]))
        out.append("- **触发**：%s　｜　**首响**：%s" % (e["trigger"], e["sla"]))
        out.append("- **动作**：")
        for i, s in enumerate(e["steps"], 1):
            out.append("  %d. %s" % (i, s))
        out.append("- **可发话术**（≤60 字，`【】` 填实）：`%s`" % zh_clean(e["reply"]))
        out.append("- **责任**：%s" % e["owner"])
        out.append("")
    return out


# ---------------------------------------------------------------- 承诺与自查

def block_promise():
    p = R["promise_copy"]
    out = ["## 七、%s" % p["title"], ""]
    for i, r in enumerate(p["rules"], 1):
        out.append("%d. %s" % (i, r))
    out.append("")
    out.append("### 每日自查 7 条")
    out.append("")
    for c in R["checklist_daily"]:
        out.append("- [ ] %s" % c)
    out.append("")
    return out


def scan_claims(text):
    """扫描发货承诺违规词。返回 [(级别, 分类, 词)]。"""
    hits, seen = [], set()
    for sev in ("error", "warn"):
        for group, words in R["ship_claims"][sev].items():
            for w in words:
                if w in text and (sev, w) not in seen:
                    seen.add((sev, w))
                    hits.append((sev, group, w))
    return hits


def claim_fix(sev, group, word):
    if group == "绝对时效":
        return "改成「付款后 48 小时内发出」——承诺交寄时间，不承诺到达时间"
    if group == "虚假库存":
        return "无货源代发就删掉，写「48 小时内发出」；硬写现货，缺货时就是虚假宣传"
    if group == "责任转嫁":
        return "删掉。这类单方免责条款在平台规则下无效，写了反而成为违规证据"
    if group == "模糊时效":
        return "改成可核对的数字：「48 小时内发出」"
    if group == "过度承诺":
        return "改成「泡沫+护角包装，破损按平台规则处理」，别打包票"
    if group == "口头包赔":
        return "承诺要能兑现：写清「破损凭开箱视频补发/退款」，比空口包赔可信"
    return "核对后再决定"


def block_claims(all_text, orders):
    out = ["## 八、发货文案合规自查", ""]
    hits = scan_claims(all_text)
    # 叠加广告法通用违规词（复用 design_rules）
    ad = db.scan_ban(all_text)
    out.append("> 扫描对象：订单备注 + 本单生成的对外文案。详情页与私聊话术请另外单独 `--check`。")
    out.append("")
    if not hits and not ad:
        out.append("- ✅ 未命中时效违规词 / 广告法违规词")
    for sev, group, word in hits:
        mark = "🔴 硬违规" if sev == "error" else "🟡 需改"
        out.append("- %s ｜[%s] `%s` → %s" % (mark, group, word, claim_fix(sev, group, word)))
    for sev, group, word in ad:
        mark = "🔴 硬违规" if sev == "error" else "🟡 需核对"
        out.append("- %s ｜[%s] `%s` → %s" % (mark, group, word, db.suggest(sev, group, word)))
    out.append("")
    return out


# ---------------------------------------------------------------- 样例

SAMPLE = {
    "shop": "闲鱼小店（样例）",
    "orders": [
        {"order_id": "XY20261111001", "sku": "二手 Switch OLED 掌机 白色",
         "qty": 1, "paid_at": "2026-11-11 09:20", "province": "广东", "city": "深圳",
         "amount": 1799, "weight_kg": 1.2, "note": "周末前能到吗", "photos": True},
        {"order_id": "XY20261111002", "sku": "罗技 MX Master 3S 鼠标",
         "qty": 2, "paid_at": "2026-11-11 14:05", "province": "新疆", "city": "乌鲁木齐",
         "amount": 429, "weight_kg": 0.6, "note": ""},
        {"order_id": "XY20261111003", "sku": "iPhone 13 128G 午夜色",
         "qty": 1, "paid_at": "2026-11-10 21:40", "province": "江苏", "city": "南京",
         "amount": 2299, "weight_kg": 0.5, "note": "上班时间送"},
        {"order_id": "XY20261111004", "sku": "小米空气炸锅 4L",
         "qty": 1, "paid_at": "2026-11-11 20:30", "province": "", "city": "",
         "amount": 219, "weight_kg": 4.8, "note": ""},
    ],
    "stock": [
        {"sku": "二手 Switch OLED 掌机 白色", "on_hand": 3, "safety": 2, "in_transit": 2,
         "eta_days": 3, "sold_7d": 6, "loc": "A-03"},
        {"sku": "罗技 MX Master 3S 鼠标", "on_hand": 1, "safety": 2, "in_transit": 0,
         "eta_days": None, "sold_7d": 5, "loc": "B-11"},
        {"sku": "iPhone 13 128G 午夜色", "on_hand": 2, "safety": 1, "in_transit": 1,
         "eta_days": 2, "sold_7d": 3, "loc": "C-01"},
        {"sku": "小米空气炸锅 4L", "on_hand": 0, "safety": 1, "in_transit": 4,
         "eta_days": 2, "sold_7d": 9, "loc": "D-07"},
    ],
}


# ---------------------------------------------------------------- 主流程

def build(data, sample=False):
    orders = data.get("orders", []) if isinstance(data, dict) else data
    stock = data.get("stock", []) if isinstance(data, dict) else []

    rows = orders_table(orders)
    demand = demand_by_sku(orders)

    out = ["# 履约单 · 仓捷运", "",
           "> 生成器：`fulfill_plan.py`　规则库：`fulfill_rules.json`（品类必查项复用 `design_rules.json`）",
           "> 基准时间：%s　｜　店铺：%s" % (NOW.strftime("%Y-%m-%d %H:%M"), data.get("shop") or "—"),
           "> 口径：脚本**不编造单号 / 地址 / 库存 / 轨迹**。缺数据一律留【】或标占位。"
           "运费为参考价，以当地网点为准。", ""]
    if sample:
        out.insert(2, "> ⚠️ **当前为样例数据**：未检测到 `%s`，下面的订单/库存全是演示值，不可当真实履约单执行。"
                      % TEMPLATE_HINT)
        out.insert(3, "")

    out.append("**总览**：待发 %d 单 ｜ 超时 %d 单 ｜ 涉及 SKU %d 个 ｜ 缺货 SKU %d 个"
               % (sum(1 for r in rows if not r["shipped"]),
                  sum(1 for r in rows if r["overdue"]),
                  len(demand),
                  sum(1 for sku, q in demand.items()
                      if num(stock_map(stock).get(sku, {}).get("on_hand")) is not None
                      and num(stock_map(stock).get(sku, {}).get("on_hand")) < q)))
    out.append("")
    out.append("---")
    out.append("")

    out.extend(block_orders(rows, orders))
    pick, _ = block_pick(orders, stock)
    out.extend(pick)
    out.extend(block_qc(orders, demand))
    out.extend(block_stock(stock, demand))
    out.extend(block_logistics(orders, stock))
    out.extend(block_exceptions(orders, demand, stock))
    out.extend(block_promise())

    blob = " ".join(zh_clean(o.get("note") or "") for o in orders)
    out.extend(block_claims(blob, orders))
    out.append("---")
    out.append("")
    out.append("> 下一步：待发清单 → 拣货 → 质检打包（录像） → 交寄扫单 → 站内回传单号。"
               "超时单与缺货单由 **customer-service** 兜话术，**ops-director** 决定是否停售。")
    out.append("")
    return "\n".join(out)


def main():
    global R, NOW
    ap = argparse.ArgumentParser(description="仓捷运 · 履约一键出单")
    ap.add_argument("--input", help="订单+库存 JSON（见 %s）" % TEMPLATE_HINT)
    ap.add_argument("--sku", help="单件试算：商品名")
    ap.add_argument("--weight", help="单件试算：重量 kg")
    ap.add_argument("--amount", help="单件试算：订单金额")
    ap.add_argument("--province", help="单件试算：收件省")
    ap.add_argument("--check", help="只做发货文案自查")
    ap.add_argument("--now", help="基准时间，如 '2026-11-11 22:00'（默认取本机当前时间）")
    ap.add_argument("--out", help="输出 Markdown 路径")
    args = ap.parse_args()

    R = load_rules()
    db.RULES = db.load_rules()
    NOW = parse_dt(args.now) or datetime.now()

    # 模式：发货文案自查
    if args.check:
        hits = scan_claims(args.check)
        ad = db.scan_ban(args.check)
        buf = ["# 发货文案自查\n", "> 待检文案：%s\n" % args.check]
        if not hits and not ad:
            buf.append("✅ 未命中时效违规词 / 广告法违规词。")
        for sev, group, word in hits:
            mark = "🔴 硬违规" if sev == "error" else "🟡 需改"
            buf.append("- %s ｜[%s] `%s` → %s" % (mark, group, word, claim_fix(sev, group, word)))
        for sev, group, word in ad:
            mark = "🔴 硬违规" if sev == "error" else "🟡 需核对"
            buf.append("- %s ｜[%s] `%s` → %s" % (mark, group, word, db.suggest(sev, group, word)))
        text = "\n".join(buf)
        print(text)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text)
        return 0

    # 模式：单件物流试算
    if args.sku and not args.input:
        w = num(args.weight)
        c, why = pick_carrier(args.province, args.sku, w, num(args.amount), "")
        cost = cost_of(c, w)
        print("# 物流试算 · %s\n" % args.sku)
        print("> 重量：%s　收件地：%s　订单额：%s\n"
              % ("%.2f kg" % w if w else PH % "重量",
                 args.province or PH % "省", money(num(args.amount)) if num(args.amount) else "—"))
        print("- 建议承运：**%s**（%s）" % (c["name"], c["eta"]))
        print("- 参考运费：%s" % (moneyx(cost) if cost is not None else PH % "运费（缺重量）"))
        print("- 判定理由：%s" % why)
        print("\n**全承运商比价**\n")
        print("| 承运 | 参考运费 | 时效 | 适合 |")
        print("|---|---|---|---|")
        for cc in sorted(R["logistics"], key=lambda x: cost_of(x, w) if cost_of(x, w) is not None else 999):
            cc_cost = cost_of(cc, w)
            print("| %s | %s | %s | %s |" % (cc["name"],
                                             moneyx(cc_cost) if cc_cost is not None else PH % "运费",
                                             cc["eta"], cc["best"]))
        return 0

    # 模式：整单
    sample = False
    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = SAMPLE
        sample = True
        print("::warning::未指定 --input，已用内置样例数据出单，不可当真实履约单执行。", file=sys.stderr)

    text = build(data, sample)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("[OK] 已写出履约单 → %s" % args.out, file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
