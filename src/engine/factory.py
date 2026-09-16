"""数据源与模拟器装配 —— web 进程内调度器复用 CLI 的同一套选择逻辑。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_data_provider():
    """数据源优先级：新浪(实时) > Mock。容器访问不到大陆行情端点时自动回落。"""
    import os

    if os.environ.get("USE_MOCK") == "1":
        from ..data.mock_client import MockDataProvider
        return MockDataProvider()

    if os.environ.get("USE_AKSHARE") == "1":
        from ..data.akshare_client import AkshareClient
        return AkshareClient()

    try:
        from ..data.sina_client import SinaClient
        provider = SinaClient()
        snap = provider.get_snapshot("600519")
        if snap and snap.close > 0:
            logger.info("数据源: sina (实时) 贵州茅台 %.2f", snap.close)
            return provider
        raise RuntimeError("sina 返回空数据")
    except Exception as e:
        logger.warning("实时行情不可用(%s)，回落模拟数据", e)
        from ..data.mock_client import MockDataProvider
        return MockDataProvider()


def register_default_traders() -> None:
    """把六个策略操盘手注册进全局 registry（幂等）。"""
    from ..traders.registry import registry
    from ..traders.value_hunter import ValueHunter
    from ..traders.trend_follower import TrendFollower
    from ..traders.mean_reversion import MeanReversion
    from ..traders.dividend_collector import DividendCollector
    from ..traders.index_dca import IndexDca
    from ..traders.macro_hedger import MacroHedger

    pairs = [
        ("value_hunter.ValueHunter", ValueHunter),
        ("trend_follower.TrendFollower", TrendFollower),
        ("mean_reversion.MeanReversion", MeanReversion),
        ("dividend_collector.DividendCollector", DividendCollector),
        ("index_dca.IndexDca", IndexDca),
        ("macro_hedger.MacroHedger", MacroHedger),
    ]
    for path, cls in pairs:
        if path not in registry._traders:
            registry.register(path, cls)


def build_simulator(repo):
    """构建模拟器实例。"""
    from .simulator import Simulator

    register_default_traders()
    from ..traders.registry import registry
    return Simulator(repo, build_data_provider(), registry)
