#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
design_render.py — 图玲珑 · 出图器（把文案稿直接渲成可上架的图）

design_brief.py 只出「文字稿」，还要人手开浏览器改字截图；本脚本把这最后一环自动化：
读同一份 candidates.json，按设计规则渲染 3 套主图版式 + 详情页长图，调用本机 Edge
无头模式截成 PNG，尺寸严格 1080×1080 与 1080×长图。

核心约束（与 design_brief 一致）：
    脚本不编造任何实物事实。没有实拍图就留「虚线占位框」，提示你把图贴进去再渲一次。
    没有实拍图的成品图**绝对不能上架**——AI 合成图冒充实物属于虚假描述。

用法：
    # 批量：读候选 → 每个 SKU 出一套图
    python design_render.py --input candidates.json --outdir renders

    # 单件快出
    python design_render.py --sku "二手 Switch OLED 掌机" --cond 95新 \
        --price 1799 --points "港版/含底座/无拆修" --outdir renders

    # 已有实拍图：放进 photos/<SKU同名>.jpg 后重跑，自动嵌入
    python design_render.py --input candidates.json --photos photos --outdir renders

    # 只出 HTML 不截图（没装 Edge 的机器）
    python design_render.py --input candidates.json --outdir renders --no-shot

依赖：仅标准库 + 本机 Edge/Chrome（无头截图）。
"""

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys

import design_brief as db

HERE = os.path.dirname(os.path.abspath(__file__))

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]

W = 1080          # 画布宽
PAD = 60          # 安全边距（平台裁切保护）

BASE_CSS = """
*{margin:0;padding:0;box-sizing:border-box;-webkit-font-smoothing:antialiased}
body{width:%(w)dpx;background:#fff;font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",sans-serif;color:#1a1a1a}
.canvas{position:relative;width:%(w)dpx;overflow:hidden;background:#fff}
.slot{position:absolute;border:3px dashed #c9ccd1;border-radius:18px;background:#f7f8fa;
      display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;
      color:#9aa0a6;font-size:26px;line-height:1.5}
.slot b{font-size:32px;color:#7b8085;font-weight:600;display:block;margin-bottom:10px}
.slot img{width:100%%;height:100%%;object-fit:cover;border-radius:15px;display:block}
.chip{display:inline-block;padding:10px 22px;border-radius:999px;font-size:26px;
      background:#f1f3f5;color:#4a4f55;margin:0 10px 10px 0}
.price-tag{display:inline-flex;align-items:baseline;background:#FFDA00;color:#111;
      padding:14px 30px;border-radius:16px;font-weight:800}
.price-tag .sym{font-size:38px;margin-right:4px}
.price-tag .num{font-size:72px;letter-spacing:-1px}
""" % {"w": W}


def esc(s):
    return html.escape(str(s or ""))


def fit_size(text, sizes):
    """按字数挑字号。sizes = [(字数上限, 字号), ...]，取第一个满足的。"""
    n = len(text)
    for limit, size in sizes:
        if n <= limit:
            return size
    return sizes[-1][1]


def slugify(sku):
    s = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", sku.strip())
    return s.strip("_")[:40] or "sku"


def find_browser():
    for p in BROWSERS:
        if os.path.exists(p):
            return p
    for name in ("msedge", "chrome", "google-chrome", "chromium"):
        p = shutil.which(name)
        if p:
            return p
    return None


def slot_html(x, y, w, h, label="实拍图", hint="1080×1080 · 主体占画面 70%", photo=None, framed=True):
    style = "left:%dpx;top:%dpx;width:%dpx;height:%dpx" % (x, y, w, h)
    if photo and os.path.exists(photo):
        # 有实拍图：去掉虚线占位框，只留圆角遮罩
        uri = "file:///" + os.path.abspath(photo).replace("\\", "/")
        style += ";border:0;background:transparent"
        return ('<div class="slot" style="%s"><img src="%s"></div>'
                % (style, esc(uri)))
    inner = "<b>%s</b>%s" % (esc(label), esc(hint))
    if not framed:
        style += ";border:0;border-radius:0;background:#f2f3f5"
    return '<div class="slot" style="%s">%s</div>' % (style, inner)


# ---------------------------------------------------------------- 主图三版式

def layout_a(d):
    """A 左图右文：信息量最大，适合有明确型号/成色的机器类。"""
    model_size = fit_size(d["model"], [(6, 80), (9, 68), (12, 58), (16, 48)])
    return """
<div class="canvas" style="height:%(w)dpx">
  %(slot)s
  <div style="position:absolute;left:632px;top:0;width:392px;height:%(w)dpx;
              display:flex;flex-direction:column;justify-content:center">
    <div style="font-size:34px;font-weight:800;color:#E8452C;letter-spacing:1px">%(cond)s</div>
    <div style="font-size:%(ms)dpx;font-weight:800;line-height:1.14;margin-top:16px;word-break:keep-all">%(model)s</div>
    <div style="width:84px;height:6px;background:#FFDA00;border-radius:3px;margin:26px 0 22px"></div>
    <div style="font-size:28px;color:#55595e;line-height:1.6;margin-bottom:26px">%(sub)s</div>
    <div style="margin-bottom:30px">%(price)s</div>
    <div>%(badges)s</div>
  </div>
</div>
""" % {
        "w": W, "ms": model_size, "cond": esc(d["cond"]), "model": esc(d["model"]),
        "sub": esc(d["sub"]), "badges": d["badge_html"], "price": d["price_html"],
        "slot": slot_html(PAD, PAD, 512, W - 2 * PAD, "实拍主图", "主体居中 · 白底或浅灰底", d["photo"]),
    }



def layout_b(d):
    """B 大图压底条：图占满上部，底部黄色价格条，缩略图里最抢眼。"""
    model_size = fit_size(d["model"], [(8, 76), (12, 64), (16, 54)])
    bar_h = 300
    return """
<div class="canvas" style="height:%(w)dpx">
  %(slot)s
  <div style="position:absolute;left:0;right:0;bottom:0;height:%(bh)dpx;background:#FFDA00;
              display:flex;align-items:center;justify-content:space-between;padding:0 %(pad)dpx">
    <div style="max-width:600px">
      <div style="font-size:26px;font-weight:700;color:#5a4a00;letter-spacing:2px">%(cond)s</div>
      <div style="font-size:%(ms)dpx;font-weight:800;line-height:1.16;color:#111;margin-top:10px;word-break:keep-all">%(model)s</div>
    </div>
    <div style="text-align:right">
      <div style="font-size:24px;color:#5a4a00;font-weight:700">到手价</div>
      <div style="font-size:66px;font-weight:800;color:#111;letter-spacing:-1px">%(price)s</div>
    </div>
  </div>
</div>
""" % {
        "w": W, "bh": bar_h, "pad": PAD, "ms": model_size,
        "cond": esc(d["cond"]), "model": esc(d["model"]), "price": esc(d["price"]),
        "slot": slot_html(0, 0, W, W - bar_h, "实拍主图（满幅）", "主体居中 · 背景干净不抢戏", d["photo"], framed=False),
    }


def layout_c(d):
    """C 三卖点堆叠：适合配置差异大、要靠事实说服的品类。"""
    model_size = fit_size(d["model"], [(8, 70), (12, 58), (16, 48)])
    chips = "".join('<div class="chip">%s</div>' % esc(p) for p in d["points"][:3])
    return """
<div class="canvas" style="height:%(w)dpx;background:#f5f6f7">
  %(slot)s
  <div style="position:absolute;left:%(pad)dpx;right:%(pad)dpx;bottom:%(pad)dpx;
              background:#fff;border-radius:22px;padding:34px 38px 28px">
    <div style="display:flex;align-items:baseline;justify-content:space-between">
      <div style="font-size:%(ms)dpx;font-weight:800;line-height:1.2;word-break:keep-all;max-width:640px">%(model)s</div>
      <div style="font-size:52px;font-weight:800;color:#E8452C;white-space:nowrap">%(price)s</div>
    </div>
    <div style="margin-top:20px">%(chips)s</div>
  </div>
</div>
""" % {
        "w": W, "pad": PAD, "ms": model_size, "model": esc(d["model"]),
        "price": esc(d["price"]), "chips": chips,
        "slot": slot_html(PAD, PAD, W - 2 * PAD, 610, "实拍主图", "主体居中 · 背景干净", d["photo"]),
    }


# ---------------------------------------------------------------- 详情页长图

SCREEN_H = 1200


def detail_page(d):
    """详情页 4 屏拼成一张长图。每屏高度按内容动态计算，避免大片留白。"""
    screens = db.RULES["detail_screens"]
    out, total = [], 0
    for i, s in enumerate(screens):
        band = i in (0, 2)                       # 第 1、3 屏配整条实拍图
        must_items = d["must_state"] if i == len(screens) - 1 else []
        h = 600 + (300 if band else 0) + len(must_items) * 78

        bullets = "".join(
            '<li style="font-size:29px;line-height:1.95;color:#3c4043">%s</li>' % esc(c)
            for c in s["content"]
        )
        must = ""
        if must_items:
            must = "".join(
                '<div style="font-size:26px;line-height:1.6;color:#8a2b1a;background:#fff4f1;'
                'border-left:6px solid #E8452C;padding:12px 18px;margin-bottom:12px;border-radius:6px">'
                '必须写清：%s</div>' % esc(m) for m in must_items
            )
        img = ""
        if band:
            img = slot_html(PAD, h - 330, W - 2 * PAD, 270,
                            "实拍/细节图（整条）", "第 %d 屏配图 · 可贴瑕疵特写或配件全家福" % (i + 1),
                            d["photo"])

        out.append("""
<div class="canvas" style="height:%(h)dpx;border-bottom:14px solid #f0f1f3">
  <div style="position:absolute;left:%(pad)dpx;top:52px;font-size:110px;font-weight:800;
              color:#FFDA00;line-height:1">%(no)02d</div>
  <div style="position:absolute;left:%(tx)dpx;top:96px;font-size:42px;font-weight:800">%(name)s</div>
  <div style="position:absolute;left:%(tx)dpx;top:158px;width:560px;height:4px;background:#e8eaed"></div>
  <div style="position:absolute;left:%(pad)dpx;top:232px;width:%(tw)dpx">
    <ul style="list-style:none">%(bullets)s</ul>
    %(must)s
  </div>
  %(img)s
</div>
""" % {
            "h": h, "pad": PAD, "no": s["no"], "name": esc(s["name"]), "tx": PAD + 168,
            "tw": W - 2 * PAD, "bullets": bullets, "must": must, "img": img,
        })
        total += h + 14
    return "".join(out), total



# ---------------------------------------------------------------- 渲染与截图

def build_data(item, photo_dir):
    sku = item.get("sku") or item.get("title") or "未命名 SKU"
    cond = item.get("cond") or ""
    points = item.get("points") or ([item["note"]] if item.get("note") else [])
    cat_name, cat_rule = db.pick_category(sku, item.get("cat"), item.get("note"))

    model = sku[2:].strip() if sku.startswith("二手") else sku
    headline = db.trim_words(("%s %s" % (cond, model)).strip(), 16)

    price = item.get("price")
    price_txt = db.money(price) if price else "【价格】"
    price_html = ('<span class="price-tag"><span class="sym">¥</span>'
                  '<span class="num">%s</span></span>' % esc(format(float(price), ",.0f"))) \
        if price else ('<span class="price-tag"><span class="num" style="font-size:48px">%s</span></span>'
                       % esc(price_txt))

    badges = cat_rule.get("badges", [])[:3]
    badge_html = "".join('<span class="chip">%s</span>' % esc(b) for b in badges)

    photo = None
    if photo_dir:
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            p = os.path.join(photo_dir, slugify(sku) + ext)
            if os.path.exists(p):
                photo = p
                break

    return {
        "sku": sku, "model": model, "headline": headline, "cond": cond,
        "sub": (points[0] if points else "【一句核心事实】"),
        "points": points or ["【卖点1】", "【卖点2】", "【卖点3】"],
        "price": price_txt, "price_html": price_html, "badge_html": badge_html, "photo": photo,
        "cat_name": cat_name,
        "must_state": cat_rule.get("must_state", []),
    }


def page(title, body, extra_css=""):
    return """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>%s</title><style>%s%s</style></head><body>%s</body></html>""" % (
        esc(title), BASE_CSS, extra_css, body)


def shoot(browser, html_path, png_path, height):
    url = "file:///" + os.path.abspath(html_path).replace("\\", "/")
    cmd = [
        browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1", "--default-background-color=FFFFFFFF",
        "--window-size=%d,%d" % (W, height),
        "--screenshot=%s" % os.path.abspath(png_path),
        url,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=90)
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)
    return os.path.exists(png_path), ""


def render_one(item, idx, opts, browser):
    d = build_data(item, opts.photos)
    d_slug = "%02d_%s" % (idx, slugify(d["sku"]))
    outdir = os.path.join(opts.outdir, d_slug)
    os.makedirs(outdir, exist_ok=True)

    layouts = {"main_A": (layout_a(d), W), "main_B": (layout_b(d), W), "main_C": (layout_c(d), W)}
    detail_body, detail_h = detail_page(d)
    layouts["detail"] = (detail_body, detail_h)

    made, failed = [], []
    for name, (body, h) in layouts.items():
        hp = os.path.join(outdir, name + ".html")
        with open(hp, "w", encoding="utf-8") as f:
            f.write(page("%s · %s" % (d["sku"], name), body))
        if not opts.no_shot and browser:
            png = os.path.join(outdir, name + ".png")
            ok, err = shoot(browser, hp, png, h)
            (made if ok else failed).append((name, err))
        else:
            made.append((name, ""))

    # 违规词兜底提示（渲染的是真会发出去的文案）
    publish_txt = " ".join([d["headline"], d["sub"], " ".join(d["points"])])
    hits = [h for h in db.scan_ban(publish_txt) if h[0] == "error"]
    return d, outdir, made, failed, hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="候选 JSON（与 selection_scorer 同一份）")
    ap.add_argument("--sku", help="单件：SKU 名称")
    ap.add_argument("--cond", help="单件：成色")
    ap.add_argument("--price", type=float, help="单件：挂牌价")
    ap.add_argument("--points", action="append", help="单件：卖点，可多次传")
    ap.add_argument("--outdir", default="renders", help="输出目录（默认 renders/）")
    ap.add_argument("--photos", help="实拍图目录（文件名 = SKU 同名 .jpg）")
    ap.add_argument("--no-shot", action="store_true", help="只出 HTML，不截图")
    args = ap.parse_args()

    db.RULES = db.load_rules()

    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            items = json.load(f)
        if isinstance(items, dict):
            items = items.get("candidates", [])
    elif args.sku:
        items = [{"sku": args.sku, "cond": args.cond, "price": args.price,
                  "points": args.points or []}]
    else:
        ap.error("要么 --input candidates.json，要么 --sku '商品名'")

    browser = None if args.no_shot else find_browser()
    if not args.no_shot and not browser:
        print("[WARN] 未找到 Edge/Chrome，仅输出 HTML。可手动打开截图，或加 --no-shot。", file=sys.stderr)

    os.makedirs(args.outdir, exist_ok=True)
    total_png, all_hits = 0, []

    for i, it in enumerate(items, 1):
        d, outdir, made, failed, hits = render_one(it, i, args, browser)
        n_png = sum(1 for _, e in made if not e) if browser and not args.no_shot else 0
        total_png += n_png
        flag = "图 %d 张" % n_png if n_png else "HTML %d 个" % len(made)
        print("[%d/%d] %-26s → %s  (%s)" % (i, len(items), d["sku"], outdir, flag))
        if not d["photo"]:
            print("       ⚠ 无实拍图，已留占位框：把照片放成 %s/%s.jpg 再跑一次"
                  % (args.photos or "photos", slugify(d["sku"])))
        for name, err in failed:
            print("       ✗ 截图失败 %s: %s" % (name, err[:80]))
        if hits:
            all_hits.append((d["sku"], [w for _, _, w in hits]))

    print("\n完成：%d 个 SKU，输出目录 %s" % (len(items), os.path.abspath(args.outdir)))
    if all_hits:
        print("\n🔴 以下 SKU 的待发布文案命中硬违规词，上架前必须改：")
        for sku, ws in all_hits:
            print("  - %s：%s" % (sku, "、".join(ws)))


if __name__ == "__main__":
    main()
