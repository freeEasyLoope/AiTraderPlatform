"""操盘手注册表 — 工厂模式。"""
from __future__ import annotations


import logging
from typing import Optional

from .base import BaseTrader

logger = logging.getLogger(__name__)


class TraderRegistry:
    """操盘手注册表。

    usage:
        registry = TraderRegistry()
        registry.register("value_hunter.ValueHunter", ValueHunter)
        trader = registry.create("value_hunter.ValueHunter", name="价值猎手", capital=1666.67)
    """

    def __init__(self):
        self._traders: dict[str, type[BaseTrader]] = {}

    def register(self, strategy_path: str, trader_cls: type[BaseTrader]) -> None:
        """注册操盘手类。

        Args:
            strategy_path: 策略标识，如 "value_hunter.ValueHunter"
            trader_cls: 操盘手类
        """
        self._traders[strategy_path] = trader_cls
        logger.debug(f"注册操盘手: {strategy_path}")

    def create(
        self,
        strategy_path: str,
        name: str,
        capital: float,
        params: Optional[dict] = None,
    ) -> Optional[BaseTrader]:
        """创建操盘手实例。

        Args:
            strategy_path: 策略标识
            name: 操盘手名称
            capital: 初始资金
            params: 策略参数

        Returns:
            操盘手实例，未注册则返回 None
        """
        cls = self._traders.get(strategy_path)
        if cls is None:
            logger.warning(f"未注册的策略: {strategy_path}")
            return None
        return cls(name=name, capital=capital, params=params)

    def list_strategies(self) -> list[str]:
        """列出所有已注册策略。"""
        return list(self._traders.keys())


# 全局注册表实例
registry = TraderRegistry()
