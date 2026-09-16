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

平台把仓库根目录整包识别成一个应用，产出 `https://<slug>.pocketbay.app`。
**前端不用改**：所有接口都是相对路径，同域名同源。

## 1. 已做的适配（代码侧）

| 适配点 | 实现 |
|---|---|
| 监听端口 | `web.py` 读 `PORT` 并绑定 `0.0.0.0` |
| 可写目录 | `src/runtime.py` 统一解析：平台注入 `POCKETBAY_DATA_DIR=/data` 时全部读写落到持久卷，本地回落仓库根 |
| 配置播种 | `config/traders.yaml`、`watchlist.yaml` 首次运行自动复制到可写目录（页面会改它们） |
| 数据库 | SQLite 落 `$POCKETBAY_DATA_DIR/data/simulation.db`；若平台注入 `DATABASE_URL` 则自动改用托管库 |
| 首启自举 | `web/main.py` 的 `lifespan` 建表 + 创建 6 个操盘手账户，避免首屏空看板 |
| 定时交易 | 平台没有 cron，托管环境下由 web 进程内的 APScheduler 调度（时区 `Asia/Shanghai`） |
| 事件循环 | 首屏与探活路径的处理器改成同步 `def`，阻塞行情拉取走线程池，不冻结单进程服务 |

## 2. 部署方式

对 AI 助手说一句即可，平台会读仓库自动识别为 python 应用：

```
请把当前项目部署到 PocketBay，部署手册：https://pocketbay.com/deploy
```

## 3. 运行时环境变量

| 变量 | 谁注入 | 说明 |
|---|---|---|
| `PORT` | 平台 | 必须监听它 |
| `POCKETBAY_DATA_DIR` | 平台 | 持久卷路径，跨版本保留；也是"是否启用进程内调度"的判据 |
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
- **数据源地域**：`hq.sinajs.cn`、baostock、akshare 都是中国大陆端点。若运行节点在境外，`/recommendations`、`/signals`、首页市场环境判断会变慢或超时；`/api/health` 已有 5 分钟缓存兜底。
- **本地 SQLite 不会自动带上云**：线上从零开始跑模拟。要延续本地记录，需在配对页选择把数据迁到托管 PostgreSQL。
- `config/*.yaml` 是"页面可改的运行时配置"，不要把它们当作敏感配置在配对页申报——那会变成只读挂载，策略调参/自选池增删会写不进去。
