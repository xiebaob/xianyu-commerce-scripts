#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
拾货源 · 1688 全新小件货源线

只做一件事：把「1688 拿货」算成「闲鱼能不能卖、能赚多少、会不会翻车」。

三个模式：
  1) 整单：--input sourcing.json      出 9 个板块的进货决策单
  2) 快算：--cost 12 --return-rate 5   单条货源倒推挂价
  3) 自查：--check "标题文案"          货源侧违禁词与风险词

口径铁律：
  - 本脚本不含任何真实经营数据。拿货价、退货率、供应商信息全部由你填。
  - 缺任何一个关键数字，那一条就标占位、跳过算账，绝不替你估。
  - 1688 拿货的利润必须扣掉两段运费和退货期望损失，否则卖得越多亏得越多。
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
R = {}
NOW = None
PH = "【%s】"

# 强制 3C 认证的关键词（命中即要求供应商提供证书，否则红线否决）
CERT_KEYWORDS = [
    "充电器", "充电头", "移动电源", "充电宝", "快充", "氮化镓",
    "小风扇", "加湿器", "暖手宝", "加热杯垫", "插排", "取暖器",
    "台灯", "氛围灯", "补光灯", "夜灯", "投影灯", "夹子灯",
]


# ---------------------------------------------------------------- 基础工具

def load_rules():
    global R
    with open(os.path.join(BASE, "sourcing_rules.json"), "r", encoding="utf-8") as f:
        R = json.load(f)


def money(v):
    """整数不带小数，非整数保留两位——¥2.5 被显示成 ¥2 会让比价算错。"""
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(v - round(v)) < 0.005:
        return "%d" % round(v)
    return "%.2f" % v


def pct(v, digits=1):
    if v is None:
        return "—"
    try:
        return ("%." + str(digits) + "f%%") % (float(v) * 100)
    except (TypeError, ValueError):
        return str(v)


def num(v, default=None):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def band(txt):
    """「8-45」这种价格带拆成上下限。"""
    if not txt:
        return None, None
    m = re.findall(r"[\d.]+", str(txt))
    if len(m) >= 2:
        return float(m[0]), float(m[1])
    if len(m) == 1:
        return float(m[0]), float(m[0])
    return None, None


def match_cat(text):
    """按品类关键词匹配规则库。

    两级判定：
      1) 互斥词优先——「车载手机支架」命中「桌面支架」是错的，桌面支架带 exclude
         （车载/出风口），命中排除词就直接跳过该品类。
      2) 同级内按命中词总字符数 + 命中数排序，最具体的品类赢。
    """
    blob = (text or "").lower()
    best = None
    for c in R["categories"]:
        ex = [w for w in c.get("exclude", []) if w.lower() in blob]
        if ex:
            continue
        hits = [k for k in c.get("match", []) if k.lower() in blob]
        if not hits:
            continue
        score = (sum(len(h) for h in hits), len(hits))
        if best is None or score > best[0]:
            best = (score, c)
    if best:
        return best[1]
    for c in R["categories"]:
        if c.get("name") == "通用":
            return c
    return None


def need_cert(text):
    for k in CERT_KEYWORDS:
        if k in (text or ""):
            return k
    return None


def cat_band(cat, key):
    if not cat:
        return None, None
    return band(cat.get(key))


# ---------------------------------------------------------------- 核心算账

def calc_item(it, params):
    """单条货源的净利倒推与决策。

    单件净毛利 = 售价 − 拿货价 − 1688运费 − 闲鱼运费 − 期望退货损失
    期望退货损失 = 退货率 × (两段不退运费 + 人工处理 + 货值折价)

    反推最低挂价（把期望退货损失展开成含售价的项）：
        售价 = [拿货价 + 1688运费 + 闲鱼运费 + 退货率×(两段运费+人工)]
               ÷ (1 − 退货率×折价率 − 目标净利率)
    """
    cm = R["cost_model"]
    dec = R["decision"]

    name = it.get("sku") or it.get("name") or "未命名货源"
    cost = num(it.get("cost"))
    ship = num(it.get("ship_fee"), cm["ship_fee_default"])
    buyer_fee = num(params.get("buyer_ship_fee"), cm["buyer_ship_fee"])
    rr = num(it.get("return_rate"))
    disc = cm["resale_discount"]
    handling = cm["handling_per_return"]
    target = num(params.get("target_margin"), dec["target_margin"])

    res = {
        "name": name,
        "supplier": it.get("supplier") or PH % "供应商待填",
        "cost": cost,
        "ship": ship,
        "buyer_fee": buyer_fee,
        "return_rate": rr,
        "moq": num(it.get("moq")),
        "lead_days": num(it.get("lead_days")),
        "stock": num(it.get("stock")),
        "onepiece": it.get("supports_onepiece"),
        "notes": [],
        "blocks": [],
        "warns": [],
        "price": None,
        "price_min": None,
        "net_profit": None,
        "net_margin": None,
        "verdict": "无法判断",
        "level": "",
        "cat_rule": match_cat(name + " " + str(it.get("cat") or "")),
    }

    # ---- 缺数字就不算：硬规矩，不猜
    missing = []
    if cost is None:
        missing.append("cost（1688 拿货价）")
    if rr is None:
        missing.append("return_rate（退货率 %）")
    if missing:
        res["notes"].append("缺 %s → 跳过算账（占位不编数）" % "、".join(missing))
        res["verdict"] = "缺数据"
        res["level"] = "⚪"
        return res

    r = rr / 100.0
    if r >= 1:
        res["notes"].append("退货率 ≥ 100%%，数据有误")
        res["verdict"] = "数据有误"
        res["level"] = "🔴"
        return res

    denom = 1 - r * disc - target
    if denom <= 0.02:
        res["notes"].append("退货率 %.1f%% 已被折价率与目标净利率吃掉，这门生意算不出来"
                            % (rr * 100))
        res["verdict"] = "算不过来"
        res["level"] = "🔴"
        res["blocks"].append("退货率过高")
        return res

    p_min = (cost + ship + buyer_fee + r * (ship + buyer_fee + handling)) / denom

    given = num(it.get("listing_price"))
    price = given if given is not None else p_min
    res["price_min"] = p_min
    res["price"] = price
    res["price_given"] = given is not None

    exp_ret = r * (ship + buyer_fee + handling + price * disc)
    net = price - cost - ship - buyer_fee - exp_ret
    margin = net / price if price else 0.0
    res["net_profit"] = net
    res["net_margin"] = margin
    res["expect_return_loss"] = exp_ret

    # ---- 硬性否决
    if res["moq"] is not None and res["moq"] > dec["max_moq"] and not res["onepiece"]:
        res["blocks"].append("起批量 %d 件 > 上限 %d 且不支持一件代发，压货压不起"
                             % (res["moq"], dec["max_moq"]))
    if res["lead_days"] is not None and res["lead_days"] > dec["max_lead_days"]:
        res["blocks"].append("发货时效 %d 天 > %d 天，会破 48 小时交寄承诺（仓捷运铁律）"
                             % (res["lead_days"], dec["max_lead_days"]))
    ck = need_cert(name + " " + str(it.get("cat") or ""))
    if ck:
        cert = it.get("cert_3c")
        if cert is True:
            res["notes"].append("「%s」属 3C 认证目录，已确认供应商有证书" % ck)
        elif cert is False:
            res["blocks"].append("「%s」属 3C 认证目录，供应商明确无证书 —— 违法销售，不碰" % ck)
        else:
            res["blocks"].append("「%s」属 3C 认证目录，证书状态未确认 —— 先要证书编号" % ck)
    if it.get("image_authorized") is False:
        res["warns"].append("图片不可用：必须自己实拍重做（design_render）")
    if it.get("invoice") is False:
        res["warns"].append("供应商不开票：成本口径与售后追溯都缺一环")
    if res["stock"] is not None and res["stock"] < dec["min_stock"]:
        res["warns"].append("供货商库存 %d < %d，货源不稳，容易断" % (res["stock"], dec["min_stock"]))

    # ---- 价位带校验：算出来的最低价没人买，就是白算
    cat = res["cat_rule"]
    lo, hi = cat_band(cat, "price_band")
    is_generic = bool(cat) and cat.get("name") == "通用"
    if is_generic:
        res["warns"].append("未匹配到品类库，已按「通用」口径算账——"
                            "先确认这东西在闲鱼上该挂多少钱，再回来定")
    elif hi is not None:
        if p_min > hi:
            res["blocks"].append("最低可行挂价 ¥%s 已超品类价位上限 ¥%s —— 挂到这个价没人买"
                                 % (money(p_min), money(hi)))
        elif p_min < lo:
            res["warns"].append("最低可行挂价 ¥%s 低于品类价位下限 ¥%s，可能定价偏低、卖不出量"
                                % (money(p_min), money(lo)))

    comp = cat.get("competition") if cat else None
    res["competition"] = comp
    if comp is not None and comp >= 4 and margin >= dec["good_margin"]:
        res["warns"].append("竞争强度 %d/5 的红海品类：净利率高不等于卖得动，"
                            "必须靠组合装 + 自拍图突围" % comp)

    # ---- 判定
    if res["blocks"]:
        res["verdict"] = "不做"
        res["level"] = "🔴"
    elif margin >= dec["good_margin"]:
        res["verdict"] = "做"
        res["level"] = "🟢"
    elif margin >= dec["trial_margin"]:
        res["verdict"] = "试单 %d 单" % dec["trial_orders"]
        res["level"] = "🟠"
    else:
        res["verdict"] = "不做"
        res["level"] = "🔴"
        res["blocks"].append("净毛利率 %s < 试单线 %s" % (pct(margin), pct(dec["trial_margin"])))
    return res


def bundle_pnl(item, res, params):
    """组合装：把单品并进套装后重算客单价与净利。

    组合是全新小件在闲鱼上唯一的活法——单品是红海，套装不是。
    """
    b = item.get("bundle")
    if not b:
        return None
    cost = num(b.get("cost"))
    price = num(b.get("price"))
    if cost is None or price is None:
        return None
    cm = R["cost_model"]
    ship = num(item.get("ship_fee"), cm["ship_fee_default"])
    buyer_fee = num(params.get("buyer_ship_fee"), cm["buyer_ship_fee"])
    rr = num(item.get("return_rate"), 0) or 0
    r = rr / 100.0
    exp_ret = r * (ship + buyer_fee + cm["handling_per_return"] + price * cm["resale_discount"])
    net = price - cost - ship - buyer_fee - exp_ret
    return {
        "name": b.get("name") or "组合装",
        "items": b.get("items") or PH % "组合件待填",
        "cost": cost,
        "price": price,
        "net": net,
        "margin": net / price if price else 0,
        "single_price": num(b.get("single_price")),
    }


# ---------------------------------------------------------------- 输出板块

def sec_overview(items, res_list, out):
    out.append("## 一、货源总览")
    out.append("")
    out.append("> 口径：拿货价、退货率、起批量、时效全部来自你填的 `sourcing.json`。"
               "缺项在下面标「待填」，**脚本不会替你估一个数**。")
    out.append("")
    out.append("| # | 货源 | 品类 | 拿货价 | 1688运费 | 退货率 | 起批量 | 发货时效 | 一件代发 | 供货商库存 |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for i, (it, r) in enumerate(zip(items, res_list), 1):
        out.append("| %d | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                   % (i, it.get("sku") or it.get("name") or PH % "货源待填",
                      (r["cat_rule"]["name"] if r["cat_rule"] else (it.get("cat") or PH % "待判")),
                      money(r["cost"]) if r["cost"] is not None else PH % "拿货价待填",
                      money(r["ship"]),
                      ("%.1f%%" % r["return_rate"]) if r["return_rate"] is not None else PH % "退货率待填",
                      ("%d 件" % r["moq"]) if r["moq"] is not None else PH % "待填",
                      ("%d 天" % r["lead_days"]) if r["lead_days"] is not None else PH % "待填",
                      ("是" if r["onepiece"] else ("否" if r["onepiece"] is not None else PH % "待填")),
                      ("%d" % r["stock"]) if r["stock"] is not None else PH % "待填"))
    out.append("")
    counts = {"做": 0, "试单": 0, "不做": 0, "缺数据": 0, "算不过来": 0, "数据有误": 0}
    for r in res_list:
        v = r["verdict"]
        if v.startswith("做"):
            counts["做"] += 1
        elif v.startswith("试单"):
            counts["试单"] += 1
        elif v == "缺数据":
            counts["缺数据"] += 1
        elif v == "算不过来":
            counts["算不过来"] += 1
        elif v == "数据有误":
            counts["数据有误"] += 1
        else:
            counts["不做"] += 1
    out.append("> 汇总：可做 **%d** ｜ 试单 **%d** ｜ 不做 **%d** ｜ 缺数据 **%d**"
               % (counts["做"], counts["试单"], counts["不做"], counts["缺数据"]))
    out.append("")


def sec_pnl(items, res_list, params, out):
    tm = params.get("target_margin", R["decision"]["target_margin"])
    out.append("## 二、逐条算账（拿货 → 挂价 → 净利）")
    out.append("")
    out.append("> 净利公式：售价 − 拿货价 − 1688运费 − 闲鱼运费 − **期望退货损失**。")
    out.append("> 少算退货损失是这条线上最常见的亏法——单看毛价以为有赚，卖完一算全是运费。")
    out.append("")
    out.append("| 货源 | 最低可行挂价 | 实际挂价 | 单件净利 | 净毛利率 | 判定 |")
    out.append("|---|---|---|---|---|---|")
    for r in res_list:
        if r["price"] is None:
            out.append("| %s | %s | %s | %s | %s | %s |"
                       % (r["name"], PH % "缺数据", PH % "缺数据", PH % "缺数据",
                          PH % "缺数据", r["level"] + " " + r["verdict"]))
            continue
        out.append("| %s | %s | %s | %s | %s | %s |"
                   % (r["name"], money(r.get("price_min")), money(r["price"]),
                      money(r["net_profit"]), pct(r["net_margin"]),
                      r["level"] + " " + r["verdict"]))
    out.append("")
    for it, r in zip(items, res_list):
        out.append("### %s %s" % (r["level"], r["name"]))
        out.append("")
        if r["verdict"] == "缺数据":
            for n in r["notes"]:
                out.append("- %s" % n)
            out.append("- 补齐后再跑一次，本条才能给挂价")
            out.append("")
            continue
        if r.get("price_min") is not None:
            out.append("- **最低可行挂价 ¥%s**（按目标净利率 %s 倒推）"
                       % (money(r["price_min"]), pct(tm)))
            if r.get("price_given"):
                out.append("- 你填的挂价 ¥%s → 单件净利 ¥%s，净毛利率 %s"
                           % (money(r["price"]), money(r["net_profit"]), pct(r["net_margin"])))
            else:
                out.append("- 净利 ¥%s／件，净毛利率 %s" % (money(r["net_profit"]), pct(r["net_margin"])))
        out.append("- 成本构成：拿货 ¥%s ＋ 1688运费 ¥%s ＋ 闲鱼运费 ¥%s ＋ 期望退货损失 ¥%s"
                   % (money(r["cost"]), money(r["ship"]), money(r["buyer_fee"]),
                      money(r.get("expect_return_loss"))))
        for b in r["blocks"]:
            out.append("- 🔴 **%s**" % b)
        for w in r["warns"]:
            out.append("- 🟠 %s" % w)
        for n in r["notes"]:
            out.append("- %s" % n)
        bn = bundle_pnl(it, r, params)
        if bn:
            lift = ("；单品价 ¥%s → 客单价提升 %.1f 倍"
                    % (money(bn["single_price"]), bn["price"] / bn["single_price"])
                    ) if bn["single_price"] else ""
            out.append("- **组合装**（%s）：挂 ¥%s，单件净利 ¥%s，净毛利率 %s%s"
                       % (bn["items"], money(bn["price"]), money(bn["net"]), pct(bn["margin"]), lift))
        out.append("")


def sec_supply_mode(items, res_list, params, out):
    out.append("## 三、一件代发 vs 备货（资金占用对比）")
    out.append("")
    cm = R["cost_model"]
    hold = num(params.get("stock_days"), 7)
    daily = num(params.get("daily_orders"), 0) or 0
    out.append("> 备货天数按 %d 天算（参数可改）。资金占用 = 备货件数 × 拿货价；"
               "一件代发不压货，但把风险换成了时效违约和售后失控。" % hold)
    out.append("")
    out.append("| 货源 | 判定 | 方式 | 建议备货量 | 资金占用 | 风险 |")
    out.append("|---|---|---|---|---|---|")
    total_hold = 0.0
    for it, r in zip(items, res_list):
        if r["cost"] is None or r["verdict"] == "缺数据":
            continue          # 缺关键数据的货源不进备货表——它现在还只是想法
        one = bool(r["onepiece"])
        moq = r["moq"] if r["moq"] is not None else 1
        if r["verdict"].startswith("试单"):
            qty = R["decision"]["trial_orders"]
        else:
            qty = max(moq, int(round(daily * hold))) if daily else moq
        ld = r["lead_days"]
        if one:
            # 一件代发：不压货，货款随单结算，资金占用为 0
            capital = 0.0
            if ld is None:
                risk = "不压货，但发货时效没确认，48 小时承诺悬着"
            elif ld <= 2:
                risk = "不压货，发货 %d 天，48 小时承诺够用；但你见不到货" % ld
            elif ld == 3:
                risk = "不压货，发货 3 天，紧贴 48 小时上限，供应商一延迟就破"
            else:
                risk = "不压货，但发货 %d 天，必定破 48 小时承诺" % ld
        else:
            capital = qty * r["cost"]
            fund = capital * hold * cm["stock_holding_per_day"]
            total_hold += capital
            capital_txt = "¥%s（+资金成本 ¥%s）" % (money(capital), money(fund))
            risk = "压货：卖不动就是死货，%d 天后资金全锁住" % hold
        out.append("| %s | %s %s | %s | %s | %s | %s |"
                   % (r["name"], r["level"], r["verdict"],
                      "一件代发" if one else "备货",
                      ("%d 件" % qty) if not one else "按单结算",
                      capital_txt if not one else "¥0（零压货）",
                      risk))
    out.append("")
    out.append("> 备货总占用：**¥%s**。这个数才是货源决策真正的成本——"
               "不是毛利率，是压进去拿不回来的钱。一件代发资金占用为零，"
               "但代价写在「风险」列里，别以为白赚。" % money(total_hold))
    out.append("")


def sec_gaps(out):
    out.append("## 四、1688 → 闲鱼 的六个断层（翻车的地方）")
    out.append("")
    out.append("> 货源问题一半不是「找不到货」，是「找到了但用不了」。这六条是断点，逐条对。")
    out.append("")
    for g in R["platform_gaps"]:
        out.append("### %s　%s（风险 %s）" % (g["id"], g["gap"], g["risk"]))
        out.append("")
        out.append("- 1688 那边：%s" % g["b1688"])
        out.append("- 闲鱼这边：%s" % g["bxy"])
        out.append("- **应对**：%s" % g["act"])
        out.append("")


def sec_supplier(out):
    out.append("## 五、供应商必问清单与红线")
    out.append("")
    out.append("> 前十句问完再谈价。口头承诺不算，聊天记录和订单截图才算。")
    out.append("")
    for i, q in enumerate(R["supplier_questions"], 1):
        out.append("%d. %s" % (i, q))
    out.append("")
    out.append("### 不碰清单")
    out.append("")
    for r in R["redlines"]:
        out.append("- %s **%s**——%s" % (r["level"], r["title"], r["detail"]))
    out.append("")


def sec_buy_list(items, res_list, params, out):
    out.append("## 六、采购执行清单（今天该下什么单）")
    out.append("")
    hold = num(params.get("stock_days"), 7)
    daily = num(params.get("daily_orders"), 0) or 0
    out.append("| 货源 | 判定 | 供应商 | 下单量 | 单件拿货价 | 本次占用 | 下单前必须确认 |")
    out.append("|---|---|---|---|---|---|---|")
    for it, r in zip(items, res_list):
        if r["verdict"] == "缺数据":
            out.append("| %s | %s | %s | %s | %s | %s | 先补拿货价与退货率 |"
                       % (r["name"], r["verdict"], r["supplier"], PH % "待定",
                          PH % "待填", PH % "待定"))
            continue
        if r["verdict"].startswith("不做"):
            out.append("| %s | %s %s | %s | %s | %s | %s | — |"
                       % (r["name"], r["level"], r["verdict"], r["supplier"], "不下单",
                          PH % "不适用", PH % "不占用"))
            continue
        moq = r["moq"] if r["moq"] is not None else 1
        if r["verdict"].startswith("试单"):
            qty = R["decision"]["trial_orders"]
        else:
            qty = max(moq, int(round(daily * hold))) if daily else moq
        must = []
        if it.get("cert_3c") is True:
            must.append("3C 证书编号")
        if it.get("image_authorized") is False:
            must.append("图片自拍重做")
        if r["onepiece"] is False:
            must.append("发货时效书面确认")
        if not must:
            must.append("样品与批量一致")
        out.append("| %s | %s %s | %s | %d 件 | ¥%s | ¥%s | %s |"
                   % (r["name"], r["level"], r["verdict"], r["supplier"], qty,
                      money(r["cost"]), money(qty * r["cost"]), "、".join(must)))
    out.append("")


def sec_listing_check(out):
    out.append("## 七、上架风险自查（1688 货最容易踩的两类坑）")
    out.append("")
    out.append("### 一、搬运供应商文案里的违禁词")
    out.append("")
    out.append("| 词 | 为什么不能写 |")
    out.append("|---|---|")
    for f in R["listing_check"]["forbidden_phrases"]:
        out.append("| %s | %s |" % (f["w"], f["why"]))
    out.append("")
    out.append("### 二、图片")
    out.append("")
    for r in R["listing_check"]["image_rules"]:
        out.append("- %s" % r)
    out.append("")
    out.append("> 违禁词表与 `design_rules.json` / `content_rules.json` 同源，但这里多的是**货源侧**"
               "特有的坑：「秒发」「当天发货」对 1688 代发是必然做不到的。")
    out.append("")


def sec_bundles(out):
    out.append("## 八、组合打包策略（单品是红海，套装不是）")
    out.append("")
    out.append("> 全新小件在闲鱼唯一能跑通的方式：**按场景重组 + 自己出图**。"
               "组合之后买家搜的是场景不是品名，比价无从下手。")
    out.append("")
    out.append("| 组合 | 含哪些件 | 单件价带 | 组合挂价带 | 客单价提升 | 为什么有效 |")
    out.append("|---|---|---|---|---|---|")
    for b in R["bundle_strategies"]:
        out.append("| **%s** | %s | ¥%s | ¥%s | %s | %s |"
                   % (b["name"], b["items"], b["single_band"], b["bundle_band"],
                      b["lift"], b["why"]))
    out.append("")
    out.append("> 组合的代价是**发货件数变多、包装变复杂、退货更麻烦**。"
               "所以组合做「一包 3 件以内」，别做成 8 件全家桶——那是给自己找差评。")
    out.append("")


def sec_supply_risk(items, res_list, params, out):
    out.append("## 九、断货与货源稳定性预警")
    out.append("")
    hold = num(params.get("stock_days"), 7)
    out.append("| 货源 | 供货商库存 | 你的备货周期 | 判断 |")
    out.append("|---|---|---|---|")
    any_warn = False
    for r in res_list:
        if r["stock"] is None or r["lead_days"] is None:
            out.append("| %s | %s | %s | ⚪ 数据不全，无法判断 |"
                       % (r["name"], PH % "待填", PH % "待填"))
            continue
        span = r["lead_days"] + hold
        if r["stock"] < span * 2:
            any_warn = True
            out.append("| %s | %d | %d 天 | 🔴 供应商库存撑不过一个备货周期 + 发货时效，容易断 |"
                       % (r["name"], r["stock"], span))
        else:
            out.append("| %s | %d | %d 天 | 🟢 库存尚可 |" % (r["name"], r["stock"], span))
    out.append("")
    if any_warn:
        out.append("> 有货源撑不过一个周期。**备货的前提是货源能续上**，"
                   "否则你只是把「缺货」换成了「断货」。")
    out.append("")


# ---------------------------------------------------------------- 命令行

SAMPLE = {
    "params": {"buyer_ship_fee": 8, "stock_days": 7, "daily_orders": 2},
    "suppliers": [
        {"sku": "USB-C 氮化镓充电器 65W", "cost": 38.5, "ship_fee": 6, "return_rate": 4.5,
         "moq": 2, "lead_days": 3, "stock": 400, "supports_onepiece": True,
         "supplier": "东莞某厂", "cert_3c": True, "invoice": True, "image_authorized": False,
         "listing_price": 79},
        {"sku": "桌面收纳盒 单个装", "cost": 12.8, "ship_fee": 5, "return_rate": 6,
         "moq": 10, "lead_days": 2, "stock": 900, "supports_onepiece": False,
         "supplier": "义乌档口", "invoice": False, "image_authorized": False,
         "listing_price": 39,
         "bundle": {"name": "桌面收纳套装", "items": "收纳盒 + 笔筒 + 线缆收纳 + 桌垫",
                    "cost": 26, "price": 59, "single_price": 39}},
        {"sku": "便携小风扇 USB 静音", "cost": 16.5, "ship_fee": 7, "return_rate": 11,
         "moq": 5, "lead_days": 6, "stock": 60, "supports_onepiece": True,
         "supplier": "中山厂家", "cert_3c": False, "invoice": True},
        {"sku": "显示器增高架铝合金", "cost": 21, "ship_fee": 6, "return_rate": 3,
         "moq": 1, "lead_days": 2, "stock": 260, "supports_onepiece": True,
         "supplier": "东莞", "invoice": True, "image_authorized": False,
         "listing_price": 49},
        {"sku": "车载手机支架 出风口款", "cost": 4.2, "ship_fee": 4, "return_rate": 5,
         "moq": 50, "lead_days": 1, "stock": 2000, "supports_onepiece": False,
         "supplier": "深圳配件厂", "invoice": True},
    ],
}


def run_check(text, out):
    out.append("## 货源文案自查")
    out.append("")
    hits = []
    low = text.lower()
    for f in R["listing_check"]["forbidden_phrases"]:
        if f["w"].lower() in low:
            hits.append(f)
    if hits:
        out.append("| 命中的词 | 为什么不能写 |")
        out.append("|---|---|")
        for f in hits:
            out.append("| 🔴 %s | %s |" % (f["w"], f["why"]))
        out.append("")
    else:
        out.append("✅ 未命中货源侧违禁词。")
        out.append("")
    out.append("### 货源侧替代表述")
    out.append("")
    out.append("| 不要写 | 改成 |")
    out.append("|---|---|")
    out.append("| 秒发 / 当天发货 | 现货 48 小时内交寄（写你能做到的） |")
    out.append("| 正品 / 官方 / 专柜同款 | 参数写实测；拿得出授权再写品牌 |")
    out.append("| 最低价 / 全网最低 | 不比价，写清为什么值这个价（材质、承重、配件） |")
    out.append("| 假一赔十 | 无授权就不写；改成「支持验货，不满意可退」 |")
    out.append("| 包邮 | 按实际运费模板设，偏远地区写清楚 |")
    out.append("| 质量保证 | 换成可核验的具体承诺（几号发货、怎么验） |")
    out.append("| 包退 | 写清退货运费谁承担、多久到账 |")
    out.append("")
    out.append("### 图片自查")
    out.append("")
    for r in R["listing_check"]["image_rules"]:
        out.append("- [ ] %s" % r)
    out.append("")
    return len(hits)


def quick_calc(args):
    it = {"sku": args.name, "cost": args.cost, "return_rate": args.return_rate,
          "ship_fee": args.ship_fee}
    params = {"buyer_ship_fee": args.buyer_fee, "target_margin": args.target_margin}
    r = calc_item(it, params)
    out = ["## 单条货源快速算账", ""]
    out.append("| 项 | 值 |")
    out.append("|---|---|")
    out.append("| 货源 | %s |" % r["name"])
    out.append("| 1688 拿货价 | ¥%s |" % money(r["cost"]))
    out.append("| 1688 运费 | ¥%s |" % money(r["ship"]))
    out.append("| 闲鱼运费 | ¥%s |" % money(r["buyer_fee"]))
    out.append("| 退货率 | %s |" % ("%.1f%%" % r["return_rate"]
                                    if r["return_rate"] is not None else PH % "缺"))
    out.append("| 最低可行挂价 | %s |" % (("¥%s" % money(r.get("price_min")))
                                         if r.get("price_min") is not None else PH % "缺数据"))
    out.append("| 单件净利 | %s |" % (("¥%s" % money(r["net_profit"]))
                                      if r["net_profit"] is not None else PH % "缺数据"))
    out.append("| 净毛利率 | %s |" % (pct(r["net_margin"])
                                      if r["net_margin"] is not None else PH % "缺数据"))
    out.append("| 判定 | %s %s |" % (r["level"], r["verdict"]))
    out.append("")
    for b in r["blocks"]:
        out.append("- 🔴 %s" % b)
    for w in r["warns"]:
        out.append("- 🟠 %s" % w)
    for n in r["notes"]:
        out.append("- %s" % n)
    out.append("")
    out.append("> 口径说明：")
    for s in R["supply_formula"]["steps"]:
        out.append("> - %s" % s)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="拾货源 · 1688 全新小件货源线")
    ap.add_argument("--input", help="sourcing.json 货源清单")
    ap.add_argument("--cost", type=float, help="1688 拿货价（快速算账）")
    ap.add_argument("--ship-fee", type=float, help="1688 发货运费")
    ap.add_argument("--buyer-fee", type=float, help="闲鱼发到买家运费")
    ap.add_argument("--return-rate", type=float, help="退货率 %")
    ap.add_argument("--target-margin", type=float, help="目标净利率（0.25 = 25%）")
    ap.add_argument("--name", default="快速试算", help="货源名称")
    ap.add_argument("--check", help="自查货源/上架文案")
    ap.add_argument("--categories", action="store_true", help="打印全新小件品类库")
    ap.add_argument("--bundles", action="store_true", help="打印组合打包策略")
    ap.add_argument("--gaps", action="store_true", help="只打印六个断层")
    ap.add_argument("--now", default=None, help="基准日期 YYYY-MM-DD")
    ap.add_argument("--out", help="输出到文件")
    args = ap.parse_args()

    global NOW
    NOW = datetime.strptime(args.now, "%Y-%m-%d") if args.now else datetime.now()
    load_rules()

    if args.categories:
        out = ["## 全新小件品类库（拾货源 · 1688 线）", ""]
        out.append("| 品类 | 拿货价带 | 建议挂价带 | 竞争强度 | 关键提醒 | 问供应商必问 |")
        out.append("|---|---|---|---|---|---|")
        for c in R["categories"]:
            out.append("| **%s** | ¥%s | ¥%s | %d/5 | %s | %s |"
                       % (c["name"], c["cost_band"], c["price_band"], c["competition"],
                          c["note"], c["must_ask"]))
        out.append("")
        text = "\n".join(out)
        print(text)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text)
        return 0

    if args.bundles:
        out = ["## 组合打包策略", ""]
        out.append("| 组合 | 含哪些件 | 单件价带 | 组合挂价带 | 客单价提升 | 为什么有效 |")
        out.append("|---|---|---|---|---|---|")
        for b in R["bundle_strategies"]:
            out.append("| **%s** | %s | ¥%s | ¥%s | %s | %s |"
                       % (b["name"], b["items"], b["single_band"], b["bundle_band"],
                          b["lift"], b["why"]))
        text = "\n".join(out)
        print(text)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text)
        return 0

    if args.gaps:
        out = []
        sec_gaps(out)
        text = "\n".join(out)
        print(text)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text)
        return 0

    if args.check:
        out = []
        n = run_check(args.check, out)
        text = "\n".join(out)
        print(text)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text)
        return 0 if n == 0 else 1

    if args.cost is not None:
        text = quick_calc(args)
        print(text)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text)
        return 0

    # ---- 整单
    if args.input:
        if not os.path.exists(args.input):
            print("错误：找不到输入文件 %s" % args.input)
            print("      模板：sourcing.template.json　示例：examples/sourcing.example.json")
            return 2
        try:
            with open(args.input, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print("错误：%s 不是合法 JSON（第 %d 行第 %d 列：%s）"
                  % (args.input, e.lineno, e.colno, e.msg))
            print("      常见原因：中文引号、末尾多逗号、缺右括号。")
            return 2
    else:
        data = SAMPLE
        print("::warning::未指定 --input，已用内置样例数据出单，不可当真实进货决策执行。",
              file=sys.stderr)

    items = data.get("suppliers") or []
    params = data.get("params") or {}
    if args.target_margin is not None:
        params["target_margin"] = args.target_margin
    if args.buyer_fee is not None:
        params["buyer_ship_fee"] = args.buyer_fee

    res_list = [calc_item(it, params) for it in items]

    out = []
    out.append("# 拾货源 · 1688 全新小件进货决策单")
    out.append("")
    out.append("> 生成器：`sourcing_plan.py`　规则库：`sourcing_rules.json`")
    out.append("> 基准日：%s" % NOW.strftime("%Y-%m-%d"))
    out.append("> 口径：脚本**不含任何真实经营数据**。拿货价、退货率、供应商信息全部由你填，"
               "缺项标占位，不替你估。")
    out.append("")
    out.append("---")
    out.append("")
    sec_overview(items, res_list, out)
    sec_pnl(items, res_list, params, out)
    sec_supply_mode(items, res_list, params, out)
    sec_gaps(out)
    sec_supplier(out)
    sec_buy_list(items, res_list, params, out)
    sec_listing_check(out)
    sec_bundles(out)
    sec_supply_risk(items, res_list, params, out)
    out.append("---")
    out.append("")
    out.append("> 执行顺序：先过六个断层 → 再谈价 → 算净利 → 定下单量 → 自己拍图上架。"
               "**别跳过断层那一步**，那是 1688 货翻车最集中的地方。")
    out.append("")

    text = "\n".join(out)
    print(text)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
