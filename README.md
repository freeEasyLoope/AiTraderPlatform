# AITrader — A股模拟交易系统

六个自动化策略操盘手在真实行情下模拟交易，帮助个人投资者理解不同量化策略的行为和表现。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，填入你的 API 密钥：

```bash
copy .env.example .env
```

| 变量 | 必须 | 说明 |
|---|---|---|
| `ANTHROPIC_API_KEY` | 否 | LLM 周报生成（支持 DeepSeek 代理） |
| `ANTHROPIC_BASE_URL` | 否 | LLM API 地址，默认 Anthropic |
| `TUSHARE_TOKEN` | 否 | tushare 数据（PE/PB 基本面） |

不配置任何密钥也可运行——系统会使用免费的 Sina + baostock 数据源。

### 3. 启动

```bash
# Web Dashboard（推荐）
python web.py
# 浏览器打开 http://127.0.0.1:8000

# CLI 模式
python cli.py run          # 执行今日交易
python cli.py status       # 查看状态
python cli.py leaderboard  # 收益排行榜
python cli.py screening -v # 选股漏斗
```

### 4. 定时自动运行

```
# 双击运行（Windows）
run_daily.bat
# 或配置 Windows 任务计划程序每天 21:00 执行
```

## 六个操盘手

| 操盘手 | 类型 | 策略 | 选股逻辑 |
|---|---|---|---|
| 趋势跟随者 | 短线 | MA5/MA20 金叉 + 放量 | 动量突破 |
| 均值回归者 | 短线 | RSI(14)<30 + 布林下轨 | 超卖反弹 |
| 宏观对冲者 | 短线 | 股/债/黄金轮动 | 利率环境切换 |
| 价值猎手 | 长线 | PE<行业中位×0.7 + PB<2.0 | 低估值 |
| 红利收集者 | 长线 | 股息率>3% + PB<1.5 | 高股息 |
| 指数定投者 | 长线 | 每周定投沪深300ETF | 被动投资 |

## 选股漏斗

5 步筛选——从全市场 5000+ 只 A 股逐步缩到 30 只安全可做清单：

```
①量价+PE → ②财务排雷 → ③资金验证 → ④赛道择优 → ⑤风险过滤
```

```bash
python cli.py screening --steps 1,3,5 -v -f   # CLI
# 或访问 http://127.0.0.1:8000/screening       # Web
```

## 数据源

| 数据 | 来源 | 费用 |
|---|---|---|
| 实时行情 | Sina Finance (hq.sinajs.cn) | 免费 |
| 历史K线 | baostock | 免费 |
| 财报/资金流向 | akshare (Eastmoney) | 免费 |
| 基本面 (PE/PB) | tushare | 免费（需注册 token） |
| 周报分析 | Claude / DeepSeek | 按用量 |

## 项目结构

```
InvestProject/
├── web.py                  # Web Dashboard 入口
├── cli.py                  # CLI 入口
├── run_daily.bat           # 每日自动交易脚本
├── config/
│   ├── settings.yaml       # 全局配置
│   ├── traders.yaml        # 操盘手参数
│   ├── screening.yaml      # 漏斗参数
│   └── watchlist.yaml      # 自选股列表
├── src/
│   ├── data/               # 数据源（Sina/akshare/baostock）
│   ├── traders/            # 六个策略操盘手
│   ├── engine/             # 模拟器 + 撮合引擎
│   ├── screening/          # 5步选股漏斗
│   ├── analysis/           # 绩效分析 + LLM 周报
│   ├── storage/            # SQLite 持久化
│   └── web/                # FastAPI + Jinja2 模板
└── tests/                  # 单元测试（27 个）
```

## 免责声明

本项目仅用于学习和技术研究。所有交易均为模拟，不构成投资建议。任何因参考本项目进行实盘投资造成的损失，开发者不承担责任。
