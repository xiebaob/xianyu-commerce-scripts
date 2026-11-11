#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
github_trending.py — 技术消费趋势信号采集（甄选品·趋势信号源）

数据源：GitHub 官方 Search API。
原因：/trending 网页已对未登录请求返回登录跳转，Actions 运行器（数据中心 IP）
      抓不到真实榜单，旧抓取方案会产出垃圾字符串。
思路：用「最近 N 天新建、按 star 排序」近似 Trending 榜单。

v2 质量修正（2026-11-11）：
  1) 关键词从「子串匹配」改为「词边界匹配」——旧的 "agent"/"local"/"model"
     会把「Let AI agents use your phone」误判成「二手迷你主机」。
  2) 关键词收敛为**具体商品/技术词**，不再用泛词。
  3) 增加刷星垃圾过滤——近期新建榜里混入大量伪装成
     "pre-configured environment / automated deployment pipeline" 的盗版软件农场。
  4) 信号从「逐个仓库打标」改为「趋势级判定」：同一品类 ≥2 个仓库才算结构性信号，
     避免单仓库噪声被当成趋势。

用法：
    python3 github_trending.py                    # 近 7 天榜（daily）
    python3 github_trending.py --since weekly     # 近 30 天
    python3 github_trending.py --since monthly    # 近 90 天
    python3 github_trending.py --json out.json    # 额外导出 JSON

鉴权：优先读环境变量 GITHUB_TOKEN（GitHub Actions 内置），无 token 时走匿名限额（60 次/小时）。
依赖：仅标准库。
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

API = "https://api.github.com/search/repositories"
UA = "xianyu-commerce-scripts/2.1"
WINDOW_DAYS = {"daily": 7, "weekly": 30, "monthly": 90}
PER_PAGE = 25          # 最终展示条数
FETCH_PAGE = 60        # 先多取一些，过滤垃圾后再截断
MIN_STARS = 30
MIN_REPOS_FOR_SIGNAL = 2   # 同品类 ≥2 个仓库才算结构性信号

# 关键词：只用「具体商品 / 具体技术」词，禁止 agent/llm/local/model/smart/network 这类泛词
KEYWORD_MAP = {
    "二手迷你主机/准系统": [
        "mini pc", "minipc", "barebone", "nuc", "homelab", "proxmox",
        "self-hosted", "selfhosted", "home server",
    ],
    "二手显卡/GPU": [
        "gpu", "cuda", "rocm", "vllm", "tensorrt", "diffusion",
        "llama.cpp", "ollama", "inference engine", "local llm",
    ],
    "智能家居二手配件": [
        "home assistant", "homeassistant", "zigbee", "z-wave", "zwave",
        "matter", "esphome", "esp-home", "smart home",
    ],
    "开发板/传感器套件": [
        "esp32", "arduino", "raspberry pi", "raspberrypi", "micropython",
        "stm32", "sensor", "embedded", "robot",
    ],
    "软路由/高端路由器": [
        "openwrt", "router", "pfsense", "opnsense", "soft router", "wifi 7",
    ],
    "二手 NAS/轻量服务器": [
        "nas", "truenas", "unraid", "synology", "openmediavault", "storage server",
    ],
    "二手游戏机/掌机": [
        "nintendo", "switch", "steam deck", "emulator", "retro handheld",
        "game boy", "psp", "handheld console",
    ],
    "二手手机/平板": [
        "iphone", "ipad", "ios", "android", "jailbreak", "sideload",
    ],
    "客制化键盘/外设": [
        "mechanical keyboard", "custom keyboard", "hot-swap keyboard",
        "qmk", "zmk", "keycap", "macro pad",
    ],
}

# 刷星垃圾特征：伪装的盗版/破解软件农场，描述高度模板化
SPAM_PATTERNS = [
    r"pre-?configured environment",
    r"automated deployment pipeline",
    r"optimized package deployment",
    r"seamless desktop software",
    r"desktop software utility",
    r"configuration folder",
    r"pre-?activated",
    r"\bcrack(ed)?\b",
    r"\bkeygen\b",
    r"\blicen[cs]e key\b",
    r"\bfull version\b",
    r"download (free|full)",
    # 同一批农场的变种模板（2026-11-11 实测漏网）
    r"workstation deployment",
    r"deployment package",
    r"environment (suite|configuration)",
    r"pipeline management",
    r"isolated environment",
]
SPAM_RE = re.compile("|".join(SPAM_PATTERNS), re.I)


def _boundary_pattern(keyword):
    """把关键词编译成词边界正则；含连字符/空格的词整体加边界。"""
    esc = re.escape(keyword)
    return re.compile(r"(?<![a-z0-9])" + esc + r"(?![a-z0-9])", re.I)


COMPILED_MAP = {cat: [_boundary_pattern(k) for k in kws] for cat, kws in KEYWORD_MAP.items()}


def fetch_repos(since, token):
    days = WINDOW_DAYS.get(since, 7)
    since_date = (date.today() - timedelta(days=days)).isoformat()
    q = "created:>%s stars:>%d" % (since_date, MIN_STARS)
    params = urllib.parse.urlencode({
        "q": q, "sort": "stars", "order": "desc", "per_page": FETCH_PAGE,
    })
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": UA,
    }
    if token:
        headers["Authorization"] = "Bearer %s" % token
    req = urllib.request.Request("%s?%s" % (API, params), headers=headers)
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode("utf-8", errors="ignore"))
    return data.get("items", [])


def is_spam(it):
    """疑似刷星垃圾仓库判定。"""
    desc = (it.get("description") or "")
    if SPAM_RE.search(desc):
        return True
    # 无描述 + 无语言 + 高星：典型农场特征
    if not desc.strip() and not (it.get("language") or "").strip():
        return True
    return False


def tag_signal(items):
    out = []
    for it in items:
        text = ((it.get("full_name") or "") + " " + (it.get("description") or ""))
        hits = [cat for cat, pats in COMPILED_MAP.items() if any(p.search(text) for p in pats)]
        out.append({
            "repo": it.get("full_name", ""),
            "language": it.get("language") or "",
            "description": (it.get("description") or "").strip(),
            "stars": it.get("stargazers_count", 0),
            "created": (it.get("created_at") or "")[:10],
            "xianyu_signal": hits,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="daily", choices=list(WINDOW_DAYS))
    ap.add_argument("--json", help="输出 JSON 路径")
    ap.add_argument("--token", help="GitHub token（默认读环境变量 GITHUB_TOKEN）")
    args = ap.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN")
    try:
        items = fetch_repos(args.since, token)
    except Exception as e:
        print("[WARN] GitHub Search API 请求失败：%s" % e)
        print("[INFO] 未登录限额 60 次/小时；请设置 GITHUB_TOKEN 环境变量提升额度。")
        sys.exit(2)

    raw_count = len(items)
    clean = [it for it in items if not is_spam(it)]
    spam_count = raw_count - len(clean)
    repos = tag_signal(clean)[:PER_PAGE]

    days = WINDOW_DAYS[args.since]
    since_date = (date.today() - timedelta(days=days)).isoformat()

    # 页首写清数据来源与口径，便于回溯（stdout 会被重定向进 trends/*.md）
    print("# GitHub 技术趋势信号 · %s（近 %d 天新建、按 star 排序）" % (date.today(), days))
    print("")
    print("> 数据源：GitHub 官方 Search API　q=`created:>%s stars:>%d`" % (since_date, MIN_STARS))
    print("> 口径：以「近期新建的热门仓库」近似 Trending，非官方 Trending 页；仅作趋势参考。")
    print("> 清洗：原始 %d 条 → 剔除疑似刷星垃圾 %d 条 → 取前 %d 条。"
          % (raw_count, spam_count, len(repos)))
    print("")

    # 趋势级信号：同品类 ≥MIN_REPOS_FOR_SIGNAL 个仓库才算结构性信号
    sig_repos = {}
    for r in repos:
        for s in r["xianyu_signal"]:
            sig_repos.setdefault(s, []).append(r)

    print("## 一、品类信号（趋势级判定）")
    strong = {k: v for k, v in sig_repos.items() if len(v) >= MIN_REPOS_FOR_SIGNAL}
    weak = {k: v for k, v in sig_repos.items() if len(v) < MIN_REPOS_FOR_SIGNAL}
    if strong:
        for s, rs in sorted(strong.items(), key=lambda x: -len(x[1])):
            print("- **%s**：%d 个仓库（结构性信号）" % (s, len(rs)))
            for r in rs:
                print("    - %s ★%d" % (r["repo"], r["stars"]))
    else:
        print("- 本窗口内无结构性品类信号（同品类需 ≥%d 个仓库）" % MIN_REPOS_FOR_SIGNAL)
    if weak:
        print("- 单仓库弱信号（不作趋势依据）：%s"
              % "、".join("%s(%d)" % (k, len(v)) for k, v in sorted(weak.items(), key=lambda x: -len(x[1]))))
    print("")

    print("## 二、仓库明细（前 %d）" % len(repos))
    for r in repos:
        sig = ",".join(r["xianyu_signal"]) or "-"
        print("- %s ★%d [%s] 信号:%s" % (r["repo"], r["stars"], r["language"], sig))
        if r["description"]:
            print("    %s" % r["description"][:100])

    if args.json:
        out = {
            "date": str(date.today()), "since": args.since,
            "window_days": days, "raw_count": raw_count,
            "spam_filtered": spam_count, "repo_count": len(repos),
            "strong_signals": {k: [r["repo"] for r in v] for k, v in strong.items()},
            "repos": repos,
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print("[OK] 已写出 %d 个仓库 → %s" % (len(repos), args.json), file=sys.stderr)


if __name__ == "__main__":
    main()
