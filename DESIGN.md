---
name: AITrader Dashboard
description: 精密交易终端 — 现代、锐利、科技感。暗色玻璃与钢材质感，冷调双色渐变。
colors:
  abyss-bg: "#0a0e17"
  steel-surface: "#111827"
  frosted-card: "#161d2a"
  cold-border: "#1e2d45"
  sky-accent: "#38bdf8"
  indigo-accent: "#818cf8"
  profit-green: "#22c55e"
  loss-red: "#ef4444"
  warn-yellow: "#f59e0b"
  ink-primary: "#e2e8f0"
  ink-secondary: "#94a3b8"
  ink-tertiary: "#64748b"
  glass-overlay: "rgba(255,255,255,0.02)"
typography:
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Microsoft YaHei', 'PingFang SC', sans-serif"
    fontSize: "14px"
    lineHeight: 1.6
    fontWeight: 400
  heading:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Microsoft YaHei', 'PingFang SC', sans-serif"
    fontSize: "20px"
    fontWeight: 600
    letterSpacing: "0.02em"
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Microsoft YaHei', 'PingFang SC', sans-serif"
    fontSize: "12px"
    fontWeight: 500
    letterSpacing: "0.1em"
    textTransform: "uppercase"
  stat-value:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Microsoft YaHei', 'PingFang SC', sans-serif"
    fontSize: "30px"
    fontWeight: 800
    letterSpacing: "-0.02em"
  badge:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Microsoft YaHei', 'PingFang SC', sans-serif"
    fontSize: "12px"
    fontWeight: 600
    letterSpacing: "0.02em"
rounded:
  card: "14px"
  button: "8px"
  badge: "20px"
  input: "8px"
  modal: "16px"
spacing:
  container-padding: "28px 24px"
  card-padding: "24px"
  stat-padding: "20px"
  table-cell: "11px 10px"
  nav-padding: "0 28px"
  section-gap: "20px"
components:
  button-primary:
    backgroundColor: "linear-gradient(135deg, #38bdf8, #818cf8)"
    textColor: "#ffffff"
    rounded: "{rounded.button}"
    padding: "10px 24px"
    typography: "{typography.badge}"
  button-primary-hover:
    textColor: "#ffffff"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "#38bdf8"
    rounded: "{rounded.button}"
    padding: "10px 24px"
  button-danger:
    backgroundColor: "linear-gradient(135deg, #ef4444, #f87171)"
    textColor: "#ffffff"
    rounded: "{rounded.button}"
    padding: "10px 24px"
  badge-buy:
    backgroundColor: "rgba(34,197,94,0.12)"
    textColor: "#22c55e"
    rounded: "{rounded.badge}"
  badge-sell:
    backgroundColor: "rgba(239,68,68,0.12)"
    textColor: "#ef4444"
  badge-filled:
    backgroundColor: "rgba(56,189,248,0.12)"
    textColor: "#38bdf8"
  badge-rejected:
    backgroundColor: "rgba(245,158,11,0.12)"
    textColor: "#f59e0b"
---

# Design System: AITrader Dashboard

## 1. Overview

**Creative North Star: "Glass & Steel"**

AITrader 的界面是一块精密打磨的暗色玻璃——数据浮在表面上，背景退入深渊。不是嘈杂的营业部大屏，不是温吞的 SaaS 奶油色仪表盘。它是一台个人的交易终端：冷静、锐利、让人信赖。

深色三层背景（abyss → steel → frosted）构建空间感。天蓝与靛蓝的双色渐变是唯一的主色调，承载导航、按钮、图表和数据高亮——克制使用，每次出现都有明确含义。毛玻璃效果（backdrop-filter）用于浮层和导航，强化"玻璃"隐喻，但不出现在内容区以避免干扰数据阅读。

这个系统明确拒绝：传统炒股软件的密集表格和红绿闪烁、SaaS 模板的奶油暖色和圆角卡片海洋、扁平暗色但无层次的"开发者默认"风格。

**Key Characteristics:**

- 三层深度（bg / surface / card）+ 毛玻璃浮层，构建清晰的空间层级
- 双色渐变（天蓝→靛蓝）为唯一品牌强调，占屏幕面积 ≤10%
- 对标 Vercel Dashboard 的信息密度：数据锐利、留白克制、一眼看清
- 拒绝传统金融软件的一切视觉语言

## 2. Colors

冷调暗色基底 + 双色渐变强调。背景向品牌色微偏蓝而非暖色，避免落入"AI 默认暖色调"陷阱。

### Primary

- **Sky Accent** (`#38bdf8` / oklch(73% 0.14 230)): 主要强调色。用于主按钮渐变起点、图表线条、链接、活跃状态、accent 文字。出现在 ≤10% 的屏幕面积。
- **Indigo Accent** (`#818cf8` / oklch(62% 0.14 275)): 辅强调色。用于渐变终点、排行榜紫色标记。从不单独出现，始终与 Sky Accent 成对。

### Neutral

- **Abyss BG** (`#0a0e17`): 页面底色。最深层，不可用于卡片或交互元素。
- **Steel Surface** (`#111827`): 导航栏背景、弹窗遮罩下的暗面。第二层。
- **Frosted Card** (`#161d2a`): 卡片和 stat 块背景。与 steel 之间的微妙对比（ΔL ≈ 5%）构建层次而非依赖阴影。
- **Cold Border** (`#1e2d45`): 所有边框、分割线、表格底部线。比 card 亮一档，足够区分但不抢眼。
- **Ink Primary** (`#e2e8f0`): 正文。与 abyss bg 对比度 ≈ 12:1，远超 4.5:1。
- **Ink Secondary** (`#94a3b8`): 辅助文本、描述、提示。与 bg 对比度 ≈ 5.5:1。
- **Ink Tertiary** (`#64748b`): 日期、hint 文字、非活跃导航。与 bg 对比度 ≈ 3.8:1——够用但仅限大号文字。
- **Glass Overlay** (`rgba(255,255,255,0.02)`): 半透明覆盖，用于 card 背景的额外纹理层，非必要不用。

### Semantic

- **Profit Green** (`#22c55e`): 盈利、上涨、买入方向。始终配合 `+` 号或 `↑`，不单靠颜色。
- **Loss Red** (`#ef4444`): 亏损、下跌、卖出方向。始终配合 `-` 号或 `↓`。
- **Warn Yellow** (`#f59e0b`): 警告提示、拒绝状态、关注信号。用于 tip-card 和 rejected badge。

### Named Rules

**The 10% Rule.** 双色渐变（sky + indigo）只出现在 ≤10% 的屏幕面积——渐变按钮、nav logo、stat hover 顶线。其余地方用单色。渐变的稀缺性是它的力量。

**The Cold Steel Rule.** 所有 neutral 色向 sky blue 微偏 0.005–0.01 chroma，不向暖色偏。背景是冷的、锐利的——温暖来自数据和策略的"活"感，而非颜色本身。

**The Green-Red With Symbols Rule.** profit-green 和 loss-red 永远配合 `+`/`-` 符号或箭头图标出现。不依赖颜色作为唯一的信息编码。

## 3. Typography

**Body Font:** -apple-system, BlinkMacSystemFont, 'Microsoft YaHei', 'PingFang SC', sans-serif

单字体族策略：通过 weight（300/400/500/600/800）和 size 对比构建层级，而非引入多个字体。Microsoft YaHei 和 PingFang SC 确保中英文混排质量。无衬线强化科技感和数据锐度。

### Hierarchy

- **Stat Value** (800, 30px, 1.1, -0.02em): Dashboard 大数字——总资产、收益率。页面中最大、最重的文字。每页 ≤8 个。
- **Heading** (600, 20px, 1.6, 0.02em): 页面主标题和卡片标题（h2 级别）。与 stat value 的 scale 比 ≈ 1.5:1。
- **Body** (400, 14px, 1.6): 正文、表格内容、参数值。line-height 1.6 确保中文字符呼吸空间。
- **Label** (500, 12px, 1.6, 0.1em, uppercase): Stat 标签、表格头、分类标记。全部大写 + 宽字距表明这是元数据而非内容。
- **Badge** (600, 12px, 0.02em): 状态标记——买入/卖出/成交/拒绝。加粗 + 微字距。

### Named Rules

**The Scale Gap Rule.** 相邻层级之间的 font-size 比例 ≥ 1.25。Stat (30px) → Heading (20px) → Body (14px) → Label (12px)：每步下降明显，无扁平感。

**The Single Family Rule.** 一页中最多一个字体族。用 weight 和 size 区分角色，不用第二个字体。

## 4. Elevation

本系统使用**色调分层（tonal layering）为主、阴影为辅**的深度策略。三层背景色（abyss → steel → frosted）本身就是深度——越浅越"靠近"用户。阴影只在 hover 和浮层（nav、modal、toast）时激活，静态下卡片与背景的区分靠色调而非影子。

毛玻璃（backdrop-filter: blur）用于 nav 和 modal overlay，强化"透过玻璃看数据"的隐喻。这是系统唯一的装饰性深度效果。

### Shadow Vocabulary

- **Ambient Card** (`box-shadow: 0 4px 24px rgba(0,0,0,0.3)`): 卡片默认阴影。足够区分层次但不过深——不会让人想起"2014 年的投影"。
- **Hover Lift** (`box-shadow: 0 6px 32px rgba(0,0,0,0.4)`): 配合 `translateY(-1px)` 上浮，卡片 hover 激活。
- **Button Glow** (`box-shadow: 0 2px 12px rgba(56,189,248,0.25)`): 渐变按钮专属。带 accent 色的扩散光晕。
- **Button Glow Hover** (`box-shadow: 0 4px 20px rgba(56,189,248,0.4)`): 按钮 hover 时增强光晕。

### Named Rules

**The Flat-At-Rest Rule.** 表面在静态下是平的；阴影作为状态响应出现（hover、elevation、focus）。静态无阴影 = 干净；hover 有阴影 = 可交互的信号。

**The Glass-Is-Layered Rule.** 毛玻璃效果（backdrop-filter blur）只在 z-index ≥ 100 的元素上使用——nav（sticky top 100）和 modal overlay（200）。内容区永远不 blur。

## 5. Components

### Buttons

**Character:** 利落、有重量感。渐变按钮是系统中最强的视觉信号——一个屏幕最多一个。

- **Shape:** 8px 圆角（`--radius-sm`）。不是胶囊，不是直角。刚好"圆"到感觉精准。
- **Primary:** 天蓝→靛蓝 135° 渐变 + 白色文字 + 10px 24px 内边距。带 accent 色光晕阴影（0 2px 12px rgba(56,189,248,0.25)）。hover 上浮 1px + 光晕增强。active 回弹。
- **Ghost:** 透明背景 + 天蓝文字 + 1px cold-border 边框。用于次要操作（展开全部、帮助切换）。hover 背景变 rgba(56,189,248,0.08)。
- **Danger:** 红色渐变（#ef4444 → #f87171）。仅用于不可逆操作。

### Badges

**Character:** 微型状态标记，不抢内容。

- **Shape:** 20px 全圆角胶囊。
- **Buy (badge-buy):** rgba(34,197,94,0.12) 半透明绿底 + profit-green 文字。
- **Sell (badge-sell):** rgba(239,68,68,0.12) 半透明红底 + loss-red 文字。
- **Filled (badge-fill):** rgba(56,189,248,0.12) 半透明天蓝底 + sky-accent 文字。
- **Rejected (badge-rej):** rgba(245,158,11,0.12) 半透明黄底 + warn-yellow 文字 + help cursor（hover 显示拒绝原因）。

### Cards

**Character:** 安静的容器。frosted-card 背景 + cold-border 边框 + ambient shadow。

- **Corner Style:** 14px（`--radius`），比按钮更圆润——区分"容器"和"操作"。
- **Background:** `#161d2a`（frosted-card），比 surface 亮一档（ΔL ≈ 5%）。
- **Border:** 1px solid `#1e2d45`（cold-border）。微妙但存在。
- **Shadow:** Ambient Card + hover 时增强为 Hover Lift + translateY(-1px)。
- **Internal Padding:** 24px 统一。不随内容密度变化。
- **Nesting:** 禁止卡片嵌套卡片。

### Stats

**Character:** Dashboard 的核心信息单元。独立的迷你卡片，hover 时顶线亮起。

- **Shape:** 14px 圆角 + 20px 内边距 + ambient shadow。
- **Hover:** translateY(-2px) + 顶部 2px 渐变线（sky→indigo）渐显（opacity 0→1，transition 0.3s）。这是系统唯一的 stat 动画。
- **Value:** stat-value typography（800, 30px）。颜色根据语义：cyan（总资产）、green/red（收益率）、default（数量）。
- **Label:** label typography（12px uppercase + 0.1em letter-spacing）。
- **Hint:** 11px ink-tertiary 变体（`#475569` 比 `--text3` 稍暗），附加一行上下文。

### Inputs / Fields

**Character:** 融入背景、focus 时亮起。

- **Style:** abyss bg + 1px cold-border + 8px 圆角 + 14px 字号 + 8px 14px 内边距。
- **Focus:** border-color 变为 sky-accent + 3px rgba(56,189,248,0.1) 光晕（box-shadow）。
- **Date input:** 同 text input 样式，统一风格。
- **Select:** 同 input 样式 + 最小宽度 140px。

### Navigation

**Character:** 固定顶部，毛玻璃底层。简洁的标签式导航。

- **Style:** steel-surface 背景 + 底部 1px cold-border + backdrop-filter blur(12px)。高 60px。
- **Logo:** 20px weight 800 + 双色渐变文字（`background-clip: text`）。唯一允许渐变文字的元素——品牌标识，非装饰。
- **Nav Links:** 14px weight 500。默认 ink-tertiary（非活跃），hover 变 ink-primary + rgba(255,255,255,0.04) 背景，active 变 sky-accent + rgba(56,189,248,0.08) 背景。8px 16px padding + 8px 圆角。
- **Data Source Status:** 11px ink-tertiary，nav 内嵌，实时显示数据源连接状态（🟢/🔴 指示灯）。

### Modal

**Character:** 浮层玻璃，聚焦股票详情。

- **Overlay:** rgba(0,0,0,0.7) + backdrop-filter blur(4px)。全屏，z-index 200。
- **Panel:** frosted-card 背景 + 16px 圆角 + 28px 内边距。max-width 560px, 90% 宽度。最大高度 80vh，overflow-y auto。
- **Close Button:** 绝对定位右上角。透明背景，22px ink-tertiary，hover 变 ink-primary。无阴影。
- **Stock Stats:** 内部 3 列 grid（repeat(3,1fr)），每列 abyss bg + 8px 圆角 + 12px padding。

### Toast

**Character:** 短暂的消息浮层，右上角滑入。

- **Style:** 14px weight 600 + 14px 24px padding + 8px 圆角 + ambient shadow。z-index 999。
- **Success:** profit-green 背景 + 白色文字。
- **Error:** loss-red 背景 + 白色文字。
- **Animation:** toastIn（0.3s，从右滑入）→ 停留 2.4s → toastOut（0.3s，fade out）。

### Tables

**Character:** 数据密度最大化，装饰最小化。

- **Header:** 11px ink-tertiary + uppercase + 0.06em letter-spacing + 2px cold-border 底部分割线。12px 10px padding。
- **Body:** 13px ink-primary + 11px 10px padding。行底部 1px rgba(30,45,69,0.5) 分割线（比 cold-border 更淡）。
- **Hover:** 行背景变 rgba(56,189,248,0.03)（几乎不可见但足以追踪视线）。
- **Empty State:** 居中 ink-tertiary + 20px padding，"暂无数据"。

### Chart

**Character:** Chart.js 折线图。天蓝色调，半透明填充。

- **Line:** 2px sky-accent (`#38bdf8`)，tension 0.3，无数据点（pointRadius: 0）。
- **Fill:** 天蓝到透明渐变（rgba(56,189,248,0.3) → transparent）。
- **Grid:** cold-border 色（`#1e293b` 对应图表的 dark grid），x 轴最多 10 ticks，y 轴 ¥ 格式化。
- **Tooltip:** 白色文字 + `¥XX.XX` 格式。
- **Legend:** ink-secondary 文字色 + 圆点样式（8px boxWidth）。

### Help Box

**Character:** 折叠式新手帮助面板，默认隐藏。

- **Style:** rgba(56,189,248,0.03) 背景 + rgba(56,189,248,0.15) border + 14px 圆角 + 20px 24px padding。
- **Toggle:** 圆角 20px 胶囊按钮 + rgba(56,189,248,0.06) 背景 + sky-accent 文字。hover 加深背景。
- **Animation:** fadeIn（opacity + translateY(-8px)），0.3s。

### Tip Card

**Character:** 条件性警告/提示条。

- **Warning:** rgba(245,158,11,0.06) 背景 + rgba(245,158,11,0.15) border + warn-yellow 文字。
- **Info:** rgba(56,189,248,0.04) 背景 + rgba(56,189,248,0.1) border + ink-secondary 文字。

### Collapsible Card (Control Panel)

**Character:** 可折叠的参数组，用于控制台。

- **Header:** 16px 20px padding + pointer cursor + 点击折叠。左侧 ▼/▶ 图标（12px ink-tertiary，transition 0.2s）。
- **Body:** 默认展开。折叠时 display: none。
- **Param Row:** flex + 12px gap + 底部 rgba(30,45,69,0.3) 分割线。label 13px ink-secondary 最小宽 130px。desc 11px ink-tertiary 最小宽 200px。

## 6. Do's and Don'ts

### Do:

- **Do** 使用三层背景（abyss → steel → frosted）构建深度，不依赖重度阴影。
- **Do** 双色渐变（sky + indigo）用于 ≤10% 的屏幕面积：nav logo、主按钮、stat hover 顶线、图表线条。
- **Do** 盈利用 green(#22c55e) + `+` 号，亏损用 red(#ef4444) + `-` 号。颜色和符号双重编码。
- **Do** 毛玻璃效果（backdrop-filter blur）仅用于 z-index ≥ 100 的浮层（nav、modal overlay）。
- **Do** 每页面最多一个渐变主按钮。其余操作用 ghost 或文字链接。
- **Do** 表格行 hover 用 rgba(56,189,248,0.03) 背景——足够追踪视线但不干扰内容。
- **Do** stat value(800 30px) 和 heading(600 20px) 保持 ≥1.5:1 的 scale 比。
- **Do** 所有动画配 `@media (prefers-reduced-motion: reduce)` 降级为 instant 或 crossfade。

### Don't:

- **Don't** 使用传统炒股软件的密集表格、红绿闪烁、信息过载布局。这是交易终端，不是营业部大屏。
- **Don't** 使用 SaaS 奶油色暖调背景（oklch L 0.84-0.97 C < 0.06 hue 40-100）。中性色永远偏冷，向 sky blue 微偏 chroma。
- **Don't** 卡片嵌套卡片。card 是最外层容器。
- **Don't** 使用 side-stripe border（border-left/right > 1px 作为彩色装饰条）。
- **Don't** 在正文中使用渐变文字（background-clip: text）。nav logo 是唯一例外——它是品牌标识。
- **Don't** 使用 `z-index: 999` 或 `9999`。系统的语义 scale 是：dropdown(50) → sticky(100) → modal-backdrop(200) → modal(210) → toast(999)。
- **Don't** 添加第三个字体族。系统栈（-apple-system / Microsoft YaHei / PingFang SC）是唯一的字体。
- **Don't** 在静态卡片上使用可见阴影。Ambient shadow 是微妙的——如果阴影比卡片背景亮，就已经太深了。
- **Don't** 使用 tiny uppercase tracked eyebrow（"ABOUT" / "PROCESS" / "PRICING"）作为 section 标记——这是 AI 语法，不是设计。
- **Don't** 使用 01/02/03 编号作为 section 的默认 scaffolding。
