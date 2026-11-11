#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selection_scorer.py — 闲鱼选品评分器（甄选品核心工具）

方法论：《闲鱼选品分析报告 2026-10-29》四维评分卡 + 军团 SOP
四维（均 0-100，越高越好）：
    demand      需求热度（热搜/趋势信号强度）
    comp_favor  竞争友好度（越高=竞争越小越好做）
    profit      利润空间（毛利空间）
    risk_favor  风险友好度（越高=售后/合规/假货风险越低）
综合分 = 0.35*demand + 0.25*comp_favor + 0.25*profit + 0.15*risk_favor
决策门槛： >=75 强烈推荐 | 60-74 可以上架 | <60 谨慎/放弃

用法：
    python3 selection_scorer.py candidates.json      # 跑真实候选（推荐）
    python3 selection_scorer.py                      # 无参=跑内置样例（演示用，会打警告）
    python3 selection_scorer.py --out ranked.json    # 同时导出 JSON
"""

import argparse
import json
import sys

WEIGHTS = {"demand": 0.35, "comp_favor": 0.25, "profit": 0.25, "risk_favor": 0.15}

# —— 内置样例候选（仅演示，非真实市场数据）——
# 真实使用时请把本周候选填入 candidates.json 再作为第一个参数传入。
# signal 标注来源：GH=GitHub趋势新增信号；RPT=报告常青品类
CANDIDATES = [
    {"sku": "二手迷你主机/准系统", "cat": "本地大模型算力", "signal": "GH",
     "demand": 92, "comp_favor": 55, "profit": 70, "risk_favor": 80,
     "note": "AI Agent/本地LLM热潮(anthropics/skills, agent-browser)→准系统/NUC需求旺；无货源可做"},
    {"sku": "智能家居二手配件", "cat": "Home Assistant生态", "signal": "GH",
     "demand": 78, "comp_favor": 70, "profit": 72, "risk_favor": 82,
     "note": "ha-mcp/Home Assistant趋势→Zigbee网关/温湿度传感器/智能插座；客单低、复购高"},
    {"sku": "开发板/传感器套件", "cat": "IoT/机器人", "signal": "GH",
     "demand": 75, "comp_favor": 68, "profit": 70, "risk_favor": 80,
     "note": "mujoco/RuView(IoT感知)→ESP32/树莓派配件/传感器；教育+极客刚需"},
    {"sku": "二手显卡/GPU", "cat": "本地推理", "signal": "GH",
     "demand": 88, "comp_favor": 40, "profit": 65, "risk_favor": 50,
     "note": "本地推理需求强，但矿卡/翻新风险高、竞争烈，须验货宝"},
    {"sku": "软路由/高端路由器", "cat": "网络", "signal": "GH",
     "demand": 70, "comp_favor": 60, "profit": 65, "risk_favor": 70,
     "note": "Agent/网络工具趋势→刷机软路由；需基础技术答疑"},
    {"sku": "二手NAS/轻量服务器", "cat": "存储", "signal": "GH",
     "demand": 72, "comp_favor": 58, "profit": 68, "risk_favor": 75,
     "note": "家庭存储/备份需求稳；重货物流注意"},
    {"sku": "家用投影仪(入门)", "cat": "影音", "signal": "RPT",
     "demand": 95, "comp_favor": 45, "profit": 72, "risk_favor": 55,
     "note": "报告常青：长尾强、无货源可做；售后较多"},
    {"sku": "秋冬取暖小电", "cat": "季节", "signal": "RPT",
     "demand": 90, "comp_favor": 62, "profit": 68, "risk_favor": 70,
     "note": "报告常青：2-3周应季窗口，立即行动"},
    {"sku": "AI服务接单", "cat": "虚拟服务", "signal": "RPT",
     "demand": 88, "comp_favor": 55, "profit": 95, "risk_favor": 70,
     "note": "报告常青：零库存纯利润；交付能力是门槛"},
    {"sku": "DDR4/SSD", "cat": "电脑硬件", "signal": "RPT",
     "demand": 80, "comp_favor": 70, "profit": 60, "risk_favor": 80,
     "note": "报告常青：走量压舱石、风险低"},
]

REQUIRED_FIELDS = ["sku", "signal"] + list(WEIGHTS.keys())


def score(c):
    s = sum(WEIGHTS[k] * c[k] for k in WEIGHTS)
    c["score"] = round(s, 1)
    c["decision"] = ("强烈推荐" if s >= 75 else
                     "可以上架" if s >= 60 else "谨慎/放弃")
    return c


def main():
    ap = argparse.ArgumentParser(description="闲鱼选品评分器")
    ap.add_argument("input", nargs="?", help="候选 JSON 文件（缺省时用内置样例）")
    ap.add_argument("--out", help="导出评分结果 JSON 路径")
    args = ap.parse_args()

    using_demo = args.input is None
    cands = CANDIDATES
    if args.input:
        try:
            with open(args.input, encoding="utf-8") as f:
                cands = json.load(f)
        except Exception as e:
            print("[ERR] 读取 %s 失败: %s" % (args.input, e))
            sys.exit(1)

    # 字段校验，避免打分时 KeyError
    for i, c in enumerate(cands):
        miss = [k for k in REQUIRED_FIELDS if k not in c]
        if miss:
            print("[ERR] 第 %d 条候选缺字段 %s，请参考 candidates.template.json" % (i + 1, miss))
            sys.exit(1)

    if using_demo:
        print("=" * 78)
        print("⚠️  [样例数据] 未提供 candidates.json，当前输出为脚本内置示例，非真实选品结论。")
        print("    真实用法：把本周候选填入 candidates.json，再执行")
        print("             python selection_scorer.py candidates.json")
        print("=" * 78)

    ranked = sorted((score(dict(c)) for c in cands), key=lambda x: -x["score"])

    print("=" * 78)
    print("闲鱼选品评分 · 候选 %d 项（综合分=0.35需求+0.25竞争+0.25利润+0.15风险）"
          % len(ranked))
    print("=" * 78)
    print("%-4s%-16s%-5s%-5s%-5s%-5s%-5s%-7s%s"
          % ("排名", "SKU", "信号", "需求", "竞争", "利润", "风险", "综合", "决策"))
    print("-" * 78)
    for i, c in enumerate(ranked, 1):
        print("%-4d%-16s%-5s%-5d%-5d%-5d%-5d%-7s%s"
              % (i, c["sku"], c["signal"], c["demand"], c["comp_favor"],
                 c["profit"], c["risk_favor"], c["score"], c["decision"]))
    print("-" * 78)
    gh = [c for c in ranked if c["signal"] == "GH"]
    print("GitHub 趋势新增信号 %d 项：%s" % (len(gh), "、".join(c["sku"] for c in gh)))
    print("=" * 78)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(ranked, f, ensure_ascii=False, indent=2)
        print("[OK] 已导出 JSON → %s" % args.out)


if __name__ == "__main__":
    main()
