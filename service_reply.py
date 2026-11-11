#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
service_reply.py — 客如汇 · 客服话术生成与质检（判意图 / 出回复 / 让步阶梯 / 合规自查）

它解决客服每天最耗时的两个动作：
    1. 买家这句话什么意思、该怎么回   → 按 13 类意图判定，直接给可发送的回复
    2. 还价到底能让到哪               → 让步阶梯（空间=标价-底线，单次让一半，三次到线）

边界（和 design_brief / content_plan 一个原则）：
    本脚本**不编造成色、来源、库存、物流单号**。缺数据一律留【】占位，由你对着实物填。
    底线价格必须来自真实成本；没给成本时脚本用「成本+8%」推算，并在输出里标明是推算值。

用法：
    # 1) 回一条买家消息（最常用）
    python service_reply.py --msg "最低多少钱能出" --sku "二手 Switch OLED 掌机" \
        --price 1799 --cost 1400 --cond 95新

    # 2) 批量过一遍今天的咨询
    python service_reply.py --input buyers.json --out replies.md

    # 3) 生成《标准话术库》（角色交付物）
    python service_reply.py --lib --sku "二手 Switch OLED 掌机" --price 1799 --cost 1400

    # 4) 话术合规自查（自己写好的话术，发之前过一遍）
    python service_reply.py --check "最低给你 绝对正品 加微信聊"

依赖：仅标准库。话术全部读 service_rules.json，违规词表复用 design_rules.json。
"""

import argparse
import json
import os
import re
import sys

import design_brief as db

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, "service_rules.json")

R = {}
PH = "【%s】"

# 模板里允许出现的变量（其余一律当占位符处理，避免 .format 抛 KeyError）
VAR_KEYS = [
    "sku", "cond", "point", "flaw", "price", "band_low", "band_high",
    "offer", "floor", "ship", "logistics", "transit", "freight",
    "source", "warranty", "accessories", "must_state",
]


# ---------------------------------------------------------------- 基础

def load_rules():
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def num(v):
    """把输入转成 float；转不了返回 None（不瞎猜）。"""
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("¥", "").strip())
    except (TypeError, ValueError):
        return None


def fmt_money(v):
    if v is None:
        return None
    return db.money(v)


def zh_clean(s):
    """去掉中文之间的多余空格（模板变量多为英文型号，拼接后会冒出「掌机 前」）。"""
    s = re.sub(r"(?<=[\u4e00-\u9fa5]) +(?=[\u4e00-\u9fa5])", "", s)
    s = re.sub(r"(?<=[\u4e00-\u9fa5]) +(?=【)", "", s)
    s = re.sub(r"(?<=】) +(?=[\u4e00-\u9fa5])", "", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def render(tpl, ctx):
    """填变量。缺的留【占位】，绝不留空或猜。"""
    out = tpl
    for key in VAR_KEYS:
        val = ctx.get(key)
        if val in (None, ""):
            val = PH % key
        out = out.replace("{%s}" % key, str(val))
    # 模板里剩下的未知变量也转占位符，不让 format 崩
    out = re.sub(r"\{(\w+)\}", lambda m: PH % m.group(1), out)
    return zh_clean(out)


# ---------------------------------------------------------------- 上下文

def build_ctx(item):
    """把候选/参数整理成模板变量。数字留一份原始值给体检算账。"""
    item = item or {}
    sku = (item.get("sku") or "").strip()
    points = [p for p in (item.get("points") or []) if p]
    cond = item.get("cond") or ""
    ev = item.get("evidence") or {}

    price = num(item.get("price"))
    cost = num(item.get("cost"))
    floor = num(item.get("floor"))
    floor_note = ""

    if floor is None and cost is not None:
        pct = R["ladder"]["min_margin_pct"]
        floor = round(cost * (1 + pct / 100.0), 2)
        floor_note = "按成本 +%d%% 自动推算" % pct

    offer = None
    if price is not None and floor is not None and price > floor:
        offer = round(price - (price - floor) / 2.0, 2)

    # 品类 → 必答项
    cat_name, cat_rule = db.pick_category(sku, item.get("cat"), item.get("note"))
    must_state = "、".join(cat_rule.get("must_state", [])[:3]) if cat_rule else ""

    flaw = item.get("flaw") or ""
    if not flaw and points:
        cand = [p for p in points if re.search(r"划痕|痕|磕|瑕疵|磨|掉漆|黄", p)]
        flaw = cand[0] if cand else ""
    if not flaw:
        flaw = PH % "瑕疵位置与程度，如屏幕左下轻微划痕"

    ctx = {
        "sku": sku or (PH % "商品名"),
        "cond": cond or (PH % "成色"),
        "point": points[0] if points else (PH % "一句核心事实"),
        "flaw": flaw,
        "band_low": fmt_money(num(ev.get("price_low"))) or (PH % "同款价带下限"),
        "band_high": fmt_money(num(ev.get("price_high"))) or (PH % "同款价带上限"),
        "_has_band": bool(num(ev.get("price_low")) and num(ev.get("price_high"))),
        "ship": item.get("ship") or (PH % "今日 17:00"),
        "logistics": item.get("logistics") or (PH % "快递公司"),
        "transit": item.get("transit") or (PH % "2-3 天到"),
        "freight": item.get("freight") or (PH % "包邮 / 买家自理"),
        "source": item.get("source") or (PH % "自用一手/二手购入"),
        "warranty": item.get("warranty") or (PH % "是否在保"),
        "accessories": item.get("accessories") or (PH % "配件清单"),
        "must_state": must_state or (PH % "该品类的必答项"),
        # 原始数值（不参与模板）
        "_price": price, "_cost": cost, "_floor": floor, "_offer": offer,
        "_floor_note": floor_note, "_cat": cat_name,
    }
    ctx["price"] = fmt_money(price) or (PH % "标价")
    ctx["floor"] = fmt_money(floor) or (PH % "底线价")
    ctx["offer"] = fmt_money(offer) or (PH % "中间价")
    return ctx


# ---------------------------------------------------------------- 意图判定

def offer_price(msg, floor):
    """从消息里抠「出价」数字。

    要区分两种数字：
      「800 卖不卖」→ 出价，低价
      「便宜 100 行吗」→ 让价额，不是出价
    做法：带「元/块」的一律当出价；不带的只在 floor 的 30%~90% 区间内才算，
    并排除「95新 / 128G / 3成新」这类规格数字。
    """
    if not floor:
        return None
    best = None
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(元|块)?", msg or ""):
        raw, unit = m.group(1), m.group(2)
        v = float(raw)
        nxt = (msg or "")[m.end():m.end() + 2]
        if re.match(r"\s*(新|成|G|g|寸|%|个|台|件|天|年|月|小时|毫安|mAh)", nxt):
            continue
        if unit:
            hit = 0 < v < floor * 0.9
        else:
            hit = floor * 0.3 <= v <= floor * 0.9
        if hit:
            best = v if best is None else max(best, v)
    return best


def classify(msg, ctx=None):
    """返回 (主意图, 命中词, 全部命中意图)。风险意图优先级天然更高。"""
    text = (msg or "").strip().lower()
    found = []
    for it in R["intents"]:
        hits = [k for k in it["keywords"] if k.lower() in text]
        if hits:
            found.append({
                "intent": it,
                "hits": hits,
                "priority": it["priority"],
                "longest": max(len(k) for k in hits),
            })

    # 数字出价：关键词抓不到「800卖不卖」，补一层
    floor = (ctx or {}).get("_floor")
    off = offer_price(msg, floor)
    if off is not None:
        tag = "报价 %s" % fmt_money(off)
        low = next(i for i in R["intents"] if i["id"] == "lowball")
        exist = [f for f in found if f["intent"]["id"] == "lowball"]
        if exist:
            exist[0]["priority"] += 5
            exist[0]["hits"].append(tag)
        else:
            # 72 高于议价 65：带超低出价的，本质是「离谱低价」而不是普通议价
            found.append({"intent": low, "hits": [tag], "priority": 72, "longest": 6})

    if not found:
        return None, [], []
    found.sort(key=lambda x: (-x["priority"], -x["longest"]))
    top = found[0]
    others = [f for f in found[1:] if f["intent"]["id"] != top["intent"]["id"]]
    return top["intent"], top["hits"], others


# ---------------------------------------------------------------- 报价体检

def quote_check(ctx):
    """只用真实数字算账，缺失就不算——不拿假数糊人。"""
    price, cost, floor = ctx["_price"], ctx["_cost"], ctx["_floor"]
    lines = []
    if price is None and cost is None and floor is None:
        return lines

    if price is not None:
        lines.append("- 标价：**%s**" % fmt_money(price))
    if cost is not None:
        lines.append("- 成本：%s" % fmt_money(cost))
    if floor is not None:
        tip = "（%s）" % ctx["_floor_note"] if ctx["_floor_note"] else "（你给的底线）"
        lines.append("- 底线：**%s** %s" % (fmt_money(floor), tip))

    if price is not None and floor is not None:
        space = price - floor
        if space > 0:
            lines.append("- 可让空间：%s，单次让步 ≤ %s，三次到线"
                         % (fmt_money(space), fmt_money(round(space / 2, 2))))
        else:
            lines.append("- ⚠️ **标价已低于底线**：没有议价空间，任何还价都直接拒绝")

    if price is not None and cost is not None and price > 0:
        gp = price - cost
        lines.append("- 毛利率：%.1f%%（毛利 %s）" % (gp / price * 100, fmt_money(gp)))
        if floor is not None:
            left = floor - cost
            if left >= 0:
                lines.append("- 让到底线仍赚 %s（毛利率 %.1f%%）"
                             % (fmt_money(left), (left / floor * 100) if floor else 0))
            else:
                lines.append("- 🔴 **底线低于成本**：让到底线是亏的，请重新核算")
    return lines


# ---------------------------------------------------------------- 合规自查

def scan(texts):
    """对**要发出去的话**做违规词扫描。参考词表不扫，只扫正文。"""
    if not db.RULES:
        db.RULES = db.load_rules()
    results = []
    for label, text in texts:
        # 【】里是待填的占位符，不是要发布的内容，不能算进违规扫描
        plain = re.sub(r"【[^】]*】", "", text or "")
        hits = db.scan_ban(plain)
        results.append((label, text, hits))
    return results


# ---------------------------------------------------------------- 单条输出

def block_single(msg, item, idx=None):
    ctx = build_ctx(item)
    intent, hits, others = classify(msg, ctx)

    out = []
    head = "## " + ("%d. " % idx if idx else "") + "买家：`%s`" % msg.strip()
    out.append(head)
    out.append("")

    if intent is None:
        out.append("**判定**：未命中任何已知意图 → 按「先问清需求」处理")
        out.append("")
        out.append("> 在的，你想确认哪一项？我拍给你看。")
        out.append("")
        out.append("**下一步动作**")
        out.append("- 别急着报价，先确认型号/成色要求/收货城市，这三项决定能不能成交")
        out.append("- 判不准就补一句开放式提问，让买家自己说需求")
        out.append("")
        out.append("**商品上下文**：%s ｜ %s ｜ %s" % (ctx["sku"], ctx["cond"], ctx["price"]))
        out.append("")
        return "\n".join(out)

    risk_mark = " 🔴 风险场景" if intent.get("risk") else ""
    out.append("**判定**：%s（命中：%s）　优先级 %d%s"
               % (intent["name"], "、".join(hits[:6]), intent["priority"], risk_mark))
    if others:
        out.append("")
        out.append("> 这句话里还含：%s —— 先把风险那条回完，再处理它"
                   % "、".join(o["intent"]["name"] for o in others[:3]))
    out.append("")

    # ---- 回复
    # 模板：议价走阶梯；没有同款价带数据时换掉第 1 条，避免只剩一堆【】发不出去
    tpls = list(intent["reply"])
    if intent.get("reply_no_band") and not ctx.get("_has_band") and tpls:
        tpls[0] = intent["reply_no_band"]

    out.append("### 建议回复")
    out.append("")
    if intent.get("use_ladder"):
        tips = R["ladder"]["stage_tip"]
        for i, tpl in enumerate(tpls):
            label = tips[i] if i < len(tips) else "继续压价，不再让"
            out.append("**%s**" % label)
            out.append("")
            out.append("> %s" % render(tpl, ctx))
            out.append("")
        if ctx["_floor"] is None:
            out.append("> ⚠️ 没有底线数据，上面第 3 条里的价位是占位符。先给 `--cost` 或 `--floor`，否则不要报底价。")
            out.append("")
    else:
        ab = ["说法 A", "说法 B", "说法 C"]
        if len(tpls) > 1:
            out.append("> 下面 %d 条任选一条发，别连发。" % len(tpls))
            out.append("")
        for i, tpl in enumerate(tpls):
            if len(tpls) > 1:
                out.append("**%s**" % (ab[i] if i < len(ab) else "备选"))
                out.append("")
            out.append("> %s" % render(tpl, ctx))
            out.append("")

    # ---- 报价体检（只有议价相关才出）
    if intent.get("use_ladder") or intent["id"] == "lowball":
        qc = quote_check(ctx)
        if qc:
            out.append("### 报价体检")
            out.append("")
            out.extend(qc)
            out.append("")

    # ---- 动作
    if intent.get("actions"):
        out.append("### 下一步动作")
        out.append("")
        for a in intent["actions"]:
            out.append("- %s" % render(a, ctx))
        out.append("")

    if intent.get("dont"):
        out.append("### 不要做")
        out.append("")
        for d in intent["dont"]:
            out.append("- %s" % render(d, ctx))
        out.append("")

    # ---- 话术自查
    texts = [(("第 %d 次" % (i + 1)) if intent.get("use_ladder") else ("回复 %d" % (i + 1)), render(t, ctx))
             for i, t in enumerate(tpls)]
    res = scan(texts)
    out.append("### 话术自查")
    out.append("")
    bad = False
    for label, text, hits in res:
        if hits:
            bad = True
            for sev, group, word in hits:
                mark = "🔴 硬违规" if sev == "error" else "🟡 需核对"
                out.append("- %s ｜%s ｜`%s` 命中 `%s`" % (mark, label, word, group))
                out.append("  - 改法：%s" % db.suggest(sev, group, word))

    # 字数：闲鱼聊天窗窄，超了买家读不完
    mx = R["tone"]["max_chars"]
    over = []
    for label, text in texts:
        n = len(re.sub(r"【[^】]*】", "", text))
        if n > mx:
            over.append((label, n))
    for label, n in over:
        out.append("- ⚠️ %s 共 %d 字，超过 %d 字上限，发之前砍掉修饰" % (label, n, mx))

    if not bad and not over:
        out.append("✅ 未命中违规词，字数均在 %d 字内" % mx)
    elif not bad:
        out.append("- 违规词：✅ 未命中")
    elif all(sev != "error" for _, _, hits in res for sev, _, _ in hits):
        out.append("- 硬违规：✅ 无（上面 🟡 几处只要与实物一致就可以发）")
    out.append("")
    out.append("---")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- 话术库

def block_lib(items):
    """生成《标准话术库》——角色要求的那份交付物。"""
    ctxs = [build_ctx(it) for it in (items or [{}])]
    out = ["# 标准话术库", ""]
    sku_line = " / ".join(c["sku"] for c in ctxs)
    out.append("> 商品：%s" % sku_line)
    out.append("> 规则版本：service_rules v%s ｜ 生成：本仓库 `service_reply.py --lib`" % R["version"])
    out.append("")
    out.append("**说话口径**（每条回复都受这几条约束）：")
    out.append("")
    out.append("- 单条 ≤ %d 字，闲鱼聊天窗窄，长段落没人读完" % R["tone"]["max_chars"])
    for r in R["tone"]["rules"]:
        out.append("- %s" % r)
    out.append("")
    out.append("---")
    out.append("")

    # 一、售前
    out.append("## 一、售前：开场与介绍")
    out.append("")
    pre = next(i for i in R["intents"] if i["id"] == "pre_sale")
    for i, tpl in enumerate(pre["reply"], 1):
        out.append("%d. %s" % (i, render(tpl, ctxs[0])))
    out.append("")
    out.append("**主动提问清单**（问到这些，成交率才会上去）：")
    out.append("")
    for q in R["prefill_base"]:
        out.append("- %s" % q)
    cat = ctxs[0]["_cat"]
    cat_qs = R["prefill_by_cat"].get(cat) or R["prefill_by_cat"].get("通用") or []
    if cat_qs:
        out.append("")
        out.append("**%s 品类必问**：" % cat)
        out.append("")
        for q in cat_qs:
            out.append("- %s" % q)
    out.append("")

    # 二、异议
    out.append("## 二、异议处理：三类标准应答")
    out.append("")
    out.append("### 1. 价格异议（让步阶梯）")
    out.append("")
    out.append("| 次数 | 动作 | 话术 |")
    out.append("|---|---|---|")
    price_it = next(i for i in R["intents"] if i["id"] == "price")
    tips = R["ladder"]["stage_tip"]
    p_tpls = list(price_it["reply"])
    if price_it.get("reply_no_band") and not ctxs[0].get("_has_band"):
        p_tpls[0] = price_it["reply_no_band"]
    for i, tpl in enumerate(p_tpls):
        action = tips[i] if i < len(tips) else "继续压"
        action = re.sub(r"^第\s*\d+\s*次[:：]?\s*", "", action)   # 次数列已有，别重复
        out.append("| 第 %d 次 | %s | %s |" % (i + 1, action, render(tpl, ctxs[0])))
    out.append("")
    qc = quote_check(ctxs[0])
    if qc:
        out.append("**这台的账**：")
        out.append("")
        out.extend(qc)
        out.append("")
    out.append("> 铁律：三次到线，第四次不接。省下来的每块钱都是从毛利里割的，"
               "为一个磨价的买家让到底线，不如留给下一个直接拍的。")
    out.append("")

    for title, iid in (("2. 成色异议", "condition"), ("3. 发货时效异议", "shipping")):
        it = next(i for i in R["intents"] if i["id"] == iid)
        out.append("### %s" % title)
        out.append("")
        for tpl in it["reply"]:
            out.append("- %s" % render(tpl, ctxs[0]))
        out.append("")

    # 三、售后
    out.append("## 三、售后：退换货流程")
    out.append("")
    out.append("| 情形 | 谁承担 | 处理步骤 |")
    out.append("|---|---|---|")
    for c in R["after_sales"]:
        out.append("| %s | %s | %s |" % (c["case"], c["who"], " → ".join(c["steps"])))
    out.append("")
    out.append("> 通用顺序：先分类（功能/描述不符/主观/人为/物流）→ 再定责任 → 全程留在平台内 → 退货开箱同样录像。")
    out.append("")

    # 四、复购
    out.append("## 四、复购：客户沉淀")
    out.append("")
    out.append("- 成交后 1 天：确认收到、功能正常（不推销，只要一句确认）")
    out.append("- 成交后 7-15 天：同类新品到货时点对点提示，不群发")
    out.append("- 标签化：按品类/价位/挑剔程度打标，下次来直接推匹配的，不推贵的不推差的")
    out.append("- 差评预警：出现不满先解决货，再谈评价；不拿补偿换好评（平台明令禁止）")
    out.append("")

    # 五、红线
    out.append("## 五、高风险场景红线")
    out.append("")
    for r in R["redlines"]:
        out.append("- %s" % r)
    out.append("")
    out.append("### 风险场景速查")
    out.append("")
    out.append("| 场景 | 一眼识别 | 一句话应对 |")
    out.append("|---|---|---|")
    for it in R["intents"]:
        if not it.get("risk"):
            continue
        out.append("| %s | %s | %s |"
                   % (it["name"], "、".join(it["keywords"][:4]), render(it["reply"][0], ctxs[0])))
    out.append("")

    # 六、禁用替换
    out.append("## 六、禁用表达 → 替换说法")
    out.append("")
    out.append("| 别说 | 为什么 | 改说 |")
    out.append("|---|---|---|")
    for f in R["forbidden_phrases"]:
        out.append("| `%s` | %s | %s |" % (f["bad"], f["why"], f["good"]))
    out.append("")

    # 七、自查
    out.append("## 七、话术自查")
    out.append("")
    all_texts = []
    for it in R["intents"]:
        for i, tpl in enumerate(it["reply"], 1):
            all_texts.append(("%s #%d" % (it["name"], i), render(tpl, ctxs[0])))
    res = scan(all_texts)
    errs, warns = [], []
    for lab, t, hits in res:
        for sev, group, word in hits:
            (errs if sev == "error" else warns).append((lab, group, word))
    if errs:
        for lab, group, word in errs:
            out.append("- 🔴 %s ｜`%s`（%s）—— 必须改掉再发" % (lab, word, group))
    if warns:
        words = sorted({w for _, _, w in warns})
        out.append("- 🟡 %d 处需与实物核对：%s" % (len(warns), "、".join("`%s`" % w for w in words)))
        out.append("  - 这类不是违规词，只要**与实物一致**就可以发；不一致就是虚假描述")
    if not errs:
        n_err = sum(len(v) for k, v in db.RULES["ban_words"]["error"].items() if not k.startswith("_"))
        out.append("")
        out.append("✅ %d 条标准话术**无硬违规**（硬违规词表 %d 词已全扫）。" % (len(all_texts), n_err))
    out.append("")
    out.append("> 自查只覆盖词表能抓的部分。**「绝对化」「无瑕疵」这类改了词也未必合规**——"
               "根子在承诺超出实物，措辞只是表象。")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- 入口

def main():
    ap = argparse.ArgumentParser(description="客如汇 · 客服话术生成与质检")
    ap.add_argument("--msg", help="一条买家原话")
    ap.add_argument("--input", help="批量 JSON（每条含 msg 与可选 sku/price/cost/cond/points）")
    ap.add_argument("--lib", action="store_true", help="生成《标准话术库》")
    ap.add_argument("--check", help="对已有话术做合规自查")
    ap.add_argument("--out", help="输出到文件（默认打印）")
    # 上下文
    ap.add_argument("--sku")
    ap.add_argument("--price", help="标价")
    ap.add_argument("--cost", help="真实成本（议价底线由此推算）")
    ap.add_argument("--floor", help="你能接受的最低成交价（优先于成本推算）")
    ap.add_argument("--cond")
    ap.add_argument("--points", action="append", help="卖点，可多次传")
    ap.add_argument("--ship")
    ap.add_argument("--source")
    ap.add_argument("--warranty")
    ap.add_argument("--accessories")
    ap.add_argument("--flaw")
    args = ap.parse_args()

    global R
    R = load_rules()
    db.RULES = db.load_rules()   # 违规词表在 design_rules.json

    ctx_item = {
        "sku": args.sku, "price": args.price, "cost": args.cost, "floor": args.floor,
        "cond": args.cond, "points": args.points or [],
        "ship": args.ship, "source": args.source, "warranty": args.warranty,
        "accessories": args.accessories, "flaw": args.flaw,
    }

    buf = []

    # 模式 4：合规自查
    if args.check:
        res = scan([("待检话术", args.check)])
        buf.append("# 话术合规自查\n")
        buf.append("> 待检文案：%s\n" % args.check)
        total = 0
        for label, text, hits in res:
            if not hits:
                buf.append("✅ 未命中违规词。\n")
            for sev, group, word in hits:
                total += 1
                mark = "🔴 硬违规" if sev == "error" else "🟡 需核对"
                buf.append("- %s ｜`%s` ｜%s" % (mark, word, group))
                buf.append("  - 改法：%s" % db.suggest(sev, group, word))
        if total:
            buf.append("\n共 %d 处。🔴 的必须改掉再发，否则限流或下架。" % total)
        text = "\n".join(buf)
        print(text)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text)
        return 0

    # 模式 3：话术库
    if args.lib:
        items = []
        if args.input:
            data = json.load(open(args.input, "r", encoding="utf-8"))
            items = data if isinstance(data, list) else [data]
        else:
            items = [ctx_item]
        text = block_lib(items)
        print(text)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text)
            print("\n[已写入 %s]" % args.out, file=sys.stderr)
        return 0

    # 模式 2：批量
    if args.input:
        data = json.load(open(args.input, "r", encoding="utf-8"))
        rows = data if isinstance(data, list) else [data]
        buf.append("# 客服应答 · 批量")
        buf.append("")
        buf.append("> 共 %d 条咨询。判定按「风险优先」排序：同一句话同时含风险与议价时，先回风险。" % len(rows))
        buf.append("")
        for i, row in enumerate(rows, 1):
            merged = dict(ctx_item)
            for k, v in row.items():
                if v not in (None, ""):
                    merged[k] = v
            buf.append(block_single(row.get("msg") or "", merged, idx=i))
        text = "\n".join(buf)
        print(text)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text)
            print("\n[已写入 %s]" % args.out, file=sys.stderr)
        return 0

    # 模式 1：单条
    if args.msg:
        text = block_single(args.msg, ctx_item)
        print(text)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text)
            print("\n[已写入 %s]" % args.out, file=sys.stderr)
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
