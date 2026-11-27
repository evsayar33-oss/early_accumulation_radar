"""Only independently replicated discoveries and strong new research observations.
State is preserved before delivery; durable receipts prevent routine messages.
"""
from __future__ import annotations
import argparse,json,os
from pathlib import Path
from research_v4.v13_notify import deliver

def events(report):
    entries=[]
    for d in report["new_decisions"]:
        if d["status"]=="FORWARD_REPLICATED_RESEARCH_ONLY":
            r=d.get("rule",{})
            entries.append(("decision:"+d["lock_id"],f"Bağımsız ileri test doğrulandı · {r.get('market','')} · {r.get('direction','')}"))
    for s in report["new_shadows"]:
        entries.append(("shadow:"+s["lock_id"],f"Koşullu sanal izleme · {s['rule']['market']} · 90 gün (fiyat işaretlemesi)"))
    for a in report.get("new_alerts",[]):
        entries.append(("alert:"+a["id"],f"{a['market']} · {a['symbol']} · {'YÜKSELİŞ' if a['direction']=='UP' else 'DÜŞÜŞ'} ÖNCÜ OLAY ARAŞTIRMASI"))
    return entries

def format_lines(lines):
    if not lines:return None
    return "EAR V18 | YENİ ARAŞTIRMA KANITI\n"+"\n".join(lines)+"\nGerçek emir, kesin kazanç veya Superlab ACCEPT değildir."

def message(report):
    if report.get("schema")!="EAR.adaptive.v18.1":raise ValueError("V18_REPORT_SCHEMA")
    return format_lines([text for _,text in events(report)])

def main():
    p=argparse.ArgumentParser();p.add_argument("--report",required=True)
    p.add_argument("--ledger");p.add_argument("--receipts");a=p.parse_args()
    current=json.loads(Path(a.report).read_text())
    if not a.ledger or not a.receipts:
        print(deliver(message(current),os.environ.get("TELEGRAM_BOT_TOKEN"),os.environ.get("TELEGRAM_CHAT_ID")));return
    from research_v4.v18_adaptive import read_state,DAY
    ledger=read_state(a.ledger)
    path=Path(a.receipts)
    delivered=json.loads(path.read_text()) if path.exists() else {}
    queue=[]
    for b in ledger:
        r={"new_decisions":b["decisions"],"new_shadows":b.get("shadows",[]),
           "new_alerts":[x for x in b.get("alerts",[]) if ledger[-1]["observed_ms"]-x["seen"]<=DAY]}
        queue.extend((key,txt) for key,txt in events(r) if key not in delivered)
    queue=list(dict(queue).items())[:8]
    status=deliver(format_lines([v for _,v in queue]),os.environ.get("TELEGRAM_BOT_TOKEN"),os.environ.get("TELEGRAM_CHAT_ID"))
    print(status)
    if status=="ALPHA_RESEARCH_MILESTONE_DELIVERED":
        delivered.update({k:ledger[-1]["observed_ms"] for k,_ in queue})
        tmp=path.with_suffix(".tmp");tmp.write_text(json.dumps(delivered,sort_keys=True,indent=2)+"\n");tmp.replace(path)

if __name__=="__main__":main()
