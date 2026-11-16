# V2 kaynak bütünlüğü ve alarm denetimi

## Kaynak ayrımı
Binance ve OKX: başarıyla gözlenen halka açık spot işlem örnekleri. Gate spot trades: taker taraflı ek bağımsız kaynak; bağlantı başarısı canlı smoke ile denetlenir. Bybit: resmi API, fakat GitHub çalıştırıcı IP'lerinde 403 erişim kısıtı olabilir; bunun için proxy/konum atlatma yapılmaz. Erişilemiyorsa ayrı kaydedilir, Gate verisi Bybit adı altında gösterilmez.

BTC/USD (Kraken/Coinbase) ve BTC/USDT (Binance/OKX/Bitget/Gate/Bybit) farklı kotasyon para birimleridir. USD çiftleri gözlemde yer alır ancak USDT kotasyonlarıyla likidite uzlaşması hesabına katılmaz. Bu değişim eski SHA zincirli gözlemleri geri dönük değiştirmez.

## Kanıt zinciri
`paper/early-radar-v2/observations/scan.jsonl` orijinal tek/genişleyen SHA-256 zincirini korur. `radar.audit` her satırın sha256 ve prev_sha256 bağlantısını, zaman artışını, BTC/ETH/SOL son kapanmış mum tazeliğini, çoklu USDT spot kotasyon durumunu ve 2 saatlik veri tazelik sınırını denetler. 45 dakikayı aşan iki gözlem arasındaki boşluklar gerçek kayıt aralığı olarak listelenir. Yaklaşık kaç adet 30 dakikalık planlanmış gözlem atlandığı tahmin edilebilir ama GitHub cron'unun kesin icrasına dair kanıt sayılmaz. Geçmiş kayıt yeniden oluşturulmaz; değişmiş veya eksik kayıt durumunda workflow kırmızı olur.

`Independent V2 evidence and freshness audit` saatte bir GitHub Actions üzerinden salt okunur denetim yapar; main veya state dalına yazmaz.

## Telegram
`TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` varsa her V2 çalışmasında getMe/getChat ile doğrulanır. Merge sonrasında ilk `push` çalışması ayrıca bir adet **bağlantı testi** mesajı yollar ve Telegram API'nin mesajı kabul ettiğini doğrular. Bu, kullanıcının mesajı açtığına dair kanıt değildir. Boş veya tek eksik Secret durumlarında `NOT_CONFIGURED` ya da `TELEGRAM_SECRETS_INCOMPLETE` çıktısı oluşturulur. Konfigürasyon eksikse gerçek Telegram gönderim başarısı iddia edilmez. Secrets çıktı/log'a basılmaz.

Yeni kaynaklar, eşikler ve alarmlar halen yalnızca araştırma amaçlıdır. Gerçek emir, paper NAV, kârlılık beyanı veya manipülatör kimliği çıkarımı yoktur.

## Kurulum
PR CI ve canlı kaynak smoke yeşil olursa main'e merge edilir. Main push V2'yi zaten otomatik başlatır. İlk run'da kaydın eklendiğini, SHA zincirinin doğrulandığını ve Telegram test sonucunu Actions adımlarından kontrol et. Ayrıca bu PR'ın bağımsız denetim workflow'u ilk saatlik zamanlama veya manuel çalıştırmayla devreye girer.
