# V4 — BIST + ABD Small-Cap Ücretsiz Veri Kanalları (Research Only)

Bu hattın amacı erken birikim araştırması için **önce veri kaynağını ve tarihsel doğruluğu test etmektir**. BTC/ETH/SOL'dan elde edilen V3 kâr/zarar sonuçları BIST ve küçük ölçekli ABD hisselerinin strateji kanıtı değildir.

## Çalışan kaynaklar ve kapsam

| Piyasa | Kaynak / bağlantı | Erişim | Sağladığı | Doğrulayamadığı |
|---|---|---|---|---|
| BIST | KAP halka açık BIST şirketleri: https://kap.org.tr/tr/bist-sirketler | Anahtarsız HTML, şema değişebilir | Güncel şirket/kod keşfi | Geçmişteki evren, gerçek free-float, doğrudan günlük OHLCV |
| BIST | Yahoo Finance v8 chart `THYAO.IS` | Anahtarsız, **resmî BIST API değil**, 429/engellenme olabilir | Sınırlı son 3 aylık günlük fiyat/hacim | Seviye-2 derinlik, doğrulanmış düzeltmeler ve kapsam |
| BIST | DataCedar v3 `bist:<symbol>/bars` | Opsiyonel ücretsiz Explorer key; `DATACEDAR_API_KEY` secret | Bağımsız **raw** günlük bar denemesi | Hisse geriye dönük seçildiği dönemdeki float/ownership, tam kapsama garantisi |
| ABD | Nasdaq public web screener https://api.nasdaq.com/api/screener/stocks | Anahtarsız ama **resmen desteklenmeyen** web endpoint | Cari sembol, fiyat, son hacim, yaklaşık piyasa değeri | Dönemsel geçmiş, float, dark-pool ve derinlik |
| ABD | SEC EDGAR https://www.sec.gov/files/company_tickers_exchange.json, https://data.sec.gov/api/xbrl/companyfacts/ | **Ücretsiz, API anahtarı yok**; tanımlayıcı User-Agent gerektirir | CIK eşleşmesi; *filing date* ile kamuya açıklanmış public-float parasal değeri (USD) ve pay sayısı (varsa) | **Yüzde halka açıklık, sahiplik yoğunluğu veya hisse bazlı float** otomatik doğrulanamaz |
| ABD | Yahoo chart `TICKER` | Anahtarsız ve resmî olmayan fiyat kaynağı; 429 olabilir | Son 3 aylık fiyat/hacim örnekleri | Geçmişteki gerçek universe ve işlemlerin PIT maliyetleri |

Kullandığımız ek/az bilinen seçenek **DataCedar v3** (ücretsiz Explorer anahtarı) ikincil BIST veri denetimidir. `bist-api.com` açık kaynak topluluk projesi de incelendi fakat JWT/kayıt ve hizmet güvenilirliği ayrıca doğrulanmadan otomatik üretim hattına sokulmadı. KAP'ın resmî site sayfaları halka açık olsa bile kurumsal REST hizmeti veya BIST lisanslı anlık veri ücretsiz olduğu anlamına gelmez.

**Kaynaklar:**
- SEC: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC adil erişim: https://www.sec.gov/about/webmaster-frequently-asked-questions
- DataCedar: https://datacedar.com/docs
- KAP: https://kap.org.tr/tr/bist-sirketler
- Nasdaq web API teknik açıklaması: https://github.com/oscraters/nasdaq-public-api-skill/blob/main/references/api_docs.md

## Kapsam ve eşikler

- ABD Nasdaq/AMEX/NYSE ilk 1000 satır **her borsa için sadece örneklem**; şu an market cap 10–500 milyon USD, fiyat 0.25–50 USD, son günlük hacim >=25.000 lot koşullarını sağlayan en fazla 6 sembol (kâr kriteri değil).
- BIST KAP kodlarından 6 sabit tanılama sembolünün eşleşmesi kullanılır; KAP başarısızsa seed kodları yalnız test amacıyla denenir. **Bu liste düşük float/kapitilizasyon örneklemi olduğu iddiasını taşımaz.**
- Güncel fiyat serileri yalnızca **son 3 ay** ile sınırlı test veri örnekleridir. Günlük barlarda split/temettü uyarlama doğrulanmış değildir.
- SEC `dei.EntityPublicFloat` varsa **raporlanan USD toplamı** tutulur, `free_float_percent` *asla* çıkarılmaz. `filed <= observation_date` ve `end <= observation_date` koşulu kullanılır.
- BIST optional DataCedar raw series ile Yahoo günlük kapanış farkı, ortak günlerde >%2 ise otomatik kalite engeli oluşturur. **Kaynak çatışmasında bir kaynağı doğru saymaz.**
- Her borsa kaynak kesintisini kendi raporlar. Hata durumunda geçmiş veri veya float uydurulmaz.

## Actions ve kanıt kayıtları

`V4 BIST US free data and PIT gate (no trades)` Actions, merge sonrası otomatik, ardından **hafta içi UTC 23:19** çalışır ve `workflow_dispatch` ile manuel başlatılabilir. Sonuçlar `out/v4_equities/bist.json`, `us.json`, `out/v4_equity_audit/decision.json` ve `report.md` halinde 90 gün Actions artifact olarak kaydedilir.

İlk-görülen ölçüm özeti SHA256 zinciriyle **ayrı** `research/v4-equity-evidence` dalında `observations/v4_equities/ledger.jsonl` dosyasına *append-only* kaydedilir. Aynı timestamp veya kırık SHA zinciri fail-closed'dur. Eski V2/V3/PAPER dallarına yazılmaz. GitHub cron kesin saat garantisi vermez; gerçekleşmeyen seanslar sonradan doldurulmaz.

## Kârlılık ve PAPER geçiş kilidi

`INSUFFICIENT_EQUITY_EVIDENCE` varsayılan ve doğru tanıdır. Veri testleri başarılı olsa bile aşağıdakiler doğrulanmadan tarihsel kâr oranı üretilmez ve PAPER başlatılmaz:

1. Kapsayıcı ve **tarihsel dönem itibarıyla bilinebilen** evren; delist edilmiş şirketler dahil geçmiş seçim.
2. Kurumsal işlemler ve gerçek OHLCV birimleri (split/temettü) ile lisans/erişim uyumu.
3. Halka açıklık/ownership yoğunluğu için kaynak ve gözlem tarihi. Güncel FDV veya 13F/SEC şirket raporu tek başına float yüzdesi değildir.
4. Likidite, gerçek spread, piyasa etkisi, tavan-taban / işlem durması / BIST açılış-kapanış müzayedeleri ve para birimi ayrımı.
5. Eğitim-test zaman ayrımı; multiple testing/selection bias; farklı maliyetler ve karşılaştırma endeksleri.
6. Kârlı olduğu bağımsız olarak doğrulanan, **dondurulmuş** bir aday için ayrı SHA kanıtlı ileriye dönük PAPER; gerçek emir yetkisi yok.

## Opsiyonel sıfır ücretli erişim

GitHub repo Settings → Secrets and variables → Actions içinden:
- `SEC_USER_AGENT`: SEC'nin adil erişim politikasına uygun **kendi araştırma projesi adı ve erişilebilir iletişim adresi**. Bu yoksa SEC sorgusu atlanır, fiyat taraması yine çalışır.
- `DATACEDAR_API_KEY`: varsa ücretsiz Explorer anahtarın. Yoksa DataCedar atlanır, diğer kaynaklara dokunulmaz.

Hassas değerler loglara yazılmaz. Özellikle ücretli API, premium plan veya yeni sunucu kurulumu şartı yoktur.
