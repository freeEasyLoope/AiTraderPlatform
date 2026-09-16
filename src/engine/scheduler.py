"""调度器 — 每日自动交易 + 每周报告。"""
from __future__ import annotations


import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


class TradingScheduler:
    """交易调度器。

    使用 APScheduler 管理定时任务：
    - 每个交易日 15:00 执行交易
    - 每周五 16:00 生成周报
    """

    def __init__(self, simulator, reporter=None):
        self.simulator = simulator
        self.reporter = reporter
        self._scheduler = BackgroundScheduler()
        self._running = False

    def start(self, trading_time: str = "15:00", report_time: str = "16:00",
              report_day: str = "fri") -> None:
        """启动调度器。

        Args:
            trading_time: 每日交易执行时间 HH:MM
            report_time: 周报生成时间 HH:MM
            report_day: 周报日 mon/tue/wed/thu/fri
        """
        if self._running:
            logger.warning("调度器已在运行")
            return

        hour_t, minute_t = trading_time.split(":")
        hour_r, minute_r = report_time.split(":")
        day_map = {"mon": "mon", "tue": "tue", "wed": "wed",
                    "thu": "thu", "fri": "fri"}

        # 每日交易任务
        self._scheduler.add_job(
            self._daily_trade,
            CronTrigger(hour=int(hour_t), minute=int(minute_t),
                        day_of_week="mon-fri"),
            id="daily_trade",
            name="每日交易",
            replace_existing=True,
        )
        logger.info(f"每日交易任务已调度: {trading_time} (周一至周五)")

        # 每周报告任务
        self._scheduler.add_job(
            self._weekly_report,
            CronTrigger(hour=int(hour_r), minute=int(minute_r),
                        day_of_week=day_map.get(report_day, "fri")),
            id="weekly_report",
            name="周报生成",
            replace_existing=True,
        )
        logger.info(f"周报任务已调度: 每{report_day} {report_time}")

        self._scheduler.start()
        self._running = True
        logger.info("调度器已启动")

    def stop(self) -> None:
        """停止调度器。"""
        if self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("调度器已停止")

    def _daily_trade(self) -> None:
        """每日交易任务。"""
        today = datetime.now().strftime("%Y-%m-%d")
        logger.info(f"⏰ 定时触发每日交易: {today}")
        try:
            results = self.simulator.run_daily(today)
            if results:
                total_orders = sum(len(r) for r in results.values())
                logger.info(f"每日交易完成: {len(results)} 个操盘手, {total_orders} 笔订单")
        except Exception as e:
            logger.error(f"每日交易失败: {e}", exc_info=True)

    def _weekly_report(self) -> None:
        """每周报告任务。"""
        if self.reporter is None:
            logger.warning("未配置报告生成器，跳过周报")
            return
        today = datetime.now().strftime("%Y-%m-%d")
        logger.info(f"⏰ 定时触发周报生成: {today}")
        try:
            report = self.reporter.generate()
            logger.info(f"周报已生成: {report.week_start} ~ {report.week_end}")
        except Exception as e:
            logger.error(f"周报生成失败: {e}", exc_info=True)

    @property
    def is_running(self) -> bool:
        return self._running


def get_date_range_for_week(date_str: str | None = None) -> tuple[str, str]:
    """获取给定日期所在周的周一至周五。

    Args:
        date_str: 日期 YYYY-MM-DD，默认今天

    Returns:
        (周一, 周五)
    """
    if date_str is None:
        dt = datetime.now()
    else:
        dt = datetime.strptime(date_str, "%Y-%m-%d")

    # 周一 = 今天 - weekday()
    monday = dt.replace(day=dt.day - dt.weekday())
    friday = monday.replace(day=monday.day + 4)

    return monday.strftime("%Y-%m-%d"), friday.strftime("%Y-%m-%d")
