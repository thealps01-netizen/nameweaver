# Changelog

Bu projedeki tüm önemli değişiklikler bu dosyada tutulur.
Biçim [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) temellidir ve
[Semantic Versioning](https://semver.org/lang/tr/) izler.

## [Unreleased]

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
