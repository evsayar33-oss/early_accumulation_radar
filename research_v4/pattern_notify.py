"""Send only durable V11 discovery/closed-holdout decisions, never scan noise."""
import argparse,json,os
from pathlib import Path
from research_v4.perp_notify import send

def format_message(report):
    if report.get("schema")!="EAR.v11_automatic_pattern_discovery.v1":
        raise ValueError("INVALID_V11_REPORT")
    notices=report.get("notices",[])
    if not notices:return None
    lines=["🧪 EAR V11 — OTONOM ÖRÜNTÜ ARAŞTIRMASI"]
    for item in notices[:4]:
        dir_tr="YÜKSELİŞ" if item["direction"]=="UPSIDE_EXTREME" else "DÜŞÜŞ"
        rule=item["rule"]
        if item["kind"]=="NEW_RESEARCH_CANDIDATE":
            lines.append(f"YENİ ORTAKLIK ADAYI | {dir_tr} | {rule}")
            lines.append(f"Keşif örneği: {item['n']} olay, FDR q={item['q']:.4g}.")
            lines.append("Bağımsız 7 günlük ileri test ŞİMDİ BAŞLAYACAK. Henüz doğrulanmadı.")
        else:
            status=item["status"]
            outcome=("İLERİ VERİDE TEKRARLANDI — YALNIZ İSTATİSTİKSEL İLİŞKİ"
                if status=="PROSPECTIVE_ASSOCIATION_REPLICATED_NOT_TRADING_ALPHA"
                else "İLERİ VERİDE DOĞRULANMADI VEYA KANIT YETERSİZ")
            lines.append(f"{outcome} | {dir_tr} | {rule}")
            lines.append(f"Yedi günlük test: {item['n']} olay, FDR q={item['q']:.4g}.")
    lines.append("Nedensellik veya maliyet sonrası kâr kanıtı değildir. AL/SAT, PAPER ya da gerçek emir yok.")
    return "\n".join(lines)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--report",required=True)
    args=p.parse_args()
    report=json.loads(Path(args.report).read_text(encoding="utf8"))
    print(send(format_message(report),
       os.environ.get("TELEGRAM_BOT_TOKEN",""),
       os.environ.get("TELEGRAM_CHAT_ID","")))

if __name__=="__main__":main()
