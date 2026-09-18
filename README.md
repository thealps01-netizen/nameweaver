# Nameweaver

Right-size LLM models to your hardware — PyQt6 desktop app

## Kurulum (geliştirme)

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python app.py
```

## Derleme (Windows .exe + installer)

```bash
build.bat
```

Bu, PyInstaller ile `dist\Nameweaver\Nameweaver.exe`, Inno Setup kuruluysa
`installer\Nameweaver_Setup.exe` üretir.

## Sürüm yayınlama & otomatik güncelleme

**Geliştirme sırasında** sürümün tek kaynağı [`version.py`](version.py). **Yayında**
sürüm **git tag'inden** okunur: `v*.*.*` tag'i GitHub Actions'ı tetikler
([release.yml](.github/workflows/release.yml)) ve workflow tag'deki sürümü
`version.py` + `file_version_info.txt` içine **enjekte eder** → bu yüzden tag ile
`version.py` aynı olmalı.

```bash
git tag v0.1.29
git push origin v0.1.29
```

Yayın hattı: test → sürüm enjeksiyonu → PyInstaller → Inno Setup installer → SHA256 →
**GitHub Release**.

Uygulama her açılışta [`updater.py`](updater.py) ile son sürümü kontrol eder ve
yeni sürüm varsa kullanıcıya güncelleme sunar.

> `pyproject.toml`, `nameweaver.iss` ve `file_version_info.txt` içindeki sürümler
> yalnızca **elle** çalıştırılan araçlar için varsayılandır (workflow ve `build.bat`
> hepsini `/DAppVersion` veya enjeksiyonla ezer). Yayın öncesi `version.py` ile
> birlikte güncel tutulurlar; sapma `version.py` 0.1.29 iken 0.1.12 kalması gibi
> kafa karışıklığına yol açar.

## Lisans

[MIT](LICENSE) © 2026 thealps01-netizen
