"""新浪财经数据客户端 — 免费实时 A 股行情。

纯 HTTP 请求，零依赖（除了标准库），不经过东方财富。
数据来源: https://hq.sinajs.cn/

新浪 API 格式:
- 个股: http://hq.sinajs.cn/list=sh600519
- 批量: http://hq.sinajs.cn/list=sh600519,sz000858,sh510300
- 返回格式: var hq_str_sh600519="名称,今开,昨收,最新价,最高,最低,..."
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional
from urllib import request

from .provider import MarketDataProvider, MarketSnapshot

logger = logging.getLogger(__name__)

# 模块级历史数据缓存（跨实例共享）
_HIST_CACHE: dict[str, dict] = {}

# 抑制 baostock 的 login/logout 日志噪音
logging.getLogger("baostock").setLevel(logging.WARNING)

# 新浪 API 前缀
SINA_PREFIX = {
    "6": "sh",     # 上海主板
    "5": "sh",     # 上海 ETF/基金
    "9": "sh",     # 上海 B 股
    "0": "sz",     # 深圳主板
    "2": "sz",     # 深圳中小板
    "3": "sz",     # 深圳创业板
    "1": "sz",     # 深圳基金
    "68": "sh",    # 科创板（上海）
}


def _sina_symbol(symbol: str) -> str:
    """将 akshare 格式代码转为新浪格式。"""
    if symbol.startswith("sh") or symbol.startswith("sz"):
        return symbol
    prefix = SINA_PREFIX.get(symbol[0], "sz")
    # 科创板 688 前缀特殊处理
    if symbol.startswith("688"):
        prefix = "sh"
    return f"{prefix}{symbol}"


class SinaClient(MarketDataProvider):
    """基于新浪财经 API 的市场数据提供者。

    优点:
    - 完全免费，无需注册
    - 实时数据延迟 ~3-5 秒
    - 支持 A 股/ETF/指数
    - 纯 HTTP，无额外依赖

    限制:
    - 不提供 PE/PB/股息率等基本面数据
    - 不提供历史均线/RSI 等指标（需自行计算）
    - 批量查询最多 ~200 只股票
    """

    # 标的池（100只代表性A股，覆盖主要行业）
    HS300_SAMPLE = [
        # 白酒消费
        "600519", "000858", "000568", "600809", "002304",
        # 金融
        "601318", "600036", "601398", "600030", "601166",
        "000001", "600016", "601688", "600837", "000166",
        # 家电制造
        "000333", "000651", "002415", "300124", "002475",
        # 医药
        "600276", "300760", "000538", "600196", "300015",
        # 科技
        "000725", "002230", "600570", "300059", "688981",
        "002049", "603986", "300782", "002371", "688012",
        # 新能源
        "300750", "002594", "601012", "600438", "002459",
        # 地产建筑
        "000002", "600048", "601668", "600585", "600019",
        # 交通运输
        "601888", "600009", "601111", "600029", "601006",
        # 电力能源
        "600900", "601985", "600886", "600674", "600025",
        # 汽车
        "000625", "600104", "601633", "002920", "600741",
        # 农业食品
        "000895", "002714", "300498", "600887", "002311",
        # 有色化工
        "600309", "601899", "002460", "600989", "000792",
        # 通信
        "600050", "000063", "002281", "600498", "300308",
        # 银行补充
        "002142", "600000", "601009", "601818", "600015",
        # 保险证券
        "601628", "601336", "600958", "000776", "002736",
        # 其他
        "600690", "000100", "002027", "600233", "603259",
    ]

    ETF_SYMBOLS = ["510300", "510050"]
    BOND_SYMBOLS = ["511010", "511260"]
    GOLD_SYMBOLS = ["518880", "159934"]

    def __init__(self, batch_size: int = 50):
        self._batch_size = batch_size
        self._cache: dict[str, dict] = {}
        self._cache_time: Optional[datetime] = None
        self._fundamentals = None
        # 历史数据缓存: {date: {symbol: [MarketSnapshot]}}
        self._hist_cache: dict[str, dict] = {}

    def get_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        result = self.get_snapshots([symbol])
        return result.get(symbol)

    def get_snapshots(self, symbols: list[str], date: str = None) -> dict[str, MarketSnapshot]:
        result: dict[str, MarketSnapshot] = {}
        if not symbols:
            return result

        # 分批请求实时行情
        for i in range(0, len(symbols), self._batch_size):
            batch = symbols[i:i + self._batch_size]
            try:
                batch_result = self._fetch_batch(batch)
                result.update(batch_result)
            except Exception as e:
                logger.error(f"批次 {i // self._batch_size} 请求失败: {e}")

        # 补充技术指标
        if result:
            trade_date = date or datetime.now().strftime("%Y-%m-%d")
            self._enrich_indicators(result, trade_date)

        return result

    def _enrich_indicators(self, snapshots: dict[str, MarketSnapshot], trade_date: str) -> None:
        """为快照补充技术指标和基本面数据。"""
        from .indicators import compute_all_indicators

        symbols = list(snapshots.keys())
        # 批量获取历史数据（120 天窗口）
        dt = datetime.strptime(trade_date, "%Y-%m-%d")
        start = (dt - timedelta(days=120)).strftime("%Y-%m-%d")

        history = self.get_historical_data(symbols, start, trade_date)

        for symbol, snap in snapshots.items():
            hist_snaps = history.get(symbol, [])
            if len(hist_snaps) >= 20:
                closes = [h.close for h in hist_snaps]
                indicators = compute_all_indicators(closes)

                snap.ma_5 = indicators.get("ma_5")
                snap.ma_20 = indicators.get("ma_20")
                snap.ma_60 = indicators.get("ma_60")
                snap.rsi_14 = indicators.get("rsi_14")
                snap.boll_upper = indicators.get("boll_upper")
                snap.boll_mid = indicators.get("boll_mid")
                snap.boll_lower = indicators.get("boll_lower")

        # 补充 PE/PB/股息率（tushare → baostock 降级）
        from .fundamentals import enrich_fundamentals
        enrich_fundamentals(snapshots, symbols, trade_date)

        # 补充股息率（baostock 分红数据）
        from .dividends import enrich_dividend_yields
        enrich_dividend_yields(snapshots, symbols, trade_date)

        # 如果是历史日期，用历史收盘价覆盖实时价（保持数据一致）
        today = datetime.now().strftime("%Y-%m-%d")
        if trade_date != today:
            for symbol, snap in snapshots.items():
                hist_snaps = history.get(symbol, [])
                for h in hist_snaps:
                    h_date = trade_date  # 简化：用最近的
                    if h.close > 0:
                        snap.close = h.close
                        snap.open = h.open
                        snap.high = h.high
                        snap.low = h.low
                        snap.volume = h.volume
                        break

    def _fetch_batch(self, symbols: list[str]) -> dict[str, MarketSnapshot]:
        """请求一批股票数据。"""
        sina_symbols = [_sina_symbol(s) for s in symbols]
        url = "http://hq.sinajs.cn/list=" + ",".join(sina_symbols)

        req = request.Request(url, headers={
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0",
        })

        with request.urlopen(req, timeout=10) as resp:
            # 新浪返回 gbk 编码
            raw = resp.read().decode("gbk", errors="replace")

        return self._parse_response(raw, symbols)

    def _parse_response(
        self, raw: str, symbols: list[str]
    ) -> dict[str, MarketSnapshot]:
        """解析新浪返回数据。"""
        result: dict[str, MarketSnapshot] = {}

        # 按行分割
        lines = raw.strip().split("\n")
        for line in lines:
            if not line.strip() or "=" not in line:
                continue

            try:
                # 格式: var hq_str_sh600519="数据";
                match = re.match(r'var hq_str_(\w+)="(.+)"', line.strip())
                if not match:
                    continue

                sina_code = match.group(1)   # sh600519
                data_str = match.group(2)

                if not data_str or data_str == '""':
                    continue

                parts = data_str.split(",")
                if len(parts) < 32:
                    continue

                # 还原原始代码
                symbol = sina_code[2:]  # 去掉 sh/sz 前缀

                # 解析字段
                # [0]名称 [1]今开 [2]昨收 [3]当前价 [4]最高 [5]最低
                # [8]成交量(手) [9]成交额(万) [31]日期
                name = parts[0]
                open_price = self._f(parts[1])
                prev_close = self._f(parts[2])
                price = self._f(parts[3])
                high = self._f(parts[4])
                low = self._f(parts[5])
                volume = self._f(parts[8]) * 100  # 手 → 股
                amount = self._f(parts[9]) * 10000  # 万 → 元

                if price <= 0:
                    continue

                change_pct = (price - prev_close) / prev_close if prev_close > 0 else 0

                result[symbol] = MarketSnapshot(
                    symbol=symbol,
                    name=name,
                    close=price,
                    open=open_price,
                    high=high,
                    low=low,
                    volume=volume,
                    change_pct=change_pct,
                    # 新浪不提供以下字段
                    pe=None,
                    pb=None,
                    dividend_yield=None,
                    ma_5=None,
                    ma_20=None,
                    ma_60=None,
                    rsi_14=None,
                    boll_upper=None,
                    boll_mid=None,
                    boll_lower=None,
                    turnover_rate=None,
                    total_market_cap=None,
                )
            except (ValueError, IndexError) as e:
                logger.debug(f"解析行失败: {e}")
                continue

        return result

    def get_stock_universe(self, universe: str) -> list[str]:
        if universe == "etf":
            return self.ETF_SYMBOLS
        if universe == "macro":
            return self.ETF_SYMBOLS + self.BOND_SYMBOLS[:1] + self.GOLD_SYMBOLS[:1]
        return self.HS300_SAMPLE

    def get_historical_data(
        self, symbols: list[str], start_date: str, end_date: str
    ) -> dict[str, list[MarketSnapshot]]:
        """历史数据 — 模块级缓存，同日期区间只拉一次。"""
        cache_key = f"{start_date}_{end_date}"
        if cache_key in _HIST_CACHE:
            cached = _HIST_CACHE[cache_key]
            missing = [s for s in symbols if s not in cached]
            if missing:
                new_data = self._fetch_history_baostock_batch(missing, start_date, end_date)
                cached.update(new_data)
            return {s: cached[s] for s in symbols if s in cached}
        result = self._fetch_history_baostock_batch(symbols, start_date, end_date)
        _HIST_CACHE[cache_key] = result
        return result

    def _fetch_history_baostock_batch(
        self, symbols: list[str], start_date: str, end_date: str
    ) -> dict[str, list[MarketSnapshot]]:
        """批量获取 baostock 历史日线（一次登录）。"""
        import baostock as bs
        import io
        import sys

        result: dict[str, list[MarketSnapshot]] = {}

        # 抑制 baostock 的 stdout 噪音
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            lg = bs.login()
        finally:
            sys.stdout = old_stdout

        if lg.error_code != "0":
            logger.warning(f"baostock 登录失败: {lg.error_msg}")
            return result

        try:
            for symbol in symbols:
                try:
                    sina_sym = _sina_symbol(symbol)
                    bs_code = f"{sina_sym[:2]}.{sina_sym[2:]}"

                    rs = bs.query_history_k_data_plus(
                        bs_code,
                        "date,open,high,low,close,volume",
                        start_date=start_date,
                        end_date=end_date,
                        frequency="d",
                        adjustflag="2",
                    )

                    data_rows = rs.get_data() if hasattr(rs, 'get_data') else None
                    if data_rows is None or data_rows.empty:
                        continue

                    snapshots = []
                    for _, row in data_rows.iterrows():
                        try:
                            snapshots.append(MarketSnapshot(
                                symbol=symbol,
                                name="",
                                close=float(row["close"]),
                                open=float(row["open"]),
                                high=float(row["high"]),
                                low=float(row["low"]),
                                volume=float(row["volume"]),
                                change_pct=0,
                            ))
                        except (ValueError, KeyError):
                            continue

                    if snapshots:
                        result[symbol] = snapshots
                except Exception as e:
                    logger.debug(f"baostock {symbol}: {e}")
                    continue
        finally:
            bs.logout()

        return result

    def _fetch_history_netease(
        self, symbol: str, start_date: str, end_date: str
    ) -> list[MarketSnapshot]:
        """通过网易接口获取历史日线数据。"""
        sina_sym = _sina_symbol(symbol)
        code = "0" if sina_sym.startswith("sh") else "1"
        code += sina_sym[2:]

        start = start_date.replace("-", "")
        end = end_date.replace("-", "")

        url = (
            f"http://quotes.money.163.com/service/chddata.html"
            f"?code={code}&start={start}&end={end}"
            f"&fields=TCLOSE;TOPEN;THIGH;TLOW;TVOL;TCHG;PCHG"
        )

        req = request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
        })

        snapshots = []
        with request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("gbk", errors="replace")
            lines = raw.strip().split("\n")

            for line in lines[1:]:  # 跳过表头
                parts = line.split(",")
                if len(parts) < 8:
                    continue
                try:
                    date_str = parts[0].strip().strip("'")
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    close = float(parts[3])
                    open_p = float(parts[6])
                    high = float(parts[4])
                    low = float(parts[5])
                    volume = float(parts[11]) if len(parts) > 11 else 0

                    snapshots.append(MarketSnapshot(
                        symbol=symbol,
                        name="",
                        close=close,
                        open=open_p,
                        high=high,
                        low=low,
                        volume=volume,
                        change_pct=0,
                    ))
                except (ValueError, IndexError):
                    continue

        return snapshots

    def is_trading_day(self, date: str) -> bool:
        dt = datetime.strptime(date, "%Y-%m-%d")
        if dt.weekday() >= 5:
            return False
        # 简单判断：周一至周五即视为交易日
        # 精确判断需要交易日历，新浪/网易不提供此接口
        return True

    def get_trading_days(self, year: int, month: int) -> list[str]:
        result = []
        dt = datetime(year, month, 1)
        while dt.month == month:
            if dt.weekday() < 5:
                result.append(dt.strftime("%Y-%m-%d"))
            dt += timedelta(days=1)
        return result

    @staticmethod
    def _f(val: str) -> float:
        """安全转 float。"""
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0
