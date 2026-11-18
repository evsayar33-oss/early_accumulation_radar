# V11 — Özerk Örüntü Keşfi ve Bağımsız Doğrulama

## Sorun

V8–V10 gözlem ve metrik sapmalarını kaydediyordu. V9 aynı zaman ve likidite ortamındaki şiddetli hareket eden coinleri hareket etmeyen coinlerle karşılaştırıyordu. Ancak **öğrenilen ortaklığın otomatik keşfedilmesi, gelecekteki veriye karşı sınanması ve bildirilmesi** için kalıcı bir durum makinesi yoktu. V11 bu eksiği gidermeye yönelik bağımsız bir araştırma hattıdır.

## Özerk veri döngüsü

Var olan **V8 SHA-256 zincirli perpetual gözlemlerini salt okuyarak**, her gün UTC 02:23'te (GitHub cron gecikebilir/atlanabilir) çalışır. Özellikler `t` zamanında veya öncesinde gerçekten gözlenmiştir. Sonraki dört saatte gözlenen +%12 / −%12 hareket yalnız `t` sonrası sonuç etiketi olarak kullanılır. Eksik OHLCV/OI, yeniden ölçekleme, farklı sözleşme, görülmemiş gelecek fiyatı hiçbir zaman kazanç veya sinyal olarak doldurulmaz.

- Yükseliş ve düşüş **ayrı** incelemeler: V9'dan 12 tekil motif, V10 kaynaklarından 10 bağımsız bilgi boyutu kombinasyonu ve birleşik OI+aktivite hipotezi, iki yön için **46 önceden yazılmış test**. Bu sayı koddan hesaplanır; kısmi veya başka sürümlere ait veri karıştırılmaz.
- Kontrol grubu: **aynı UTC tarama zamanı ve aynı başlangıç ciro/fiyat bandında** hareket etmeyenler. Ters yönde büyük hareketler kontrol sayılmaz. Gerçek tahmini isabet oranı / piyasa genelinde PPV değil, **eşleştirilmiş örneklem içindeki** duyarlılık, yanlış alarm oranı, taban olay olasılığı ve lift ölçülür.
- İstatistik: 2×2 olay/kontrol tabloları, tek yönlü Fisher exact testi ve tüm aile/iki yönde Benjamini–Hochberg **FDR q** düzeltmesi. 30 eşleşmiş olay, 200 eşleşmiş kontrol, 10 farklı olay sembolü, 3 ayrı olay günü, en az 8 olayda metrik, kontrol yanlış alarm oranı ≤%10, taban olasılığa göre lift ≥2 ve q ≤0,05 geçmeden yeni örüntü **keşfedildi** denmez. Bu ilk aşama yine yalnız *keşif örneklemi*dir.
- Yeni keşif, `research/v11-pattern-evidence` adlı **ayrı Git araştırma dalında** metodoloji SHA-256 sürümü, kural, keşif sayımları, bağımsız sınama başlangıcı ve sonuyla kalıcı olarak mühürlenir. Test başlangıcı **keşiften sonraki ilk UTC gece yarısı**, 7 günlük pencere sabittir. Bu aralık sırasında başarı eşiği, kural, hedef, süre, maliyet veya örnekler yeniden seçilmez.
- İleriye dönük ve tamamlanmış V8 fiyat gözlemlerinden gelen doğrulama olayları aynı **ayrı SHA zincirli** kanıt kaydına eklenir. Yedi günün tamamı ve dört saatlik sonuç süresi dolmadan karar verilmez. Kod/metodoloji değişmişse geçmiş aday **PAUSED_CODE_DRIFT** olur; yeni kodla geriye dönük başarıya çevrilmez.
- Bağımsız test aynı örnek yeterliliği, yanlış alarm, lift ve FDR sınırlarıyla başarılıysa `PROSPECTIVE_ASSOCIATION_REPLICATED_NOT_TRADING_ALPHA`, aksi halde `NOT_REPLICATED_OR_INSUFFICIENT` olarak **bir kez** kalıcı karar üretilir. Olumsuz sonuçlar silinmez.
- Yeni aday ilk defa dondurulduğunda ve yedi günlük doğrulama tamamlandığında **Telegram'a bir defalık rapor** iletilebilir. Normal taramalarda, yeni veri eklendiğinde veya kanıt yetersizken sürekli mesaj gönderilmez. Günlük **ayrıntılı GitHub Actions raporu** `out/v11_pattern_discovery/report.json` ve `report.md` olarak 90 gün saklanır; `research/v11-pattern-evidence/research_archive/v11/latest.json` kalıcı son durumdur.

## Kanıt hiyerarşisi

1. `NO_EVIDENCE_YET`: Yetersiz gözlem, tek başına yüksek hacim/OI veya geçmiş örnekler. Bildirim yok, rapor var.
2. `NEW_RESEARCH_CANDIDATE`: Çoklu sınamada kontrol gruplarına göre istatistiksel ilinti var; bağımsız **7 günlük test yeni başlayacak**. Telegram'da açıkça kanıtın geçici olduğu yazılır.
3. `PROSPECTIVE_ASSOCIATION_REPLICATED` veya `NOT_REPLICATED_OR_INSUFFICIENT`: Baştan dondurulmuş gelecek penceresi tamamlandı ve yanlış alarmlar dahil değerlendirildi. Telegram sonucunda yalnız `istatistiksel ilişki` ifadesi kullanılır.

Bu sistem **nedenselliği veya maliyet sonrası kârlılığı kanıtlamaz**. OI büyümesi tasfiye, hedge, yeni long/short veya piyasa yapıcı faaliyeti olabilir. İki farklı göstergenin aynı anda yükselmesi ortak sebebin kanıtı değildir; piyasa genelindeki birlikte hareket, çoklu karşılaştırma, farklı coinlerin bağımsız olmaması ve sonradan seçilmiş tarihsel örneklem yanlılığı ayrıca incelenmelidir. İleri aşamada gerçek maliyet, funding, derinlik, spread, gerçek pozisyon boyutu, gecikme ve *bağımsız* PAPER performansı gerekir. Otomatik işlem stratejisi terfisi **yasaktır**.

## İşletim ve koruma

Yalnız **yeni** `.github/workflows/v11_pattern_discovery.yml` günlük araştırma iş akışını ekler; V8 yarım saatlik tarama, V9/V10 gözlem/rapor, V3 PAPER, V5–V7, Telegram al/sat kararları ve eski SHA kanıtı **değiştirilmez**. `research/v11-pattern-evidence` dalına ilk başarılı çalışmada yalnız V11 kayıtları yazılır; geçmişi elle güncellemez. GitHub Secrets `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` yalnız **varsa** sonuç bildirimi için kullanılır. Eğer özel mesaj başarısız olursa kanıt kaydı ve artifact zaten kalıcıdır; sınırsız tekrar mesaj gönderilmez.

Not: V9'un dört saatlik örnek seçiminde kayan pencere başlangıcının üretebileceği farklı örnekleri önlemek amacıyla **UTC'ye sabit dört saatlik zaman dilimi** eklendi. Veri eksikliği, kaynak erişim hataları ve işlemlerin gerçekte yapılabilirliği hâlen araştırma riskidir. Otomatik değerlendirme başarısı ticari başarı anlamına gelmez.
