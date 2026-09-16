"""技术指标计算 — 从 OHLCV 数据计算 MA/RSI/布林带。

纯 Python，无外部依赖。所有函数接收价格序列，返回对应指标值。
"""

from __future__ import annotations


def calc_sma(prices: list[float], period: int) -> list[float]:
    """简单移动平均。前 period-1 个位置返回 0（数据不足）。"""
    result = []
    for i in range(len(prices)):
        if i < period - 1:
            result.append(0.0)
        else:
            result.append(sum(prices[i - period + 1:i + 1]) / period)
    return result


def calc_ema(prices: list[float], period: int) -> list[float]:
    """指数移动平均。"""
    if not prices:
        return []
    result = [prices[0]]
    alpha = 2.0 / (period + 1)
    for i in range(1, len(prices)):
        result.append(alpha * prices[i] + (1 - alpha) * result[-1])
    return result


def calc_rsi(prices: list[float], period: int = 14) -> list[float]:
    """RSI 相对强弱指标。"""
    if len(prices) < period + 1:
        return [0.0] * len(prices)

    result = [0.0] * period
    gains = []
    losses = []

    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    # 初始平均值
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(prices)):
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100.0 - 100.0 / (1.0 + rs))

        # 平滑更新
        if i < len(prices) - 1:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    return result


def calc_bollinger_bands(
    prices: list[float], period: int = 20, std_mult: float = 2.0
) -> tuple[list[float], list[float], list[float]]:
    """布林带。返回 (upper, mid, lower) 三个序列。"""
    mid = calc_sma(prices, period)
    upper = [0.0] * len(prices)
    lower = [0.0] * len(prices)

    for i in range(period - 1, len(prices)):
        window = prices[i - period + 1:i + 1]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / period
        std = variance ** 0.5
        upper[i] = mean + std_mult * std
        lower[i] = mean - std_mult * std

    return upper, mid, lower


def compute_all_indicators(
    closes: list[float],
) -> dict:
    """给定收盘价序列，计算全部技术指标。

    Returns:
        {
            'ma_5': 最新 MA5 值 或 None,
            'ma_20': ...,
            'ma_60': ...,
            'rsi_14': ...,
            'boll_upper': ...,
            'boll_mid': ...,
            'boll_lower': ...,
        }
    """
    result = {}

    if not closes:
        return result

    # MA
    ma5 = calc_sma(closes, 5)
    ma20 = calc_sma(closes, 20)
    ma60 = calc_sma(closes, 60)

    result["ma_5"] = ma5[-1] if ma5 and ma5[-1] > 0 else None
    result["ma_20"] = ma20[-1] if ma20 and ma20[-1] > 0 else None
    result["ma_60"] = ma60[-1] if ma60 and ma60[-1] > 0 else None

    # RSI
    rsi = calc_rsi(closes, 14)
    result["rsi_14"] = rsi[-1] if rsi else None

    # 布林带
    upper, mid, lower = calc_bollinger_bands(closes, 20)
    result["boll_upper"] = upper[-1] if upper and upper[-1] > 0 else None
    result["boll_mid"] = mid[-1] if mid and mid[-1] > 0 else None
    result["boll_lower"] = lower[-1] if lower and lower[-1] > 0 else None

    return result
