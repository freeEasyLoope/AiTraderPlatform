"""akshare 数据客户端 — A股/基金/债券/黄金市场数据。"""
from __future__ import annotations


import logging
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

from .provider import MarketDataProvider, MarketSnapshot

logger = logging.getLogger(__name__)


class AkshareClient(MarketDataProvider):
    """基于 akshare 的市场数据提供者。"""

    # 标的池定义
    UNIVERSE_FUNDS = {
        "hs300": "000300",      # 沪深300指数成分
        "zz500": "000905",      # 中证500指数成分
        "dividend_index": "000922",  # 中证红利指数
    }

    # 宏观标的有
    MACRO_SYMBOLS = {
        "stock": ["510300", "510050"],    # 沪深300ETF, 上证50ETF
        "bond": ["511010", "511260"],     # 国债ETF, 10年国债ETF
        "gold": ["518880", "159934"],     # 黄金ETF
    }

    def get_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        """获取单只股票快照。"""
        import akshare as ak

        try:
            # 尝试获取个股实时数据
            df = ak.stock_zh_a_spot_em()
            row = df[df["代码"] == symbol]
            if row.empty:
                logger.warning(f"未找到股票: {symbol}")
                return None
            return self._row_to_snapshot(row.iloc[0])
        except Exception as e:
            logger.error(f"获取 {symbol} 快照失败: {e}")
            return None

    def get_snapshots(self, symbols: list[str], date: str = None) -> dict[str, MarketSnapshot]:
        """批量获取快照。"""
        import akshare as ak

        result: dict[str, MarketSnapshot] = {}
        if not symbols:
            return result

        try:
            df = ak.stock_zh_a_spot_em()
            for symbol in symbols:
                row = df[df["代码"] == symbol]
                if not row.empty:
                    result[symbol] = self._row_to_snapshot(row.iloc[0])
                else:
                    logger.warning(f"未找到股票: {symbol}")
        except Exception as e:
            logger.error(f"批量获取快照失败: {e}")
        return result

    def get_stock_universe(self, universe: str) -> list[str]:
        """获取标的池股票列表。"""
        import akshare as ak

        if universe == "all":
            try:
                df = ak.stock_zh_a_spot_em()
                # 剔除 ST、*ST、退市
                df = df[~df["名称"].str.contains("ST|退", na=False)]
                return df["代码"].tolist()[:500]  # 限制500只避免过慢
            except Exception as e:
                logger.error(f"获取全市场股票失败: {e}")
                return []

        if universe in ("hs300", "zz500", "dividend_index"):
            index_code = self.UNIVERSE_FUNDS.get(universe, "000300")
            try:
                df = ak.index_stock_cons_weight_csindex(index_code)
                return df["成分券代码"].tolist()
            except Exception as e:
                logger.error(f"获取指数 {universe} 成分股失败: {e}")
                return []

        if universe == "etf":
            return self.MACRO_SYMBOLS["stock"]

        if universe == "macro":
            result = []
            for symbols in self.MACRO_SYMBOLS.values():
                result.extend(symbols)
            return result

        # 默认返回沪深300
        return self.get_stock_universe("hs300")

    def get_historical_data(
        self, symbols: list[str], start_date: str, end_date: str
    ) -> dict[str, list[MarketSnapshot]]:
        """获取历史数据（用于回测）。"""
        import akshare as ak

        result: dict[str, list[MarketSnapshot]] = {}
        for symbol in symbols:
            try:
                df = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                    adjust="qfq",  # 前复权
                )
                if df.empty:
                    continue
                snapshots = []
                for _, row in df.iterrows():
                    snapshots.append(self._hist_row_to_snapshot(symbol, row))
                result[symbol] = snapshots
            except Exception as e:
                logger.warning(f"获取 {symbol} 历史数据失败: {e}")
        return result

    def is_trading_day(self, date: str) -> bool:
        """判断是否为交易日。"""
        import akshare as ak

        try:
            df = ak.tool_trade_date_hist_sina()
            target = datetime.strptime(date, "%Y-%m-%d").date()
            return target in df["trade_date"].values
        except Exception:
            # 降级：周六日一定不是交易日
            dt = datetime.strptime(date, "%Y-%m-%d")
            return dt.weekday() < 5

    def get_trading_days(self, year: int, month: int) -> list[str]:
        """获取指定月份的所有交易日。"""
        import akshare as ak

        try:
            df = ak.tool_trade_date_hist_sina()
            target_month = f"{year}-{month:02d}"
            return [
                d.strftime("%Y-%m-%d") for d in df["trade_date"].values
                if d.strftime("%Y-%m-%d").startswith(target_month)
            ]
        except Exception:
            logger.warning("获取交易日历失败，使用简单推算")
            # 简单推算：周一至周五
            result = []
            dt = datetime(year, month, 1)
            while dt.month == month:
                if dt.weekday() < 5:
                    result.append(dt.strftime("%Y-%m-%d"))
                dt += timedelta(days=1)
            return result

    def get_index_data(self, index_symbol: str = "000300") -> Optional[float]:
        """获取指数当前点位。"""
        import akshare as ak

        try:
            df = ak.stock_zh_index_spot_em()
            row = df[df["代码"] == index_symbol]
            if not row.empty:
                return float(row.iloc[0]["最新价"])
        except Exception as e:
            logger.warning(f"获取指数 {index_symbol} 失败: {e}")
        return None

    def get_shibor(self) -> Optional[float]:
        """获取 SHIBOR 隔夜利率。"""
        import akshare as ak

        try:
            df = ak.rate_interbank(market="中国银行间同业拆借", indicator="隔夜", need_recent_days=1)
            if not df.empty:
                return float(df.iloc[0]["利率"])
        except Exception as e:
            logger.warning(f"获取 SHIBOR 失败: {e}")
        return None

    def get_dividend_yield_data(self, symbols: list[str]) -> dict[str, float]:
        """获取股票股息率。"""
        import akshare as ak

        result: dict[str, float] = {}
        try:
            df = ak.stock_zh_a_spot_em()
            for symbol in symbols:
                row = df[df["代码"] == symbol]
                if not row.empty:
                    # akshare 返回的股息率可能在不同列
                    for col in ["股息率", "dividend_yield"]:
                        if col in df.columns:
                            val = row.iloc[0].get(col)
                            if val and not np.isnan(float(val)):
                                result[symbol] = float(val)
                                break
        except Exception as e:
            logger.error(f"获取股息率失败: {e}")
        return result

    def _row_to_snapshot(self, row) -> MarketSnapshot:
        """将 akshare 行数据转为 MarketSnapshot。"""
        def _f(val, default=0.0):
            try:
                return float(val) if val and not np.isnan(float(val)) else default
            except (ValueError, TypeError):
                return default

        return MarketSnapshot(
            symbol=str(row.get("代码", "")),
            name=str(row.get("名称", "")),
            close=_f(row.get("最新价")),
            open=_f(row.get("今开")),
            high=_f(row.get("最高")),
            low=_f(row.get("最低")),
            volume=_f(row.get("成交量")),
            change_pct=_f(row.get("涨跌幅", 0)) / 100.0 if _f(row.get("涨跌幅", 0)) > 1 else _f(row.get("涨跌幅", 0)),
            pe=_f(row.get("市盈率-动态"), None) or None,
            pb=_f(row.get("市净率"), None) or None,
            turnover_rate=_f(row.get("换手率"), None) or None,
            total_market_cap=_f(row.get("总市值"), None) or None,
        )

    def _hist_row_to_snapshot(self, symbol: str, row) -> MarketSnapshot:
        """将 akshare 历史行数据转为 MarketSnapshot。"""
        def _f(val, default=0.0):
            try:
                return float(val) if val and not np.isnan(float(val)) else default
            except (ValueError, TypeError):
                return default

        return MarketSnapshot(
            symbol=symbol,
            name="",
            close=_f(row.get("收盘")),
            open=_f(row.get("开盘")),
            high=_f(row.get("最高")),
            low=_f(row.get("最低")),
            volume=_f(row.get("成交量")),
            change_pct=_f(row.get("涨跌幅", 0)) / 100.0 if abs(_f(row.get("涨跌幅", 0))) > 1 else _f(row.get("涨跌幅", 0)),
        )
