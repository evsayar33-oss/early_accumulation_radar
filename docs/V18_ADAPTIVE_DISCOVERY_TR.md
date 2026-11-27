# V18 — Hatalardan öğrenen erken olay araştırması (NO REAL TRADES)

V18 ayrı, sürekli araştırma hattıdır. V3 PAPER, V8/V9/V11/V12/V13, V17,
mevcut Telegram ve geçmiş kanıt dalları değiştirilmez. Yeni kanıt dalı:
`research/v18-adaptive-evidence`. Son rapor `research_archive/v18/latest.json`.
Eaverse ve Quant Superlab çalışma revizyonları sabit Git SHA ile okunur;
Global Capital Radar'ın ilk görülen tarihli raporu ve commit'i kaydedilir.
Yeni token/ücretli kaynak gerekmez.

## Veri ve kaçırılan olaylar

- V8'den bağımsız olarak OKX/Bitget/Binance'ın tamamlanmış 15 dakikalık
  USDT perpetual mumları, aynı borsa geçmişi ve yeni gerçek sonuç pencereleri
  alınır. Mevcut aktif evren keşfedilir; en fazla 32 yeni sözleşme/tur,
  takip bekleyenler öncelikli. BTC/ETH/SOL/BNB/XRP ve stablecoinler yeni
  araştırma rotasyonundan çıkarılır; piyasa değeri geçmişi doğrulanmamıştır.
  OKX instCategory, Bitget isRwa ve Binance underlyingType ile kripto dayanağı
  doğrulanmayan ya da çelişen sözleşmeler bu araştırma evreninden çıkarılır.
  İlk karma evrenin gözlem ve denemeleri değişmeden saklanır, aktif kripto
  öğrenmesinde kullanılmaz; bütün gerçek denemeler çoklu karşılaştırmada sayılır.
  Güncel dayanak metadatası geçmiş tarihteki kimliği doğrulamaz; retrospektif
  sonuçlar geçmiş PIT evreni olarak yorumlanmaz.
- Mumlar başka borsaya eklemlenmez. Bağımsız borsanın örtüşen mumları
  karşılaştırılır, çelişkili veri yeni gözlem üretmez. Geç gelen gerçek kapalı
  mumlar ilk görülme zamanından SONRA gerçekleşmiş sonucu tamamlayabilir;
  yapay snapshot veya eski emir gerçekleşmesi üretmez.
- Orijinal V8'in SHA zinciri salt okunur. Her turda en fazla 16 eski as-of
  V9-uygun adayın aynı borsa gerçek tarihli mumlarıyla farklı bir **sonraki
  mum işaretleme tanısı** yapılır. V9/V11/V13'ün eski sonuçları yerlerinde
  kalır. Bu sonuçlar V13 spread ve order-book fill kanıtı değildir.
- V5 güvenilir main başarılı işinin SHA doğrulanmış kalite elemesinden BIST
  ve ABD günlük mumları; daha önce görülen fakat evrenden çıkmış semboller
  için sonuç-only kurtarma. V12 kayıtları korunur.
- Kripto 4s uç olayları ve BIST/ABD beş seans uç hareketleri ayrı ölçülür.
  Her gerçek olay ve kontrolün kapsama/venue/gözlem/sonuç bilgisi korunur.
  Kaçırılan, yanlış, geç ve doğru olay örnekleri raporda görünür.
- Geçmiş mumlardan üretilen araştırma **retrospektiftir**. İlk görülme
  gözlemleri yalnız gerçek alınma zamanı sonrası ilk açılışla değerlendirilir.
  Fiyatın hareket etmesinden önceki özellikler kullanılır; fiyat yükselişi
  zorunlu giriş şartı değildir. Veri yok, eksik veya yeniden ölçeklenmişse
  ayrı durum; ne kâr ne zarar uydurulur.

## Öğrenme

Eaverse indicator_bank'in 24 gösterge ailesinin ikişer başlangıç parametresi:
kripto 15dk/1s/4s, hisse 1G/1H (haftalık). Haftalık yeni parametre denemeleri
ve anlamlı AND/OR, ters yön, ters koşul, hacim/oynaklık ve mikro yapı
kombinasyonları; eski dondurulmuş parametreler saklanır. Takipteki
OI değişimi yalnız aynı borsanın gerçek iki gözlemiyle; funding, basis,
spread ve Binance gerçekleşen taker-buy hacmi sadece kaynağın sağladığı
zamanda. Makro akış yalnız gerçekten yayımlanmış kaynaktan ve as-of
anında, alternatif kaynak/provenance ayrı; geçmiş makro geri doldurulmaz.
Eksik gösterge FALSE değildir.

20 yeni/süreç bazında anlamlı yeni veriyle tekrar sınanan gerçek deney
piyasa başına/tur. Başlangıç bütçesi %40 iyileştirme, %30 yeni,
%20 kaçırılan/yanlış olaylar, %10 ters mantık; boş kulvar bütçesi diğerlerine
dağılır. Benzersiz kural ve veri SHA, deneme sayısı, hata nedeniyle
kullanılan araştırma kulvarı ve sonuçlar kalıcı. Yetersiz kanıt, düşük
duyarlılık, yanlış alarm ve maliyet/kontrol başarısızlığı ayrı. Aynı veri +
aynı kural yeniden sınanmaz; anlamlı yeni gözlem veya yeni dönem gerekir.

## Bağımsız doğrulama

Önce keşif, sonra Quant Superlab'ın farklı koduyla ham OHLC pencere hash'i,
etiket ve getiri yeniden hesaplaması, hata oranı, taban olay olasılığı,
eşzamanlı likidite kontrolü ve günlük kümelenmiş istatistik; tüm gerçek
denemeler çoklu karşılaştırma hesabına dahil. Olumlu keşif adayından yeni
30 takvim günlük bağımsız ileri test, 14 günlük sonuç tamamlama payı.
Dondurulan kurallar oynatılmaz, holdout tekrar keşif örneği yapılmaz.
Yeterli ileri kanıt yoksa onay yok. İleri başarısızlıklar sonraki
hipotezleri besler. Yalnız olumlu doğrulanan yukarı yönlü araştırma,
sonraki günden başlayarak ayrı 90 günlük **koşullu, işaretleme tabanlı**
sanal izleme açabilir; kasa, maliyet stresi ve toparlanma izlenir.
Bu gerçek fill veya resmi Superlab PAPER/ACCEPT değildir. Short yön için
borçlanma ve teminat uygulanabilirliği kanıtlanmadan sanal işlem açılmaz.

## İşletim ve açık sınırlamalar

V8/V5 trusted main bitişi ve 2 saatte bir yedek cron tetikler. GitHub
cron gerçek zamanlı değildir. Kanıt zinciri sıkıştırılmış 8 MiB parçalara
ayrılır; 96 MiB aktif kayıt kapasitesi aşılırsa güvenli duruş/archiving gerekir,
eski kayıt silinmez. Sadece doğrulanmış ileri keşif ve yeni güçlü araştırma
olayı Telegram; normal tur ve başarısızlıkta mesaj yok. Başarılı teslim
makbuzu kalıcı; kayıt sonrası teslim, başarısız teslim sonraki turda denenir.

Kapsam gerçek derinlik/order-book/CVD, tasfiye, tüm zaman dilimleri,
tüm PIT/delist evreni ve gerçek maliyetler değildir. 1/5dk tam akış ve
gün içi BIST/ABD henüz yok. Mevcut maliyet varsayımları ve iki kat stres
ayrı raporlanır. PBO için tam, hizalanmış aday portföy getirisi henüz yok;
DSR yalnız yeterli günlük eşleşmiş işaretleme serisinde araştırma tanısıdır.
Resmi `lab/validation.py` kapısı ve canlı emirler değiştirilmez.

## İleriye dönük tüm vadeli sözleşme evreni (geçmiş veri şartı yok)

Ayrı `v18_forward_universe.yml` iş akışı 30 dakikalık hedef sıklıkta
OKX, Bitget, Binance, Gate.io, BingX ve erişilebilir olduğunda Bybit ile
natif USDT perpetual sözleşmelerin bütün taze toplu ticker verisini toplar.
Yeni listeleme, sıfır geçmiş ve düşük hacim gözlemi engellemez. Aynı dayanak
farklı borsalarda farklı sözleşmedir; normalize sembol sayısı benzersiz
varlık sayısı değildir. Kripto, hisse, endeks, emtia, FX, tahvil, ETF,
standart perpetual ve dayanağı açıklanmayan RWA/kimliği belirsiz sözleşmeler
ayrı raporlanır. Gate'in boş sınıfı veya BingX'in displayName alanı, kripto
kimliğinin doğrulanması değildir. Bir borsa kesintisinde diğerleri sürer.

Gerçek ilk ticker'dan sonra 4 saat ila 4 saat 45 dakika aralığında yine aynı
natif sözleşmenin yeni fiyatı ile yalnız **uç nokta fiyat sonucu** ölçülür.
Kayıp, kimliği değişmiş, zaman aralığı dışı veya olası yeniden ölçekleme
sonucu censored; borsa değiştirme, geçmiş fiyat yerleştirme, işlem fill'i,
OHLC maksimum/minimum ya da kesin gerçek zamanlılık iddiası yok. Gate ticker
başına exchange timestamp sağlamadığında yalnız gerçek alınma saati açıkça
belirtilir. Olay eşikleri sınıfa göre deneysel ve raporda görünür. Hacim
artışı yalnız yuvarlanan 24 saatlik turnover farkı olup gerçek CVD değildir.
Eksik özellik unknown; gerçek sonuçlarda true/false/UP/DOWN/NONE sayımları
borsa ve sınıf bazında tutulur. Bağımsız strateji/işlem onayı değildir.

Yeni `research/v18-forward-universe` kanıt dalındaki `latest.json` ve
`state.json` aktiftir. En son alınan fiyatlar, açık takip pencereleri, kümülatif
sayım ve son sonuç partisi sınırlı aktif durumdur; önceki anlık durumlar
normal (force olmayan) commit zincirinde korunur. Git geçmişi doğal olarak
büyür; sonsuz depolama garantisi yoktur. Ana V18 geçmiş OHLC araştırması
ayrı ve değişmeden devam eder. Doğrulanmış kripto kimliği, güncel sessiz fiyat
ve turnover/OI değişimi görüldüğünde ana V18'e en çok %25 ayrıntılı araştırma
önceliği verilir. %75 rotasyon korunur. Öneri 2 saati aşarsa kullanılmaz.
V18 doğrulama, PAPER ve canlı işlem kapıları değişmez.
