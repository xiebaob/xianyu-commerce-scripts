#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
content_plan.py — 文种草 · 内容排期与选题出稿（关键词矩阵 / 选题池 / 排期 / 脚本要点 / 文案体检）

它解决内容运营每天最耗时的三个动作：
    1. 今天发什么         → 选题池：按 8 条公式 × 你的 SKU 自动生成候选标题，按适配度排序
    2. 关键词怎么铺        → 四层关键词矩阵（品牌/型号/属性/长尾转化）
    3. 什么时候发、发什么形式 → 一周发布节奏 + 每条内容的脚本要点

边界（重要，和 design_brief 一个原则）：
    本脚本**不编造任何搜索量、价格、销量数据**。关键词需要你回闲鱼搜索框核对下拉词；
    标题里带【】的部分必须换成真实信息；公式 F2「第 k 个我踩过」的 k 必须是你真踩过的那个。

用法：
    # 1) 生成 N 天排期（读选品候选）
    python content_plan.py --input candidates.json --days 7 --out content_plan.md

    # 2) 单件快出选题池
    python content_plan.py --sku "二手 Switch OLED 掌机" --price 1799 --cond 95新

    # 3) 文案体检（发布前打分，看哪项拖后腿）
    python content_plan.py --review --title "标题" --body "正文"

    # 4) 违规自查
    python content_plan.py --check "待发布文案"

依赖：仅标准库。规则全部读 content_rules.json。
"""

import argparse
import datetime
import json
import os
import re
import sys

import design_brief as db

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, "content_rules.json")

R = {}
PH = "【%s】"
WEEK_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 公式 → 首选钩子类型
FORMULA_HOOK = {
    "F1": "价格钩", "F2": "反常识钩", "F3": "价格钩", "F4": "身份钩",
    "F5": "证据钩", "F6": "反常识钩", "F7": "稀缺钩", "F8": "证据钩",
}


def load_rules():
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def money(v):
    try:
        return "¥%s" % format(float(v), ",.0f")
    except (TypeError, ValueError):
        return PH % "价格"


# ---------------------------------------------------------------- 关键词

def extract_model_tokens(sku):
    """从 SKU 抽型号词：拉丁字母/数字串，长度≥2。中文名不当型号。"""
    toks = re.findall(r"[A-Za-z][A-Za-z0-9\-]*|\d{1,4}\s?[GgTt][Bb]?|\d{2,4}", sku)
    out = []
    for t in toks:
        t = t.strip()
        if len(t) >= 2 and t.lower() not in ("二手",):
            if t not in out:
                out.append(t)
    return out


def detect_brand(sku):
    low = sku.lower()
    best = None
    for k, v in R["brand_dict"].items():
        if k in low:
            if best is None or len(k) > len(best[0]):
                best = (k, v)
    return best[1] if best else PH % "品牌"


def keyword_matrix(item):
    """四层关键词。全部标注「待核验」——脚本不提供搜索量。"""
    sku = item.get("sku") or ""
    cond = item.get("cond") or ""
    points = item.get("points") or []
    brand = detect_brand(sku)
    toks = extract_model_tokens(sku)
    model = " ".join(toks) if toks else PH % "型号"

    attr = []
    if cond:
        attr.append(cond)
    for kw in ("国行", "港版", "日版", "美版", "无锁", "有锁", "原装"):
        if kw in sku or any(kw in p for p in points):
            attr.append(kw)
    if any("含" in p or "带" in p for p in points):
        attr.append(PH % "配件名")
    if not attr:
        attr.append(PH % "成色/版本/配件")

    rows = [
        ("品牌词", brand, "曝光最大、竞争最烈，必须配型号词用"),
        ("型号词", model, "转化主力，买家真正搜的是「型号+二手」"),
        ("属性词", " ".join(attr), "筛掉预算不匹配的人，反而提高咨询率"),
    ]

    # 型号已含品牌时不再重复拼品牌，避免「任天堂 Switch Switch」这类废词
    dup = brand.lower() and model.lower().startswith(brand.lower())
    longtails = []
    alt = item.get("alt") or PH % "对比型号"
    for tpl in R["longtail_templates"]:
        kw = tpl.format(model=model, cond=cond or PH % "成色", alt=alt)
        kw = re.sub(r"\s+", " ", kw).strip()
        if dup:
            kw = kw.replace(brand + " ", "")
        longtails.append(kw)
    rows.append(("长尾转化词", "\n".join(longtails[:4]), "搜索量小但意图最强，优先用作标题"))
    return rows


# ---------------------------------------------------------------- 选题

def cat_checklist_counts(item):
    """从 design_rules 的品类规则取「必填项数 / 风险点数」，让标题里的数字是真的。"""
    try:
        _, rule = db.pick_category(item.get("sku", ""), item.get("cat"), item.get("note"))
        return len(rule.get("must_state") or []), len(rule.get("risks") or [])
    except Exception:
        return 0, 0


def render_title(tpl, item, month):
    sku = item.get("sku") or ""
    model = sku[2:].strip() if sku.startswith("二手") else sku
    price = item.get("price")
    new_price = item.get("new_price")
    if price and new_price:
        try:
            save = money(float(new_price) - float(price))
        except (TypeError, ValueError):
            save = PH % "省多少"
    else:
        save = PH % "省多少"

    point = (item.get("points") or [PH % "核心卖点"])[0]
    n_check, n_pit = cat_checklist_counts(item)
    ctx = {
        "model": model,
        "price": money(price) if price else PH % "价格",
        "new_price": money(new_price) if new_price else PH % "新机价",
        "save": save,
        "cond": item.get("cond") or PH % "成色",
        "point": point,
        "alt": item.get("alt") or PH % "对比型号",
        "gap": PH % "价差",
        "days": item.get("days") or PH % "使用天数",
        "month": str(month),
        "n": str(n_pit or 5),
        "n_pit": str(n_pit) if n_pit else PH % "坑数",
        "n_check": str(n_check) if n_check else PH % "步数",
        "k": PH % "真踩过的序号",
    }
    try:
        out = tpl.format(**ctx)
    except (KeyError, IndexError):
        return tpl
    # 中文之间不留空格（模板变量多为英文型号，拼接后常出现「掌机 前」）
    out = re.sub(r"(?<=[\u4e00-\u9fa5]) +(?=[\u4e00-\u9fa5])", "", out)
    out = re.sub(r"(?<=[\u4e00-\u9fa5]) +(?=【)", "", out)
    out = re.sub(r"(?<=】) +(?=[\u4e00-\u9fa5])", "", out)
    return re.sub(r" +", " ", out).strip()


def fit_score(f, item):
    """排序 = 公式经验权重 + 数据齐备度。weight 在 content_rules.json 里，可自己调。"""
    when = f.get("when") or {}
    s = float(f.get("weight", 1)) * 2
    cats = when.get("cat_any")
    if cats:
        blob = " ".join([item.get("sku", ""), item.get("cat", ""), item.get("note", "")])
        s += 2 if any(c in blob for c in cats) else -1
    if item.get("price"):
        s += 2
    if item.get("alt"):
        s += 1
    if when.get("need_price") and not item.get("price"):
        s -= 8
    if when.get("need_alt") and not item.get("alt"):
        s -= 8
    return s


def topic_pool(item, per_sku, month):
    scored = [(fit_score(f, item), f) for f in R["topic_formulas"]]
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    picked = scored[:per_sku]
    return [{
        "fid": f["id"], "name": f["name"], "form": f["form"],
        "title": render_title(f["title"], item, month),
        "outline": f["outline"], "why": f["why"],
        "score": sc,
    } for sc, f in picked]


def pick_hook(fid, item):
    want = FORMULA_HOOK.get(fid, "反常识钩")
    text = next((h["text"] for h in R["hooks"] if h["type"] == want), "")
    ctx = {
        "days": item.get("days") or PH % "使用天数",
        "price": money(item.get("price")) if item.get("price") else PH % "价格",
        "new_price": money(item.get("new_price")) if item.get("new_price") else PH % "新机价",
    }
    try:
        return want, text.format(**ctx)
    except (KeyError, IndexError):
        return want, text


# ---------------------------------------------------------------- 排期

def build_schedule(pools, start, days):
    """跨 SKU 轮转，避免连续几天同一个 SKU。"""
    queue = []
    max_len = max((len(p) for p in pools), default=0)
    for i in range(max_len):
        for key, topics in pools.items():
            if i < len(topics):
                queue.append((key, topics[i]))
    if not queue:
        return []

    rows = []
    for d in range(days):
        date = start + datetime.timedelta(days=d)
        slot = R["publish_slots"][date.weekday() % 7]
        key, t = queue[d % len(queue)]
        rows.append({"date": date, "slot": slot, "sku": key, "topic": t})
    return rows


# ---------------------------------------------------------------- 文案体检

def review_text(title, body):
    text = (title or "") + "\n" + (body or "")
    items, total = [], 0
    for r in R["review_rubric"]:
        name, weight = r["item"], r["weight"]
        got, note = weight, "达标"

        if name == "标题长度":
            n = len(re.sub(r"\s", "", title))
            if not (12 <= n <= 25):
                got, note = weight - 10, "当前 %d 字，建议 12-25 字" % n
        elif name == "标题含关键词":
            has_model = bool(re.search(r"[A-Za-z]{2,}|\d{2,}", title))
            has_ask = any(k in title for k in ("值得", "怎么", "避坑", "选", "吗", "多少钱"))
            if not (has_model or has_ask):
                got, note = weight - 15, "只有泛品类词，缺型号或决策疑问"
        elif name == "标题含数字或价格":
            if not re.search(r"\d", title):
                got, note = weight - 8, "没有具体数字/价格，纯形容词"
        elif name == "开头钩子":
            head = "\n".join((body or "").splitlines()[:3])
            strong = re.search(r"[¥\d]|自用|不是商家|不建议|别买|说实话", head)
            weak = re.search(r"大家好|今天给|hello|各位", head, re.I)
            if weak:
                got, note = weight - 15, "开头是寒暄，改成身份/价格/反常识"
            elif not strong:
                got, note = weight - 8, "前 3 行没有钩子"
        elif name == "瑕疵披露":
            has_flaw = any(k in (body or "") for k in ("瑕疵", "划痕", "磕碰", "磨损", "掉漆", "电池健康", "拆修", "成色"))
            fake = any(k in (body or "") for k in ("无瑕疵", "完美成色", "零磨损"))
            if fake:
                got, note = weight - 12, "写了「无瑕疵/完美」，这是退货主因"
            elif not has_flaw:
                got, note = weight - 8, "没提任何瑕疵与成色依据"
        elif name == "场景具体性":
            # 注意："今天"里的"天"不算场景，必须是具体使用情境或量化时长
            scene = re.search(r"通勤|出差|带娃|上课|旅行|搬家|宿舍|公司|每天|每周"
                              r"|\d+\s*(小时|分钟|个月|天|年|周|次)", body or "")
            if not scene:
                got, note = weight - 8, "全篇无具体使用场景"
        elif name == "站内钩子":
            if re.search(r"微信|加V|vx|qq|手机号|二维码|支付宝", text, re.I):
                got, note = 0, "出现站外引流，直接 0 分（平台重点打击）"
            elif not re.search(r"想要的直接拍|私信|站内|拍下|留言", body or ""):
                got, note = weight - 6, "结尾没有站内行动号召"

        got = max(0, got)
        total += got
        items.append((name, weight, got, note))
    return total, items


# ---------------------------------------------------------------- 输出

def render(out, pools, items, sched, start, days, month):
    out.append("# 内容排期计划 · 文种草")
    out.append("")
    out.append("> 生成器：`content_plan.py`　规则库：`content_rules.json`")
    out.append("> 口径一：**脚本不含任何搜索量/销量数据**。关键词必须回闲鱼搜索框核对下拉词后再用。")
    out.append("> 口径二：标题里的 `【】` 必须换成真实信息；`【真踩过的序号】` 必须是你真踩过的那个。")
    out.append("> 周期：%s 起 %d 天　｜　SKU：%d 个" % (start.isoformat(), days, len(pools)))
    out.append("")
    out.append("---")
    out.append("")

    # 一、关键词矩阵
    out.append("## 一、关键词矩阵（四层，逐层铺）")
    out.append("")
    for key, item in items.items():
        out.append("### %s" % key)
        out.append("")
        out.append("| 层级 | 关键词（待核对） | 为什么这么铺 |")
        out.append("|---|---|---|")
        for layer, kw, why in keyword_matrix(item):
            kw_cell = kw.replace("\n", "<br>")
            out.append("| %s | %s | %s |" % (layer, kw_cell, why))
        out.append("")
        out.append("> 核对动作：把上面每个词粘进闲鱼搜索框，看**下拉联想**和「相关搜索」，")
        out.append("> 有联想说明有人搜，没联想就换说法。这一步不能省，脚本替你猜不了。")
        out.append("")

    # 二、选题池
    out.append("## 二、选题池（按适配度排序，取前几条）")
    out.append("")
    for key, topics in pools.items():
        out.append("### %s" % key)
        out.append("")
        out.append("| # | 公式 | 标题 | 形式 |")
        out.append("|---|---|---|---|")
        for i, t in enumerate(topics, 1):
            out.append("| %d | %s | %s | %s |" % (i, t["name"], t["title"].replace("|", "/"), t["form"]))
        out.append("")
        for t in topics:
            out.append("- **%s**（%s）：%s" % (t["name"], t["fid"], t["why"]))
        out.append("")

    # 三、排期
    out.append("## 三、发布排期（%d 天）" % days)
    out.append("")
    out.append("| 日期 | 星期 | 时间 | SKU | 公式 | 标题 | 形式 |")
    out.append("|---|---|---|---|---|---|---|")
    for row in sched:
        out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            row["date"].strftime("%m-%d"), WEEK_CN[row["date"].weekday()],
            row["slot"]["time"], row["sku"], row["topic"]["name"],
            row["topic"]["title"].replace("|", "/"), row["topic"]["form"]))
    out.append("")
    out.append("> 时段依据：%s" % "；".join(
        "%s %s（%s）" % (s["day"], s["time"], s["why"]) for s in R["publish_slots"][:3]))
    out.append("")

    # 四、逐篇脚本要点
    out.append("## 四、逐篇脚本要点")
    out.append("")
    out.append("### 通用骨架（两种形式，先记住再写单篇）")
    out.append("")
    for form, lines in R["body_text"].items():
        out.append("**%s**" % form)
        for line in lines:
            out.append("- %s" % line)
        out.append("")
    out.append("---")
    out.append("")
    for i, row in enumerate(sched, 1):
        t = row["topic"]
        item = items[row["sku"]]
        hook_type, hook_text = pick_hook(t["fid"], item)
        out.append("### %d. %s ｜%s %s" % (i, t["title"], row["date"].strftime("%m-%d"), row["slot"]["time"]))
        out.append("")
        out.append("- 公式：**%s**（%s）　形式：%s　SKU：%s" % (t["name"], t["fid"], t["form"], row["sku"]))
        out.append("- 开头第一句（%s）：`%s`" % (hook_type, hook_text))
        out.append("- 结构：")
        for line in t["outline"]:
            out.append("  - %s" % line)
        out.append("")
        out.append("---")
        out.append("")

    # 五、复盘
    out.append("## 五、发出去之后看什么（复盘判据）")
    out.append("")
    out.append("| 现象 | 判断 | 下一步动作 |")
    out.append("|---|---|---|")
    for r in R["replay_rules"]:
        out.append("| %s | %s | %s |" % (r["signal"], r["judge"], r["action"]))
    out.append("")
    out.append("**爆款要素拆解表**（每出一条爆款填一次，攒够 5 条就能提炼自己的模板）：")
    out.append("")
    out.append("| 日期 | 标题 | 公式 | 曝光 | 点击率 | 收藏率 | 咨询 | 成交 | 起作用的那个点 |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    out.append("|  |  |  |  |  |  |  |  |  |")
    out.append("")
    out.append("> 「起作用的那个点」只写一条，写不出说明你也不知道为什么爆，那条不可复用。")
    out.append("")

    # 六、合规
    out.append("## 六、合规提醒")
    out.append("")
    for n in R["compliance_notes"]:
        out.append("- %s" % n)
    out.append("")


def main():
    global R
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="候选 JSON（与 selection_scorer 同一份）")
    ap.add_argument("--sku", help="单件：SKU 名称")
    ap.add_argument("--price", type=float, help="单件：挂牌价")
    ap.add_argument("--new-price", type=float, help="单件：同款新机价（算省多少）")
    ap.add_argument("--cond", help="单件：成色")
    ap.add_argument("--points", action="append", help="单件：卖点，可多次传")
    ap.add_argument("--days", type=int, default=7, help="排期天数（默认 7）")
    ap.add_argument("--per-sku", type=int, default=3, help="每个 SKU 出几条选题（默认 3）")
    ap.add_argument("--start", help="起始日期 YYYY-MM-DD（默认今天）")
    ap.add_argument("--check", help="只做违规自查")
    ap.add_argument("--review", action="store_true", help="文案体检打分（配 --title / --body）")
    ap.add_argument("--title", help="体检：标题")
    ap.add_argument("--body", help="体检：正文")
    ap.add_argument("--out", help="输出 Markdown 路径")
    args = ap.parse_args()

    R = load_rules()
    db.RULES = db.load_rules()   # 违规词库在 design_rules.json，任何分支都要先加载

    if args.check:
        hits = db.scan_ban(args.check)
        print("# 违规自查结果\n")
        print("> 待检文案：%s\n" % args.check)
        if not hits:
            print("✅ 未命中违规词。")
        for sev, group, word in hits:
            mark = "🔴 硬违规" if sev == "error" else "🟡 需核对"
            print("- %s ｜[%s] `%s`" % (mark, group, word))
        return

    if args.review:
        total, rows = review_text(args.title or "", args.body or "")
        print("# 文案体检：%d / 100\n" % total)
        print("| 项目 | 满分 | 得分 | 说明 |")
        print("|---|---|---|---|")
        for name, w, got, note in rows:
            print("| %s | %d | %d | %s |" % (name, w, got, note))
        bad = [x for x in rows if x[2] < x[1]]
        print("")
        if not bad:
            print("✅ 各项达标，可以发。")
        else:
            print("要改的 %d 项：" % len(bad))
            for name, w, got, note in bad:
                print("  - **%s**：%s" % (name, note))
        return

    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            items = json.load(f)
        if isinstance(items, dict):
            items = items.get("candidates", [])
    elif args.sku:
        items = [{"sku": args.sku, "price": args.price, "new_price": args.new_price,
                  "cond": args.cond, "points": args.points or []}]
    else:
        ap.error("要么 --input candidates.json，要么 --sku '商品名'")

    start = datetime.date.today()
    if args.start:
        start = datetime.date.fromisoformat(args.start)
    month = start.month

    db.RULES = db.load_rules()   # 违规自查要读 design_rules.json 的词库

    keyed, pools = {}, {}
    # 选题数量要够铺满周期，否则第 N 天会重复用同一条
    need = max(1, -(-args.days // max(1, len(items))))
    per = max(args.per_sku, need)
    for it in items:
        key = it.get("sku") or it.get("title") or "未命名 SKU"
        keyed[key] = it
        pools[key] = topic_pool(it, per, month)

    sched = build_schedule(pools, start, args.days)

    out = []
    render(out, pools, keyed, sched, start, args.days, month)
    text = "\n".join(out)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("[OK] %d 个 SKU / %d 天排期 → %s" % (len(pools), args.days, args.out), file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
