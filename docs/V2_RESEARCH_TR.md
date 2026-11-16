# V2 — Kanıt zinciri ve erken birikim araştırması

## Birinci sürümden farkı
* V1 yalnızca spot best-bid/ask görüntüsüdür.
* V2 kamuya açık Binance, Bybit, OKX **en yeni işlem örneklerini** ve Binance tamamlanmış 1 dakikalık OHLCV ile taker-buy quote volume alanlarını toplar.
* Bybit spot endpoint en fazla 60 son işlem, OKX 100 ve Binance aggTrades 500 son toplulaştırılmış işlemdir. Bunlar kesintisiz CVD, emir defteri geçmişi veya sistematik spoofing tespiti değildir.
* Bir borsadaki ölçüm diğer borsanın kaynağı olarak etiketlenmez. Mum stratejisi Binance spot örneğidir, bağımsız çoklu borsa strateji onayı değildir.

## Sabit hipotez
Önceki 60 tamamlanmış 1m barın medyan hacmine göre son 10 bar medyan hacmi >=1.8, son 10 bar quote taker buy >=%56 ve 10m fiyat değişimi -%3 ila +%2.5: yalnızca accumulation_watch. Dağıtım adayı için hacim >=1.5, taker buy <=%38, 10m fiyat <=-%1. **Her ikisinde trade_allowed=false.** Eşikler varsayımsal hipotezlerdir, backtest kazananları değildir. Minimum 80 ve kesintisiz kapanmış bar; veri eksikse işlem yok.

## Prospektif gözlem
main'de Actions > Research V2 sampled tape and immutable evidence > Run workflow.
Varsayılan plan UTC her saatin 11 ve 41. dakikasıdır. GitHub zamanlaması gecikebilir/atlanabilir.
Gözlemler `paper/early-radar-v2` dalındaki `observations/scan.jsonl` içinde SHA-256 zinciriyle saklanır; yeni kayıt bir öncekinin hash'ini taşır. Git commitleri ek kontrol sağlar. Force-push veya yönetici değiştirmeleri karşısında bağımsız dış noter değildir.
Eksik tikler için veri üretilemez. GitHub token dal oluşturamaz veya push atamazsa workflow kırmızı olmalı, **persist edildi denemez**. Artifaktlar 30 günlük yedektir, kalıcı ana kaynak değildir.

## Bağımsız doğrulama şartı
Geriye dönük testlerin ardından ayrı tutulan en az 30/60/90 günlük gelecekteki (o anda gerçekten ilk kez görülen) gözlemler, doğru zamanlı etiketleme, likidite ve spread ile net işlem maliyeti testleri, random/momentum baseline ve rejim alt-kümeleri. Bu şartlar sağlanmadan paper NAV ve ekonomik alfa iddiası yok.

## Secrets
V2 kamuya açık spot veri akışları için hiçbir Secret gerekmez. Önceki `docs/API_KEYS_TR.md` dosyasındaki anahtarlar, sonraki bağımsız sağlayıcı adaptörleri açılıncaya kadar saklanabilir. Hiçbir secret değeri çıktı veya rapora yazılmaz.
