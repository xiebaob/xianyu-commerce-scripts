#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ops_plan.py — 许达标 · 运营排期与卡点诊断（目标倒推 / 漏斗诊断 / 周计划 / SKU 处置 / 应季窗口）

它解决运营最常犯的三个错：
    1. 目标只写在纸上，没倒推成「每天需要多少曝光」   → 目标倒推账
    2. 一出单少就降价，其实卡点在点击率               → 漏斗卡点诊断（只修缺口最大的那环）
    3. 上新靠心情，应季窗口过了才想起来               → 应季窗口 + 7 天排期

边界（和其它脚本一个原则）：
    本脚本**不含任何真实经营数据**。曝光、点击率、咨询率、成交率、客单价、上架天数、成交量
    全部由 plan.json 提供；缺哪个就标占位，绝不替你估一个「大概是这个数」。
    目标是你的目标，阈值是规则库的阈值，两者混用会得出假结论——输出里分开标注。

用法：
    # 1) 出本周运营计划（最常用）
    python ops_plan.py --input plan.json --out ops_plan.md

    # 2) 快速算账：只给目标和现状，看缺口在哪
    python ops_plan.py --goal 30000 --aov 400 --exposure 8000 \
        --ctr 1.8 --consult 5 --deal 12 --days 30

    # 3) 只看应季窗口（未来 21 天会撞上什么窗口）
    python ops_plan.py --season

依赖：仅标准库。规则读 plan_rules.json，违规词表复用 design_rules.json。
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import design_brief as db

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, "plan_rules.json")
TEMPLATE_HINT = "plan.template.json"

R = {}
PH = "【%s】"
NOW = None

# 转化率字段名 → 诊断条目 key（两处命名不同，必须显式映射，否则周计划取不到卡点）
RATE_KEY = {"ctr": "ctr", "consult_rate": "consult", "deal_rate": "deal"}


# ---------------------------------------------------------------- 基础

def load_rules():
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("¥", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def money(v):
    return db.money(v)


def pct(v, digits=1):
    if v is None:
        return "—"
    return ("%." + str(digits) + "f%%") % v


def qty(v):
    """小数量保留两位：日均成交 0.86 单显示成 1 单会骗人。"""
    if v is None:
        return "—"
    return "%.2f" % v if abs(v) < 10 else "%.0f" % v


def zh_clean(s):
    import re
    s = re.sub(r"(?<=[\u4e00-\u9fa5]) +(?=[\u4e00-\u9fa5])", "", s or "")
    s = re.sub(r"(?<=[\u4e00-\u9fa5]) +(?=【)", s, s)
    return s.strip()


def role_name(key):
    """只输出中文角色名——报告是给人看的，英文 agent id 是内部实现细节。"""
    r = R["roles"].get(key)
    return r["name"] if r else key


def dday(n):
    return (NOW + timedelta(days=n)).strftime("%m-%d")


# ---------------------------------------------------------------- 漏斗账

def funnel_from(rates, aov, exposure_day):
    """现状 → 日均单量与 GMV。缺任一环节返回 None。"""
    if None in (exposure_day, rates.get("ctr"), rates.get("consult_rate"), rates.get("deal_rate")):
        return None
    clicks = exposure_day * rates["ctr"] / 100.0
    consults = clicks * rates["consult_rate"] / 100.0
    orders = consults * rates["deal_rate"] / 100.0
    gmv = orders * aov if aov else None
    return {"clicks": clicks, "consults": consults, "orders": orders, "gmv": gmv}


def need_funnel(orders_needed, rates):
    """倒推：要达成多少单，各环节需要多少量。"""
    need = {"orders": orders_needed}
    deal = rates.get("deal_rate")
    consult = rates.get("consult_rate")
    ctr = rates.get("ctr")
    need["consults"] = orders_needed / (deal / 100.0) if deal else None
    need["clicks"] = need["consults"] / (consult / 100.0) if (need["consults"] and consult) else None
    need["exposure"] = need["clicks"] / (ctr / 100.0) if (need["clicks"] and ctr) else None
    return need


def block_target(goal, cur, days):
    """目标倒推账：月目标 → 日需求 → 各环节需要多少。"""
    out = ["## 一、目标倒推账（先算清楚每天需要多少曝光）", ""]
    gmv = num(goal.get("gmv"))
    aov = num(cur.get("aov"))
    orders_goal = num(goal.get("orders"))
    profit_goal = num(goal.get("profit"))

    if gmv and aov:
        orders_calc = gmv / aov
    else:
        orders_calc = None
    orders_day = orders_goal / days if orders_goal else (orders_calc / days if orders_calc else None)

    if orders_day is None:
        out.append("> ⚪ 目标缺 `goal.gmv` 或 `goal.orders`，无法倒推。至少给一个目标 + 客单价。")
        out.append("")
        return out, None

    daily_gmv = orders_day * aov if aov else None
    out.append("> 口径：月目标 ÷ %d 天 = 日均目标。客单价 %s 来自你的实际成交均价，不是估值。"
               % (days, money(aov) if aov else PH % "客单价"))
    out.append("")
    out.append("| 项 | 月目标 | 日均需求 |")
    out.append("|---|---|---|")
    if gmv:
        out.append("| GMV | %s | %s |" % (money(gmv), money(daily_gmv) if daily_gmv else "—"))
    if profit_goal:
        out.append("| 利润 | %s | %s |" % (money(profit_goal), money(profit_goal / days)))
    out.append("| 单量 | %s | **%.2f 单/天** |"
               % ("%.0f" % (orders_goal or orders_calc) if (orders_goal or orders_calc) else "—", orders_day))
    out.append("")

    rates = {k: num(cur.get(k)) for k in ("ctr", "consult_rate", "deal_rate")}
    exp_day = num(cur.get("exposure_day"))
    need = need_funnel(orders_day, rates)
    today = funnel_from(rates, aov, exp_day)

    out.append("**按你现在的转化率，要达成上面的单量，各环节每天需要：**")
    out.append("")
    out.append("| 环节 | 现状（日） | 需求（日） | 倍率 | 判据 |")
    out.append("|---|---|---|---|---|")
    rows = [
        ("曝光", exp_day, need.get("exposure")),
        ("点击", today["clicks"] if today else None, need.get("clicks")),
        ("咨询", today["consults"] if today else None, need.get("consults")),
        ("成交", today["orders"] if today else None, orders_day),
    ]
    for name, have, want in rows:
        if want is None:
            out.append("| %s | %s | %s | — | 数据不全 |"
                       % (name, "—" if have is None else "%.0f" % have, PH % "需求"))
            continue
        ratio = (want / have) if have else None
        judge = "✅ 已够" if ratio and ratio <= 1.05 else ("🔴 缺口 %.1f 倍" % ratio if ratio else "⚪ 缺现状")
        out.append("| %s | %s | %s | %s | %s |"
                   % (name,
                      qty(have),
                      qty(want),
                      ("%.2f×" % ratio) if ratio else "—",
                      judge))
    out.append("")

    if exp_day and need.get("exposure"):
        mult = need["exposure"] / exp_day
        if mult > 1.05:
            out.append("**结论**：曝光不变的话，全链路转化必须提升 **%.2f 倍**；"
                       "或曝光提到 **%.0f/天**（现在 %s/天）。"
                       % (mult, need["exposure"], "%.0f" % exp_day))
        elif mult < 0.95:
            out.append("**结论**：按现在的转化率，这个目标只需 **%.0f/天** 曝光（你现在 %s/天），"
                       "**已经够甚至有余**。要么目标定低了该上调，要么流量没被转化成单——"
                       "去下一节看哪一环在漏。" % (need["exposure"], "%.0f" % exp_day))
        else:
            out.append("**结论**：所需曝光 %.0f/天，与现状 %s/天基本持平——目标贴着当前产能，"
                       "想增长只能提转化率或加 SKU。" % (need["exposure"], "%.0f" % exp_day))
        out.append("")
        out.append("> 注意：转化率不变时，曝光→点击→咨询→成交是**乘法链条**，四环必然同倍放大，"
                   "所以「哪环倍率高」不构成结论。先修哪一环，看下一节的**达成度**——离基准最远的那环。")
        out.append("")
    return out, orders_day


def block_diagnose(cur, need_orders, days):
    """漏斗卡点诊断：按 现状/基准 的比值排序，最低的是最弱环节。"""
    out = ["## 二、漏斗卡点诊断（只修缺口最大的那一环）", ""]
    bm = R["funnel_benchmark"]
    keys = [("ctr", "点击率"), ("consult_rate", "咨询率"), ("deal_rate", "成交率")]
    rows = []
    for k, name in keys:
        v = num(cur.get(k))
        base = bm[k]
        rows.append({"k": k, "name": name, "v": v, "base": base,
                     "ratio": (v / base) if v is not None else None})
    known = [r for r in rows if r["ratio"] is not None]
    known.sort(key=lambda r: r["ratio"])

    out.append("> 基准来自 `plan_rules.json`：点击率 ≥%s、咨询率 ≥%s、成交率 ≥%s。"
               "「达成度」= 现状 ÷ 基准，最低的那环就是当前最弱环节。"
               % (pct(bm["ctr"]), pct(bm["consult_rate"]), pct(bm["deal_rate"])))
    out.append("")
    out.append("| 环节 | 现状 | 基准 | 达成度 | 判定 |")
    out.append("|---|---|---|---|---|")
    for r in rows:
        if r["v"] is None:
            out.append("| %s | — | %s | — | ⚪ 数据未填 |" % (r["name"], pct(r["base"])))
            continue
        mark = "🟢 达标" if r["v"] >= r["base"] else ("🟠 偏低" if r["ratio"] >= 0.8 else "🔴 卡点")
        out.append("| %s | %s | %s | %.0f%% | %s |"
                   % (r["name"], pct(r["v"]), pct(r["base"]), r["ratio"] * 100, mark))
    out.append("")

    if not known:
        out.append("> ⚪ 三个转化率都没填，无法定位卡点。至少填点击率与成交率。")
        out.append("")
        return out, None

    worst = known[0]
    diag = next((d for d in R["link_diagnosis"] if d["key"] == worst["k"]), None)
    if worst["ratio"] >= 1.0:
        out.append("> ✅ 三个环节都达标。这时候瓶颈多半在**曝光量**或**SKU 数量**，看第一部分的曝光缺口。")
        out.append("")
        # 仍给出曝光环诊断
        diag = next((d for d in R["link_diagnosis"] if d["key"] == "exposure"), None)
        worst = {"name": "曝光不足", "v": None, "base": None, "ratio": None}
    else:
        flag = "🔴" if worst["ratio"] < 0.8 else "🟠"
        out.append("> %s 最弱环节：**%s**（达成度 %.0f%%）。先修这一个，别同时动手。"
                   % (flag, worst["name"], worst["ratio"] * 100))
        out.append("")

    if diag:
        owners = "、".join(role_name(o) for o in diag["owner"])
        out.append("### 主攻方向：%s" % diag["name"])
        out.append("- 识别信号：%s" % diag["signal"])
        out.append("- 责任角色：%s" % owners)
        out.append("- 本周三件事（每条都指定到人）：")
        for a in diag["actions"]:
            out.append("  - %s　→ **%s**" % (a["text"], role_name(a["owner"])))
        out.append("")

        # 只修这一环到基准，看所需曝光降多少
        cur2 = dict(cur)
        if worst.get("k") and worst["k"] in cur2:
            cur2[worst["k"]] = str(bm[worst["k"]])
            exp_have = num(cur.get("exposure_day"))
            rates2 = {k: num(cur2.get(k)) for k in ("ctr", "consult_rate", "deal_rate")}
            need2 = need_funnel(need_orders, rates2) if need_orders else None
            rates1 = {k: num(cur.get(k)) for k in ("ctr", "consult_rate", "deal_rate")}
            need1 = need_funnel(need_orders, rates1) if need_orders else None
            if need1 and need2 and need1.get("exposure") and need2.get("exposure") and exp_have:
                out.append("- **算一下值不值得**：只把 %s 提到基准 %s，所需曝光从 %.0f 降到 %.0f/天"
                           "（缺口从 %.1f 倍收窄到 %.1f 倍）。"
                           % (worst["name"], pct(bm[worst["k"]]),
                              need1["exposure"], need2["exposure"],
                              need1["exposure"] / exp_have, need2["exposure"] / exp_have))
                out.append("")
    return out, worst


# ---------------------------------------------------------------- 周计划

def block_weekly(goal, cur, worst, orders_day, days):
    out = ["## 三、周运营计划表", ""]
    bm = R["funnel_benchmark"]
    tasks = []

    # 1) 卡点修复（本周唯一主攻）
    if worst and worst.get("k"):
        dkey = RATE_KEY.get(worst["k"], worst["k"])
        diag = next((d for d in R["link_diagnosis"] if d["key"] == dkey), None)
        if diag:
            short = diag.get("short") or diag["name"]
            a0, a1 = diag["actions"][0], diag["actions"][1]
            tasks.append({
                "goal": "%s从 %s 修到 %s" % (short, pct(worst["v"]), pct(bm[worst["k"]])),
                "task": a0["text"],
                "owner": a0["owner"],
                "due": dday(3),
                "kpi": "%s ≥ %s" % (short, pct(bm[worst["k"]])),
                "review": "第 3 天看是否动，7 天看是否到位",
            })
            tasks.append({
                "goal": "%s第二手段（与上面只留一条）" % short,
                "task": a1["text"],
                "owner": a1["owner"],
                "due": dday(5),
                "kpi": "两条动作同口径对比，保留数据好的",
                "review": "只保留数据更好的那一版",
            })
    elif worst and worst.get("name") == "曝光不足":
        tasks.append({
            "goal": "把日均曝光提上去",
            "task": "同品类铺 3-5 个价格带，每天固定擦亮，标题前 6 字换搜索词",
            "owner": "ops-specialist",
            "due": dday(3),
            "kpi": "在售 SKU 数与日均曝光",
            "review": "第 3 天看曝光是否跟着 SKU 数涨",
        })

    # 2) 常规三件
    tasks.append({"goal": "保住上新节奏", "task": "本周上 2-3 个新 SKU，每个都要过四维评分卡",
                  "owner": "ops-specialist", "due": dday(2),
                  "kpi": "上新数 ≥2", "review": "上新 48 小时看点击率"})
    tasks.append({"goal": "内容不断供", "task": "每周 3 条内容，至少 1 条是真实使用场景",
                  "owner": "content-ops", "due": dday(4),
                  "kpi": "内容带来的咨询数", "review": "哪条带来咨询就复制它的结构"})
    tasks.append({"goal": "发货不掉分", "task": "全部订单 48 小时内交寄，逐一留证",
                  "owner": "warehouse", "due": "每日",
                  "kpi": "超时单 = 0", "review": "周五盘一次超时与差评"})
    tasks.append({"goal": "把数据看清楚", "task": "周五出漏斗看板：曝光/点击/咨询/成交四环对比目标",
                  "owner": "data-analyst", "due": dday(5),
                  "kpi": "四个环节达成度", "review": "下周一据此定下周主攻"})
    if not (worst and worst.get("k") == "deal_rate"):
        tasks.append({"goal": "议价不亏", "task": "议价走三级阶梯，第三次到线不接",
                      "owner": "customer-service", "due": "每日",
                      "kpi": "成交率、平均让价幅度", "review": "看让价换来的成交是否划算"})

    out.append("> 拆解口径：**本周只有一个主攻**（卡点那环），其余是保底动作。"
               "同时推五个方向，等于五个都没推。"
               if worst else "> 没有明确卡点，本周以「上新 + 曝光」为主。")
    out.append("")
    out.append("| 目标 | 拆解任务 | 责任角色 | 截止 | 关键指标 | 复盘点 |")
    out.append("|---|---|---|---|---|---|")
    for t in tasks:
        out.append("| %s | %s | %s | %s | %s | %s |"
                   % (t["goal"], t["task"], role_name(t["owner"]), t["due"], t["kpi"], t["review"]))
    out.append("")
    return out


# ---------------------------------------------------------------- SKU 处置

def block_skus(skus):
    out = ["## 四、在售 SKU 处置（该保的保，该砍的砍）", ""]
    cfg = R["sku_actions"]
    if not skus:
        out.append("> 没填 `skus`，跳过。填上 sku / days_live / sold_7d / stock 才能判断。")
        out.append("")
        return out

    out.append("> 判据：上架 %d 天零成交换图 / %d 天零成交降价 %d%% / %d 天零成交下架换品。"
               "压着不出单的 SKU = 占着免费展位。"
               % (cfg["new_days"], cfg["stale_days"], cfg["price_cut_pct"], cfg["dead_days"]))
    out.append("")
    out.append("| SKU | 上架天数 | 近7日成交 | 库存 | 判定 | 动作 | 责任 |")
    out.append("|---|---|---|---|---|---|---|")
    counts = {"保": 0, "砍": 0, "改": 0}
    for s in skus:
        sku = s.get("sku") or PH % "SKU"
        d = num(s.get("days_live"))
        sold = num(s.get("sold_7d"))
        stock = num(s.get("stock"))

        if sold is None or d is None:
            verdict, action, owner = "⚪ 数据不全", "补上架天数与近 7 日成交", "—"
        elif sold >= 1:
            verdict, action, owner = "✅ 有成交", "加库存、按同款结构复制上新", "ops-specialist"
            counts["保"] += 1
        elif stock is not None and stock <= 0:
            verdict, action, owner = "🔴 缺货", "先停售，补货或退款（OOS 预案）", "warehouse"
            counts["改"] += 1
        elif d < cfg["new_days"]:
            verdict, action, owner = "🟡 观察期", "满 3 天再判断，别提前改价", "designer"
            counts["改"] += 1
        elif d < cfg["stale_days"]:
            verdict, action, owner = "🟠 换图换题", "首图换版式 + 标题前 6 字改搜索词", "designer"
            counts["改"] += 1
        elif d < cfg["dead_days"]:
            verdict, action, owner = "🟠 该降价", "降价 %d%% 试 3 天" % cfg["price_cut_pct"], "ops-specialist"
            counts["改"] += 1
        else:
            verdict, action, owner = "⛔ 下架换品", "下架，把展位让给新候选", "ops-specialist"
            counts["砍"] += 1

        out.append("| %s | %s | %s | %s | %s | %s | %s |"
                   % (sku,
                      "—" if d is None else "%d 天" % d,
                      "—" if sold is None else "%d" % sold,
                      "—" if stock is None else "%d" % stock,
                      verdict, action, role_name(owner) if owner != "—" else "—"))
    out.append("")
    out.append("> 汇总：有成交 **%d** 个 ｜ 需调整 **%d** 个 ｜ 建议下架 **%d** 个"
               % (counts["保"], counts["改"], counts["砍"]))
    out.append("")
    return out


# ---------------------------------------------------------------- 排期与窗口

def block_rhythm():
    out = ["## 五、每日动作排期（照着做，不用每天想）", ""]
    out.append("| 时段 | 动作 | 具体做什么 |")
    out.append("|---|---|---|")
    for r in R["daily_rhythm"]:
        out.append("| %s | **%s** | %s |" % (r["slot"], r["name"], r["detail"]))
    out.append("")
    out.append("> 两个不能挪的：**12:00-13:00 与 20:00-22:00** 是咨询峰值，这两个时段离开手机就等于丢单。")
    out.append("")
    return out


def season_hits(days_ahead=21):
    """找出未来 N 天会撞上的窗口（支持跨年）。"""
    hits = []
    for w in R["season_windows"]:
        for offset in range(days_ahead + 1):
            d = NOW + timedelta(days=offset)
            md = d.strftime("%m-%d")
            if w["start"] <= md <= w["end"]:
                hits.append((offset, d, w))
                break
        else:
            continue
    hits.sort(key=lambda h: h[0])
    return hits


def block_season(days_ahead=21):
    out = ["## 六、应季窗口（未来 %d 天）" % days_ahead, ""]
    hits = season_hits(days_ahead)
    if not hits:
        out.append("> 未来 %d 天没有命中窗口。这是常态——**没窗口的月份靠持续上新与内容，不靠等风来**。"
                   % days_ahead)
        out.append("")
        return out

    out.append("| 距今天 | 窗口 | 日期 | 适配品类 | 操作建议 |")
    out.append("|---|---|---|---|---|")
    for offset, d, w in hits:
        out.append("| %s | **%s** | %s ~ %s | %s | %s |"
                   % ("今天" if offset == 0 else "D+%d" % offset,
                      w["name"], w["start"], w["end"],
                      "、".join(w["items"][:4]) if w["items"] else "—",
                      w["advice"]))
    out.append("")
    out.append("> 窗口纪律：**提前上架比降价有用**。窗口前 7-10 天上架、备好库存，正日子才有位置。")
    out.append("")
    return out


def block_season_full():
    out = ["# 全年应季窗口表", "",
           "> 生成器：`ops_plan.py --season`　规则库：`plan_rules.json`",
           "> 口径：窗口是「需求起来的时间」，不是「你该开始卖的时间」——上架要提前 7-10 天。", ""]
    out.append("| 起 | 止 | 窗口 | 适配品类 | 操作建议 |")
    out.append("|---|---|---|---|---|")
    for w in R["season_windows"]:
        out.append("| %s | %s | **%s** | %s | %s |"
                   % (w["start"], w["end"], w["name"],
                      "、".join(w["items"]) if w["items"] else "—", w["advice"]))
    out.append("")
    today_md = NOW.strftime("%m-%d")
    now_hit = [w for w in R["season_windows"] if w["start"] <= today_md <= w["end"]]
    out.append("**今天（%s）处于**：%s"
               % (today_md, "、".join(w["name"] for w in now_hit) if now_hit else "无窗口期，靠持续上新"))
    out.append("")
    return out


# ---------------------------------------------------------------- 预警与复盘

def block_alerts(metrics, skus):
    out = ["## 七、预警线（触线就上报主理人，别自己扛）", ""]
    m = metrics or {}
    fired = []
    z = num(m.get("zero_sales_days"))
    if z is not None and z >= 3:
        fired.append("连续 %d 天零出单 → 🔴 当天上报，按漏斗从头查，别先改价" % int(z))
    bad = num(m.get("bad_review_rate"))
    if bad is not None and bad > 3:
        fired.append("差评率 %.1f%% > 3%% → 🔴 停发同类，回查发货留证与描述一致性" % bad)
    late = num(m.get("late_ship"))
    if late is not None and late > 0:
        fired.append("超时未交寄 %d 单 → 🔴 先补说明 + 补偿，再发货" % int(late))
    low = num(m.get("low_stock"))
    if low is not None and low > 0:
        fired.append("库存低于警戒线仍在接单 %d 个 SKU → 🟠 先停售再补货" % int(low))
    for s in (skus or []):
        d = num(s.get("days_live"))
        sold = num(s.get("sold_7d"))
        if d is not None and sold == 0 and d >= R["sku_actions"]["dead_days"]:
            fired.append("`%s` 上架 %d 天零成交 → 🟠 下架换品" % (s.get("sku"), int(d)))

    if fired:
        out.append("### 当前已触线")
        for f in fired:
            out.append("- %s" % f)
        out.append("")
    else:
        out.append("- ✅ 已填指标均未触线")
        out.append("")

    out.append("### 全部预警规则")
    out.append("")
    out.append("| 触发条件 | 级别 | 动作 |")
    out.append("|---|---|---|")
    for a in R["alerts"]:
        out.append("| %s | %s | %s |" % (a["cond"], a["level"], a["do"]))
    out.append("")
    return out


def block_review(worst):
    out = ["## 八、本周卡点 + 下周优化动作", ""]
    out.append("**本周卡点**：%s" % (worst["name"] if worst else "数据不足，先补漏斗四个数字"))
    out.append("")
    out.append("**下周五问自己（答不上来就是没复盘）**")
    out.append("")
    for c in R["review_checklist"]:
        out.append("- [ ] %s" % c)
    out.append("")
    out.append("**下周动作只写一条**：%s"
               % ("继续修「%s」，未到位不换方向" % worst["name"] if worst
                  else "补齐漏斗数据，再定方向"))
    out.append("")
    return out


# ---------------------------------------------------------------- 样例

SAMPLE = {
    "month": "2026-11",
    "days": 30,
    "goal": {"gmv": 30000, "profit": 6000, "orders": None},
    "current": {"aov": 400, "exposure_day": 8000, "ctr": 1.8,
                "consult_rate": 5.0, "deal_rate": 12.0},
    "skus": [
        {"sku": "二手 Switch OLED 掌机 白色", "days_live": 12, "sold_7d": 3, "stock": 3},
        {"sku": "iPhone 13 128G 午夜色", "days_live": 6, "sold_7d": 0, "stock": 2},
        {"sku": "罗技 MX Master 3S 鼠标", "days_live": 18, "sold_7d": 0, "stock": 2},
        {"sku": "小米空气炸锅 4L", "days_live": 2, "sold_7d": 0, "stock": 0},
        {"sku": "二手 Kindle Paperwhite 5 8G", "days_live": 21, "sold_7d": 0, "stock": 2},
    ],
    "metrics": {"zero_sales_days": 0, "bad_review_rate": 1.2, "late_ship": 1, "low_stock": 1},
}


# ---------------------------------------------------------------- 主流程

def build(data, sample=False):
    goal = data.get("goal") or {}
    cur = data.get("current") or {}
    days = int(num(data.get("days")) or 30)
    skus = data.get("skus") or []

    out = ["# 运营计划 · 许达标", "",
           "> 生成器：`ops_plan.py`　规则库：`plan_rules.json`（漏斗阈值与 `dashboard.py` 同口径）",
           "> 基准日：%s　｜　周期：%s（%d 天）" % (NOW.strftime("%Y-%m-%d"), data.get("month") or "—", days),
           "> 口径：脚本**不含任何真实经营数据**。目标是你填的目标，阈值是规则库的阈值，两者不混算。", ""]
    if sample:
        out.insert(2, "> ⚠️ **当前为样例数据**：未检测到 `%s`，下面的目标与漏斗数字全是演示值，"
                      "不可当真实运营计划执行。" % TEMPLATE_HINT)
        out.insert(3, "")

    out.append("---")
    out.append("")

    tgt, orders_day = block_target(goal, cur, days)
    out.extend(tgt)
    diag, worst = block_diagnose(cur, orders_day, days)
    out.extend(diag)
    out.extend(block_weekly(goal, cur, worst, orders_day, days))
    out.extend(block_skus(skus))
    out.extend(block_rhythm())
    out.extend(block_season())
    out.extend(block_alerts(data.get("metrics"), skus))
    out.extend(block_review(worst))
    out.append("---")
    out.append("")
    out.append("> 执行顺序：主攻卡点 → 保底动作 → 每日排期 → 周五复盘。"
               "卡点没修好之前，不加新方向。")
    out.append("")
    return "\n".join(out)


def main():
    global R, NOW
    ap = argparse.ArgumentParser(description="许达标 · 运营排期与卡点诊断")
    ap.add_argument("--input", help="计划 JSON（见 %s）" % TEMPLATE_HINT)
    ap.add_argument("--goal", help="快速算账：月 GMV 目标")
    ap.add_argument("--orders", help="快速算账：月单量目标")
    ap.add_argument("--aov", help="快速算账：客单价")
    ap.add_argument("--exposure", help="快速算账：日均曝光")
    ap.add_argument("--ctr", help="快速算账：点击率 %%")
    ap.add_argument("--consult", help="快速算账：咨询率 %%")
    ap.add_argument("--deal", help="快速算账：成交率 %%")
    ap.add_argument("--days", help="周期天数（默认 30）")
    ap.add_argument("--season", action="store_true", help="只看全年应季窗口表")
    ap.add_argument("--now", help="基准日期，如 '2026-11-11'")
    ap.add_argument("--out", help="输出 Markdown 路径")
    args = ap.parse_args()

    R = load_rules()
    db.RULES = db.load_rules()
    NOW = datetime.strptime(args.now, "%Y-%m-%d") if args.now else datetime.now()

    if args.season:
        text = "\n".join(block_season_full())
        print(text)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text)
        return 0

    sample = False
    if args.input:
        if not os.path.exists(args.input):
            print("错误：找不到输入文件 %s" % args.input)
            print("      模板：plan.template.json　示例：examples/plan.example.json")
            return 2
        with open(args.input, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                print("错误：%s 不是合法 JSON（第 %d 行第 %d 列：%s）"
                      % (args.input, e.lineno, e.colno, e.msg))
                print("      常见原因：中文引号、末尾多逗号、缺右括号。")
                return 2
    elif args.goal or args.orders:
        data = {
            "month": NOW.strftime("%Y-%m"),
            "days": int(num(args.days) or 30),
            "goal": {"gmv": args.goal, "orders": args.orders},
            "current": {"aov": args.aov, "exposure_day": args.exposure,
                        "ctr": args.ctr, "consult_rate": args.consult, "deal_rate": args.deal},
            "skus": [], "metrics": {},
        }
    else:
        data = SAMPLE
        sample = True
        print("::warning::未指定 --input / --goal，已用内置样例数据出计划，不可当真实运营计划执行。",
              file=sys.stderr)

    text = build(data, sample)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("[OK] 已写出运营计划 → %s" % args.out, file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
