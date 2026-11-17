"""V6 train-only selection must never use validation/holdout for family choice."""
import unittest
from research_v4.v6_selection import select_train_only

def leg(ret,trades=30,days=30):
    return {"closed_trades":trades,"days_in_market":days,
            "unclosed_positions":0,"max_drawdown_pct":-8,"net_return_pct":ret}
def sample(name,train,valid,hold):
    return {"market":"US","family":name,"train":leg(train),
        "validation":leg(valid),"previously_exposed_holdout":leg(hold)}

class SelectionIntegrityTests(unittest.TestCase):
    def test_rank_uses_only_training_data(self):
        data={"results":[sample("A",12,-5,-5),sample("B",10,100,100)]}
        r=select_train_only(data)
        us=next(x for x in r["results"] if x["market"]=="US")
        self.assertEqual(us["selected_family"],"A")
        self.assertEqual(us["status"],"OUT_OF_TRAIN_REJECT_OR_INSUFFICIENT")
        self.assertFalse(r["paper_approved"])
        self.assertFalse(r["profitable_strategy_confirmed"])
    def test_zero_trade_winner_is_rejected(self):
        a=sample("A",500,100,100)
        a["train"]["closed_trades"]=0
        us=next(x for x in select_train_only({"results":[a]})["results"]
                if x["market"]=="US")
        self.assertIsNone(us["selected_family"])
    def test_holdout_mutation_never_changes_selected_family(self):
        rows=[sample("A",5,-10,1),sample("B",4,20,100)]
        a=next(x for x in select_train_only({"results":rows})["results"] if x["market"]=="US")
        rows[1]["previously_exposed_holdout"]["net_return_pct"]=-999
        b=next(x for x in select_train_only({"results":rows})["results"] if x["market"]=="US")
        self.assertEqual(a["selected_family"],b["selected_family"])

if __name__=="__main__":unittest.main()
