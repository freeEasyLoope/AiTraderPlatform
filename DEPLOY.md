# AITrader 云服务器部署指南

> 不想自己买服务器？见文末「方式二：PocketBay 托管部署」——代码已适配，无需改业务逻辑。

## 服务器要求

- CentOS 7+ / Ubuntu 20.04+
- Python 3.10+
- 1 核 1G 内存起步（2G 推荐，跑 LLM 周报用）
- 2Mbps 带宽以上

## 1. 服务器初始化

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y   # Ubuntu
# sudo yum update -y                     # CentOS

# 安装 Python 和工具
sudo apt install -y python3 python3-pip python3-venv git nginx

# 安装 TA-Lib（技术指标库可能需要）
# sudo apt install -y build-essential wget
# wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
# tar -xzf ta-lib-0.4.0-src.tar.gz && cd ta-lib/
# ./configure --prefix=/usr && make && sudo make install
```

## 2. 部署代码

```bash
# 上传项目到服务器（任选一种方式）
# 方式 A: git clone（如果有仓库）
git clone <你的仓库地址> /opt/aitrader

# 方式 B: scp 上传
# 在本地执行: scp -r x:\myWorkspace\InvestProject user@server:/opt/aitrader

# 方式 C: 服务器直接下载 zip（如果有网盘链接）

# 进入目录
cd /opt/aitrader
```

## 3. 安装依赖

```bash
# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装
pip install -r requirements.txt
pip install gunicorn    # 生产级 WSGI 服务器
```

## 4. 配置环境变量

```bash
cp .env.example .env
nano .env   # 填入你的 API 密钥
```

## 5. 启动服务

### 方式 A：直接启动（测试用）

```bash
gunicorn src.web.main:app \
    -k uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --daemon
```

### 方式 B：systemd 持久化运行（推荐）

```bash
sudo cp deploy/aitrader.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable aitrader
sudo systemctl start aitrader
sudo systemctl status aitrader
```

## 6. 配置 Nginx 反向代理

```bash
sudo cp deploy/nginx-aitrader.conf /etc/nginx/sites-available/aitrader
sudo ln -s /etc/nginx/sites-available/aitrader /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## 7. 配置防火墙

```bash
# 只开放 80/443，不暴露应用端口
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## 8. 访问

```bash
http://<你的服务器IP>
```

## 可选：配置 HTTPS

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

## 可选：设置访问密码

编辑 `.env`，添加：
```
AITRADER_USERNAME=admin
AITRADER_PASSWORD=your_password
```

重启服务后生效。

## 定时任务

服务器上每天 21:00 自动跑交易：

```bash
crontab -e
```

添加：
```
0 21 * * 1-5 cd /opt/aitrader && /opt/aitrader/.venv/bin/python cli.py run >> logs/trading.log 2>&1
```

---

# 方式二：PocketBay 托管部署

平台把仓库根目录整包识别成一个应用，产出 `https://<slug>.app.workbuddy.host`。
**前端不用改**：所有接口都是相对路径，同域名同源。

当前线上地址：<https://aitrader-dashboard.app.workbuddy.host/>

## 1. 已做的适配（代码侧）

| 适配点 | 实现 |
|---|---|
| 监听端口 | `web.py` 读 `PORT` 并绑定 `0.0.0.0` |
| 可写目录 | `src/runtime.py` 统一解析：平台注入 `POCKETBAY_DATA_DIR=/data` 时全部读写落到持久卷，未注入则回落应用目录（容器层，**不跨版本保留**） |
| 配置播种 | `config/traders.yaml`、`watchlist.yaml` 首次运行自动复制到可写目录（页面会改它们） |
| 数据库 | SQLite 落 `<可写目录>/data/simulation.db`；若平台注入 `DATABASE_URL` 且驱动已装则优先；驱动缺失自动回退 SQLite（不会因连接串致整站起不来） |
| 首启自举 | `web/main.py` 的 `lifespan` 建表 + 创建 6 个操盘手账户，避免首屏空看板 |
| 定时交易 | 平台没有 cron，检测到部署信号时由 web 进程内 APScheduler 调度（时区 `Asia/Shanghai`） |
| 首屏不阻塞 | 市场环境改为「先返回缓存/占位 + 后台刷新」（10 分钟 TTL、单飞、失败指数退避、180s 卡死看门狗）。**这是部署能否成功的关键**——详见第 6 节 |
| 启动不阻塞 | 数据源探测（`engine/factory.py`）设 15s 上界并回落 mock；调度器装配 `try/except` 兜底，装配失败也保证 web 能起 |
| 事件循环 | 首屏与探活路径的处理器改同步 `def`，阻塞行情拉取走线程池，不冻结单进程服务 |
| 数据源设界 | 对不接受超时参数的第三方数据源（baostock）用 `runtime.run_with_timeout` 兜底 |

## 2. 部署方式

对 AI 助手说一句即可，平台会读仓库自动识别为 python 应用：

```
请把当前项目部署到 PocketBay，部署手册：https://pocketbay.com/deploy
```

## 3. 运行时环境变量

| 变量 | 谁注入 | 说明 |
|---|---|---|
| `PORT` | 平台 | 必须监听它；同时作为「是否启用进程内调度」的部署判据（沙箱实测**未**注入 `POCKETBAY_DATA_DIR`） |
| `POCKETBAY_DATA_DIR` | 平台 | 持久卷路径，跨版本保留；注入时同样启用进程内调度 |
| `TZ` | 本代码 | 默认置 `Asia/Shanghai`，否则容器 UTC 会让交易日错一天 |
| `DATABASE_URL` | 平台 | 选了托管 PostgreSQL 时优先使用（需自行加 `psycopg2-binary`） |
| `AITRADER_DISABLE_SCHEDULER` | 手动 | 置 `1` 强制关闭进程内调度 |

## 4. 密钥安全（重要）

**不要把密钥打进源码包，也不要让平台迁移本地 `.env`。**

- 平台文档明确提到"打包进源码的密钥会影响别人基于你的项目创建专属副本"——源码里的 key 会随公开项目扩散。
- 本项目的 LLM 相关接口在**无密钥时自动降级**：周报返回"请设置 ANTHROPIC_API_KEY"，个股 AI 分析返回"AI 分析暂不可用"，不会 500。
- 因此推荐的部署形态是：**看板 + 模拟交易全功能可用，LLM 功能关闭**。确实需要 AI 周报时，再用一个**独立的小额度 key**，通过平台提供的配置迁移入口（审批后加密入库、只读挂载）注入，绝不复用主力 key。

## 5. 上线后注意事项

- **保持单进程**：启动命令不要加 `--workers`，否则每个 worker 各起一个调度器，会重复下单。
- **本地 SQLite 会被打进包**：平台压缩的是仓库整包（只排除 `.git`/`node_modules`/构建产物），`data/simulation.db` 会一起上传，所以线上首屏带着本地的持仓与净值历史（实测如此）。反过来，**线上产生的交易不在持久卷上，重新部署可能被包内旧库覆盖**；要真正保留线上状态，需申请挂持久卷或改用托管数据库。
- `config/*.yaml` 是"页面可改的运行时配置"，不要把它们当作敏感配置在配对页申报——那会变成只读挂载，策略调参/自选池增删会写不进去。

## 6. 实测记录与已知限制（2026-09-16）

这一步踩了**两次**坑，都是同一个病根：**启动/探活路径上存在不受控的网络等待**。记下来，因为报错信息完全误导——它说"服务不可达"，其实是"服务卡住了"。

### 失败一：首屏阻塞

报错 `service did not become reachable on port 8000 within 60s`。日志显示应用其实**已经启动成功**（`Uvicorn running on http://0.0.0.0:8000`、端口 LISTEN 正常），是**探活请求拿不到响应**。

> 根因：`GET /` 同步调用 `_calc_market_env()` → `baostock`，而 `bs.login()` **没有超时参数**，在访问不到大陆行情端点的沙箱里无限阻塞（本机复现单次 80s+）。

修复：市场环境改为「先返回缓存/占位 + 后台刷新」。本机实测 **80s+ → 0.07s**。

### 失败二：启动就卡住（更隐蔽）

修完首屏后第二次部署**仍然失败**，但这次日志停在 `Waiting for application startup.` 且 `port 8000 NOT listening`——应用根本没起来。

> 根因：`engine/factory.py` 的 `build_data_provider()` 在 **lifespan 里同步探测实时行情**（拉贵州茅台现价）来决定用真实源还是 mock。而 sina 的探测路径会顺带调 `baostock` 补技术指标 → 同样无超时 → lifespan 永不完成。

修复：探测加 15s 上界（`run_with_timeout`），超时即回落 mock；并给整个调度器装配加 `try/except`，**定时任务装配失败绝不允许阻断 web 启动**。本机实测：数据源永久挂死时启动 **8.11s → 有界完成**，首屏 0.06s 正常响应。

### 三条可复用的结论

1. **启动路径和探活路径都不能有不受控的网络等待**。平台的判定是"不可达"，但真实原因是"卡住"，报错信息会把你引向错误方向——先看日志里有没有 `Application startup complete`。
2. **`run_with_timeout` 应是调用第三方数据源的默认姿势**。baostock / akshare 这类库都不接受超时参数，裸调等于把进程可用性交给对端网络。预算不要给太紧：宁可多等几秒，也别在"网络慢但数据可用"时误回落 mock 写入虚构价格。
3. **不要在可能阻塞的调用外面替换全局 `sys.stdout`**。原 `bs.login()` 外包了 `sys.stdout = io.StringIO()`，登录一挂死这个全局重定向就永久生效，进程日志整段静音——线上反而看不到真正原因。相关替换已从 `src/data/sina_client.py` 移除。

### 沙箱网络限制（重要）

线上实例实测 `GET /api/health` 返回：

```json
{"sina": false, "baostock": false, "tushare": false}
```

三个数据源**全部不可达**。影响面：

| 功能 | 线上表现 |
|---|---|
| 页面渲染、6 位操盘手、净值/排名/收益曲线 | ✅ 正常（数据来自包内 SQLite） |
| 配置读写（策略调参、自选池增删） | ✅ 正常 |
| 市场环境横条 | ⚠️ 显示「行情离线」（已如实降级，不再永远卡在「加载中」） |
| 每日自动交易、`/recommendations`、`/signals`、条件选股 | ❌ 拿不到行情，无法产生新信号 |

如果需要一个**行情可用**的实例，把同一份代码部署到能访问大陆行情的机器上即可（见方式一）；本仓库的 `src/runtime.py` 让两处环境跑同一套代码，无需改动。
