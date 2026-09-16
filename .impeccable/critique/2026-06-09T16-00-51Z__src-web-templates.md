---
target: src/web/templates
total_score: 27
p0_count: 0
p1_count: 3
p2_count: 2
timestamp: 2026-06-09T16-00-51Z
slug: src-web-templates
---
# Critique Report: AITrader Web Dashboard

**Target**: `src/web/templates/` (5 pages: dashboard, trader, stock, reports, control)
**Date**: 2026-06-09

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Toast 和状态指示良好，但手动触发交易缺少 loading 反馈 |
| 2 | Match System / Real World | 3 | 新手语言翻译到位，参数英文 key 经 JS 映射无影响 |
| 3 | User Control and Freedom | 3 | Esc 关闭 Modal、可折叠面板，但无可撤销的参数修改 |
| 4 | Consistency and Standards | 3 | 组件体系一致，个别内联样式漂移 |
| 5 | Error Prevention | 2 | 数字输入限定了类型，但触发交易/保存参数缺少确认 |
| 6 | Recognition Rather Than Recall | 3 | 上下文帮助完善，悬停提示覆盖关键元素 |
| 7 | Flexibility and Efficiency | 2 | 无键盘快捷键、无搜索/筛选、表格不支持排序 |
| 8 | Aesthetic and Minimalist Design | 3 | 干净克制，策略简介区域文字密度偏高 |
| 9 | Error Recovery | 2 | 错误可检测但恢复路径不明确，无可回退操作 |
| 10 | Help and Documentation | 3 | 每页都有可折叠帮助，参数有提示，但无搜索功能 |
| **Total** | | **27/40** | **Good — 坚实基础，针对性改进可达 32+** |

## Anti-Patterns Verdict

**干净通过。** 这不是 AI 生成的界面——没有渐变文字（logo 是唯一例外且有意为之）、没有 side-stripe border、没有 hero-metric 模板、没有 tiny uppercase eyebrow、没有 01/02/03 编号 scaffolding、没有 SaaS 奶油色背景。三层暗色调分层（abyss→steel→frosted）+ 双色渐变克制使用 + 毛玻璃仅在浮层出现。通过了二阶 reflex 检查：不是"暗色金融工具 → 通常的 navy-and-gold"，而是冷调蓝靛渐变 + 玻璃隐喻，有自己的语言。

**Deterministic scan**: `detect.mjs` 返回 0 个发现——自动化检测器也未发现任何反模式。

## Overall Impression

这是一个超出预期的 Dashboard：暗色主题有三层深度、帮助系统对新手友好、策略信号有人话翻译、CSS token 体系完整。最大的问题是它停留在"功能完整"阶段——交互是静态页面跳转，缺少实时感和效率工具（搜索、排序、键盘快捷键）。把它从"能用的报表"升级到"好用的工具"，收益最高。

## What's Working

1. **三层背景深度**：`abyss → steel → frosted` 的区别微妙但有效。卡片不是靠阴影从背景里"跳出来"，而是靠色调——这个处理比大多数暗色 Dashboard 成熟。

2. **新手友好系统**：可折叠帮助框 + `translateReason()` 函数将 RSI/MA/PE 翻译成人话 + 悬停 tooltip + PE/PB 的"偏低/偏高/合理"解释。这在本该冷冰冰的金融工具里是意外的人性化。

3. **统一的 Token 体系**：所有颜色通过 CSS 自定义属性引用，Semantic Badge 色有独立变量——这意味着改主题只需改 `:root`，不是散落在 5 个文件里的硬编码。

## Priority Issues

1. **[P1] 无键盘导航和效率工具** — Dashboard 和数据表格不支持搜索、筛选、排序。操盘手列表只能按收益率排序（服务端固定），无法按名称/策略类型/资产规模排序。股票表格没有搜索框——在 50+ 只股票里找特定代码靠肉眼扫描。
   - **Why it matters**: 个人投资者每天看一遍，几次之后就想要效率——每次都要滚动找同一个操盘手是纯粹的摩擦。
   - **Fix**: 添加客户端表格排序（点击表头排序）、简易搜索框（filter 输入）、键盘快捷键（`1`/`2` 切换短线/长线组）
   - **Suggested command**: `/impeccable harden src/web/templates/dashboard.html`

2. **[P1] 对比度违规——红色文字不达标** — `--red: #ef4444` 在 `--bg: #0a0e17` 上的对比度约 4.0:1，低于 WCAG AA 要求的 4.5:1。亏损百分比和卖出标签使用此红色，色弱用户在快速扫读时可能无法区分。
   - **Why it matters**: 金融数据的涨跌区分是核心信息——如果用户看不清楚亏损数字，信任感直接受损。红/绿色盲占男性 8%。
   - **Fix**: 将 `--red` 调亮至 `#f87171`（对比度 5.2:1），或为亏损值添加 `↓` 箭头图标作为双重编码
   - **Suggested command**: `/impeccable audit` (已在本轮中覆盖，见 Audit 报告)

3. **[P1] 触发交易/保存参数缺少确认和 loading 状态** — "手动触发交易"按钮点击后无 loading 指示器、无确认对话框。参数保存无"保存中..."以外的反馈——修改完直接写文件。
   - **Why it matters**: 触发真实交易（即使是模拟）有心理重量。点击后没有反馈 = 用户不确定操作是否生效，可能重复点击。
   - **Fix**: 触发交易前弹出确认对话框（"确定要执行今日交易吗？将撮合所有操盘手的挂单"）；按钮在请求期间显示 spinner + 禁用状态；完成后 toast 显示成交/拒绝数量
   - **Suggested command**: `/impeccable harden src/web/templates/control.html`

4. **[P2] 第三方 CSS 颜色 (#475569, #1e293b) 硬编码在 HTML 中** — Chart.js 的 grid/tick 颜色使用了不在 CSS token 中的值：`#1e293b`（图表网格）、`#475569`（stat hint 变体）、`#1e293b`（参数行分割线）。它们和 `--border: #1e2d45` 相近但不相等——视觉上几乎看不出来但 token 体系不完整。
   - **Why it matters**: 不破坏当前体验，但未来如果有人想统一调亮/调暗所有分割线，这些硬编码值会被遗漏。
   - **Fix**: 添加 `--chart-grid` 和 `--text-hint` token 到 `:root`，替换所有内联硬编码颜色
   - **Suggested command**: `/impeccable document` (已在 init 中完成，可作为 polish 的一部分)

5. **[P2] 表格在窄屏无横向滚动处理** — 768px 以下 grid-2 变成单列，但表格（交易历史、持仓明细）没有 `overflow-x: auto` 包裹。数据列超过 5 列时在小屏上会溢出。
   - **Why it matters**: 虽然目标用户是桌面端，但在 iPad 竖屏或小笔记本上表格会截断。响应式不是"手机优先"才算——768px 是常见窗口宽度。
   - **Fix**: 给所有 `<table>` 父容器添加 `overflow-x: auto` 和 `-webkit-overflow-scrolling: touch`
   - **Suggested command**: `/impeccable adapt src/web/templates`

## Persona Red Flags

**Alex (Power User — 每日盯盘的量化投资者)**：
- 无键盘快捷键：要在短线/长线之间切换必须用鼠标点导航——Tab 键序列是 logo→短线→长线→周报→控制，无法一键直达
- 表格不支持排序：想找"最近交易最多"的操盘手，只能肉眼扫
- 参数列表全部展开时长达 6 个策略 × 平均 6 个参数 = 36 行，无折叠全部/展开全部的视觉区分
- **高流失风险**：3 天后仍然没有效率捷径，Alex 会放弃 Dashboard 直接用 CLI

**Sam (Accessibility-Dependent — 屏幕阅读器用户)**：
- 无 ARIA label：nav 链接没有 `aria-label`，屏幕阅读器读出的是 emoji 字符 "⚡ 短线"
- `#64748b`（text3）对比度 3.8:1，低于 4.5:1 —— 日期、hint 文字对低视力用户不可读
- 无显式 focus 指示器：默认浏览器 focus ring 是唯一键盘导航可见标记，在暗色背景下可能不够醒目
- Chart.js canvas 无 `aria-label` 或 fallback 描述

## Minor Observations

- 控制面板的"展开全部"按钮在 allOpen=true 时文字应变为"收起全部"，但初始状态和实际展开状态可能不同步
- Dashboard "活跃策略" stat 的判定逻辑 `abs(return_pct) > 0.001` —— 收益率刚好 0.001% 的策略会被标记为"不活跃"，这个阈值过于敏感
- `translateReason()` 函数的正则替换 map 缺少对某些常见模式的处理（如"放量突破"）
- Nav 的数据源状态指示灯使用了 emoji（🟢🔴），在旧版 Windows 上 emoji 渲染可能异常

## Questions to Consider

- "如果 Dashboard 是一个实时终端而不是静态报表，用户会每天多看几次吗？"
- "6 个策略操盘手——用户真正关注的是哪 2-3 个？能否支持自定义置顶？"
- "收益曲线的 6 条线在 320px 高度里重叠严重——拆成独立小图会更清晰吗？"
