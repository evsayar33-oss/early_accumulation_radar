# API kaydı ve GitHub Actions Secrets

## İlk sürüm
**V1 halka açık spot kaynakları anahtar istemez.** Binance, OKX, Bybit, Bitget, Gate, Kraken ve Coinbase top-of-book gözlem adaptörleri Secrets olmadan test edilir. Bazı bölgelerde ağ erişimi/yanıt yapısı değişebilir. Başarısız kaynak sıfır veri olarak rapor edilir; başka borsanın verisi o borsanın gözlemiymiş gibi yazılmaz.

## İleriki entegrasyonlar için önerilen Secret isimleri
| Kaynak | Kayıt | Secret | Durum |
|---|---|---|---|
| CoinGecko Demo | https://www.coingecko.com/en/api/pricing | COINGECKO_DEMO_API_KEY | Yalnızca rezerv, V1 kullanmıyor |
| Helius | https://dashboard.helius.dev/ | HELIUS_API_KEY | Yalnızca rezerv, V1 kullanmıyor |
| FMP | https://site.financialmodelingprep.com/developer/docs | FMP_API_KEY | Yalnızca rezerv, V1 kullanmıyor |
| Alpaca | https://app.alpaca.markets/signup | ALPACA_API_KEY ve ALPACA_API_SECRET | Yalnızca rezerv, V1 kullanmıyor |
| MKK KAP | https://apiportal.mkk.com.tr/ | MKK_API_KEY | Yalnızca rezerv, V1 kullanmıyor |
| Telegram | https://t.me/BotFather | TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID | Yalnızca rezerv, V1 kullanmıyor |

GitHub: Repo > Settings > Secrets and variables > Actions > New repository secret.
**Hiçbir anahtarı issue, commit, PR, chat veya log'a yazmayın.** Ücretli plan seçmeyin. Yukarıdaki adların hepsi V1 için isteğe bağlıdır; kullanımı doğrulanmadığı sürece eklenmiş secret aktif entegrasyon anlamına gelmez.

## V1 kapsamı ve sınırlar
Sistem gerçek emir vermez, giriş/çıkış sinyali üretmez, yalnızca gözlem yapar.
Mevcut top-of-book snapshot birikimi, CVD, spoofing veya manipülatör tespiti değildir.
Sürekli WebSocket yoktur; GitHub Actions zamanlayıcısı dakikayı garanti etmez.
Geriye dönük test, kalıcı prospektif NAV ve ücretli kaynak entegrasyonu sonraki denetimli sürüme aittir.
