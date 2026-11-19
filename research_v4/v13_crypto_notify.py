"""Only evidence milestones; NEVER routine noise or investment instructions."""
import argparse,json,os
from pathlib import Path
from research_v4.v13_notify import deliver


def message(r):
    if r.get("schema")!="EAR.v13_crypto_costed_research.v1":
        raise ValueError("INVALID_CRYPTO_REPORT")
    lines=[]
    for x in r["new_frozen"]:
        lines.append(f"Yeni maliyet-sonrasi ARAŞTIRMA adayi: "
                     f"{x['direction']} {x['rule']} {x['horizon_minutes']}dk. "
                     "30 gun ileri veri testi basliyor.")
    for x in r["new_decisions"]:
        lines.append(f"Kripto sonraki-veri testi: {x['status']} "
                     f"{x['direction']} {x['rule']} "
                     f"{x['horizon_minutes']}dk.")
    if not lines:return None
    return ("EAR V13 KRIPTO | Modellemis PERP arastirmasi\n"+
            "\n".join(lines[:8])+
            "\nGercek emir/PnL, fonlama, likidasyon veya "
            "aracilik icrasi kanitlanmis degildir.")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--report",required=True)
    a=p.parse_args()
    r=json.loads(Path(a.report).read_text(encoding="utf8"))
    print(deliver(message(r),os.environ.get("TELEGRAM_BOT_TOKEN"),
                  os.environ.get("TELEGRAM_CHAT_ID")))


if __name__=="__main__":main()
