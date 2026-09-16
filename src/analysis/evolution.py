"""策略迭代 — 根据 LLM 建议调整操盘手参数。"""
from __future__ import annotations


import json
import logging
from typing import Optional

import yaml

from ..storage.repository import Repository

logger = logging.getLogger(__name__)


class StrategyEvolution:
    """策略参数迭代管理器。

    工作流程：
    1. 读取最新周报中的 strategy_adjustments 建议
    2. 展示给用户
    3. 用户确认后更新 traders.yaml
    """

    def __init__(self, repo: Repository, config_path: str | None = None):
        self.repo = repo
        if config_path is None:
            from ..runtime import config_path as _resolve_config_path
            config_path = str(_resolve_config_path("traders.yaml"))
        self.config_path = config_path

    def get_pending_adjustments(self) -> list[dict]:
        """获取最新周报中待确认的策略调整。"""
        report = self.repo.get_latest_report()
        if not report or not report.rankings:
            return []

        try:
            # 从 llm_raw 中提取 strategy_adjustments
            raw = report.llm_raw or ""
            data = json.loads(raw) if raw else {}
            return data.get("strategy_adjustments", [])
        except json.JSONDecodeError:
            return []

    def apply_adjustments(self, adjustments: list[dict]) -> bool:
        """应用策略调整到 traders.yaml。

        Args:
            adjustments: 要应用的调整列表

        Returns:
            是否成功
        """
        if not adjustments:
            return False

        try:
            with open(self.config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f)

            for adj in adjustments:
                trader_name = adj.get("trader", "")
                param_name = adj.get("param", "")
                new_value = adj.get("suggested_value")

                if not trader_name or not param_name or new_value is None:
                    continue

                for t in config.get("traders", []):
                    if t["name"] == trader_name:
                        if param_name in t.get("params", {}):
                            old_val = t["params"][param_name]
                            t["params"][param_name] = type(old_val)(new_value)
                            logger.info(f"调整 {trader_name}.{param_name}: {old_val} → {new_value}")
                            break

            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

            return True
        except Exception as e:
            logger.error(f"应用策略调整失败: {e}")
            return False

    def suggest_fund_reallocation(self) -> Optional[dict]:
        """建议资金重新分配。

        根据各操盘手表现，建议将更多资金分配给表现好的操盘手。
        """
        traders = self.repo.get_traders(active_only=True)
        if len(traders) < 2:
            return None

        # 计算每个操盘手的收益率
        performances = []
        for t in traders:
            snapshots = self.repo.get_snapshots(t.id, limit=90)
            if snapshots:
                initial = t.initial_capital
                current = snapshots[0].total_value  # 最新
                ret = (current - initial) / initial
                performances.append((t.name, ret, initial))

        if not performances:
            return None

        # 按收益排序
        performances.sort(key=lambda x: x[1], reverse=True)

        # 简单策略：给前 2 名各加 10%，最后 2 名各减 10%
        suggestion = {
            "increased": [],
            "decreased": [],
        }

        total_capital = sum(p[2] for p in performances)
        per_trader = total_capital / len(performances)

        for i, (name, ret, cap) in enumerate(performances[:2]):
            suggestion["increased"].append({
                "name": name,
                "from": cap,
                "to": cap + per_trader * 0.1,
                "reason": f"收益率 {ret:+.1%}，排名 {i+1}",
            })

        for i, (name, ret, cap) in enumerate(performances[-2:]):
            suggestion["decreased"].append({
                "name": name,
                "from": cap,
                "to": cap - per_trader * 0.1,
                "reason": f"收益率 {ret:+.1%}，排名 {len(performances) - 1 + i}",
            })

        return suggestion
