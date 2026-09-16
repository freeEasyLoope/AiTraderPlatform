"""技术指标计算单元测试。"""

from __future__ import annotations

import math

from src.data.indicators import calc_sma, calc_rsi, calc_bollinger_bands


class TestSMA:
    def test_simple_case(self):
        result = calc_sma([1, 2, 3, 4, 5], 3)
        # [0, 0, 2.0, 3.0, 4.0]
        assert result[0] == 0.0
        assert result[1] == 0.0
        assert result[2] == 2.0  # (1+2+3)/3
        assert result[3] == 3.0  # (2+3+4)/3
        assert result[4] == 4.0  # (3+4+5)/3

    def test_insufficient_data(self):
        result = calc_sma([1, 2], 5)
        assert all(v == 0.0 for v in result)


class TestRSI:
    def test_all_up(self):
        """连续上涨，RSI 应接近 100。"""
        prices = list(range(1, 30))  # 29 天连续涨
        rsi = calc_rsi(prices, 14)
        assert rsi[-1] > 70  # 超买

    def test_all_down(self):
        """连续下跌，RSI 应接近 0。"""
        prices = list(range(30, 1, -1))  # 29 天连续跌
        rsi = calc_rsi(prices, 14)
        assert rsi[-1] < 30  # 超卖


class TestBollinger:
    def test_bands_width(self):
        """布林带上下轨应在价格两侧。"""
        prices = [10 + math.sin(i * 0.5) for i in range(30)]
        upper, mid, lower = calc_bollinger_bands(prices, 20)

        # 最后一条数据：上轨 > 中轨 > 下轨
        assert upper[-1] > mid[-1] > lower[-1]
