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

Sürüm bilgisi tek yerde: [`version.py`](version.py). Yayın için:

```bash
git tag v0.1.0
git push origin v0.1.0
```

`v*.*.*` tag'i GitHub Actions'ı tetikler ([release.yml](.github/workflows/release.yml)):
test → PyInstaller → Inno Setup installer → SHA256 → **GitHub Release**.
Uygulama her açılışta [`updater.py`](updater.py) ile son sürümü kontrol eder ve
yeni sürüm varsa kullanıcıya güncelleme sunar.

## Lisans

[MIT](LICENSE) © 2026 thealps01-netizen
