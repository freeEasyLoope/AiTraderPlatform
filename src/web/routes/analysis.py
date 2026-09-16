"""LLM 分析 & 压力测试路由。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from fastapi import APIRouter

from ...data.provider import MarketSnapshot
from ...runtime import config_path

router = APIRouter()


# ── helpers ──

def _get_wl_names() -> dict:
    import yaml
    wl_path = config_path("watchlist.yaml")
    with open(wl_path, encoding="utf-8") as f:
        wl = yaml.safe_load(f)
    return {**wl.get("stocks", {}), **wl.get("funds", {})}


# ── routes ──

@router.get("/api/recommendations/analyze/{symbol}")
async def api_analyze_stock(symbol: str):
    """LLM 深度分析单个标的——给新手的具体建议。"""
    names = _get_wl_names()
    name = names.get(symbol, symbol)

    # 快速行情（多源链：腾讯优先、失败回落新浪；见 data/realtime_http.py）
    price_info = {}
    try:
        from ...data.realtime_http import fetch_sina_format
        import re
        raw = fetch_sina_format([symbol])
        m = re.search(r'"(.+)"', raw)
        if m:
            parts = m.group(1).split(",")
            if len(parts) >= 6:
                price_info = {"price": float(parts[3]), "open": float(parts[1]),
                              "high": float(parts[4]), "low": float(parts[5]),
                              "prev_close": float(parts[2])}
    except Exception:
        pass

    pe = pb = None
    try:
        from ...data.fundamentals import _try_baostock
        fake = {symbol: MarketSnapshot(symbol=symbol, name=name,
                close=price_info.get("price", 0), open=0, high=0, low=0, volume=0, change_pct=0)}
        _try_baostock(fake, [symbol], datetime.now().strftime("%Y-%m-%d"))
        pe, pb = fake[symbol].pe, fake[symbol].pb
    except Exception:
        pass

    # 操盘手建议
    trader_advice = _get_trader_advice(symbol, name, price_info, pe, pb)

    # LLM 分析
    try:
        prompt = f"""你是投资教育专家，用新手能理解的语言分析股票。

股票：{name}（{symbol}）
当前价格：¥{price_info.get('price','未知')}
市盈率PE：{pe if pe else '未知'}（<15低估，15-30合理，>30偏高）
市净率PB：{pb if pb else '未知'}（<1破净，1-3合理，>3偏高）

六位操盘手判断：
{chr(10).join(trader_advice)}

用中文JSON回答：
{{"summary":"一句话总结是否值得关注","novice_advice":"3-5句详细建议：估值水平、风险等级、适合什么投资者","buy_plan":"如果买入：建议仓位%、什么价位、止损价","sell_plan":"如果持有：什么情况卖","target_price":"合理买入价区间","risk_level":"低/中/高","holding_period":"短线1-2周/中线1-3月/长线半年以上"}}
只输出JSON。"""

        from anthropic import Anthropic
        ak = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        if ak:
            base = os.environ.get("ANTHROPIC_BASE_URL", None)
            client = Anthropic(api_key=ak, base_url=base) if base else Anthropic(api_key=ak)
            msg = client.messages.create(
                model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
                max_tokens=2048, temperature=0.3,
                messages=[{"role": "user", "content": prompt}])
            text = ""
            for block in msg.content:
                if hasattr(block, "text") and block.text:
                    text = block.text
                    break
            if not text:
                text = str(msg.content)
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("\n```", 1)[0]
            text = text.strip()
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                m = re.search(r'\{.+\}', text, re.DOTALL)
                if m:
                    return json.loads(m.group())
                return {"summary": name + " AI分析暂不可用",
                        "novice_advice": "模型返回格式异常，请稍后重试或查看操盘手建议",
                        "buy_plan": "", "sell_plan": "", "target_price": "",
                        "risk_level": "中", "holding_period": ""}
    except Exception as e:
        return {"summary": name + " AI分析暂不可用",
                "novice_advice": "网络或模型服务异常，请稍后重试: " + str(e)[:50],
                "buy_plan": "", "sell_plan": "", "target_price": "",
                "risk_level": "中", "holding_period": ""}


@router.get("/api/stress/{symbol}")
async def api_stress_test(symbol: str):
    """压力测试——估值/成交量/支撑位/资金分歧 + 事件复盘。"""
    names = _get_wl_names()
    name = names.get(symbol, symbol)
    result = {"symbol": symbol, "name": name, "valuation": {}, "volume": {},
              "support": {}, "divergence": {}, "events": []}

    hist_prices, hist_volumes = [], []
    try:
        from ...data.sina_client import SinaClient
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        snaps = SinaClient().get_historical_data([symbol], start, end).get(symbol, [])
        if snaps:
            hist_prices = [s.close for s in snaps]
            hist_volumes = [s.volume for s in snaps]
    except Exception:
        pass

    cp = hist_prices[-1] if hist_prices else 0
    pe = pb = None
    try:
        from ...data.fundamentals import _try_baostock
        fake = {symbol: MarketSnapshot(symbol=symbol, name=name, close=cp,
                open=0, high=0, low=0, volume=0, change_pct=0)}
        _try_baostock(fake, [symbol], datetime.now().strftime("%Y-%m-%d"))
        pe, pb = fake[symbol].pe, fake[symbol].pb
    except Exception:
        pass

    result["valuation"] = {"current_price": round(cp, 2), "pe": round(pe, 1) if pe else None,
        "pb": round(pb, 2) if pb else None,
        "pe_level": "偏低" if pe and pe < 15 else "偏高" if pe and pe > 30 else "适中" if pe else "无",
        "pb_level": "破净" if pb and pb < 1 else "合理" if pb and pb < 3 else "偏高" if pb else "无"}

    if hist_volumes and len(hist_volumes) >= 20:
        avg20, avg5 = sum(hist_volumes[-20:]) / 20, sum(hist_volumes[-5:]) / 5
        ratio = avg5 / avg20 if avg20 > 0 else 1
        vls, vds = [], []
        for i in range(max(0, len(hist_volumes) - 30), len(hist_volumes)):
            vds.append(f"-{len(hist_volumes) - i - 1}")
            vls.append(round(hist_volumes[i] / 10000, 0))
        result["volume"] = {"avg_20d": round(avg20 / 10000, 0), "recent_5d": round(avg5 / 10000, 0),
            "ratio": round(ratio, 2), "signal": "放量" if ratio > 1.5 else "缩量" if ratio < 0.5 else "正常",
            "chart": {"labels": vds[-20:], "values": vls[-20:]}}
    else:
        result["volume"] = {"signal": "数据不足"}

    if hist_prices and len(hist_prices) >= 60:
        p60 = hist_prices[-60:]
        s1, s2 = round(sum(p60) / 60, 2), round(min(p60), 2)
        r1, r2 = round(sum(p60[-20:]) / 20, 2), round(max(p60), 2)
        to_s = round((cp - s2) / cp * 100, 1) if cp > 0 else 0
        to_r = round((r2 - cp) / cp * 100, 1) if cp > 0 else 0
        result["support"] = {"current": round(cp, 2), "support1": s1, "support2": s2,
            "resist1": r1, "resist2": r2, "to_support_pct": to_s, "to_resist_pct": to_r,
            "position": "靠近支撑" if to_s < 5 else "靠近阻力" if to_r < 5 else "中间区域"}
    else:
        result["support"] = {"position": "数据不足"}

    if hist_prices and hist_volumes and len(hist_prices) >= 10:
        pc = (hist_prices[-1] - hist_prices[-6]) / hist_prices[-6] if hist_prices[-6] > 0 else 0
        vc = (sum(hist_volumes[-5:]) - sum(hist_volumes[-10:-5])) / sum(
            hist_volumes[-10:-5]) if sum(hist_volumes[-10:-5]) > 0 else 0
        if pc > 0.02 and vc < -0.1:
            ds = "价升量缩——上涨动力减弱，注意回调"
        elif pc < -0.02 and vc > 0.1:
            ds = "价跌量增——有资金低位吸筹，关注反弹"
        elif pc > 0.02 and vc > 0.1:
            ds = "量价齐升——趋势健康"
        elif pc < -0.02 and vc < -0.1:
            ds = "量价齐跌——市场冷清"
        else:
            ds = "量价同步——无明显分歧"
        result["divergence"] = {"price_change_5d": f"{pc:+.1%}", "volume_change_5d": f"{vc:+.1%}", "signal": ds}

    # 事件复盘
    try:
        from ...data.baostock_utils import close_bs, open_bs
        bs = open_bs()
        if bs is not None:
            try:
                prefix = "sh" if symbol.startswith(("5", "6", "9")) else "sz"
                rs = bs.query_dividend_data(code=f"{prefix}.{symbol}",
                                            year=str(datetime.now().year - 1),
                                            yearType="report")
                data = rs.get_data() if hasattr(rs, 'get_data') else None
                if data is not None and not data.empty:
                    for _, row in data.iterrows():
                        dd, dc = row.get("dividPayDate", ""), row.get("dividCashPsBeforeTax", 0)
                        if dd and float(dc or 0) > 0:
                            result["events"].append(
                                {"type": "分红", "date": str(dd), "detail": f"每股{float(dc):.2f}元"})
            except Exception:
                pass
            finally:
                close_bs(bs)
    except Exception:
        pass
    return result


def _get_trader_advice(symbol: str, name: str, price_info: dict,
                       pe, pb) -> list[str]:
    """获取六位操盘手对一只股票的建议。"""
    from ...traders.registry import registry
    from ...traders.base import TraderState
    from ...traders.value_hunter import ValueHunter
    from ...traders.trend_follower import TrendFollower
    from ...traders.mean_reversion import MeanReversion
    from ...traders.dividend_collector import DividendCollector
    from ...traders.index_dca import IndexDca
    from ...traders.macro_hedger import MacroHedger

    for path, cls in [("value_hunter.ValueHunter", ValueHunter),
                      ("trend_follower.TrendFollower", TrendFollower),
                      ("mean_reversion.MeanReversion", MeanReversion),
                      ("dividend_collector.DividendCollector", DividendCollector),
                      ("index_dca.IndexDca", IndexDca),
                      ("macro_hedger.MacroHedger", MacroHedger)]:
        if path not in registry._traders:
            registry.register(path, cls)

    advisor_list = [
        (ValueHunter, "value_hunter.ValueHunter", "价值猎手"),
        (DividendCollector, "dividend_collector.DividendCollector", "红利收集者"),
        (IndexDca, "index_dca.IndexDca", "指数定投者"),
        (TrendFollower, "trend_follower.TrendFollower", "趋势跟随者"),
        (MeanReversion, "mean_reversion.MeanReversion", "均值回归者"),
        (MacroHedger, "macro_hedger.MacroHedger", "宏观对冲者"),
    ]

    advice = []
    if not price_info:
        return ["无法获取实时行情，无法分析"]

    for cls, path, tname in advisor_list:
        inst = registry.create(path, tname, 10000)
        if not inst:
            continue
        state = TraderState(name=tname, cash=10000, params=inst.params)
        try:
            ms = {symbol: MarketSnapshot(
                symbol=symbol, name=name, close=price_info["price"],
                open=price_info["open"], high=price_info["high"],
                low=price_info["low"], volume=0, change_pct=0, pe=pe, pb=pb)}
            orders = inst.decide(state, ms, datetime.now().strftime("%Y-%m-%d"))
            for o in orders:
                advice.append(f"{tname}: 建议{'买入' if o.action == 'buy' else '卖出'} "
                              f"{o.shares}股，理由：{o.reason}")
            if not orders:
                advice.append(f"{tname}: 当前无交易信号")
        except Exception:
            pass
    return advice
