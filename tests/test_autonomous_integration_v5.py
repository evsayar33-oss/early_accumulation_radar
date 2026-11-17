"""End-to-end, no-network V5 contract through real CSV serialization and research modules."""
import csv,hashlib,json,tempfile,unittest
from datetime import date,timedelta
from pathlib import Path
from research_v4.historical_real_data import FIELDS
from research_v4.data_quality import screen
from research_v4.multimarket_exploratory import load,study as exploratory
from research_v4.historical_discovery import discover,load_csv
from research_v4.new_hypotheses_bias import audit as new_hypotheses
from research_v4.regime_event_research import study as regimes
from research_v4.matched_benchmark import study as matched
from research_v4.secondary_source_audit import audit as independent_sources
from research_v4.prospective_evidence import update
from research_v4.research_governance import summarize

class IntegratedResearchContract(unittest.TestCase):
    def test_all_three_markets_from_csv_to_governance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            csv_path=root/"prices.csv"
            with csv_path.open("w",newline="",encoding="utf8") as f:
                writer=csv.writer(f)
                writer.writerow(FIELDS)
                for market in ("BIST","US","CRYPTO"):
                    for ticker in range(6):
                        symbol=("STK"+str(ticker) if market!="CRYPTO" else "ALT"+str(ticker)+"USDT")
                        for i in range(350):
                            d=date(2025,1,1)+timedelta(days=i)
                            price=10+.012*i+.15*ticker
                            event=(i%35==0 and i>100)
                            o=price
                            c=price+(.35 if event else .025)
                            h=max(o,c)+.08
                            l=min(o,c)-.08
                            writer.writerow([market,symbol,d.isoformat(),o,h,l,c,
                                8000 if event else 1000,"false","false"])
            source=json.dumps({"csv_sha256":hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                "asof_utc":"2025-12-20T03:47:00Z",
                "coverage":{m:{"requested":6,"usable":6} for m in ("BIST","US","CRYPTO")},
                "trade_authorized":False,"paper_approved":False})
            manifest=root/"manifest.json"
            manifest.write_text(source)
            qa=screen(csv_path,manifest,root/"qa")
            self.assertEqual(sum(x["screened"] for x in qa["coverage"].values()),18)
            screened=load(root/"qa/screened_prices.csv")
            basic=discover(load_csv(root/"qa/screened_prices.csv"))
            self.assertFalse(basic["paper_approved"])
            self.assertFalse(exploratory(screened)["paper_approved"])
            self.assertFalse(new_hypotheses(screened)["paper_approved"])
            self.assertFalse(regimes(screened)["paper_approved"])
            matched_clean=matched(screened)
            matched_raw=matched(load(csv_path))
            self.assertEqual(len(matched_clean["results"]),45)
            self.assertTrue(any(r["train"]["n"]>0 for r in matched_clean["results"]))
            self.assertFalse(matched_clean["paper_approved"])
            stub=lambda symbol:{b["date"].isoformat():b["close"]
                                  for (market,sym),bars in screened.items()
                                  if sym==symbol for b in bars}
            # Market-specific mocks: US and crypto have synthetic identical
            # independent references; this is an OFFLINE schema test only.
            audit=independent_sources(screened,get_stooq=stub,get_nasdaq=stub,
                get_bybit=stub,get_okx=stub,get_mexc=stub,limit=2)
            asof="2025-12-20T03:47:00+00:00"
            signals,settled,forward=update(screened,dict(screened),[],[],
                                          asof,"test-fixture-version","sha-fixture")
            self.assertFalse(forward["paper_approved"])
            self.assertEqual(forward["all_settlements"],0)
            decision=summarize(json.loads(source),qa,audit,matched_clean,forward,matched_raw)
            self.assertFalse(decision["profitable_strategy_independently_confirmed"])
            self.assertFalse(decision["trade_authorized"])
            self.assertFalse(decision["paper_approved"])

if __name__=="__main__":unittest.main()
