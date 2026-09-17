# InvestProject（AITrader）项目长期约定

## 运行时可写路径
- 所有运行时可写状态走 `src/runtime.py`：`data_dir()`（本地回落仓库根，平台回落 `POCKETBAY_DATA_DIR`）、`config_path("x.yaml")`（可写，首启从包内 `config/` 播种）、`db_url()`（优先 `DATABASE_URL`，否则 SQLite 落可写目录）。
- 页面可改配置（`traders.yaml`/`watchlist.yaml`）属运行时状态，勿申报为平台"敏感配置文件"（会只读挂载致写失败）。只读配置（`settings.yaml`/`screening.yaml`/`scenarios.yaml`）留包内 `config/`，用 `src/config.py:CONFIG_DIR` 读。

## 依赖清单
- 根 `requirements.txt` 是部署唯一依赖清单，必须含 `fastapi`/`uvicorn`/`jinja2`（fastapi 核心不带 jinja2，用了 Jinja2Templates 必须显式声明）。测试/未用依赖放 `requirements-dev.txt`。

## 代码托管与部署
- 远端 `origin`=github.com/freeEasyLoope/AiTraderPlatform（公开仓库，主分支 main，不含真实密钥）。本机 `credential.helper=manager`；非交互推送加 `GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never`。
- PocketBay（`*.pocketbay.app`）：用 `~/.workbuddy/skills/pocketbay-deploy/`，`project_slug=aitrader`，language=python，勿传 framework_hint/勿写 Dockerfile；会注入 `POCKETBAY_DATA_DIR=/data`（选数据库方案 D 落持久卷）；打包排除 `*.db`/`logs/`/缓存；配对会话可复用（同会话重复 upload 即发新版）。
- WorkBuddy 发布（`*.app.workbuddy.host`）：用 `workbuddy_sites_deploy`，勿混用 PocketBay 技能。
- 启动单进程，勿加 `--workers`（每 worker 各起 APScheduler → 重复下单）。密钥不进包，LLM 无 key 时优雅降级（不 500）。

## 启动与探活铁律
- 启动路径(lifespan)与探活路径绝不允许不受控网络等待。先看日志有无 `Application startup complete`。
- 数据源探测用 `runtime.run_with_timeout(fn, timeout, default)`（守护线程+join 超时）；baostock/akshare 裸调等于把可用性交给对端。首屏只读缓存绝不等待；探测 15s 上界，超时回落 MockDataProvider（预算别太紧，误回落 mock 写入虚构价格更严重）。
- lifespan 非必需装配（调度器等）一律 try/except，任何可选功能不得阻断 web 启动。
- 勿在可能阻塞的调用外替换全局 sys.stdout；压第三方库噪声用常驻行过滤器（`data/baostock_utils.py:install_quiet_stdout()`）。

## 数据源接入
- baostock 登录只走 `open_bs()/close_bs()`（带超时+熔断），禁裸调 `bs.login()`。
- 历史日线 `kline_http.py`：新浪 KLine→腾讯 fqkline→baostock；腾讯成交量单位「手」需 ×100。
- 日期边界用 `runtime.normalize_date()`；紧凑 `YYYYMMDD` 与 `YYYY-MM-DD` 字符串比较会静默失数。
- 实时行情 `realtime_http.py`：腾讯 `qt.gtimg.cn` 批量→腾讯 `web.ifzq.gtimg.cn`；新浪 `hq.sinajs.cn` 仅兜底。路由层勿直连 `hq.sinajs.cn`，用 `fetch_sina_format()`。回落 Mock 会写虚构价格——部署后须确认 `/api/health` 的 realtime=true。

## 部署环境差异（同一份代码出口可达性不同）
- WorkBuddy 沙箱：注入 PORT、无 POCKETBAY_DATA_DIR/DATABASE_URL；可用新浪实时/腾讯 KLine，baostock 永久挂起（PE/PB/分红/公告离线降级）。TCP 探测不可信，用 `GET /api/diag` 验真。
- PocketBay：baostock 可用（PE/PB 通）；新浪实时被拒→靠腾讯多源链。外壳页+embed 帧，应用会被休眠（POST /.pocketbay/wake 唤醒）；应用侧只能保活+让失败可见。

## Web 层约定
- 页面路由写全量路径，禁「prefix+get("/")」尾斜杠形态（307→明文 http→混合内容拦截→点没反应）。导航项目标不依赖 3xx。
- `/static/*` 引用带内容指纹 `?v={{ static_version() }}`（边缘缓存 max-age=14400，HTML no-store）；改静态文件后确认指纹随变。
- 动态响应 `Cache-Control: no-store`（`main.py:DynamicNoStore` 纯 ASGI 中间件）。
- `/api/ping` 仅保活（无外部探测）；`/api/health` 真探数据源；不可互替。
- 站内跳转是异步局部加载（base.html `asyncNav`）：交换边界 `#page-root` 与 `#page-scripts` 分开；页面脚本行首 `let/const` 会二次注入报"已声明"→用 `deLexicalize()` 降级为 `var`；`#navLoading` 基态必须隐藏（仅 `.on` 显示），否则永久盖屏；兜底整页导航；pushState 后自更新导航高亮。
- 导航状态灯：行情=realtime||sina、历史=history||baostock、财务=tushare（勿只看 sina）。
- A 股涨跌配色待用户决定（现涨绿跌红；`.red`/`.green` 兼承载错误/成功语义，不能直接交换 CSS 变量，须逐个翻转三元式）。
- 验证线上页面：断言 DOM 类名≠验证界面状态（须读 getComputedStyle 的 visibility/opacity/display）；WebFetch 有 15min 缓存（加 `?_ts=N`）；静态资源看响应头 `age`；curl 200≠点了有反应，交互须真实浏览器（Playwright 已装，点后给 20s 容差，遇休眠先点唤醒）。
- base.html 用内联 data-URI SVG favicon（避免 /favicon.ico 404）。

## 前端设计系统（UX 工作约定）
- 配色/间距走 `style.css` 的 `:root` CSS 变量；主题切换用 `[data-theme]` 覆盖变量，头部早期脚本 `localStorage` 读主题避免闪烁；切主题派发 `themechange` 事件供 Chart.js 重取 `getComputedStyle` 色值后 `chart.update()`。
- 新手引导：每页 `? 指标解释` 按钮 toggle `#helpBox`（`.help-box.show` 显示）。**已覆盖全部 12 个功能页**（含 screening、stock——stock.html 是最后补的，原缺）。
- 名词提示：`.term[data-tip]` + 共享 tooltip 元素（`#termTip`），事件委托 mouseover 显示 / mouseout 自动隐藏，`initTermTips()` 在 asyncNav 边界外常驻。
- 来源日期：`.src-date` 小药丸（带 🕐 before），模板用 `数据截至 {{ as_of_date() }}`（deps.py 注入全局 lambda，逐次渲染重算）。
- AI 周报：`/reports` 模板用 `{% if not ai_report_enabled %}` 显示"🚧 AI 周报功能暂未开通"横幅并禁用生成按钮；按钮回调 `AI_REPORT_ENABLED` 常量二次拦截给 toast。banner 文案为 `AI 周报功能暂未开通`（勿与 JS toast `该功能暂未开通` 混淆——后者恒存在）。

## 6 项 UX 体验优化（已完成并验证）
1. 新手引导 onboarding（全功能页 help-box）✅
2. 名词提示 term tooltips（`.term[data-tip]`）✅
3. 投资设置（auto_invest + portfolio，/settings 表单 + invest.yaml）✅
4. 来源日期 src-date 药丸（全数据页）✅
5. AI 周报门控（/reports 未开通横幅）✅
6. 主题切换（4 套 2026 调色板，`[data-theme]` 覆盖 shell 变量，Chart.js 经 `themechange` 重取色）✅
- 验证：离线 Jinja 渲染 14 模板零错误 + 6 项断言全过（`verify_templates.py`）；进程内 TestClient 启动 + 关键路由全 200、数据源探测失败优雅降级（`boot_test.py`）。部署前用户曾要求"先解决这 6 项再部署"。
