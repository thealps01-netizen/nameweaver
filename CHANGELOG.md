# Changelog

Bu projedeki tüm önemli değişiklikler bu dosyada tutulur.
Biçim [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) temellidir ve
[Semantic Versioning](https://semver.org/lang/tr/) izler.

## [Unreleased]

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
