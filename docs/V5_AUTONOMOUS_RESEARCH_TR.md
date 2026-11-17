# V5 — Tek PR ile otomatik, üç piyasalı araştırma ve ileriye dönük kanıt

## Kurulum: yalnızca PR merge

Bu PR merge edildiğinde yeni `V5 Autonomous three-market research and prospective evidence (NO TRADING)` iş akışı `main` dalına yapılan bu workflow-dosyası eklemesiyle **kendiliğinden bir kez başlar**. Sonrasında **Salı–Cumartesi 03:47 UTC** (Türkiye 06:47; KKTC kış saatinde 05:47) çalışır. `workflow_dispatch` yalnızca manuel yeniden başlatma seçeneğidir, her seferinde gerekli değildir. GitHub zamanlayıcısı yoğunluk nedeniyle zaman zaman geç çalışabilir veya çalışmayı atlayabilir; her gerçekleşmiş çalışmanın durumu GitHub Actions üzerinde görülebilir. Süre sınırı 58 dakikadır.

Ana üretim, Telegram, PAPER ve orijinal araştırma iş akışları değiştirilmez. Orijinal `expanded_historical_discovery.yml` manuel olarak kullanılabilir ama rutin kullanımda gerekmez.

## Modüller / bağımsız veri kanıtı

1. Mevcut 36 BIST KAP güncel şirket listesi, 36 ABD güncel 10–500 milyon USD piyasa değeri taraması ve 48 Binance üzerinden işlem gören (CoinGecko güncel piyasa değerine göre 10–500 milyon USD) altcoin örneği; bunlar **hedef üst sınırlardır**. Tamamı mevcut aktif varlıklardır.
2. Beş yıllık gerçek Yahoo ve Binance fiyat verisi, özgün `prices.csv` ve SHA-256 manifest. Veri getirilmezse pozitif sonuç uydurulmaz.
3. `data_quality`: kaynak SHA doğrulaması, aşırı açık/önceki kapanış oranı ve uzun sıfır hacim/sıra dışı gün gibi serilerin işaretlenip karantinaya alınması. **Hiçbir hissede split/dividend otomatik onarılmaz**; karantina da başka bir seçim yanlılığı oluşturabilir. Ham veri saklanır.
4. `secondary_source_audit`: ABD Stooq → Nasdaq halka açık tarihsel işlem verileri; kripto Bybit spot → OKX spot (UTC gün) → MEXC spot; yasak/429/403 durumunda sağlayıcı devre kesicisi. BIST ve ABD'de yalnızca **güncel kotasyon snapshot** karşılaştırması için TradingView; bu tarihsel OHLC doğrulaması değildir. Tarih, kotasyon ve kurumsal işlem ayarları farklı olabilir; karşılaştırma onayı/PIT kaydı doğurmaz.
5. Eski temel aileler, 6 V2 ailesi, 3 V3 ve 3 V4 hipotezi (toplam **15 × 3 = 45** piyasa/aile analizi); giriş sonrası 5 bar, artan maliyet ve gecikme stresleri, 60/20/20 zaman kırılımı.
6. `matched_benchmark`: her olay için **aynı giriş ve çıkış tarihlerinde**, sinyal varlığı hariç güncel evrendeki en az 5 eşzamanlı varlığın komisyonsuz eşit ağırlıklı getirisine karşı net aşırı getiri. Kazanan tek hisse çıkarıldığında sonuç ne olur kontrolü. Bu eşleştirilmiş mevcut-survivor örneklemi de PIT değildir ve portföy NAV sayılmaz.
7. `prospective_evidence`: çalışma zamanı sonrası yeni sinyali kaynak SHA ve strateji-kod SHA ile ayrı günlüğe ekler. Sinyali **ilk kaydettiği UTC takvim gününden sonraki bir günün açılışından önce** getiri başlatmaz; 5 kapanmış gelecek bar olmadan sonucu biliniyor saymaz. BIST/ABD/kripto aynı ihtiyatlı kuralı uygular. Satışı gün sonu fiyatından ölçer; gerçek emir/fill yoktur. Sinyal evrenden çıkarılmışsa eski sembolü bir defaya mahsus veri sağlayıcıdan geri getirmeyi dener, aksi takdirde **SOURCE_SYMBOL_MISSING** olarak sonuçsuz bırakır (sessizce dışlamaz).
8. `research_governance`: kaynak erişimi, karantina, doğrulama eksikleri, mevcut tarihsel testler ve ilk defa oluşmuş ileriye dönük sonuçları kısa ve açık özetler. **Trade, PAPER, kârlılık onayı ASLA otomatik verilmez.**

## Saklama / otomasyon

- Her çalışmanın ham CSV, manifest, kalite, kaynak hata matrisi, 45 aday araştırması, prospective snapshot ve governance dosyaları `v5-autonomous-research-<run_id>` Actions artifact'ına yazılır (90 gün, GitHub yönetim politikalarına tabi).
- Sinyaller, ilk ölçülen gelecek sonuçları, en son karar ve her iş akışının küçük JSON özeti yalnızca **`research/auto-evidence` adlı ayrı Git dalına** versiyon kontrollü yazılır. Kod ve üretim `main` dalı değiştirilmez. `research_archive/runs/<run_id>.json` çalışma kayıtları, `research_archive/prospective/signals.jsonl` ve `settlements.jsonl` takip için kullanılır.
- Önceki kayıtların `record_digest` SHA-256 kontrolü başarısızsa çalışma **bilerek hata verir**; bunlar Git commit geçmişiyle incelenebilir. Bu yapı GitHub admin'ine karşı matematiksel değişmezlik sunmaz; otomatik işlemlerde basit oynama/bozulma tespitidir.
- Yetki yalnızca bu iş akışında `contents: write` olarak istenir; kayıt dalı dışına push yapılmaz. Yine de GitHub repo / organizasyon `GITHUB_TOKEN` izinleri engelliyorsa bu saklama adımı hata verir. Önce artifact yüklenir; veri kaybı yaşandığı ileri sürülmez.
- Tüm sürümlerde ölçülebilir pozitif tarihsel sonuçlar bile canlı kârlılık kanıtı değildir. İleriye dönük veri birikiminin anlamlı karar oluşturması için yeterli örnek, kaynak tutarlılığı, çoklu hipotez düzeltmesi, portföy NAV ve bağımsız maliyet/fill doğrulaması daha sonra gerekir.

## Değiştirilmeyen kritik sınırlamalar

**Sürvivorship bias çözülmedi:** tarihte delist edilmiş hisse/coinler, geçmiş piyasa değerleri, geçmiş halka açıklık ve as-of üyelik kesin biçimde yok. Yahoo/Stooq/Nasdaq hisse fiyatlarında kurumsal işlem fiyat düzeltme politikaları uyumlu olmayabilir. KAP'dan gelen BIST örneklemi küçük sermaye olarak doğrulanmış değildir. 45 hipotezin önceki holdout verileri zaten açılmıştır; yalnızca yeni sinyaller ve yeni tarihli gözlemler ileriye dönük kabul edilir. Fiyat/açılış üzerinden hesaplanan sonuçlar gerçek likidite, kayma, piyasa etkisi veya işlem emri doldurma kanıtı değildir.

## Bir problem olduğunda

Actions içinde `V5 Autonomous three-market research and prospective evidence (NO TRADING)` çalışma özeti ve artifact'a bakın. Kırmızı hata hangi adımda oluştuysa ayrı ele alınmalıdır; kaynak uyarısı bir kâr işareti değildir. Günlük otomatik araştırma tekrarı için hiçbir `Run workflow` eylemi gerekli değildir. Rutin takip mevcut bağımsız izleme otomasyonlarıyla yapılabilir; bu PR ekstra bildirim/Telegram spam'i oluşturmaz.
