"""Rich 渲染工具 — Windows GBK 兼容版本。"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.table import Table

# 强制 UTF-8 输出（Windows 兼容）
console = Console(force_terminal=True)


def print_banner():
    """打印系统横幅（无 emoji，兼容 GBK）。"""
    banner = """
+==========================================+
|  A-Share Simulation Trading System       |
|  6 Traders | 10K Capital | Strategy Evol |
+==========================================+
"""
    console.print(banner, style="bold cyan")


def format_money(amount: float) -> str:
    """格式化金额。"""
    return f"${amount:,.2f}"


def format_pct(value: float) -> str:
    """格式化百分比。"""
    if value >= 0:
        return f"[green]+{value:.2f}%[/green]"
    return f"[red]{value:.2f}%[/red]"


def print_trade_result(trader_name: str, orders: list, filled: int, rejected: int):
    """打印交易结果。"""
    table = Table(title=f"Trade Result: {trader_name}")
    table.add_column("Status", style="bold")
    table.add_column("Count")
    table.add_row("[green]Filled[/green]", str(filled))
    table.add_row("[red]Rejected[/red]", str(rejected))
    table.add_row("Total", str(len(orders)))
    console.print(table)
