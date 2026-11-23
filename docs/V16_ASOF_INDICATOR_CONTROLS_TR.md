# V16 — Yeni göstergeleri eski stratejilere karıştırmadan araştırma

Bu PR **yalnızca araştırma ve veri yeterliliği denemesidir**. Mevcut V8 gözlemleri salt okunur; V9, V11, V12, V13, V15, H119, eski kanıt dalları, Telegram, PAPER ve production gate değişmez.

## Yeni üç araştırma hipotezi

- `funding_sign_flip`: Aynı borsada yaklaşık bir saat önce ve şimdi gerçek olarak görülen funding oranları zıt işaretli, her iki oran mutlak en az %0,002 ve fiyat son bir saatte en çok %1 oynamış. Funding değişimi, yeni yönlü agresif alım veya nakit akışı kanıtı değildir.
- `spread_compression_with_activity`: Aynı borsanın gerçek bid-ask farkı son bir saatte en az %30 daralırken 24s dönen ciro *göstergesi* en az %20 yükselmiş ve fiyat yatay kalmış. Bu bir L2 derinlik ölçümü veya gerçek son 1s işlem hacmi değildir.
- `mark_basis_normalization`: Önceden en az 20bp olan last/mark ayrışması yarıdan fazla azalmış ve fiyat yatay kalmış. **Spot–perpetual basis değildir**; uygulanabilir arbitraj iddiası yoktur.

Tüm eşikler sonuçlardan önce sabittir. Sadece aynı sembol ve aynı borsanın 35–85 dakika önceki gerçekten mevcut snapshot'ı kullanılır. Eksik veya bayat alan `null` kalır. Gelecekteki veriler özellik üretmez.

## Test yöntemi

V9'un önceden seçilmemiş tam as-of kohortları ve **yalnız gerçek ileri fiyat gözlemleri tamamlanmış** kayıtları kullanılır. Aynı UTC scan zamanı, benzer başlangıç likiditesi ve fiyat bandında uç olaylar ile hareketsiz kontroller ayrı değerlendirilir. Üç hipotez × iki yön = **altı keşif testi**. En az 30 olay ve 200 kontrol yoksa `INSUFFICIENT_EVIDENCE`; geçse bile **kesinlikle alpha onayı yok**. Çoklu test düzeltmesi, ayrı ileri holdout, emir gerçekleşebilirliği ve maliyet sınamaları tamamlanmadan bunlar V11/V13 varyantlarına katılmaz.

## Henüz gerçekten eksik olan veriler

Tüm perpetual evreninde damgalı aggressor trade akışı/CVD, dinamik L2 order-book imbalance ve replenishment, spot–perp eş-zamanlı fiyat/basis, gerçek likidasyon ve fonlama ödemeleri yoktur. Bunları eski 24s hacim veya ticker spread verisinden geriye dönük üretmek bilimsel olarak geçersizdir. Kaynağı doğrulanmış ücretsiz API akışıyla *gelecekten itibaren* ayrı kanıt dalında toplanmaları sonraki aşamadır.

İş akışı: `V16 Independent as-of indicator/control research (NO TRADING)`. Her gün planlı çalışır, Github cron gecikirse boşluk doldurmaz. Yalnız rapor/artifact üretir; hiçbir Git dalına push veya Telegram sinyali göndermez. Kaynak V8 defteri bulunamazsa veya SHA doğrulaması hatalıysa rapor üretmek yerine hata verir.
