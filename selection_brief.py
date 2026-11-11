#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selection_brief.py — 本周选品简报生成器（甄选品·可定时自动化）

组合：真实候选（candidates.json）+ 四维评分卡 → 输出一份 Markdown 周简报，
      供军团晨会/上架决策。可接 crontab / 定时任务，每日或每周生成。

用法：
    python3 selection_brief.py                        # 无参=内置样例（会标注"样例"）
    python3 selection_brief.py --input candidates.json # 用真实候选
    python3 selection_brief.py --input candidates.json --out brief.md
依赖：本目录 selection_scorer.py（同包）
"""

import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from selection_scorer import score, CANDIDATES, WEIGHTS  # noqa


def build_brief(cands=None):
    is_demo = cands is None
    data = CANDIDATES if cands is None else cands
    ranked = sorted((score(dict(c)) for c in data), key=lambda x: -x["score"])
    gh = [c for c in ranked if c["signal"] == "GH"]
    top = [c for c in ranked if c["decision"] == "强烈推荐"]

    lines = []
    lines.append("# 闲鱼本周选品简报 · %s" % date.today())
    lines.append("")
    if is_demo:
        lines.append("> ⚠️ 数据来源：脚本内置**样例候选**（非真实市场数据，仅演示流程）")
    else:
        lines.append("> 数据来源：`candidates.json`（甄选品本周录入的真实候选）")
    lines.append("> 评分：综合分 = %d%%需求 + %d%%竞争 + %d%%利润 + %d%%风险"
                 % (int(WEIGHTS['demand'] * 100), int(WEIGHTS['comp_favor'] * 100),
                    int(WEIGHTS['profit'] * 100), int(WEIGHTS['risk_favor'] * 100)))
    lines.append("")
    lines.append("## 一、本周结论")
    lines.append("- 候选共 **%d** 项，其中 GitHub 趋势新增信号 **%d** 项。" % (len(ranked), len(gh)))
    lines.append("- **强烈推荐（≥75）%d** 项：%s"
                 % (len(top), "、".join(c["sku"] for c in top) or "无"))
    lines.append("")
    lines.append("## 二、排名与决策")
    lines.append("")
    lines.append("| 排名 | SKU | 信号 | 综合分 | 决策 | 备注 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for i, c in enumerate(ranked, 1):
        lines.append("| %d | %s | %s | %s | %s | %s |"
                     % (i, c["sku"], c["signal"], c["score"], c["decision"], c["note"]))
    lines.append("")
    lines.append("## 三、本周行动建议")
    lines.append("1. 立即上架强烈推荐项，定价取中位 -3%~+5%，前 3 天 -5%~-8% 冲量。")
    lines.append("2. GitHub 信号项（趋势命中品类）优先做无货源/一件代发，压库存风险。")
    lines.append("3. 高利润但高风险的（二手显卡等），必须走验货宝、明确披露成色。")
    lines.append("4. 下架/暂停综合分 < 60 项，避免占用运营精力。")
    lines.append("")
    lines.append("## 四、漏斗追踪（对齐 SOP 标准）")
    lines.append("- 曝光 → 点击率 ≥ 2% → 咨询率 ≥ 6% → 成交率 ≥ 15%")
    lines.append("- 数明察每周回流各 SKU 实际漏斗，命中率 < 40% 的品类回炉重评。")
    return "\n".join(lines)


def main():
    argv = sys.argv[1:]
    input_path = None
    out_path = None
    if "--input" in argv:
        i = argv.index("--input")
        if i + 1 < len(argv):
            input_path = argv[i + 1]
    if "--out" in argv:
        i = argv.index("--out")
        if i + 1 < len(argv):
            out_path = argv[i + 1]

    cands = None
    if input_path:
        try:
            with open(input_path, encoding="utf-8") as f:
                cands = json.load(f)
        except Exception as e:
            print("[ERR] 读取 %s 失败: %s" % (input_path, e))
            sys.exit(1)

    md = build_brief(cands)

    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md + "\n")
        print("[OK] 简报已写出 → %s" % out_path)
        return
    print(md)


if __name__ == "__main__":
    main()
