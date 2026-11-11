#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selection_brief.py — 本周选品简报生成器（甄选品·可定时自动化）

组合：GitHub 趋势信号 + 四维评分卡 → 输出一份 Markdown 周简报，供军团晨会/上架决策。
可接 crontab / 定时任务，每日或每周生成，回写资料库或推送。

用法：
    python3 selection_brief.py                  # 终端打印 Markdown
    python3 selection_brief.py --out brief.md   # 写文件
依赖：本目录 selection_scorer.py（同包）
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from selection_scorer import score, CANDIDATES, WEIGHTS  # noqa


def build_brief() -> str:
    ranked = sorted((score(dict(c)) for c in CANDIDATES), key=lambda x: -x["score"])
    gh = [c for c in ranked if c["signal"] == "GH"]
    top = [c for c in ranked if c["decision"] == "强烈推荐"]
    lines = []
    lines.append(f"# 闲鱼本周选品简报 · {date.today()}")
    lines.append("")
    lines.append("> 信号源：GitHub Trending（技术消费趋势）+ 《闲鱼选品分析报告》常青品类")
    lines.append("> 评分：综合分 = "
                 f"{int(WEIGHTS['demand']*100)}%需求 + {int(WEIGHTS['comp_favor']*100)}%竞争"
                 f" + {int(WEIGHTS['profit']*100)}%利润 + {int(WEIGHTS['risk_favor']*100)}%风险")
    lines.append("")
    lines.append(f"## 一、本周结论")
    lines.append(f"- 候选共 **{len(ranked)}** 项，其中 GitHub 趋势新增信号 **{len(gh)}** 项。")
    lines.append(f"- **强烈推荐（≥75）{len(top)}** 项："
                 + ("、".join(c["sku"] for c in top) or "无"))
    lines.append("")
    lines.append("## 二、排名与决策")
    lines.append("")
    lines.append("| 排名 | SKU | 信号 | 综合分 | 决策 | 备注 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for i, c in enumerate(ranked, 1):
        lines.append(f"| {i} | {c['sku']} | {c['signal']} | {c['score']} "
                     f"| {c['decision']} | {c['note']} |")
    lines.append("")
    lines.append("## 三、本周行动建议")
    lines.append("1. 立即上架强烈推荐项，定价取中位 -3%~+5%，前 3 天 -5%~-8% 冲量。")
    lines.append("2. GitHub 信号项（迷你主机/智能家居配件/开发板）优先做无货源/一件代发，压库存风险。")
    lines.append("3. 二手显卡等高利润但高风险的，必须走验货宝、明确披露成色。")
    lines.append("4. 下架/暂停综合分 < 60 项，避免占用运营精力。")
    lines.append("")
    lines.append("## 四、漏斗追踪（对齐 SOP 标准）")
    lines.append("- 曝光 → 点击率 ≥ 2% → 咨询率 ≥ 6% → 成交率 ≥ 15%")
    lines.append("- 数明察每周回流各 SKU 实际漏斗，命中率 < 40% 的品类回炉重评。")
    return "\n".join(lines)


def main():
    md = build_brief()
    if "--out" in sys.argv:
        i = sys.argv.index("--out")
        if i + 1 < len(sys.argv):
            p = sys.argv[i + 1]
            open(p, "w", encoding="utf-8").write(md + "\n")
            print(f"[OK] 简报已写出 → {p}")
            return
    print(md)


if __name__ == "__main__":
    main()
