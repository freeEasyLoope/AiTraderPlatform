"""CLI 入口 — Typer + Rich。"""
from __future__ import annotations


import json
from datetime import datetime

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .display import format_money, format_pct, print_banner

app = typer.Typer(
    name="aitrader",
    help="A股模拟投资系统 — 多策略操盘手对抗",
)
console = Console()

# 全局实例（惰性初始化）
_repo = None
_simulator = None
_scheduler = None
_reporter = None


def _get_repo():
    global _repo
    if _repo is None:
        from ..storage.repository import Repository
        from ..config import load_settings
        settings = load_settings()
        _repo = Repository(settings["database"]["path"])
    return _repo


def _get_simulator():
    global _simulator
    if _simulator is None:
        from ..config import load_settings
        # 数据源优先级: 新浪财经 > akshare > Mock
        # 设 USE_AKSHARE=1 强制 akshare, 设 USE_MOCK=1 强制 mock
        import os
        if os.environ.get("USE_MOCK") == "1":
            from ..data.mock_client import MockDataProvider
            data_provider = MockDataProvider()
            console.print("[dim]Data: mock[/dim]")
        elif os.environ.get("USE_AKSHARE") == "1":
            from ..data.akshare_client import AkshareClient
            data_provider = AkshareClient()
            console.print("[dim]Data: akshare[/dim]")
        else:
            try:
                from ..data.sina_client import SinaClient
                data_provider = SinaClient()
                # 快速连通性测试
                test = data_provider.get_snapshot("600519")
                if test and test.close > 0:
                    console.print(f"[dim]Data: sina (live) - 贵州茅台 {test.close:.2f}[/dim]")
                else:
                    raise Exception("sina returned no data")
            except Exception as e:
                console.print(f"[yellow]sina unavailable ({e}), using mock[/yellow]")
                from ..data.mock_client import MockDataProvider
                data_provider = MockDataProvider()

        from ..traders.registry import registry
        from ..engine.simulator import Simulator
        from ..traders.value_hunter import ValueHunter
        from ..traders.trend_follower import TrendFollower
        from ..traders.mean_reversion import MeanReversion
        from ..traders.dividend_collector import DividendCollector
        from ..traders.index_dca import IndexDca
        from ..traders.macro_hedger import MacroHedger

        # 注册所有操盘手
        registry.register("value_hunter.ValueHunter", ValueHunter)
        registry.register("trend_follower.TrendFollower", TrendFollower)
        registry.register("mean_reversion.MeanReversion", MeanReversion)
        registry.register("dividend_collector.DividendCollector", DividendCollector)
        registry.register("index_dca.IndexDca", IndexDca)
        registry.register("macro_hedger.MacroHedger", MacroHedger)

        repo = _get_repo()
        _simulator = Simulator(repo, data_provider, registry)
    return _simulator


def _get_scheduler():
    global _scheduler
    if _scheduler is None:
        from ..engine.scheduler import TradingScheduler
        from ..config import load_settings
        settings = load_settings()
        sched_config = settings["scheduler"]
        _scheduler = TradingScheduler(
            _get_simulator(),
            reporter=_get_reporter(),
        )
    return _scheduler


def _get_reporter():
    global _reporter
    if _reporter is None:
        from ..analysis.llm_reporter import LLMReporter
        from ..config import load_settings
        settings = load_settings()
        llm_config = settings["llm"]
        _reporter = LLMReporter(
            _get_repo(),
            model=llm_config.get("model", "claude-sonnet-4-6"),
            max_tokens=llm_config.get("max_tokens", 4096),
            temperature=llm_config.get("temperature", 0.3),
        )
    return _reporter


@app.command()
def init():
    """初始化系统：创建数据库和操盘手账户。"""
    from ..config import load_settings, load_traders

    settings = load_settings()
    trader_configs = load_traders()

    repo = _get_repo()
    traders = repo.init_traders(trader_configs)

    print_banner()

    table = Table(title="操盘手初始化完成")
    table.add_column("ID", style="cyan")
    table.add_column("名称", style="green")
    table.add_column("策略", style="blue")
    table.add_column("初始资金", justify="right", style="yellow")

    for t in traders:
        table.add_row(str(t["id"]), t["name"], t["strategy"], format_money(t["cash"]))

    console.print(table)
    console.print(f"\nTotal capital: {format_money(sum(t['cash'] for t in traders))}")
    console.print("\n[green][OK] Init done, run 'py cli.py run' to start trading[/green]")


@app.command()
def status(
    trader_id: int = typer.Option(None, "--trader", "-t", help="指定操盘手 ID"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="显示持仓详情"),
):
    """查看操盘手当前状态。"""
    repo = _get_repo()
    traders = repo.get_traders()

    if trader_id is not None:
        traders = [t for t in traders if t.id == trader_id]
        if not traders:
            console.print(f"[red]未找到操盘手 ID={trader_id}[/red]")
            return

    print_banner()

    for t in traders:
        snapshots = repo.get_snapshots(t.id, limit=1)
        latest = snapshots[0] if snapshots else None
        total = latest.total_value if latest else t.cash
        pnl_pct = ((total - t.initial_capital) / t.initial_capital) * 100
        color = "green" if pnl_pct >= 0 else "red"

        # 基本信息面板
        text = Text()
        text.append(f"策略: {t.strategy}\n", style="blue")
        text.append(f"现金: {format_money(t.cash)}\n")
        text.append(f"总资产: {format_money(total)}\n")
        text.append(f"收益率: ", style="white")
        text.append(f"{pnl_pct:+.2f}%", style=color)

        console.print(Panel(text, title=f"[bold cyan]#{t.id} {t.name}[/bold cyan]"))

        # 持仓详情
        if verbose:
            positions = repo.get_positions(t.id)
            if positions:
                pos_table = Table(title="持仓明细")
                pos_table.add_column("代码", style="cyan")
                pos_table.add_column("名称")
                pos_table.add_column("数量", justify="right")
                pos_table.add_column("成本价", justify="right")
                pos_table.add_column("锁定", justify="right")
                for p in positions:
                    pos_table.add_row(
                        p.symbol, p.name, str(p.shares),
                        f"¥{p.avg_cost:.2f}",
                        str(p.locked_shares),
                    )
                console.print(pos_table)
            else:
                console.print("[dim]空仓[/dim]")
        console.print()


@app.command()
def run(
    date: str = typer.Option(None, "--date", "-d", help="指定日期 YYYY-MM-DD，默认今天"),
):
    """执行当日交易（所有操盘手）。"""
    date = date or datetime.now().strftime("%Y-%m-%d")

    print_banner()
    console.print(f"[bold]交易日期: {date}[/bold]\n")

    sim = _get_simulator()
    results = sim.run_daily(date)

    if not results:
        console.print("[yellow]今日无交易（非交易日或无活跃操盘手）[/yellow]")
        return

    # 汇总展示
    table = Table(title="Trade Results")
    table.add_column("操盘手", style="green")
    table.add_column("成交", justify="right", style="cyan")
    table.add_column("拒绝", justify="right", style="red")
    table.add_column("总订单", justify="right")

    for name, orders in results.items():
        filled = sum(1 for o in orders if o.status == "filled")
        rejected = sum(1 for o in orders if o.status == "rejected")
        table.add_row(name, str(filled), str(rejected), str(len(orders)))

    console.print(table)

    # 展示拒绝原因
    all_rejected = [o for orders in results.values() for o in orders if o.status == "rejected"]
    if all_rejected:
        console.print("\n[yellow][!] Rejected orders:[/yellow]")
        for r in all_rejected[:10]:
            console.print(f"  [dim]{r.trader_id}[/dim] {r.order.symbol} {r.order.action}: {r.reject_reason}")

    console.print("\n[green][OK] Trading done[/green]")


@app.command()
def report(
    week_start: str = typer.Option(None, "--from", help="周起始日"),
    week_end: str = typer.Option(None, "--to", help="周结束日"),
):
    """生成本周周报（含 LLM 分析）。"""
    print_banner()
    console.print("[bold]正在生成周报...[/bold]\n")

    reporter = _get_reporter()
    report_obj = reporter.generate(week_start, week_end)

    console.print(f"[bold]周报: {report_obj['week_start']} ~ {report_obj['week_end']}[/bold]\n")

    if report_obj.get("rankings"):
        try:
            rankings = json.loads(report_obj["rankings"]) if isinstance(report_obj["rankings"], str) else report_obj["rankings"]
            table = Table(title="Trader Rankings")
            table.add_column("排名", style="bold")
            table.add_column("名称", style="green")
            table.add_column("评分", justify="right")
            table.add_column("评价")

            for r in sorted(rankings, key=lambda x: x.get("rank", 99)):
                medal = {1: " 1*", 2: " 2*", 3: " 3*"}.get(r["rank"], f"  {r['rank']}")
                table.add_row(medal, r["name"], str(r.get("score", "-")), r.get("comment", ""))

            console.print(table)
        except (json.JSONDecodeError, KeyError):
            console.print("[dim]排名数据不可解析[/dim]")

    if report_obj.get("summary"):
        console.print(Panel(report_obj["summary"], title="Market Summary"))

    # 策略调整建议
    from ..analysis.evolution import StrategyEvolution
    evolution = StrategyEvolution(_get_repo())
    adjustments = evolution.get_pending_adjustments()

    if adjustments:
        console.print("\n[yellow][!] Strategy adjustments (from LLM):[/yellow]")
        for adj in adjustments:
            console.print(
                f"  {adj.get('trader', '?')}.{adj.get('param', '?')}: "
                f"{adj.get('current_value', '?')} → "
                f"[bold cyan]{adj.get('suggested_value', '?')}[/bold cyan]"
            )
            console.print(f"    理由: {adj.get('reason', '无')}")

        if typer.confirm("\n是否应用这些调整?", default=False):
            evolution.apply_adjustments(adjustments)
            console.print("[green][OK] Strategy params updated[/green]")

    console.print("\n[green][OK] Weekly report generated[/green]")


@app.command()
def leaderboard():
    """操盘手收益排行榜。"""
    repo = _get_repo()
    traders = repo.get_traders()

    print_banner()

    rankings = []
    for t in traders:
        snapshots = repo.get_snapshots(t.id, limit=90)
        total = snapshots[0].total_value if snapshots else t.cash
        pnl_pct = ((total - t.initial_capital) / t.initial_capital) * 100
        rankings.append((t.name, t.strategy, total, pnl_pct, t.cash))

    rankings.sort(key=lambda x: x[3], reverse=True)

    table = Table(title="Leaderboard")
    table.add_column("排名", style="bold")
    table.add_column("名称", style="green")
    table.add_column("策略", style="blue")
    table.add_column("总资产", justify="right")
    table.add_column("收益率", justify="right")
    table.add_column("现金", justify="right")

    for i, (name, strategy, total, pnl_pct, cash) in enumerate(rankings, 1):
        medal = {1: " 1*", 2: " 2*", 3: " 3*"}.get(i, f"  {i}")
        color = "green" if pnl_pct >= 0 else "red"
        table.add_row(
            medal, name, strategy,
            format_money(total),
            f"[{color}]{pnl_pct:+.2f}%[/{color}]",
            format_money(cash),
        )

    console.print(table)


@app.command()
def start(
    trading_time: str = typer.Option("15:00", "--trading-time", help="每日交易时间 HH:MM"),
    report_time: str = typer.Option("16:00", "--report-time", help="周报时间 HH:MM"),
    report_day: str = typer.Option("fri", "--report-day", help="周报日 mon/tue/wed/thu/fri"),
):
    """启动定时调度器（每日自动交易 + 每周报告）。"""
    print_banner()

    sched = _get_scheduler()
    sched.start(trading_time, report_time, report_day)

    console.print(f"[green][OK] Scheduler started[/green]")
    console.print(f"  每日交易: {trading_time} (周一至周五)")
    console.print(f"  每周报告: 每{report_day} {report_time}")
    console.print("\n[yellow]按 Ctrl+C 停止[/yellow]")

    try:
        import time
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        sched.stop()
        console.print("\n[green]调度器已停止[/green]")


@app.command()
def backtest(
    trader_id: int = typer.Option(..., "--trader", "-t", help="操盘手 ID"),
    start: str = typer.Option(..., "--start", help="起始日期 YYYY-MM-DD"),
    end: str = typer.Option(None, "--end", help="结束日期 YYYY-MM-DD，默认今天"),
):
    """回测指定策略。"""
    end = end or datetime.now().strftime("%Y-%m-%d")

    print_banner()
    console.print(f"[bold]回测: 操盘手 #{trader_id} | {start} ~ {end}[/bold]\n")

    console.print("[yellow]回测功能需要历史数据支持，将在 Phase 6 完善[/yellow]")
    console.print("[dim]当前可用: 使用 akshare 历史数据的逐日回测[/dim]")


@app.command()
def trader_list():
    """列出所有操盘手及参数。"""
    from ..config import load_traders

    print_banner()
    traders = load_traders()

    table = Table(title="操盘手配置")
    table.add_column("名称", style="green")
    table.add_column("策略类", style="blue")
    table.add_column("启用", style="cyan")
    table.add_column("参数", style="dim")

    for t in traders:
        params_str = ", ".join(f"{k}={v}" for k, v in t.get("params", {}).items())
        table.add_row(
            t["name"], t["class"],
            "[v]" if t.get("active", True) else "[ ]",
            params_str[:80] + ("..." if len(params_str) > 80 else ""),
        )

    console.print(table)


@app.command()
def screening(
    universe: str = typer.Option("all", "--universe", "-u", help="标的池: all / hs300 / zz500"),
    steps: str = typer.Option("1,3,5", "--steps", "-s", help="执行的步骤，逗号分隔"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="显示每步详情"),
    show_failed: bool = typer.Option(False, "--failed", "-f", help="同时显示被淘汰的股票原因"),
):
    """运行5步选股漏斗，输出可交易股票清单。"""
    print_banner()
    console.print(f"[bold]选股漏斗: universe={universe}, steps={steps}[/bold]\n")

    # 加载配置
    from ..config import load_screening_config
    cfg = load_screening_config()
    step_list = [int(s.strip()) for s in steps.split(",") if s.strip().isdigit()]
    cfg["active_steps"] = step_list

    # 初始化（优先用 Sina 因为不用直连 Eastmoney）
    from ..screening.datasource import FunnelDataSource
    from ..screening.pipeline import ScreenPipeline

    # 选择可用的 MarketDataProvider
    data_provider = None
    try:
        from ..data.sina_client import SinaClient
        data_provider = SinaClient()
    except Exception:
        pass

    if data_provider is None:
        try:
            from ..data.akshare_client import AkshareClient
            data_provider = AkshareClient()
        except Exception:
            pass

    if data_provider is None:
        console.print("[red]无可用的数据源[/red]")
        return

    with console.status("[bold green]获取数据中..."):
        data = FunnelDataSource(data_provider)
        pipeline = ScreenPipeline(data, config=cfg)
        result = pipeline.run(universe=universe, steps=step_list)

    # 统计摘要
    step_names = {1: "量价+PE", 2: "财务排雷", 3: "资金验证", 4: "赛道择优", 5: "风险过滤"}

    console.print(f"\n输入: {result.input_count} 只 → 输出: [bold green]{result.output_count} 只[/bold green]")
    console.print(f"耗时: {result.duration_ms}ms")

    if verbose:
        console.print("\n[bold]各步骤统计:[/bold]")
        for step_num, stats in sorted(result.step_stats.items()):
            name = step_names.get(step_num, f"第{step_num}步")
            console.print(
                f"  第{step_num}步 [{name}]: {stats['before']} → {stats['after']} "
                f"(-{stats['dropped']})"
            )

    if result.errors:
        console.print(f"\n[yellow][!] 警告: {len(result.errors)} 个步骤出错[/yellow]")
        if verbose:
            for e in result.errors:
                console.print(f"  - {e}")

    # 通过列表
    console.print(f"\n[bold green]通过筛选 ({result.output_count} 只):[/bold green]")

    table = Table(title="通过漏斗的股票")
    table.add_column("代码", style="cyan")
    table.add_column("名称")
    table.add_column("行业", style="dim")
    table.add_column("总评分", justify="right")
    if verbose:
        table.add_column("各步详情", style="dim", max_width=60)

    passed_assessments = sorted(
        [a for a in result.assessments.values() if a.passed],
        key=lambda a: a.total_score, reverse=True
    )

    for a in passed_assessments[:30]:  # 最多显示 30 只
        score_style = "green" if a.total_score >= 0.8 else "yellow" if a.total_score >= 0.5 else "dim"
        row = [
            a.symbol, a.name or "-", a.industry or "-",
            f"[{score_style}]{a.total_score:.2f}[/{score_style}]",
        ]
        if verbose:
            step_details = " | ".join(
                f"S{s.step}:{'V' if s.passed else 'X'}" for s in a.steps
            )
            row.append(step_details)
        table.add_row(*row)

    console.print(table)

    # 淘汰原因（可选）
    if show_failed:
        failed_list = [a for a in result.assessments.values() if not a.passed]
        if failed_list:
            console.print(f"\n[yellow]淘汰 ({len(failed_list)} 只):[/yellow]")
            ft = Table(title="淘汰详情")
            ft.add_column("代码", style="red")
            ft.add_column("名称")
            ft.add_column("淘汰原因", style="dim")
            for a in failed_list[:20]:
                reasons = "; ".join(
                    s.reason for s in a.steps if not s.passed
                ) or "未知"
                ft.add_row(a.symbol, a.name or "-", reasons[:100])
            console.print(ft)

    console.print(f"\n[green][OK] 漏斗完成[/green]")


def main():
    app()


if __name__ == "__main__":
    main()
