import yfinance as yf
import json
import traceback

def validate_aapl():
    results = {}

    # Phase 1.1: Validate symbol
    ticker = yf.Ticker("AAPL")
    try:
        info = ticker.info
        if not info or (isinstance(info, dict) and len(info) == 0):
            results["symbol_valid"] = False
            results["symbol_error"] = "Empty info returned"
        elif isinstance(info, dict) and info.get("traderPcwName"):
            results["symbol_valid"] = False
            results["symbol_error"] = "Invalid symbol: " + str(info.get("traderPcwName"))
        else:
            results["symbol_valid"] = True
    except Exception as e:
        results["symbol_valid"] = False
        results["symbol_error"] = str(e)

    if not results["symbol_valid"]:
        results["verification_status"] = "FAILED_INVALID_SYMBOL"
        return results

    # Phase 1.2: Quote data
    results["quote"] = {
        "current_price": info.get("currentPrice"),
        "previous_close": info.get("previousClose"),
        "open": info.get("open"),
        "day_high": info.get("dayHigh"),
        "day_low": info.get("dayLow"),
        "volume": info.get("volume"),
        "avg_volume": info.get("averageVolume"),
        "52w_high": info.get("fiftyTwoWeekHigh"),
        "52w_low": info.get("fiftyTwoWeekLow"),
        "market_cap": info.get("marketCap"),
        "beta": info.get("beta"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "eps": info.get("trailingEps"),
    }

    # Phase 1.3: Company Profile
    results["profile"] = {
        "company_name": info.get("longName"),
        "short_name": info.get("shortName"),
        "exchange": info.get("exchange"),
        "currency": info.get("currency"),
        "quote_type": info.get("quoteType"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "business_summary": (info.get("longBusinessSummary") or "")[:500],
        "country": info.get("country"),
        "state": info.get("state"),
        "city": info.get("city"),
        "website": info.get("website"),
        "employees": info.get("fullTimeEmployees"),
        "founded": info.get("yearFounded") or info.get("firstTradeDate"),
    }

    # Phase 1.5: Key financial ratios
    results["financials"] = {
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),
        "profit_margin": info.get("profitMargins"),
        "roe": info.get("returnOnEquity"),
        "roa": info.get("returnOnAssets"),
        "debt_to_equity": info.get("debtToEquity"),
        "current_ratio": info.get("currentRatio"),
        "dividend_yield": info.get("dividendYield"),
        "payout_ratio": info.get("payoutRatio"),
    }

    # Phase 1.4: Recent news
    try:
        news_data = ticker.news
        news_items = []
        for n in (news_data or [])[:5]:
            news_items.append({
                "title": n.get("title"),
                "publisher": n.get("publisher"),
                "link": n.get("link"),
                "providerPublishTime": n.get("providerPublishTime"),
            })
        results["news"] = news_items
        results["data_sources"] = results.get("data_sources", {})
        results["data_sources"]["yfinance_news"] = len(news_items) > 0
    except Exception as e:
        results["news"] = []
        results["data_sources"]["yfinance_news"] = False
        results["news_error"] = str(e)

    # Build data source status
    results["data_sources"] = {
        "yfinance_basic": True,
        "yfinance_quote": results["quote"]["current_price"] is not None,
        "yfinance_profile": bool(results["profile"]["company_name"]),
        "yfinance_news": results.get("data_sources", {}).get("yfinance_news", False),
        "yfinance_financials": any(v is not None for v in results["financials"].values()),
    }

    results["verification_status"] = "PASSED"
    return results

try:
    data = validate_aapl()
    print(json.dumps(data, indent=2, default=str, ensure_ascii=False))
except Exception as e:
    print(json.dumps({
        "verification_status": "FAILED_DATA_UNAVAILABLE",
        "error": str(e),
        "traceback": traceback.format_exc()
    }, indent=2))
