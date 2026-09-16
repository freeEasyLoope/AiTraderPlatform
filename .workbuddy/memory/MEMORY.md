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
