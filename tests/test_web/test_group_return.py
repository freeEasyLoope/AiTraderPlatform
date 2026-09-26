"""回归测试：组收益率的成本基数必须取「该组操盘手真实初始资金之和」。

历史 bug：dashboard / strategies 用 settings.yaml 写死的 short_capital/long_capital
（设计期每组 3 人 × 10000 = 30000）当分母。长线组实际加至 4 人后，
真实基数应为 40000，但代码仍按 30000 算，收益率被凭空放大。

本测试用受控 DB（3 短 + 4 长，每人初始 10000）验证：
- 长线组「初始 ¥」显示为 40000（而非写死的 30000）
- 长线组收益率按 40000 分母计算（long_total_value=44000 → +10.0%，而非 30000 分母的 +46.7%）
"""

import os
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.storage.models import DailySnapshot, create_database
from src.storage.repository import Repository

import src.web.deps as deps
import src.web.routes.dashboard as dashboard_mod
import src.web.routes.strategies as strategies_mod
from src.web.main import app


def _make_temp_repo():
    tmp = tempfile.mkdtemp(prefix="aitrader_grp_")
    db_path = os.path.join(tmp, "sim.db")
    engine = create_database(db_path)
    repo = Repository(db_path)

    cfg = []
    for i in range(3):
        cfg.append({"name": f"S{i}", "class": "x.Short", "group": "short",
                    "initial_capital": 10000.0})
    for i in range(4):
        cfg.append({"name": f"L{i}", "class": "x.Long", "group": "long",
                    "initial_capital": 10000.0})
    repo.init_traders(cfg)

    # 给每位操盘手一个净值快照：短线 +5%、长线 +10%（相对各自初始资金）
    today = "2099-01-01"
    for t in repo.get_traders(active_only=True):
        tv = t.initial_capital * (1.05 if t.group == "short" else 1.10)
        with repo.session() as s:
            s.add(DailySnapshot(
                trader_id=t.id, date=today, total_value=tv,
                pnl=0.0, pnl_pct=0.0, cash=tv, market_value=0.0,
            ))
            s.commit()
    return repo


@pytest.fixture
def client(monkeypatch):
    repo = _make_temp_repo()
    monkeypatch.setattr(deps, "repo", repo)
    monkeypatch.setattr(dashboard_mod, "repo", repo)
    monkeypatch.setattr(strategies_mod, "repo", repo)
    return TestClient(app)


def test_dashboard_long_group_denominator_is_real_sum(client):
    r = client.get("/")
    assert r.status_code == 200, r.status_code
    body = r.text

    # 长线组 4 人 × 10000 = 40000，必须显示为「初始 ¥40000」
    assert "初始 ¥40000" in body, "长线组初始资金应显示真实之和 40000"

    # 正确分母 40000：长线 total 44000 → +10.0%
    assert "+10.0%" in body, "长线组收益率应按 40000 分母计算（+10.0%）"
    # 写死 30000 分母会算成 (44000-30000)/30000 = +46.7%，绝不能出现
    assert "+46.7%" not in body, "长线组收益率不应按写死的 30000 分母计算"


def test_strategies_long_group_denominator_is_real_sum(client):
    r = client.get("/strategies")
    assert r.status_code == 200, r.status_code
    body = r.text
    assert "初始 ¥40000" in body, "策略页长线组初始资金应显示真实之和 40000"
    assert "+10.0%" in body, "策略页长线组收益率应按 40000 分母计算（+10.0%）"
    assert "+46.7%" not in body, "策略页长线组收益率不应按写死的 30000 分母计算"
