#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
design_brief.py — 图玲珑 · 设计需求一键出稿（主图文案 / 拍摄清单 / 详情页 / 短视频分镜 / 违规自查）

设计原则（重要）：
    本工具只产出**结构与文案骨架**，凡涉及实物事实（成色、型号、配置、瑕疵位置）一律留
    【占位符】，由人对着实物填。脚本绝不替你编造成色与配置——二手交易里一句编造的描述
    就是一次纠纷。

用法：
    # 1) 批量：读取选品候选（selection_scorer 同一份 candidates.json）
    python design_brief.py --input candidates.json --out design_brief.md

    # 2) 单件：现场给一个 SKU 出稿
    python design_brief.py --sku "二手 Switch OLED 掌机" --cost 1400 --price 1799 \
        --cond 95新 --points "港版/含底座" --out brief.md

    # 3) 只做违规自查（贴现有标题/详情页文案进去，看哪里会限流）
    python design_brief.py --check "全网最低价 加微信详聊"

依赖：仅标准库。规则全部读 design_rules.json，改口径只改 JSON。
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, "design_rules.json")

PLACEHOLDER = "【%s】"
RULES = {}


def load_rules():
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def pick_category(*texts):
    """按关键词命中选品类规则，命中不到回落「通用」。

    判定用「最长命中词优先、同长比命中数」，不用「字典里谁排前面谁赢」。
    否则「小米空气炸锅」会因为泛品牌词「小米」被判成二手手机——
    品牌词和品名词同时命中时，品名词才是真品类。
    """
    blob = " ".join(t for t in texts if t).lower()
    best_name, best_rule, best_key = None, None, None
    for name, rule in RULES["category_rules"].items():
        if name == "通用":
            continue
        hits = [kw for kw in rule.get("match", []) if kw.lower() in blob]
        if not hits:
            continue
        key = (max(len(h) for h in hits), len(hits))
        if best_key is None or key > best_key:
            best_name, best_rule, best_key = name, rule, key
    if best_name:
        return best_name, best_rule
    return "通用", RULES["category_rules"]["通用"]


def scan_ban(text):
    """扫描违规词，返回 [(级别, 分类, 命中词, 建议)]。"""
    hits = []
    for severity in ("error", "warn"):
        groups = RULES["ban_words"][severity]
        for group, words in groups.items():
            if group.startswith("_"):
                continue
            for w in words:
                if w in text:
                    hits.append((severity, group, w))
    # 去重（同一词可能在多组）
    seen, uniq = set(), []
    for h in hits:
        key = (h[0], h[2])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(h)
    return uniq


def suggest(severity, group, word):
    if "绝对化" in group:
        return "删除，或改为可举证的具体事实（如「连续 30 天好评率 98%」需有数据支撑）"
    if "站外引流" in group:
        return "删除，一律引导在闲鱼站内沟通下单"
    if "禁售" in group:
        return "删除；此类表述直接触发下架甚至封号"
    if "成色" in group:
        return "保留但必须与实物一致；不一致就是虚假描述，退货必输"
    return "与实际核对后再决定是否保留"


def money(v):
    try:
        return "¥%s" % format(float(v), ",.0f")
    except (TypeError, ValueError):
        return "¥—"


def price_block(cands, cost, price):
    """定价与价格锚点建议。没有成本价就只给锚点口径。"""
    lines = []
    low = cands.get("price_low")
    high = cands.get("price_high")
    if low and high:
        mid = (float(low) + float(high)) / 2
        lines.append("- 同款价格带：%s ~ %s，中位 **%s**" % (money(low), money(high), money(mid)))
        lines.append("- 建议挂牌价：中位 **-3%% ~ +5%%**，即 %s ~ %s"
                     % (money(mid * 0.97), money(mid * 1.05)))
        lines.append("- 前 3 天冲量价：中位 **-5%% ~ -8%%**，即 %s ~ %s"
                     % (money(mid * 0.95), money(mid * 0.92)))
    else:
        lines.append("- 同款价格带：%s（回闲鱼搜同类在售价填进来）" % (PLACEHOLDER % "同款在售价，如 ¥1500 ~ ¥1800"))
        lines.append("- 建议挂牌价：同款中位 -3% ~ +5%（无锚点数据时先按中位挂，别自定高价）")

    if cost and price:
        try:
            cost, price = float(cost), float(price)
            gross = price - cost
            rate = gross / price * 100 if price else 0
            lines.append("- 本单毛利：**%s**（毛利率 %.1f%%）" % (money(gross), rate))
            ok = gross >= 30 or rate >= 20
            lines.append("- 利润门槛（≥30 元 或 ≥20%%）：%s" % ("✅ 达标" if ok else "❌ 不达标，别做"))
        except (TypeError, ValueError):
            pass
    elif not cost:
        lines.append("- 本单毛利：%s（填成本价后才能算）" % (PLACEHOLDER % "成本价"))
    return lines


def trim_words(text, limit):
    """按空格边界截断，避免把英文单词 / 型号切一半。"""
    if len(text) <= limit:
        return text
    out, cur = [], 0
    for tok in text.split(" "):
        add = len(tok) + (1 if out else 0)
        if cur + add > limit:
            break
        out.append(tok)
        cur += add
    return " ".join(out) if out else text[:limit]


def main_copy(sku, cond, points, cat_rule, collect=None):
    """主图文案方案。只给骨架，事实留空。collect 收集真正会被发布的文案，供违规自查。"""
    core = sku.strip()
    if core.startswith("二手"):
        core = core[2:].strip()
    headline = "%s %s" % (cond, core) if cond else core
    headline = trim_words(headline, 16)
    sub = points[0] if points else (PLACEHOLDER % "一句核心事实，如 港版/含底座/无拆修")
    badges = " / ".join(cat_rule.get("badges", [])[:2])
    if collect is not None:
        collect.append(headline)
        collect.append(sub)
        collect.append(badges)
    return [
        "- **首图大字**（≤16 字，手机缩略图也看得清）：`%s`" % headline,
        "- **副标**（一行，说事实不说形容词）：`%s`" % sub,
        "- **价格锚点**：`%s`" % (PLACEHOLDER % "现价 ¥1799（对比同款中位 ¥1899）"),
        "- **角标**：`%s`" % badges,
        "- 版式：主体居中偏左，文字压右侧 1/3，底部留 8% 安全边距（防平台裁切）",
    ]


def shot_list(cat_rule, cat_name):
    base = RULES["shot_plan_base"]
    seen = set(s["name"] for s in base)
    extras = [e for e in cat_rule.get("extra_shots", []) if e not in seen]
    lines = ["### 拍摄清单（%s，共 %d 张）" % (cat_name, len(base) + len(extras))]
    for s in base:
        lines.append("%d. **%s** — %s" % (s["no"], s["name"], s["spec"]))
        lines.append("   - 目的：%s；💡 %s" % (s["purpose"], s["tip"]))
    n = len(base)
    for extra in extras:
        n += 1
        lines.append("%d. **%s**（品类必备）" % (n, extra))
    return lines


def detail_pages(cat_rule):
    lines = ["### 详情页结构（4 屏）"]
    for s in RULES["detail_screens"]:
        lines.append("**第 %d 屏 · %s**" % (s["no"], s["name"]))
        for c in s["content"]:
            lines.append("- %s" % c)
    must = cat_rule.get("must_state", [])
    if must:
        lines.append("")
        lines.append("**本品类必须写清（缺一条就等着退货）：**")
        for m in must:
            lines.append("- [ ] %s" % m)
    return lines


def video_block():
    v = RULES["short_video"]
    lines = ["### 短视频分镜（%s）" % v["duration"]]
    lines.append("| # | 时间 | 镜头 | 要点 |")
    lines.append("|---|---|---|---|")
    for s in v["shots"]:
        lines.append("| %d | %s | %s | %s |" % (s["no"], s["time"], s["shot"], s["note"]))
    return lines


def title_block(sku, cands, collect=None):
    sig = RULES["title_signals"]
    lines = ["### 标题建议（覆盖 4 类信号词，别堆形容词）"]
    parts = []
    parts.append(sig["成色词"][1])
    parts.append(sku)
    parts.append(PLACEHOLDER % "型号/容量/版本")
    parts.append(sig["信任词"][0])
    parts.append(sig["回血词"][0])
    if collect is not None:
        collect.append(" ".join(p for p in parts if not p.startswith("【")))
    lines.append("- 拼装骨架：`%s`" % " ".join(parts))
    lines.append("- 信号词参考：")
    for k in ("回血词", "成色词", "信任词", "应季词"):
        lines.append("  - %s：%s" % (k, "、".join(sig[k][:4])))
    kw = (cands or {}).get("keyword")
    if kw:
        lines.append("- 核心搜索词（来自选品）：`%s`" % kw)
    return lines


def compliance_block(all_text, cat_rule, cat_name):
    lines = ["### 违规自查"]
    hits = scan_ban(all_text)
    errs = [h for h in hits if h[0] == "error"]
    warns = [h for h in hits if h[0] == "warn"]
    if not hits:
        lines.append("- ✅ 未命中硬违规词 / 需核对词")
    for sev, group, word in errs:
        lines.append("- 🔴 **[%s] `%s`** → %s" % (group, word, suggest(sev, group, word)))
    for sev, group, word in warns:
        lines.append("- 🟡 [%s] `%s` → %s" % (group, word, suggest(sev, group, word)))
    risks = cat_rule.get("risks", [])
    if risks:
        lines.append("- 本品类高风险点：%s" % "；".join(risks))
    return lines


def ctr_block():
    lines = ["### 点击率优化要点"]
    for i, c in enumerate(RULES["ctr_checklist"], 1):
        lines.append("%d. %s" % (i, c))
    return lines


def build_one(item, idx):
    sku = item.get("sku") or item.get("title") or "未命名 SKU"
    cond = item.get("cond") or ""
    points = item.get("points") or ([item["note"]] if item.get("note") else [])
    ev = item.get("evidence") or {}
    cat_name, cat_rule = pick_category(sku, item.get("cat"), item.get("note"))

    out = []
    out.append("## %d. %s" % (idx, sku))
    out.append("")
    out.append("> 品类判定：**%s**　｜　信号来源：%s" %
               (cat_name, item.get("signal") or "—"))
    if item.get("cat"):
        out.append("> 选品归类：%s" % item["cat"])
    out.append("")

    out.append("### 定价与锚点")
    out.extend(price_block(ev, item.get("cost"), item.get("price")))
    out.append("")

    out.append("### 主图文案")
    publish = []          # 只收集真正会发出去的文案，供违规自查（不扫参考清单）
    out.extend(main_copy(sku, cond, points, cat_rule, publish))
    out.append("")

    out.extend(shot_list(cat_rule, cat_name))
    out.append("")

    out.extend(detail_pages(cat_rule))
    out.append("")

    out.extend(video_block())
    out.append("")

    out.extend(title_block(sku, ev, publish))
    out.append("")

    out.extend(compliance_block(" ".join(publish), cat_rule, cat_name))
    out.append("")
    out.extend(ctr_block())
    out.append("")
    out.append("---")
    out.append("")
    return out


def render_header(n):
    return [
        "# 设计需求单 · 图玲珑",
        "",
        "> 生成器：`design_brief.py`　规则库：`design_rules.json`",
        "> 口径：本单只给**结构与骨架**，凡带【】的事实必须对着实物填，脚本不会替你编。",
        "> SKU 数量：%d" % n,
        "",
        "---",
        "",
    ]


def main():
    global RULES
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="候选 JSON（与 selection_scorer 同一份）")
    ap.add_argument("--sku", help="单件出稿：SKU 名称")
    ap.add_argument("--cat", help="单件：品类描述")
    ap.add_argument("--cond", help="单件：成色，如 95新")
    ap.add_argument("--cost", type=float, help="单件：成本价")
    ap.add_argument("--price", type=float, help="单件：挂牌价")
    ap.add_argument("--points", action="append", help="单件：卖点，可多次传")
    ap.add_argument("--check", help="只做违规自查：直接传入要检查的文案")
    ap.add_argument("--out", help="输出 Markdown 路径")
    args = ap.parse_args()

    RULES = load_rules()

    if args.check:
        hits = scan_ban(args.check)
        print("# 违规自查结果\n")
        print("> 待检文案：%s\n" % args.check)
        if not hits:
            print("✅ 未命中违规词 / 需核对词。")
        for sev, group, word in hits:
            mark = "🔴 硬违规" if sev == "error" else "🟡 需核对"
            print("- %s ｜[%s] `%s` → %s" % (mark, group, word, suggest(sev, group, word)))
        return

    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            items = json.load(f)
        if isinstance(items, dict):
            items = items.get("candidates", [])
    elif args.sku:
        items = [{
            "sku": args.sku, "cat": args.cat, "cond": args.cond,
            "cost": args.cost, "price": args.price,
            "points": args.points or [],
            "evidence": {},
        }]
    else:
        ap.error("要么 --input candidates.json，要么 --sku '商品名'")

    out = render_header(len(items))
    for i, it in enumerate(items, 1):
        out.extend(build_one(it, i))

    text = "\n".join(out)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("[OK] 已写出 %d 个 SKU 的设计需求单 → %s" % (len(items), args.out), file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
