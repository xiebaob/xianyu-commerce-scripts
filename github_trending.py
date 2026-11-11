#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
github_trending.py — GitHub Trending 抓取保育（甄选品·技术消费趋势信号源）

用途：每日扫描 GitHub Trending，提取"技术消费趋势"信号，映射到闲鱼选品机会
      （如 AI Agent 热 → 二手迷你主机/GPU/软路由；Home Assistant 热 → 智能家居二手配件）。

用法：
    python3 github_trending.py                 # 在线抓取当日榜（需联网）
    python3 github_trending.py --since weekly  # 周榜
    python3 github_trending.py --html file.html# 读取本地 HTML（离线/沙箱友好）
    python3 github_trending.py --json out.json # 输出 JSON

依赖：仅标准库（urllib + 正则）。无外部包。
说明：Trending 页面结构可能随 GitHub 改版变化；解析失败时回退到"读本地HTML"或"手动粘贴"。
"""

import argparse
import json
import re
import sys
import urllib.request
from datetime import date

TRENDING_URL = "https://github.com/trending"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="ignore")


def parse_trending(html: str) -> list:
    """粗粒度解析 Trending 仓库块（repo, lang, desc, stars, today）。"""
    repos = []
    # 每个仓库块以 <h2 class="h3 lh-condensed"> 开头
    blocks = re.findall(r'<h2[^>]*>.*?</h2>(.*?)(?=<h2[^>]*>|<footer|</main>)',
                        html, re.DOTALL)
    for b in blocks:
        repo_m = re.search(r'href="(/[^"]+)"', b)
        desc_m = re.search(r'<p[^>]*>(.*?)</p>', b, re.DOTALL)
        lang_m = re.search(r'itemprop="programmingLanguage">([^<]+)<', b)
        star_m = re.search(r'([\d,]+)\s*stars', b)
        today_m = re.search(r'([\d,]+)\s*stars today', b)
        if not repo_m:
            continue
        repos.append({
            "repo": repo_m.group(1).strip("/"),
            "language": lang_m.group(1).strip() if lang_m else "",
            "description": re.sub(r'\s+', ' ', desc_m.group(1)).strip()
                            if desc_m else "",
            "stars": int(star_m.group(1).replace(",", "")) if star_m else 0,
            "stars_today": int(today_m.group(1).replace(",", "")) if today_m else 0,
        })
    return repos


def tag_signal(repos: list) -> list:
    """把技术趋势映射为闲鱼选品信号（关键词粗匹配）。"""
    keyword_map = {
        "二手迷你主机/准系统": ["agent", "llm", "local", "mcp", "home-assistant", "rag"],
        "二手显卡/GPU": ["llm", "inference", "gpu", "diffusion", "model"],
        "智能家居二手配件": ["home-assistant", "homeassistant", "zigbee", "iot", "smart"],
        "开发板/传感器套件": ["esp32", "arduino", "raspberry", "sensor", "embedded", "robot"],
        "软路由/高端路由器": ["router", "network", "proxy", "vpn", "dns"],
    }
    for r in repos:
        text = (r["repo"] + " " + r["description"]).lower()
        hits = [k for k, kws in keyword_map.items() if any(kw in text for kw in kws)]
        r["xianyu_signal"] = hits
    return repos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="daily", choices=["daily", "weekly", "monthly"])
    ap.add_argument("--html", help="本地 trending HTML 路径（离线）")
    ap.add_argument("--json", help="输出 JSON 路径")
    args = ap.parse_args()

    try:
        if args.html:
            html = open(args.html, encoding="utf-8", errors="ignore").read()
        else:
            html = fetch_html(f"{TRENDING_URL}?since={args.since}")
    except Exception as e:
        print(f"[WARN] 在线抓取失败：{e}")
        print("[INFO] 可改用 --html 传入本地保存的 github.com/trending 页面，或手动粘贴。")
        sys.exit(2)

    repos = tag_signal(parse_trending(html))
    out = {"date": str(date.today()), "since": args.since, "repos": repos}
    if args.json:
        json.dump(out, open(args.json, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print(f"[OK] 已写出 {len(repos)} 个仓库到 {args.json}")
    else:
        for r in repos[:25]:
            sig = ",".join(r["xianyu_signal"]) or "-"
            print(f"{r['repo']:<45} ★{r['stars']:<8} +{r['stars_today']:<5} "
                  f"[{r['language']}] 信号:{sig}")
            if r["description"]:
                print(f"    {r['description'][:80]}")


if __name__ == "__main__":
    main()
