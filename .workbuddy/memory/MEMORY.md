# InvestProject（AITrader）项目长期约定

## 运行时可写路径（部署关键约定）
- **所有运行时可写状态必须走 `src/runtime.py`**，不要用 `Path(__file__).parent.parent.../config` 之类硬编码相对路径。
  - `data_dir()`：本地回落仓库根，托管平台回落 `POCKETBAY_DATA_DIR`（如 `/data`）
  - `config_path("xxx.yaml")`：返回可写路径，首启从包内 `config/` 播种
  - `db_url("data/simulation.db")`：优先 `DATABASE_URL`，否则 SQLite 落可写目录
- **页面可改的配置**（`traders.yaml`、`watchlist.yaml`）属于运行时状态，不要申报为平台"敏感配置文件"——会被只读挂载导致写入失败。
- 纯只读配置（`settings.yaml`、`screening.yaml`、`scenarios.yaml`）留在包内 `config/`，用 `src/config.py:CONFIG_DIR` 读。

## 依赖清单约定
- **根目录 `requirements.txt` 是部署平台的唯一依赖清单**，必须包含 web 服务最低集：`fastapi` / `uvicorn` / `jinja2`。
- 测试与未使用依赖放 `requirements-dev.txt`，不要混进生产清单（构建时长）。
- 注意：`fastapi` 核心不带 `jinja2`，用了 `Jinja2Templates` 就必须显式声明。

## 部署目标（两个平台，别混用）
- **PocketBay**（`*.pocketbay.app`）—— 用用户级技能 `~/.workbuddy/skills/pocketbay-deploy/`，走官方 HTTP 协议 + 配对页。
- **WorkBuddy App 发布**（`*.app.workbuddy.host`）—— 用 `workbuddy_sites_deploy` 工具。
- 用户说"部署到 pocketbay / 不是 workbuddy 那个"时，**不要**再用 `workbuddy_sites_deploy`。
- **密钥不进包**：LLM 接口在无 `ANTHROPIC_API_KEY` 时必须优雅降级，不允许 500。禁止把 key 写进源码/yaml。
- 启动命令保持**单进程**，不要加 `--workers`（每个 worker 会各起一个 APScheduler，重复下单）。

### PocketBay 已实测事实
- 线上地址：**<https://aitrader.pocketbay.app>**（`project_slug=aitrader`；`language=python`；平台自动识别入口，**不要传 `framework_hint`**、**不要写 Dockerfile**）
- **会注入 `POCKETBAY_DATA_DIR=/data`**（与 WorkBuddy 沙箱不同）→ 选数据库方案 D 即可零改动落持久卷；`DATABASE_URL` 未注入
- 打包必须排除本地 `*.db` / `logs/` / 缓存；数据库选 **D（文件/SQLite 改用 /data 持久卷）**
- **配对会话可复用**：同一会话重复 `upload` 即发布新版本，不需要用户重新配对
- 协议正文说 `client_ide` / `client_llm` "可选"是错的，实际 **422 必填**，用 `"other"` + `*_other` 字段

## 事件循环约定
- 项目全部是阻塞式 IO（urllib / baostock / akshare），**路由处理器凡是内部做网络或重计算的，一律用同步 `def`**（FastAPI 自动丢线程池），不要写 `async def` 却在里面做阻塞调用——会冻结单进程服务，导致平台探活失败。

## 启动路径铁律（踩过两次坑）
- **启动路径（lifespan）与探活路径上，绝不允许出现不受控的网络等待。** 平台只会报"服务不可达"，真实原因往往是"卡住"，报错信息会把人引向错误方向——先看日志里有没有 `Application startup complete`。
- **数据源探测必须设界**：`baostock` / `akshare` 都不接受超时参数，裸调等于把进程可用性交给对端网络。统一用 `src/runtime.py:run_with_timeout(fn, timeout, default)`（守护线程 + join 超时）。
  - 首屏市场环境：后台刷新 + 120s 计算上界 + 指数退避，首屏只读缓存，绝不等待。
  - 数据源探测：15s 上界，超时回落 `MockDataProvider`。**预算不要给太紧**——误回落 mock 会写入虚构价格，比多等几秒严重。
- **lifespan 里的非必需装配（调度器等）一律包 `try/except`**：任何可选功能出问题都不允许阻断 web 启动。
- **不要在可能阻塞的调用外面替换全局 `sys.stdout`**：一旦挂死，重定向永久生效，进程日志整段静音，线上无法排障。要压第三方库噪声，用常驻**行过滤器**（见 `data/baostock_utils.py:install_quiet_stdout()`）。
- **数据页上的网络等待用"缓存 + 墙钟预算"解决**，不要为了快而牺牲数据正确性。参考 `fundamentals._try_baostock`：按 symbol 缓存（含**负缓存**）+ `budget` 上限 + 命中缓存时不登录。

## 数据源接入约定
- **所有 baostock 登录必须走 `src/data/baostock_utils.py:open_bs()/close_bs()`**，禁止裸调 `bs.login()`。它带超时 + 熔断（不可用时立即返回 `None`），是唯一能防止进程被永久挂起拖死的入口。
- **历史日线走 HTTP 多源**（`src/data/kline_http.py`）：新浪 KLine → 腾讯 fqkline → baostock 兜底。新浪与 baostock(adjustflag=2) 口径逐项一致；腾讯成交量单位是「手」，需 ×100。
- **日期一律在边界归一化**：用 `runtime.normalize_date()`。只要有一处用字符串比较日期区间，传入紧凑格式 `YYYYMMDD` 就会**静默失数**（`"20240101" <= "2024-01-02"` 因 ASCII 顺序恒为 False），且 baostock 会判非法日期——两端都不抛异常，极难定位。回归测试见 `tests/test_data/test_dates.py`。
- **实时行情走 `src/data/realtime_http.py` 的多源链**（腾讯 `qt.gtimg.cn` 批量 → 腾讯 `web.ifzq.gtimg.cn` 的 `qt` 节点），新浪 `hq.sinajs.cn` 只作最后兜底。
  - 路由层**不要**再直连 `hq.sinajs.cn`：用 `fetch_sina_format(symbols)`，它产出与新浪**完全一致的线格式**，历史解析逻辑零改动。
  - provider 层走 `SinaClient._fetch_batch`（新浪优先 + 熔断 + 多源兜底）。**回落 Mock 会写入虚构价格，比没有数据更危险**——部署后必须确认 `/api/health` 的 `realtime` 为 true。

## 部署环境实测事实

**⚠️ 两个托管的出口可达性完全不同——同一份代码，WorkBuddy 沙箱通新浪、PocketBay 通 baostock。所以任何单一数据源都不要假设可达。**

### WorkBuddy 沙箱（`*.app.workbuddy.host`）
- 会注入 `PORT`，但**未注入 `POCKETBAY_DATA_DIR` / `DATABASE_URL`** → 可写目录回落容器内应用目录，**不跨版本保留**；`PORT` 已用作"是否在平台运行"的判据（`web/main.py` 启用进程内调度）。
- 本地 `data/simulation.db` 会随包上云（该工具不自动排除），线上首屏会带着本地历史。
- **TCP 层探测不可信**（透明代理让任何主机 1ms「连上」），必须用 HTTP 层探测真实响应体（`GET /api/diag`）。
  - **可用**：`hq.sinajs.cn` 实时行情（200/14ms）、`quotes.sina.cn` KLine（200/249ms）、`ifzq.gtimg.cn` 腾讯 fqkline（200/288ms）。
  - **不可用**：baostock（永久挂起，不是快速失败）、网易历史日线（502）、东方财富（RemoteDisconnected）、Yahoo（TLS 被断）。
  - 结论：实时行情 + 历史日线可用；baostock 派生的 PE/PB、分红、公告按"离线"优雅降级。
- 线上地址：<https://aitrader-dashboard.app.workbuddy.host/>（`sandboxId=d682aa28e8414c3a973768af2c73f16b`；`language=python` / `port=8000` / `startCmd=python web.py`）。
  - 注意：该目录默认 startCmd 探测会找 `main.py` 而报 `No such file or directory` —— 必须显式传 `startCmd`。

### PocketBay（`*.pocketbay.app`）
- **baostock 可用**（`/api/health` → `baostock:true`）→ PE/PB、分红、公告在 PocketBay 上是通的。
- **新浪实时 `hq.sinajs.cn` 被拒**（403 / 超时）→ 必须靠 `realtime_http.py` 的腾讯多源链兜住，否则 provider 会回落 Mock。
- 可达：腾讯 `qt.gtimg.cn`、腾讯 `web.ifzq.gtimg.cn`、`quotes.sina.cn` KLine、Yahoo。
- 不可达：网易（502）、东方财富（RemoteDisconnected）。
- **访问结构：外壳页 + embed 帧，且应用会被休眠**（这是"点了按钮没反应"的根因）。
  - 网关按 `Sec-Fetch-Dest` 分流**同一域名**：顶层导航 → PocketBay 外壳页（`X-Frame-Options: DENY`、`frame-ancestors 'none'`、`no-store`）；iframe 请求 → 应用原始 HTML。
  - 外壳装 `<iframe src="https://<slug>--e.pocketbay.app/<path>">`（`--e` = embed，**子路径保留**，深链接可用）。
  - **休眠**：闲置会被休眠，再访问时外壳显示「此应用当前正在休眠」+「唤醒并继续」→ `POST /.pocketbay/wake`（实测 1.5s）。
    若休眠发生在浏览过程中，页面内跳转请求会被挂住、界面无变化。
  - 后果：**`urllib` 探测与浏览器看到的不是同一个文档**；控制台的 `X-Frame-Options` 报错属平台侧，应用无需（也不应）下发 framing 头。
  - 应用侧只能"访问期间保活 + 让失败可见"（见 Web 层约定），平台休眠无法从应用侧消除。

## Web 层约定（托管平台交互）
- **动态响应一律 `Cache-Control: no-store`**（`web/main.py:DynamicNoStore`，纯 ASGI 中间件；用 `BaseHTTPMiddleware` 会缓冲响应体、与 `StaticFiles` 的 `FileResponse` 组合易出问题）。实时看板 HTML 被缓存会显示过时价格。`/static/*` 保持可缓存。
- **`GET /api/ping` 是保活端点**，只证明进程还在、**不做任何外部探测**；`/api/health` 会真的探数据源（秒级），不可互相替代。前端在页面可见且有操作时每 2 分钟打一次，30 分钟无操作停止。
- **站内跳转要有可见反馈**（`base.html` navFeedback / `style.css` `#navLoading`）：点击即显示「正在打开…」，超 6s 改「应用正在唤醒，请稍候…」。遮罩必须 `pointer-events:none` 且定时自动移除。
- 导航状态灯口径：行情 = `realtime||sina`、历史 = `history||baostock`、财务 = `tushare`。**不要只看 `sina`**，否则多源链可用时状态灯仍是红的。
- `base.html` 用内联 data-URI SVG favicon（原本没有 favicon，浏览器自动请求 `/favicon.ico` 会 404）。
- **待用户决定**：A 股涨跌配色目前是"涨绿跌红"（国际惯例），中国习惯应为**涨红跌绿**。
  注意 `.red`/`.green` 同时承载"错误/成功"语义（如 `'<span class="red">请选择起止日期</span>'`），
  **不能直接交换 CSS 变量值**，只能逐个翻转"涨跌三元表达式"并收口到单一 helper。

## 验证线上页面时的坑
- **`WebFetch` 有 15 分钟自缓存**：验证部署后刷新必须加 `?_ts=N` 破缓存，否则会把"旧快照"误判成"改动没生效"（本项目误判过一次首页『行情加载中』）。
- **`curl`/`urllib` 返回 200 不能说明"点了有反应"**，交互问题必须用真实浏览器验。
  本机可直接用：`NODE_PATH=%USERPROFILE%\.workbuddy\binaries\node\workspace\node_modules`
  + `%LOCALAPPDATA%\ms-playwright\chromium-*\chrome-win64\chrome.exe`（Playwright 已装）。
  要点：① 先 `page.frames()` 找到 `--e` 帧再读 DOM / 用坐标点；② 点击后给足 **20s** 容差，否则会把"慢"误判成"坏"；③ 遇休眠先点「唤醒并继续」。
