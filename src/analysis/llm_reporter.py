"""LLM 周报生成器 — 调用 Claude API 进行绩效分析和策略建议（含历史记忆）。"""
from __future__ import annotations


import json
import logging
from datetime import datetime

from ..storage.repository import Repository
from ..storage.models import WeeklyReport
from .performance import generate_performance_summary, get_benchmark_values
from ..engine.scheduler import get_date_range_for_week

logger = logging.getLogger(__name__)


class LLMReporter:
    """基于 Claude API 的周报生成器。

    输入：本周市场数据 + 各操盘手交易记录 + 绩效指标 + 上周建议
    输出：结构化分析报告 + 策略调整建议（带记忆追踪）
    """

    def __init__(self, repo: Repository, model: str = "claude-sonnet-4-6",
                 max_tokens: int = 4096, temperature: float = 0.3):
        self.repo = repo
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    def generate(self, week_start: str | None = None,
                 week_end: str | None = None) -> WeeklyReport:
        """生成周报（含上期建议追踪）。

        Args:
            week_start: 周起始日，默认本周一
            week_end: 周结束日，默认本周五

        Returns:
            dict with keys: week_start, week_end, summary, rankings, llm_raw
        """
        if week_start is None or week_end is None:
            week_start, week_end = get_date_range_for_week()

        logger.info(f"生成周报: {week_start} ~ {week_end}")

        # 收集数据
        traders = self.repo.get_traders(active_only=True)
        trader_data = []
        trader_info = [(t.id, t.name, t.group or "short") for t in traders]

        # 获取基准数据
        snaps_for_bench = []
        for t_id, _, _ in trader_info:
            s = self.repo.get_snapshots(t_id, limit=60)
            if s:
                snaps_for_bench = s
                break
        bench_values = None
        if snaps_for_bench:
            dates = sorted(set(s.date for s in snaps_for_bench))
            bench_values = get_benchmark_values(dates)

        for t_id, t_name, t_group in trader_info:
            snapshots = self.repo.get_snapshots(t_id, limit=90)
            orders = self.repo.get_orders(t_id, limit=100)
            summary = generate_performance_summary(t_name, snapshots, orders, bench_values)

            # 本周成交记录
            week_orders = [o for o in orders if week_start <= o.created_at[:10] <= week_end]
            buy_orders = [o for o in week_orders if o.type == "buy" and o.status == "filled"]
            sell_orders = [o for o in week_orders if o.type == "sell" and o.status == "filled"]
            rejected = [o for o in week_orders if o.status == "rejected"]

            summary["group"] = "短线" if t_group == "short" else "长线"
            summary["week_buys"] = len(buy_orders)
            summary["week_sells"] = len(sell_orders)
            summary["week_rejected"] = len(rejected)
            summary["buy_details"] = [f"{o.symbol} {o.shares}股@{o.price:.2f}" for o in buy_orders[:5]]
            summary["sell_details"] = [f"{o.symbol} {o.shares}股@{o.price:.2f}" for o in sell_orders[:5]]
            summary["reject_details"] = [f"{o.symbol} {o.type}: {o.reject_reason}" for o in rejected[:3]]

            # 当前持仓
            pos_list = self.repo.get_positions(t_id)
            summary["positions"] = [f"{p.symbol} {p.name} {p.shares}股 成本{p.avg_cost:.2f}" for p in pos_list[:10]]
            trader_data.append(summary)

        # ── 上期建议追踪 ──
        previous_context = self._get_previous_context(week_start)

        # 构建 prompt
        prompt = self._build_prompt(week_start, week_end, trader_data, previous_context)

        # 调用 Claude API
        try:
            llm_output = self._call_claude(prompt)
        except Exception as e:
            logger.warning(f"Claude API 调用失败，使用降级分析: {e}")
            llm_output = self._fallback_analysis(week_start, week_end, trader_data)

        # 解析输出
        parsed = self._parse_output(llm_output, trader_data)

        # 保存到数据库（含上期建议引用）
        rankings_json = json.dumps(parsed.get("trader_rankings", []), ensure_ascii=False)
        summary_text = parsed.get("market_summary", "")
        prev_ref = parsed.get("previous_suggestion_review", "")
        report = WeeklyReport(
            week_start=week_start,
            week_end=week_end,
            llm_raw=llm_output,
            summary=summary_text,
            rankings=rankings_json,
        )
        self.repo.save_weekly_report(report)
        return {
            "week_start": week_start,
            "week_end": week_end,
            "summary": summary_text,
            "rankings": rankings_json,
            "llm_raw": llm_output,
            "previous_review": prev_ref,
        }

    def _get_previous_context(self, current_week_start: str) -> str:
        """获取上期周报中的策略建议，形成追踪链。"""
        latest = self.repo.get_latest_report()
        if not latest:
            return ""

        try:
            prev_raw = latest.llm_raw or ""
            # 尝试提取 strategy_adjustments
            parsed = None
            text = prev_raw.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1])
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                pass

            adjustments = parsed.get("strategy_adjustments", []) if parsed else []
            if not adjustments:
                return ""

            ctx = f"""## 📝 上期建议追踪

上期周报 ({latest.week_start}~{latest.week_end}) 曾提出以下参数调整建议：

"""
            for adj in adjustments[:8]:
                ctx += f"- **{adj.get('trader', '?')}** → {adj.get('param', '?')}: "
                ctx += f"{adj.get('current_value', '?')} → {adj.get('suggested_value', '?')}"
                ctx += f"（{adj.get('reason', '')}）\n"

            ctx += """
请在本期报告中增加 `previous_suggestion_review` 字段：
- 分析每条上期建议是否被执行
- 执行后的效果（是否改善了收益率/回撤）
- 如果未执行，是否仍然建议调整"""
            return ctx
        except Exception:
            return ""

    def _build_prompt(self, week_start: str, week_end: str,
                      trader_data: list[dict], previous_context: str = "") -> str:
        """构建详细的 Claude prompt（含 Alpha/Beta 归因 + 历史记忆）。"""
        trader_summaries = ""
        for i, td in enumerate(trader_data, 1):
            alpha_info = ""
            if td.get("alpha", "N/A") != "N/A":
                alpha_info = f"""
**Alpha/Beta 归因：**
- Alpha: {td.get('alpha', 'N/A')}（{td.get('alpha_level', '')}）
- Beta: {td.get('beta', 'N/A')}（对市场敏感度）
- R²: {td.get('r_squared', 'N/A')}（基准解释度）
- Info Ratio: {td.get('info_ratio', 'N/A')}"""

            trader_summaries += f"""
### {i}. {td['name']}（{td.get('group', '短线')}组）

**绩效数据：**
- 累计收益: {td['cumulative_return']}
- 最大回撤: {td['max_drawdown']}
- 夏普比率: {td['sharpe_ratio']}
- 年化波动: {td['volatility']}
- 胜率: {td['win_rate']}
- 当前资产: {td['latest_value']}{alpha_info}

**本周交易：**
- 买入: {td.get('week_buys', 0)} 笔 — {td.get('buy_details', [])}
- 卖出: {td.get('week_sells', 0)} 笔 — {td.get('sell_details', [])}
- 被拒绝: {td.get('week_rejected', 0)} 笔 — {td.get('reject_details', [])}

**当前持仓：**
{td.get('positions', [])}
"""

        return f"""你是一位资深 A 股量化投资分析师，有 10 年实盘经验。请根据以下模拟交易系统的本周数据，生成一份**详细的**周度分析报告。

## 报告周期
{week_start} ~ {week_end}

## 系统说明
这是两组策略（短线组 vs 长线组）在 A 股市场的模拟对抗。短线组侧重技术面（均线、RSI、宏观轮动），长线组侧重基本面（PE/PB低估值、高股息、指数定投）。每组三人各有 ¥10,000 初始资金。

## Alpha/Beta 归因说明
Alpha 表示策略扣除市场涨跌后的独立收益（正=有选股能力），Beta 表示策略对市场的敏感度（>1=比市场波动大），R² 表示策略收益有多少能被市场解释，Info Ratio 表示每单位主动风险带来的超额收益。

{previous_context}

## 各操盘手本周表现
{trader_summaries}

## 输出格式

请以 JSON 格式输出。comment 字段需要**详细**（至少 2-3 句，而非一句话），必须包含：
- 该操盘手的交易行为分析（为什么买这些股票、策略是否按设计执行）
- Alpha/Beta 解读（独立选股能力 vs 靠市场上涨）
- 表现好/差的具体原因
- 下周应该怎么做

```json
{{
  "market_summary": "本周 A 股整体表现描述，包括指数走势、板块轮动、资金流向等（2-3句）",
  "trader_rankings": [
    {{
      "name": "操盘手名称",
      "rank": 1,
      "score": 85,
      "comment": "详细评价（至少2-3句）：本周买了XX股票因为XX原因。策略执行XX。Alpha为+3.2%说明有独立选股能力。Beta=0.8说明波动小于市场。回撤控制在XX%。下周建议XX。"
    }}
  ],
  "best_trade": {{
    "trader": "操盘手名称",
    "description": "哪笔交易最成功？为什么？",
    "lesson": "从这笔交易中可以学到什么投资原则？"
  }},
  "worst_trade": {{
    "trader": "操盘手名称",
    "description": "哪笔交易有问题？具体问题是什么？",
    "lesson": "如何避免类似错误？"
  }},
  "strategy_adjustments": [
    {{
      "trader": "目标操盘手",
      "param": "参数名（如 stop_loss, max_positions, pe_threshold 等）",
      "current_value": "当前值",
      "suggested_value": "建议值",
      "reason": "为什么建议这样调整？"
    }}
  ],
  "previous_suggestion_review": "对上期建议的回顾（如果有）：是否执行、效果如何、是否继续建议。如果无上期建议则写'无'。",
  "overall_advice": "对投资者的总体建议（3-5句，用中文）：本周策略表现总结、短线vs长线对比、Alpha/Beta解读、下周关注重点、风险提示。"
}}
```

## 分析要点
1. 评估每个操盘手的**风险调整后收益**（夏普比率），不仅看绝对收益
2. **重点关注 Alpha**：正 Alpha > 3% 说明策略有真正的选股能力，负 Alpha 说明只是跟着市场涨跌
3. 分析**策略在当前市场环境下的适应性**——为什么有些策略跑得好，有些差
4. 对被拒绝的交易要分析原因（资金不足？选股条件太宽松？）
5. 对比短线组和长线组的整体表现差异
6. 提出**具体的参数调整建议**，有数据支撑
7. comment 绝不能一句话敷衍——要像真正的投研周报一样详细
8. 如果上期有建议，必须评估执行情况和效果

请直接输出 JSON，不要有任何其他文字。"""

    def _call_claude(self, prompt: str) -> str:
        """调用 LLM API（支持 Anthropic 和 DeepSeek 兼容端点）。"""
        from anthropic import Anthropic
        import os

        api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        if not api_key:
            raise RuntimeError("请设置环境变量 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN")

        base_url = os.environ.get("ANTHROPIC_BASE_URL", None)
        if base_url:
            client = Anthropic(api_key=api_key, base_url=base_url)
        else:
            client = Anthropic(api_key=api_key)

        model = os.environ.get("ANTHROPIC_MODEL") or self.model

        message = client.messages.create(
            model=model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )

        for block in message.content:
            if hasattr(block, "text") and block.text:
                return block.text
        return str(message.content)

    def _fallback_analysis(self, week_start: str, week_end: str,
                           trader_data: list[dict]) -> str:
        """降级分析（API 不可用时）。"""
        sorted_data = sorted(
            trader_data,
            key=lambda x: float(x["cumulative_return"].strip("%").lstrip("+")),
            reverse=True,
        )

        rankings = []
        for i, td in enumerate(sorted_data, 1):
            alpha_note = ""
            if td.get("alpha", "N/A") != "N/A":
                alpha_note = f"，Alpha={td['alpha']}，Beta={td['beta']}"
            rankings.append({
                "name": td["name"],
                "rank": i,
                "score": max(50, 100 - i * 10),
                "comment": f"累计收益 {td['cumulative_return']}，最大回撤 {td['max_drawdown']}{alpha_note}",
            })

        return json.dumps({
            "market_summary": "本周 A 股市场正常运行。",
            "trader_rankings": rankings,
            "best_trade": {"trader": sorted_data[0]["name"] if sorted_data else "无",
                          "description": "收益最高", "lesson": "坚持策略"},
            "worst_trade": {"trader": sorted_data[-1]["name"] if sorted_data else "无",
                           "description": "回撤较大", "lesson": "注意风险控制"},
            "strategy_adjustments": [],
            "previous_suggestion_review": "无上期建议",
            "overall_advice": "建议继续观察各策略在不同市场环境下的表现，暂不调整参数。"
        }, ensure_ascii=False)

    def _parse_output(self, llm_output: str,
                      trader_data: list[dict]) -> dict:
        """解析 Claude 输出为结构化数据。"""
        try:
            text = llm_output.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1])
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Claude 输出 JSON 解析失败，使用降级分析")
            return json.loads(
                self._fallback_analysis(
                    datetime.now().strftime("%Y-%m-%d"),
                    datetime.now().strftime("%Y-%m-%d"),
                    trader_data,
                )
            )
