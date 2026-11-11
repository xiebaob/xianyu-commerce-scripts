#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
github_trending.py — 技术消费趋势信号采集（甄选品·趋势信号源）

数据源改为 GitHub 官方 Search API。
原因：/trending 网页已对未登录请求返回登录跳转，Actions 运行器（数据中心 IP）
      抓不到真实榜单，旧抓取方案会产出垃圾字符串。
思路：用「最近 N 天新建、按 star 排序」近似 Trending 榜单。

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
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

API = "https://api.github.com/search/repositories"
UA = "xianyu-commerce-scripts/2.0"
WINDOW_DAYS = {"daily": 7, "weekly": 30, "monthly": 90}
PER_PAGE = 25
MIN_STARS = 30

KEYWORD_MAP = {
    "二手迷你主机/准系统": ["agent", "llm", "local", "mcp", "home-assistant", "rag"],
    "二手显卡/GPU": ["llm", "inference", "gpu", "diffusion", "model"],
    "智能家居二手配件": ["home-assistant", "homeassistant", "zigbee", "iot", "smart"],
    "开发板/传感器套件": ["esp32", "arduino", "raspberry", "sensor", "embedded", "robot"],
    "软路由/高端路由器": ["router", "network", "proxy", "vpn", "dns"],
}


def fetch_repos(since, token):
    days = WINDOW_DAYS.get(since, 7)
    since_date = (date.today() - timedelta(days=days)).isoformat()
    q = "created:>%s stars:>%d" % (since_date, MIN_STARS)
    params = urllib.parse.urlencode({
        "q": q, "sort": "stars", "order": "desc", "per_page": PER_PAGE,
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


def tag_signal(items):
    out = []
    for it in items:
        text = ((it.get("full_name") or "") + " " + (it.get("description") or "")).lower()
        hits = [k for k, kws in KEYWORD_MAP.items() if any(kw in text for kw in kws)]
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

    repos = tag_signal(items)
    days = WINDOW_DAYS[args.since]
    since_date = (date.today() - timedelta(days=days)).isoformat()

    # 页首写清数据来源与口径，便于回溯（stdout 会被重定向进 trends/*.md）
    print("# GitHub 技术趋势信号 · %s（近 %d 天新建、按 star 排序）" % (date.today(), days))
    print("")
    print("> 数据源：GitHub 官方 Search API　q=`created:>%s stars:>%d`" % (since_date, MIN_STARS))
    print("> 口径：以「近期新建的热门仓库」近似 Trending，非官方 Trending 页；仅作趋势参考。")
    print("")

    sig_count = {}
    for r in repos:
        for s in r["xianyu_signal"]:
            sig_count[s] = sig_count.get(s, 0) + 1

    print("## 一、闲鱼品类信号命中")
    if sig_count:
        for s, n in sorted(sig_count.items(), key=lambda x: -x[1]):
            print("- %s：%d 个仓库" % (s, n))
    else:
        print("- 本窗口内无仓库命中选品关键词")
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
            "window_days": days, "repo_count": len(repos), "repos": repos,
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print("[OK] 已写出 %d 个仓库 → %s" % (len(repos), args.json), file=sys.stderr)


if __name__ == "__main__":
    main()
