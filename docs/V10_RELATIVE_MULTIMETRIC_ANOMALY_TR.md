# V10 — Coin başına çok metrikli, geçmişe göre olağan dışı değişim

**Temel yaklaşım:** Her USDT perpetual varlık için tek bir hacim, piyasa değeri veya OI eşiği kullanma. O coin için geçmişte *o ana kadar gerçekten gözlenmiş* verinin medyanı, medyandan mutlak sapması (MAD) ve geçmiş %95 yüzdeliğine göre **birden çok metrikte aynı anda** sapma olup olmadığını hesapla. Tek metrik belirgin olabilir; çoklu birliktelik ayrıca araştırılır. Gelecekte oluşacak büyük hareket bu hesapta kullanılmaz.

## Her 30 dakikada kaydedilen 10 ölçüm

| Ölçüm | Birim / kaynak | Ne anlama gelmez? |
|---|---|---|
| 24s dönen işlem cirosu | Binance/Bitget quote USDT, OKX base × last fiyat yaklaşımı | Son 30 dakikanın gerçek işlem hacmi değil |
| 24s cirodaki son ~1s değişim | Aynı borsanın iki farklı anlık 24s ciro ölçümü | Son bir saatteki net agresif alış miktarı değil |
| Açık pozisyon seviyesi | OKX tüm swap API'si, **sözleşme adedi** | Fon akışı, net long veya net alım değil |
| OI'nin ~1s artışı | OKX aynı sözleşmede zamanla değişen sözleşme adedi | OI'nin dolar değerinin fiyat kaynaklı artışı değil |
| En iyi alış-satış fiyat farkı | OKX `bidPx/askPx`, Bitget `bidPr/askPr`, bps | Gerçekleşebilir emir büyüklüğü veya L2 derinlik değil |
| 24s gün içi fiyat aralığı | OKX/Bitget `high24h/low24h`, % | Sürekli veya dakika bazlı volatilite ölçümü değil |
| Son fiyat/mark farkı | Bitget `lastPr/markPrice`, mutlak bps | Gerçek arbitraj net getirisi değil |
| Funding oranının mutlak büyüklüğü | Bitget `fundingRate` ham oranı ×100, % | Gelecek fonlama ödemesi veya tüm borsalar için güncel oran değil |
| Son ~1s mutlak fiyat hareketi | Önceki ve bugünkü **aynı borsa** fiyat gözlemi, % | Hareket öncesi tahmin kanıtı değil |
| Perpetual borsaları arası fiyat ayrışması | Aynı varlık ve USDT perpetual için fiyat farkı, bps | Spot vadeli basis veya uygulanabilir arbitraj değil |

Eksik alanlar **MISSING_VALUE** olarak kalır. OKX/Binance/Bitget her metrik için aynı bilgiyi sağlamaz; bu nedenle kaynaklar veya farklı sözleşme türleri birleştirilip olmayan ölçüm uydurulmaz. Binance erişimi kapalıysa OKX ve Bitget ile devam edilir.

## Kendi geçmişini aşma kuralı

- Sinyal zamanı `t`: yalnız `t` öncesindeki **aynı coin + aynı borsa** kayıtlarından geriye doğru en fazla 7 gün / 336 tarama alınır. Daha sonraki, aynı andaki veya diğer coinlerdeki veriler baz çizgisine girmez.
- 24 geçmiş ölçüm ve en az 10 saatlik zaman aralığı olmadan **BASELINE_BUILDING**, anomali yok; 24–95 örnekte **PROVISIONAL**, ≥96 geçmiş ölçümde **ESTABLISHED**. 96 örnek yaklaşık 48 saatlik gözlemdir; bu, farklı piyasa rejimlerine genelleme ispatı değildir.
- Her metrik **kendi mevcut veri kaynağının ayrı geçmişine** bağlanır. OKX'teki OI değişimi OKX geçmişiyle, Bitget'teki funding veya mark fiyat farkı Bitget geçmişiyle ölçülür. Sonuçlar coin altında birleştirilir; `metric_sources` alanı metrik bazında hangi borsanın seçildiğini saklar. İki borsadaki ham fiyat/hacim değerleri aynı geçmiş serisiymiş gibi karıştırılıp sahte örneklem büyüklüğü yaratılmaz.
- Her ölçüm kendi tarihsel medyanına ve MAD dağılımına göre standartlaştırılır: `robust_z = (şimdiki - geçmiş_medyana) / max(1.4826*MAD, geçmiş_medyana*%5, metriğe_özel_asgari_ölçek)`. Ancak hem `robust_z >= 3` hem de mevcut değerin **önceki ölçümlerin %95 yüzdeliğinden yüksek** olması durumunda `OUTLIER_ABOVE_OWN_BASELINE`.
- Bu eşikler istatistiksel hipotezleri **araştırmaya başlamak** için sabit tutulur; optimize edilmiş giriş parametreleri veya hata olasılığı ispatı değildir. Tarihsel veride bazı coinlerde yaygın görülen yüzdelik/dağılım sapmalarının bütün piyasalarda birden artması da kontrol edilmelidir.
- `OI seviyesi` ve `OI değişimi` gibi aynı veri kaynağının farklı türevlerini **iki bağımsız kanıt** saymayız. Ayrı *bilgi boyutu* sayısı da kayıt altına alınır. Bir metrik aşımı da, çoklu boyut anomalisinin varlığı da raporlanır.
- Hareket başlamamış araştırma kategorisi için, yalnız gözlem anında bilinebilen **son 2 saatte |getiri| ≤%3** ve güncel 24s fiyat değişimi |%15| veya altında olmalı. 24 saatlik yüksek/düşük fiyat aralığı sağlanıyorsa %25'i aşan gün içi pump–geri çekilme de temiz öncü gözlem olarak etiketlenmez. Üstünde `OUTLIER_WITH_PRIOR_MOTION_OR_UNVERIFIED_PRICE`: **geç kalmış veya kimliği tutarsız** olarak ayrılır. İki borsa arasında aşırı fiyat ayrışması varsa da erken anomali sayılmaz.

## Önce yükselişi değil, yanlış alarmı bul

Tüm coinleri birlikte say: yalnız en yüksek 30 örneği gösteren kısa rapordan bağımsız olarak tüm **sakin kalan** varlıkların da metrik sonuçları `cohort.jsonl` içinde bulunur. Mevcut V9 araştırmasındaki *aynı gözlem zamanında benzer ciro/fiyat durumundaki* +%12 / −%12 dört saatlik gelecekteki uç olaylar ve hareket etmeyenler, şu **önceden belirlenmiş** ek hipotezler için sınanır:

`relative_any_metric_outlier`, `relative_multiple_metrics_outlier` (en az iki **bağımsız** bilgi boyutu), `relative_turnover_24h_outlier`, `relative_oi_contracts_outlier`, `relative_spread_outlier`, `relative_funding_outlier`, `relative_mark_basis_outlier`.

Çok sayıda metrik izlemek, çoklu hipotez sınama ve yanlış pozitif riskini artırır. Sonuçlar ancak en az 30 uç olay, en az 200 zaman/likidite yönünden eşleşmiş kontrol, ayrı bir ileriye dönük örneklem, rejim dayanıklılığı, işlem maliyeti ve gerçek vadeli kontrat likiditesiyle doğrulanırsa değerlendirmeye alınabilir. Yeterli örnek yoksa **yeni ortak metrik keşfedildi** denmez.

## Operasyon

Mevcut `V8 all-symbol perpetual early-motion evidence (RESEARCH ONLY)` GitHub iş akışı, var olan yarım saatlik (gecikebilen) tarama saatlerini değiştirmeden **yeni 10 metriği ham fiyat gözlemine** kaydeder. Ardından `research_v4.perp_anomaly`, aynı SHA zincirli V8 kayıtlarını **salt okuyarak** `out/v10_anomalies/report.json`, `cohort.jsonl` ve `report.md` üretir. Eski kayıtları geriye dönük doldurmaz.

Bu ek hesaplama V8'in kanıt saklamasını engellememesi için advisory-only `continue-on-error: true` çalışır. V9 aynı metrikleri hareketlerden **önceki** hallerine göre test edecek şekilde genişletildi. V3 PAPER, V2 Telegram sinyalleri, V5–V7 araştırmaları ve mevcut geçmiş kanıtları değiştirilmez; V10 otomatik AL/SAT, short, PAPER veya gerçek emir oluşturmaz.

**Eksikler:** GitHub'da 30 dakikada bir tarama saniyeler içinde yaşanan pump hareketlerini kaçırabilir. Tüm borsalarda order-flow, tüm likidasyon verileri, L2 derinlik ve geçmiş funding/OI sürekliliği hâlen mevcut değil. PIPPIN'in geçmiş sıçramasını bu V10 ile sanki önceden gördük demek doğru olmaz.
