#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dashboard.py — 经营漏斗看板 + 周报（数明察核心工具）

对齐军团 SOP 漏斗标准：曝光 → 点击率≥2% → 咨询率≥6% → 成交率≥15%
输入：一段时期的 曝光/点击/咨询/成交 原始数（或逐日列表）
输出：各段转化率 vs 标准、瓶颈定位、优化建议、Markdown 周报

用法：
    python3 dashboard.py                 # 用内置示例周数据跑一遍
    python3 dashboard.py data.json       # 读自定义 JSON（{exposure,click,consult,deal} 或日列表）
    python3 dashboard.py --brief out.md  # 输出周报 Markdown
"""

import json
import sys
from datetime import date

# SOP 漏斗达标线
STD = {"click": 0.02, "consult": 0.06, "deal": 0.15}

# 内置示例：某店一周聚合（用于演示/自检）
SAMPLE = {"exposure": 120000, "click": 3200, "consult": 260, "deal": 44}


def aggregate(data):
    if isinstance(data, list):
        agg = {"exposure": 0, "click": 0, "consult": 0, "deal": 0}
        for d in data:
            for k in agg:
                agg[k] += d.get(k, 0)
        return agg
    return data


def analyze(agg: dict) -> dict:
    e, c, co, d = agg["exposure"], agg["click"], agg["consult"], agg["deal"]
    rates = {
        "click": c / e if e else 0,
        "consult": co / c if c else 0,
        "deal": d / co if co else 0,
    }
    # 瓶颈：取离标准线最远的负向段
    gaps = {k: rates[k] - STD[k] for k in STD}
    bottleneck = min(gaps, key=gaps.get)
    return {"agg": agg, "rates": rates, "gaps": gaps, "bottleneck": bottleneck}


def suggest(r: dict) -> list:
    s = []
    for k in ("click", "consult", "deal"):
        if r["gaps"][k] < 0:
            if k == "click":
                s.append("点击率不达标→图玲珑重做主图/标题，A/B 测试卖点")
            elif k == "consult":
                s.append("咨询率不达标→文种草补关键词/内容引流，价格锚点优化")
            else:
                s.append("成交率不达标→客如汇话术/催付 SOP，甄选品复核选品匹配度")
    if not s:
        s.append("漏斗全线达标，可规模化复制（许达标扩矩阵店）")
    return s


def report(r: dict) -> str:
    a, rt = r["agg"], r["rates"]
    L = []
    L.append(f"# 经营漏斗周报 · {date.today()}")
    L.append("")
    L.append(f"曝光 {a['exposure']:,} → 点击 {a['click']:,} → "
             f"咨询 {a['consult']:,} → 成交 {a['deal']:,}")
    L.append("")
    L.append("| 漏斗段 | 实际率 | 标准 | 达标 |")
    L.append("| --- | --- | --- | --- |")
    name = {"click": "点击率", "consult": "咨询率", "deal": "成交率"}
    for k in ("click", "consult", "deal"):
        ok = "✅" if r["gaps"][k] >= 0 else "❌"
        L.append(f"| {name[k]} | {rt[k]*100:.2f}% | {STD[k]*100:.0f}% | {ok} |")
    L.append("")
    L.append(f"**瓶颈段：{name[r['bottleneck']]}**")
    L.append("")
    L.append("## 优化建议")
    for i, x in enumerate(suggest(r), 1):
        L.append(f"{i}. {x}")
    return "\n".join(L)


def main():
    data = SAMPLE
    out = None
    args = sys.argv[1:]
    for a in args:
        if a.endswith(".json"):
            try:
                data = json.load(open(a, encoding="utf-8"))
            except Exception as e:
                print(f"[ERR] 读取 {a} 失败: {e}")
                sys.exit(1)
        elif a == "--brief":
            out = "weekly_report.md"
        elif a.startswith("--brief="):
            out = a.split("=", 1)[1]
    r = analyze(aggregate(data))
    md = report(r)
    print(md)
    if out:
        open(out, "w", encoding="utf-8").write(md + "\n")
        print(f"\n[OK] 周报已写出 → {out}")


if __name__ == "__main__":
    main()
