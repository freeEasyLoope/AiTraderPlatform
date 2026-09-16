"""新闻/公告获取客户端 — 多源降级策略。

数据源优先级:
1. 新浪财经个股新闻（免费、无注册）
2. baostock 公告查询（分红、业绩预告等）
3. 本地缓存降级
"""

from __future__ import annotations

import io
import logging
import re
import sys
from datetime import datetime, timedelta
from urllib.request import Request as UReq, urlopen

logger = logging.getLogger(__name__)

# 内存缓存（按 symbol+date 缓存 15 分钟）
_news_cache: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 900  # 15分钟


def get_stock_news(symbol: str, days: int = 3) -> list[dict]:
    """获取个股近期新闻/公告。

    Returns:
        [{title, url, source, date, type: "新闻"|"公告"|"分红"|"业绩预告"}, ...]
    """
    # 检查缓存
    today = datetime.now().strftime("%Y-%m-%d")
    cache_key = f"{symbol}_{today}"
    if cache_key in _news_cache:
        ts, data = _news_cache[cache_key]
        if (datetime.now().timestamp() - ts) < _CACHE_TTL:
            return data

    news = []

    # 源1: 新浪财经新闻
    sina_news = _fetch_sina_news(symbol)
    news.extend(sina_news)

    # 源2: baostock 公告（分红、业绩预告）
    baostock_news = _fetch_baostock_announcements(symbol)
    news.extend(baostock_news)

    # 过滤最近 N 天
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    news = [n for n in news if n.get("date", "") >= cutoff]

    # 按日期排序
    news.sort(key=lambda x: x.get("date", ""), reverse=True)

    # 缓存
    _news_cache[cache_key] = (datetime.now().timestamp(), news)
    return news


def get_price_move_news(symbol: str, change_pct: float) -> list[dict]:
    """根据涨跌幅智能关联新闻。

    Args:
        symbol: 股票代码
        change_pct: 当日涨跌幅（如 0.05 = +5%, -0.03 = -3%）

    Returns:
        关联新闻列表 + 智能解读
    """
    news = get_stock_news(symbol, days=5)

    # 标注相关性
    for n in news:
        n["correlation"] = _assess_correlation(n, change_pct)

    return news


def _assess_correlation(news_item: dict, change_pct: float) -> str:
    """评估新闻和价格变动的关联度。"""
    title = news_item.get("title", "")
    ntype = news_item.get("type", "")

    # 强相关关键词
    strong_keywords = ["业绩", "预增", "预减", "亏损", "重组", "停牌", "立案",
                       "减持", "增持", "分红", "送转", "回购", "中标", "订单"]
    weak_keywords = ["调研", "评级", "目标价", "研报", "互动"]

    if ntype == "业绩预告":
        if change_pct > 0.02 and any(k in title for k in ["预增", "大幅增长"]):
            return "强相关——业绩预增推动上涨"
        if change_pct < -0.02 and any(k in title for k in ["预减", "亏损"]):
            return "强相关——业绩预警导致下跌"
        return "弱相关——业绩与股价变动方向不一致"

    if ntype == "分红":
        if change_pct > 0:
            return "弱相关——分红方案可能提振情绪"
        return "弱相关"

    for kw in strong_keywords:
        if kw in title:
            if change_pct > 0.03:
                return f"可能相关——利好消息({kw})"
            elif change_pct < -0.03:
                return f"可能相关——利空消息({kw})"
            return f"中性——消息({kw})未显著影响股价"

    for kw in weak_keywords:
        if kw in title:
            return "弱相关——常规信息"

    return "无显著关联"


def _fetch_sina_news(symbol: str) -> list[dict]:
    """从新浪财经获取个股新闻。"""
    news = []
    try:
        prefix = "sh" if symbol.startswith(("5", "6", "9", "68")) else "sz"
        url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllNewsStock/symbol/{prefix}{symbol}.phtml"
        req = UReq(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("gb2312", errors="replace")

        # 简单解析新闻标题和日期
        # 新浪新闻页面结构：<a target=_blank href='...'>标题</a> <span>日期</span>
        pattern = r"<a[^>]*href='([^']*sina[^']*)'[^>]*>([^<]+)</a>.*?(\\d{4}-\\d{2}-\\d{2})"
        matches = re.findall(pattern, raw)
        for href, title, date_str in matches[:10]:
            title = title.strip()
            if title and len(title) > 4:
                news.append({
                    "title": title,
                    "url": href if href.startswith("http") else f"https:{href}",
                    "source": "新浪财经",
                    "date": date_str.strip(),
                    "type": "公告" if any(k in title for k in ["公告", "报告", "年报", "季报"]) else "新闻",
                })
    except Exception as e:
        logger.debug(f"新浪新闻获取失败 {symbol}: {e}")

    return news


def _fetch_baostock_announcements(symbol: str) -> list[dict]:
    """从 baostock 获取分红和业绩预告信息。"""
    news = []
    try:
        import baostock as bs

        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            lg = bs.login()
        finally:
            sys.stdout = old
        if lg.error_code != "0":
            return news

        try:
            prefix = "sh" if symbol.startswith(("5", "6", "9", "68")) else "sz"
            bs_code = f"{prefix}.{symbol}"

            current_year = datetime.now().year

            # 1. 分红数据
            for year in range(current_year - 2, current_year + 1):
                try:
                    old, sys.stdout = sys.stdout, io.StringIO()
                    rs = bs.query_dividend_data(code=bs_code, year=str(year), yearType="report")
                    sys.stdout = old
                    data = rs.get_data() if hasattr(rs, 'get_data') else None
                    if data is not None and not data.empty:
                        for _, row in data.iterrows():
                            plan = str(row.get("planExplain", ""))
                            pay_date = str(row.get("dividPayDate", ""))
                            cash = float(row.get("dividCashPsBeforeTax", 0) or 0)
                            if plan and cash > 0:
                                news.append({
                                    "title": f"分红方案: {plan}（每股¥{cash:.2f}）",
                                    "url": "",
                                    "source": "baostock",
                                    "date": pay_date if pay_date else f"{year}-12-31",
                                    "type": "分红",
                                })
                except Exception:
                    continue

            # 2. 业绩预告
            try:
                old, sys.stdout = sys.stdout, io.StringIO()
                rs = bs.query_performance_express_report(code=bs_code, startDate=f"{current_year - 2}-01-01")
                sys.stdout = old
                data = rs.get_data() if hasattr(rs, 'get_data') else None
                if data is not None and not data.empty:
                    for _, row in data.iterrows():
                        pub_date = str(row.get("performanceExpressPublishDate", ""))
                        if pub_date:
                            news.append({
                                "title": f"业绩快报: {row.get('performanceExpressTotalAsset', '')}",
                                "url": "",
                                "source": "baostock",
                                "date": pub_date,
                                "type": "业绩预告",
                            })
            except Exception:
                pass

        finally:
            old, sys.stdout = sys.stdout, io.StringIO()
            bs.logout()
            sys.stdout = old
    except Exception as e:
        logger.debug(f"baostock 公告查询失败 {symbol}: {e}")

    return news
