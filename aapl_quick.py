import yfinance as yf
import time

time.sleep(3)
t = yf.Ticker("AAPL")
try:
    info = t.info
    print("OK: got info, keys:", len(info) if info else 0)
    print("name:", info.get("longName") if info else "none")
    print("price:", info.get("currentPrice"))
    print("mc:", info.get("marketCap"))
    print("sector:", info.get("sector"))
    print("industry:", info.get("industry"))
    print("exch:", info.get("exchange"))
except Exception as e:
    print("ERROR:", str(e)[:200])
