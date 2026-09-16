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

## 部署目标
- 主推 **PocketBay 托管**（见 `DEPLOY.md` 方式二）：单进程、无 cron、动态应用挂 `/data`。
- **密钥不进包**：LLM 接口在无 `ANTHROPIC_API_KEY` 时必须优雅降级，不允许 500。禁止把 key 写进源码/yaml。
- 启动命令保持**单进程**，不要加 `--workers`（每个 worker 会各起一个 APScheduler，重复下单）。

## 事件循环约定
- 项目全部是阻塞式 IO（urllib / baostock / akshare），**路由处理器凡是内部做网络或重计算的，一律用同步 `def`**（FastAPI 自动丢线程池），不要写 `async def` 却在里面做阻塞调用——会冻结单进程服务，导致平台探活失败。

## 启动路径铁律（踩过两次坑）
- **启动路径（lifespan）与探活路径上，绝不允许出现不受控的网络等待。** 平台只会报"服务不可达"，真实原因往往是"卡住"，报错信息会把人引向错误方向——先看日志里有没有 `Application startup complete`。
- **数据源探测必须设界**：`baostock` / `akshare` 都不接受超时参数，裸调等于把进程可用性交给对端网络。统一用 `src/runtime.py:run_with_timeout(fn, timeout, default)`（守护线程 + join 超时）。
  - 首屏市场环境：后台刷新 + 120s 计算上界 + 指数退避，首屏只读缓存，绝不等待。
  - 数据源探测：15s 上界，超时回落 `MockDataProvider`。**预算不要给太紧**——误回落 mock 会写入虚构价格，比多等几秒严重。
- **lifespan 里的非必需装配（调度器等）一律包 `try/except`**：任何可选功能出问题都不允许阻断 web 启动。
- **不要在可能阻塞的调用外面替换全局 `sys.stdout`**：一旦挂死，重定向永久生效，进程日志整段静音，线上无法排障。

## 部署环境实测事实（PocketBay）
- 平台会注入 `PORT`，但**本轮未注入 `POCKETBAY_DATA_DIR` / `DATABASE_URL`** → 可写目录回落容器内应用目录，**不跨版本保留**；`PORT` 已用作"是否在平台运行"的判据（`web/main.py` 启用进程内调度）。
- **仓库整包会上传**（只排除 `.git`/`node_modules`/构建产物）：本地 `data/simulation.db` 会随包上云，线上首屏带着本地历史；反之线上交易不在持久卷上，重部署可能被包内旧库覆盖。
- **沙箱访问不到大陆行情端点**（实测 `/api/health` 三个源全 false）→ 线上形态是"看板 + 历史数据"可用，实时行情/自动交易/选股不可用。要行情可用需部署到能访问大陆行情的机器。
- 线上地址：<https://aitrader-dashboard.app.workbuddy.host/>
