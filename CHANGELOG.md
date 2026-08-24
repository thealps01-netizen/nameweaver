# Changelog

Bu projedeki tüm önemli değişiklikler bu dosyada tutulur.
Biçim [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) temellidir ve
[Semantic Versioning](https://semver.org/lang/tr/) izler.

## [Unreleased]

## [0.1.13] - 2026-08-24
### Fixed
- Çalıştırınca "HTTP 404": chat artık motorun **gerçek model kimliğini** gönderiyor (Ollama'ya `gemma2:2b` gibi, kataloğ adı değil) ve modeli **gerçekten içeren** motora yönlendiriyor. Model yalnızca kapalı bir motorda (ör. LM Studio sunucusu kapalı) kuruluysa, 404 yerine "o motoru başlat" uyarısı çıkar.
- Updater artık **SHA256 doğrulanmadan installer çalıştırmıyor** (sidecar yoksa/eşleşmezse iptal).
- İndirme/pull zaman aşımı 30 sn'den 300 sn'ye çıkarıldı (büyük GGUF indirmeleri kesilmesin).
- LM Studio indirme klasörü de `settings.json`'daki `downloadsFolder`'ı okuyor (özel klasör).

### Added
- Chat: **Enter ile gönder** (Shift+Enter yeni satır).
- PR'larda pytest koşan CI kapısı (`test.yml`); `nameweaver.ico` repoya eklendi.

### Changed
- Ollama tag üretimi gerçek formata çevrildi (`Llama-3.1-8B-Instruct` → `llama3.1:8b`).
- İndirme worker'ları artık takip edilip kapanışta durduruluyor.
- Sürüm her yerde hizalandı (pyproject, file_version_info, Inno); README artık `app.py`'yi gösteriyor.
- Ölü kod temizliği: `planner.py`, `crash_handler.py`, `logger.py` kaldırıldı — tek log (cfg.setup_logging) + tek crash handler (app.py).

## [0.1.12] - 2026-08-08
### Fixed
- "İndirdiğim modeller güncelleme sonrası kayboldu": modeller aslında silinmiyordu (LM Studio'nun kendi klasöründe duruyorlar) ama Nameweaver onları yalnızca sunucu açıkken görüyordu. Artık LM Studio modelleri **diskten de taranıyor** (sunucu kapalıyken bile kurulu görünürler). Özel model klasörü, LM Studio'nun `settings.json`'ındaki `downloadsFolder` okunarak destekleniyor — varsayılan ya da özel konum, her PC'de çalışır.

## [0.1.11] - 2026-08-08
### Fixed
- Run motor seçimi: chat penceresi artık çalışan tüm motorları listeliyor (eşleşenler başta). Model LM Studio'da kuruluyken Ollama'ya sıkışıp kalma sorunu düzeldi — LM Studio sunucusu açıksa artık seçilebiliyor. Motor yoksa mesaj, LM Studio sunucusunu başlatmayı da anlatıyor.

## [0.1.10] - 2026-08-08
### Fixed
- Windows'ta motor başlatınca/durdurunca açılan cmd pencereleri kapatıldı. `ollama serve` artık yalnız CREATE_NO_WINDOW ile başlatılıyor (önceki CREATE_NO_WINDOW+DETACHED_PROCESS kombinasyonu Windows'ta yok sayılıp runner süreçlerinin kendi konsollarını açmasına yol açıyordu). taskkill / lms / kurulum gibi tüm konsol çağrıları da gizli pencereyle çalışacak şekilde sarmalandı.

## [0.1.9] - 2026-08-08
### Changed
- Çakışan "Fit" bilgisi giderildi: detay panelindeki skor çubuğu "Fit" yerine "Match" olarak adlandırıldı (donanımı ne kadar iyi kullandığını ölçer); "Fit Level" ise tek net "sığma" sinyali olarak kaldı. Böylece küçük modelde "Match 75" ile "Fit Level: Perfect" artık çelişmiyor.
- Gerçekçi Est. TPS: teorik bant-genişliği tavanı yerine gerçek-dünya verimlilik katsayısı (0.55) uygulanıp makul bir tavana (300 tok/s) sınırlandı — "1622 tok/s" gibi inandırıcı olmayan değerler düzeldi.
- Tablo sadeleştirildi: "RAM Usage" ve "Run Type" sütunları varsayılan gizlendi (bilgi detay panelinde duruyor).

### Added
- "Runs" trafik-ışığı sütunu (LM Studio tarzı): 🟢 çalışır · 🟡 kıt/offload · 🔴 çalışmaz — motor formatı uyumu + bellek sığması + run mode tek bakışta özetlenir.

## [0.1.8] - 2026-08-08
### Added
- Üst filtre çubuğuna "PC Load" filtresi: modelleri sistemin çalıştırma rahatlığına göre (Effortless / Comfortable / Demanding / Heavy / Too much) süzebilirsin. Filtre durumu diğerleriyle birlikte kaydedilir.

## [0.1.7] - 2026-08-08
### Added
- Boyut sınıfı göstergesi: modeller Tiny / Small / Medium / Large / XL / Huge olarak renkli işaretleniyor (tablo "Size" sütunu + detay paneli). Küçük/büyük model tek bakışta ayırt edilir.
- "PC Load" göstergesi: sistemin modeli ne kadar rahat çalıştırdığı — Effortless / Comfortable / Demanding / Heavy / Too much — run mode + bellek + TPS'ten türetilir (tablo sütunu + detay paneli).

### Changed
- Güven rozeti ikonları daha ayırt edici: güvenilir kaynak yeşil "check-decagram", doğrulanmamış kaynak kırmızı "alert-decagram" — renkler artık birbirine yakın değil.

## [0.1.6] - 2026-08-08
### Added
- Yayıncı güven rozetleri (qtawesome ikonları): güvenilir birinci-taraf yayıncılar kalkan-onay (yeşil), doğrulanmamış/topluluk kaynaklar kalkan-uyarı ile işaretlenir. Güvenilir olmayan kaynaktan indirmeden önce uyarı diyaloğu çıkar.
- Otomatik re-upload tespiti: HF `base_model` ilişkisiyle, güvenilir bir modelin başka biri tarafından yeniden yüklenmiş/quantize edilmiş sürümü ("bartowski", "TheBloke" vb.) otomatik ayırt edilir.
- Motor uyum rozeti artık modern ikon: kurulu motorların çalıştıramayacağı format (AWQ/GPTQ) "motor kapalı" ikonu + soluk satır.

### Fixed
- Motor pill dropdown'ı: artık bir motor seçince pill o motoru gösteriyor (önceden hep Ollama önceliğinde sabitti). Seçili motor onay işaretiyle belirtiliyor.

## [0.1.5] - 2026-08-08
### Fixed
- "Motor seçimi bazen çalışmıyor": kurulu model eşleştirmesi artık isim normalize edip (küçük harf, ayraç/format/quant farklarını yok sayarak) çift yönlü karşılaştırıyor. `Llama-3.1-8B-Instruct` ↔ `llama3.1:8b-instruct` gibi adlar artık doğru eşleşiyor (app.py + runner.py).

### Added
- Motor uyumu rozeti: format olarak kurulu motorların (Ollama/LM Studio/llama.cpp/Docker) çalıştıramayacağı modeller (AWQ/GPTQ, Windows'ta MLX) tabloda soluk gösterilip "⚠" ile işaretleniyor; tooltip nedenini açıklıyor.
- Resmî yayıncı rozeti: birinci taraf/resmî org modelleri Provider sütununda "✓" ile işaretleniyor (org allowlist). Topluluk/quantizer yüklemeleri işaretsiz kalır; gizlenmez.

## [0.1.4] - 2026-08-08
### Fixed
- Kapatırken 1-2 sn donma: `closeEvent` artık pencereyi anında gizliyor, arka plan thread'lerine dur sinyalini tek seferde (paralel) gönderiyor ve kısa/sınırlı bekliyor; takılan thread son çare olarak sonlandırılıyor. Böylece kapanma anında hissediliyor.
- HF cache yazımı atomik hale getirildi (temp dosya + replace) — kapanışta yarım kalan yazım artık cache'i bozamaz.
### Added
- Manuel güncelleme denetimi: About penceresine "Güncellemeleri Denetle" butonu eklendi. Güncelleme varsa indirme istemi, yoksa "en güncel" bilgisi, ağ hatasında "denetlenemedi" uyarısı gösterilir.

## [0.1.2] - 2026-08-08
### Fixed
- Açılışta çökme: `updater.py` artık app'e ait olmayan `cfg.load_cfg` fonksiyonunu içe aktarmaya çalışmıyor. "Atlanan sürüm" bilgisi kendi `update_skip.json` dosyasında tutuluyor (app config şemasından bağımsız).

## [0.1.1] - 2026-08-08
### Added
- Açılışta GitHub Releases üzerinden otomatik güncelleme kontrolü (`app.py` → `UpdateChecker`).

### Fixed
- CI release build: eksik `Pillow` ve `pyinstaller` derleme bağımlılıkları eklendi.

## [0.1.0] - 2026-08-08
### Added
- İlk sürüm — Nameweaver iskelesi (updater, logger, crash handler, installer hattı).
