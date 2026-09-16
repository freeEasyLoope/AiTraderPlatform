import src.traders.value_hunter as vh, src.traders.trend_follower as tf, src.traders.mean_reversion as mr
import src.traders.dividend_collector as dc, src.traders.index_dca as idc, src.traders.macro_hedger as mh
from src.engine.simulator import Simulator
from src.data.sina_client import SinaClient
from src.traders.registry import registry
from src.storage.repository import Repository
from src.config import load_settings
for cls,path in [(vh.ValueHunter,"value_hunter.ValueHunter"),(tf.TrendFollower,"trend_follower.TrendFollower"),(mr.MeanReversion,"mean_reversion.MeanReversion"),(dc.DividendCollector,"dividend_collector.DividendCollector"),(idc.IndexDca,"index_dca.IndexDca"),(mh.MacroHedger,"macro_hedger.MacroHedger")]:
    registry.register(path,cls)
r=Repository(load_settings()["database"]["path"])
sim=Simulator(r,SinaClient(),registry)
for d in ["2026-06-01","2026-06-02","2026-06-03","2026-06-04","2026-06-05","2026-06-08","2026-06-09","2026-06-10","2026-06-11","2026-06-12"]:
    res=sim.run_daily(d); t=sum(len(v) for v in res.values()); f=sum(sum(1 for o in v if o.status=="filled") for v in res.values())
    s2=r.get_snapshots(2,limit=1); mr_v=s2[0].total_value if s2 else 0
    print(f"{d}: {f}/{t} MR={mr_v:.2f}",flush=True)
import os; os.remove(__file__) if os.path.exists(__file__) else None
print("DONE",flush=True)
