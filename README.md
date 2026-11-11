# 闲鱼电商选品 · GitHub 趋势信号工具箱

配套 WorkBuddy「闲鱼电商军团」Team 专家的选品 / 看板 / 设计脚本集。
**纯 Python 标准库、可离线运行**，用于把 **GitHub 技术消费趋势** 转化为闲鱼选品信号，并做评分、简报、漏斗看板与视觉出稿。

---

## 包含的脚本

| 脚本 | 归属角色 | 作用 |
|---|---|---|
| `github_trending.py` | 甄选品 | 抓取 GitHub 近期热门仓库（Search API），词边界匹配 + 刷星垃圾过滤 → 趋势级品类信号 |
| `selection_scorer.py` | 甄选品 | 四维评分卡（需求热度 / 竞争友好 / 利润空间 / 风险友好）打分排序，输出排名 JSON |
| `selection_brief.py` | 甄选品 | 汇总趋势信号 + 评分排名，生成每周选品简报 Markdown（可接定时任务） |
| `dashboard.py` | 数明察 | 经营漏斗看板 + 周报，对齐 SOP 标准（点击率 ≥2% / 咨询率 ≥6% / 成交率 ≥15%）自动定位瓶颈 |
| `design_brief.py` | 图玲珑 | 设计需求一键出稿：定价锚点 + 主图文案 + 拍摄清单 + 详情页 4 屏 + 短视频分镜 + 违规自查 |
| `design_render.py` | 图玲珑 | **出图器**：读候选直接渲出 3 套 1080×1080 主图 + 1080 宽详情页长图，调本机 Edge 截图，无需手工改字 |
| `content_plan.py` | 文种草 | **内容排期器**：四层关键词矩阵 + 8 条选题公式 → 选题池与 N 天排期 + 逐篇脚本要点；另带文案体检与违规自查 |

## 目录结构

```
xianyu-commerce-scripts/
├── README.md                      # 本文件
├── github_trending.py             # 趋势信号抓取（纯标准库）
├── selection_scorer.py            # 四维评分卡
├── selection_brief.py             # 周简报生成
├── dashboard.py                   # 经营漏斗看板
├── design_brief.py                # 设计需求出稿（图玲珑）
├── design_render.py               # 出图器：主图 ×3 + 详情页长图（图玲珑）
├── design_rules.json              # 设计规则库：违规词 / 品类必拍项 / 版式参数
├── content_plan.py                # 内容排期与选题出稿（文种草）
├── content_rules.json             # 内容规则库：选题公式权重 / 关键词层 / 发布节奏 / 复盘判据
├── 文种草SOP.md                    # 内容种草 SOP（选题公式 / 四层关键词 / 复盘判据）
├── 图玲珑SOP.md                    # 视觉设计 SOP（主图 / 详情页 / 合规红线）
├── 数据录入说明.md                  # 甄选品周更 SOP
├── candidates.template.json       # 候选录入模板
├── templates/
│   └── 主图版式.html               # 1:1 主图版式（浏览器改字直接截图）
├── examples/                      # 真实跑出的范例输出（可直接对照）
│   ├── ranked.example.json        # selection_scorer 输出
│   ├── weekly_report.example.md   # dashboard 输出
│   ├── brief.example.md           # selection_brief 输出
│   ├── design_brief.example.md    # design_brief 输出
│   ├── content_plan.example.md    # content_plan 输出（2 SKU × 7 天）
│   └── design_render/             # design_render 真实产物（1 个 SKU × 4 张）
│       ├── main_A.png             # 左图右文版式
│       ├── main_B.png             # 大图压价格条
│       ├── main_C.png             # 三卖点堆叠
│       └── detail.png             # 详情页 4 屏长图
└── .github/
    ├── workflows/                 # 自动化（见「自动化」章节）
    │   ├── daily-trend.yml        # 每天 09:00 抓趋势
    │   └── weekly-brief.yml       # 每周一 09:30 出简报
    ├── ISSUE_TEMPLATE/            # Issues 协作模板
    │   ├── config.yml
    │   ├── 选品任务.md
    │   ├── 经营复盘.md
    │   └── 脚本问题.md
    └── PULL_REQUEST_TEMPLATE.md
```

---

## 快速开始

```bash
# 全部脚本纯标准库，无需 pip install

# 1) 跑评分器（内置 10 项候选示例，可替换为自己的候选 JSON）
python selection_scorer.py --out ranked.json

# 2) 看经营漏斗看板（内置示例数据，替换为你店铺真实数据）
python dashboard.py --brief=weekly_report.md

# 3) 生成本周选品简报
python selection_brief.py --out brief.md

# 4) 给选中的 SKU 出设计稿
python design_brief.py --input candidates.json --out design_brief.md

# 5) 直接出图（需本机 Edge/Chrome；没装可加 --no-shot 只出 HTML）
python design_render.py --input candidates.json --outdir renders

# 6) 出内容排期（关键词矩阵 + 选题池 + 7 天排期）
python content_plan.py --input candidates.json --days 7 --out content_plan.md
```

---

## 使用说明（逐脚本）

### 1. `selection_scorer.py` — 四维评分卡
- **输入**：内置本周候选（GitHub Trending 信号 + 报告常青品类）；或自定义 `candidates.json`
- **输出**：排名表 + 综合分 + 决策（≥75 强烈推荐 / 60-74 可以上架 / <60 谨慎）
- **自定义候选**：准备 JSON 数组，每项含 `sku, cat, signal, demand, comp_favor, profit, risk_favor`
  ```bash
  python selection_scorer.py my_candidates.json --out my_ranked.json
  ```

### 2. `dashboard.py` — 经营漏斗看板
- **输入**：`{exposure, click, consult, deal}` 或逐日列表 JSON；不传参则跑内置示例（全线达标）
- **输出**：各段转化率 vs SOP 标准、瓶颈定位、优化建议、Markdown 周报
- **自定义数据**：
  ```bash
  python dashboard.py my_week.json --brief=weekly_report.md
  ```
  其中 `my_week.json` 形如 `{"exposure":120000,"click":3200,"consult":260,"deal":44}`

### 3. `github_trending.py` — 趋势信号抓取
- 联网抓取 GitHub Trending，按关键词映射闲鱼选品信号
- 输出 Markdown 片段（技术消费趋势 → 可上架品类清单）
- 用于每周选品会前的信息输入

### 4. `selection_brief.py` — 周简报
- 汇总趋势信号 + 评分排名，生成一份可读的周简报
- 接 GitHub Actions 后每周一自动跑，可再接微信推送

### 5. `design_brief.py` — 设计需求出稿（图玲珑）
- **输入**：`--input candidates.json`（与评分器同一份）或单件 `--sku "商品名" --cost 1400 --price 1799 --cond 95新 --points "卖点"`
- **输出**：每 SKU 一份设计需求单 —— 定价锚点 / 主图文案 / 拍摄清单 / 详情页 4 屏 / 短视频分镜 / 标题骨架 / 违规自查
  ```bash
  python design_brief.py --sku "二手 Switch OLED 掌机" --cost 1400 --price 1799 \
      --cond 95新 --points "港版/含底座/无拆修" --out brief.md
  ```
- **违规自查单跑**：
  ```bash
  python design_brief.py --check "全网最低价 加微信详聊"
  ```
  🔴 硬违规（绝对化用语 / 站外引流 / 禁售侵权）必须改；🟡 需与实物核对（成色 / 售后承诺）
- **出图（手工）**：`templates/主图版式.html` 浏览器打开 → 点文字改 → 切 100% 截图（1080×1080）
- **规则在 `design_rules.json`**：违规词、品类必拍项、版式参数全在这里，改口径只改 JSON

> ⚠️ 脚本只给**结构与骨架**，所有 `【】` 占位符必须对着实物填。它不会替你编成色、配置、瑕疵——二手交易里一句编造描述就是一次纠纷。

### 6. `design_render.py` — 出图器（图玲珑）
把上一步的文案直接渲成图，省掉手工改字截图。

- **输入**：`--input candidates.json`（与评分器同一份）或单件 `--sku ... --cond ... --price ... --points ...`
- **输出**：每个 SKU 一个目录，含 3 套主图 + 详情页长图（PNG + 同源 HTML）
  ```bash
  python design_render.py --input candidates.json --outdir renders
  python design_render.py --sku "二手 Switch OLED 掌机" --cond 95新 --price 1799 \
      --points "港版 含底座" --points "无拆修" --outdir renders
  ```
- **3 套主图版式**（都是 1080×1080，平台要求 1:1）：

  | 版式 | 结构 | 适合 |
  |---|---|---|
  | `main_A` | 左实拍 + 右成色/型号/副标/黄色价格牌/角标 | 有明确型号与成色的机器类，信息最全 |
  | `main_B` | 大图满幅 + 底部黄色价格条 | 缩略图最抢眼，走量款 |
  | `main_C` | 上图 + 白卡型号/价格 + 三卖点标签 | 靠配置差异说服的品类 |

- **详情页**：4 屏拼成 1080×约3300–3800 长图，第 1、3 屏带整条配图位，末屏自动附「必须写清」清单
- **实拍图自动嵌入**：把照片放成 `photos/<SKU名>.jpg`，加 `--photos photos` 重跑即可；没有照片就留虚线占位框
- **依赖**：仅标准库 + 本机 Edge/Chrome 无头截图。找不到浏览器时加 `--no-shot` 只出 HTML
- **安全兜底**：渲染完会再扫一遍真正要发出去的文案，命中硬违规词直接列出 SKU 与词

> 🔴 **没有实拍图渲出来的图，绝对不能上架。** AI 合成图或空占位当成实物图属于虚假描述，比错别字严重得多。


---

### 7. `content_plan.py` — 内容排期与选题出稿（文种草）
解决「今天发什么」和「关键词怎么铺」。

- **输入**：`--input candidates.json` 或单件 `--sku ... --price ... --new-price ... --cond ...`
- **输出**：四层关键词矩阵 + 按适配度排序的选题池 + N 天排期表 + 逐篇结构与开头第一句
  ```bash
  python content_plan.py --input candidates.json --days 7 --out content_plan.md
  ```
- **8 条选题公式**（权重在 `content_rules.json`，可自己调）：

  | ID | 公式 | 标题例 | 权重 |
  |---|---|---|---|
  | F1 | 价格锚点型 | ¥1,799 收的 Switch OLED，比新机省 ¥700 | 3 |
  | F2 | 避坑型 | 买二手 Switch OLED 前必看 4 个坑 | 3 |
  | F3 | 对比型 | iPhone 13 vs iPhone 14，差 300 块差在哪 | 2 |
  | F4 | 场景型 | 用了 11 天，说点实话 | 2 |
  | F5 | 验机干货型 | 验机 4 步，附我的检查表 | 2 |
  | F6 | 反向劝退型 | 这价位别买，除非你满足 2 个条件 | 2 |
  | F7 | 应季/节点型 | 11 月买最划算，因为… | 1 |
  | F8 | 拆解/细节型 | 细节实拍｜电池健康怎么看 | 1 |

- **文案体检**（发布前打分）：
  ```bash
  python content_plan.py --review --title "标题" --body "正文"
  ```
  7 项共 100 分：标题长度 / 含关键词 / 含数字 / 开头钩子 / 瑕疵披露 / 场景具体性 / 站内钩子。
  **60 分以下别发**；出现站外引流直接 0 分。
- **违规自查**：`python content_plan.py --check "待发布文案"`（与 `design_brief.py --check` 共用 `design_rules.json` 词库）

> ⚠️ **脚本不含任何搜索量/销量/竞品数据**。关键词必须回闲鱼搜索框核对下拉词；标题里的 `【】` 是真信息占位；「第 k 个我踩过」「我盯了 N 天」这类第一人称经历必须真实——编一次评论区就拆穿。

---

## 评分模型

综合分 = 35%·需求热度 + 25%·竞争友好 + 25%·利润空间 + 15%·风险友好
（权重与映射表见 `selection_scorer.py` 顶部 `WEIGHTS` 与 `CANDIDATES`）

决策门槛：
- **≥75 强烈推荐**：可批量上架
- **60–74 可以上架**：小批量试水
- **<60 谨慎/放弃**：不占用资源

---

## 接入真实数据（替换示例）

| 脚本 | 替换点 | 数据来源 |
|---|---|---|
| `selection_scorer.py` | 把 `CANDIDATES` 换成你的候选 JSON | 闲鱼搜索 / 竞品监测清单（资料库） |
| `dashboard.py` | 传入 `my_week.json` | 闲鱼「我的-数据中心」：曝光/点击/想要数（上架 48h 必看） |
| `github_trending.py` | 关键词映射表 `KEYWORD_MAP` + 垃圾过滤 `SPAM_PATTERNS` | 按你的品类调整 |
| `selection_brief.py` | 依赖上面三者输出 | 自动汇总 |
| `design_brief.py` | `design_rules.json` 的违规词 / 品类必拍项 | 广告法禁词表 + 平台规则 + 你自己的品类经验 |
| `design_render.py` | `photos/<SKU名>.jpg` 实拍图 | 自己拍（严禁用网图/AI 图冒充） |
| `content_plan.py` | `content_rules.json` 的公式权重 / 关键词层 / 发布时段 | 你的经验 + 闲鱼搜索框下拉词（脚本不含搜索量） |

---

## Issues 协作工作流

仓库已配置 3 类 Issue 模板（点 **New issue** 时选择）：

| 模板 | 用途 | 默认标签 |
|---|---|---|
| **选品任务** | 登记一次选品调研/上架闭环（甄选品主责） | `选品任务` |
| **经营复盘** | 周/月漏斗复盘（数明察主责） | `经营复盘` |
| **脚本问题** | 工具箱 bug 反馈 / 功能建议 | `脚本反馈` |

协作闭环：
1. 甄选品开「选品任务」Issue → 跑 `selection_scorer.py` 填四维 → 团队认领待办
2. 上架 48h 后数明察开「经营复盘」Issue → 跑 `dashboard.py` 定位瓶颈 → 对应角色接优化动作
3. 任何脚本问题开「脚本问题」Issue

> 模板路径：`.github/ISSUE_TEMPLATE/`，可在仓库网页直接编辑。

---

## 自动化（GitHub Actions）

两个工作流已就绪，提交到仓库即自动启用：

| 工作流 | 触发 | 动作 |
|---|---|---|
| `daily-trend.yml` | 每天 09:00（北京）/ 手动 | 抓 GitHub Trending → 落盘 `trends/YYYY-MM-DD.md` |
| `weekly-brief.yml` | 每周一 09:30（北京）/ 手动 | 跑评分器 + 生成周简报 → 落盘 `briefs/YYYY-MM-DD.md` |

手动触发：仓库 **Actions** 标签页 → 选工作流 → **Run workflow**。

---

## 免责声明

本工具仅用于选品研究与方法论沉淀，不构成任何投资建议；闲鱼交易请遵守平台规则与法律法规。

---
由 WorkBuddy「闲鱼电商军团」专家出品 · 2026-11-10 建 · 2026-11-11 补 Issues 模板与使用说明 · 2026-11-11 增加「图玲珑」设计出稿 + 出图工具链 · 2026-11-11 增加「文种草」内容排期工具链
