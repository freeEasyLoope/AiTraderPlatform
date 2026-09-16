import requests
import json
import time

# Try Yahoo Finance v8 API directly
url = "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=1d"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

results = {}

# 1. Chart API for quote
try:
    r = requests.get(url, headers=headers, timeout=10)
    if r.status_code == 200:
        data = r.json()
        chart = data.get("chart", {}).get("result", [{}])[0]
        meta = chart.get("meta", {})
        results["chart_api"] = {
            "price": meta.get("regularMarketPrice"),
            "previous_close": meta.get("chartPreviousClose"),
            "currency": meta.get("currency"),
            "exchange": meta.get("exchangeName"),
            "symbol": meta.get("symbol"),
        }
        print("CHART API OK:", results["chart_api"]["price"], results["chart_api"]["exchange"])
    else:
        results["chart_api"] = {"error": f"HTTP {r.status_code}"}
        print("CHART API FAIL:", r.status_code, r.text[:200])
except Exception as e:
    results["chart_api"] = {"error": str(e)}
    print("CHART API EXCEPTION:", str(e))

# 2. Quote Summary API for name/sector/industry
time.sleep(0.5)
url2 = "https://query1.finance.yahoo.com/v6/finance/quoteSummary/AAPL?modules=assetProfile,price,summaryDetail,defaultKeyStatistics"
try:
    r2 = requests.get(url2, headers=headers, timeout=10)
    if r2.status_code == 200:
        data2 = r2.json()
        result = data2.get("quoteSummary", {}).get("result", [{}])[0]

        # Price
        price_data = result.get("price", {})
        results["price"] = {
            "regularMarketPrice": price_data.get("regularMarketPrice", {}).get("raw"),
            "regularMarketOpen": price_data.get("regularMarketOpen", {}).get("raw"),
            "regularMarketDayHigh": price_data.get("regularMarketDayHigh", {}).get("raw"),
            "regularMarketDayLow": price_data.get("regularMarketDayLow", {}).get("raw"),
            "regularMarketVolume": price_data.get("regularMarketVolume", {}).get("raw"),
            "currency": price_data.get("currency"),
            "exchangeName": price_data.get("exchangeName"),
            "shortName": price_data.get("shortName"),
            "longName": price_data.get("longName"),
            "marketCap": price_data.get("marketCap", {}).get("raw"),
            "quoteType": price_data.get("quoteType"),
        }

        # Profile
        profile = result.get("assetProfile", {})
        results["profile"] = {
            "sector": profile.get("sector"),
            "industry": profile.get("industry"),
            "country": profile.get("country"),
            "state": profile.get("state"),
            "city": profile.get("city"),
            "website": profile.get("website"),
            "employees": profile.get("fullTimeEmployees"),
            "description": (profile.get("longBusinessSummary") or "")[:400],
        }

        # Key stats
        stats = result.get("defaultKeyStatistics", {})
        results["stats"] = {
            "beta": stats.get("beta", {}).get("raw"),
            "trailingPE": stats.get("trailingPE", {}).get("raw"),
            "forwardPE": stats.get("forwardPE", {}).get("raw"),
            "trailingEps": stats.get("trailingEps", {}).get("raw"),
            "52WeekHigh": stats.get("fiftyTwoWeekHigh", {}).get("raw"),
            "52WeekLow": stats.get("fiftyTwoWeekLow", {}).get("raw"),
            "dividendYield": stats.get("dividendYield", {}).get("raw"),
        }

        print("QUOTE API OK:", results["price"].get("longName"), results["price"].get("marketCap"))
    else:
        results["quote_summary"] = {"error": f"HTTP {r2.status_code}"}
        print("QUOTE API FAIL:", r2.status_code, r2.text[:200])
except Exception as e:
    results["quote_summary"] = {"error": str(e)}
    print("QUOTE API EXCEPTION:", str(e))

print("\n=== FULL RESULTS ===")
print(json.dumps(results, indent=2, default=str, ensure_ascii=False))
