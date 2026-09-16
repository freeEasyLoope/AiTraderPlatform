"""数据源与模拟器装配 —— web 进程内调度器复用 CLI 的同一套选择逻辑。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 探测实时行情的等待上限。必须设界：sina 的探测路径会顺带调用 baostock
# 补技术指标，而 baostock 没有超时参数，不受控时会让 lifespan 卡死、端口永不监听，
# 平台会直接判定部署失败。
#
# 预算给到 15s 是有意的：探测偏紧会在「网络慢但数据源可用」时误回落 mock，
# 那会让模拟交易写入虚构价格——比多等几秒严重得多。15s + 启动开销仍远低于
# 平台 60s 的探活上限。
_PROBE_TIMEOUT = 15.0


def build_data_provider():
    """数据源优先级：新浪(实时) > Mock。容器访问不到大陆行情端点时自动回落。"""
    import os

    if os.environ.get("USE_MOCK") == "1":
        from ..data.mock_client import MockDataProvider
        return MockDataProvider()

    if os.environ.get("USE_AKSHARE") == "1":
        from ..data.akshare_client import AkshareClient
        return AkshareClient()

    from ..runtime import run_with_timeout

    def _probe():
        from ..data.sina_client import SinaClient
        provider = SinaClient()
        snap = provider.get_snapshot("600519")
        if snap and snap.close > 0:
            return provider
        raise RuntimeError("sina 返回空数据")

    try:
        provider = run_with_timeout(_probe, _PROBE_TIMEOUT, None)
    except Exception as e:
        logger.warning("实时行情探测失败(%s)，回落模拟数据", e)
        provider = None

    if provider is not None:
        logger.info("数据源: sina (实时)")
        return provider

    logger.warning("实时行情探测超时或不可用，回落模拟数据源（Mock）")
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
