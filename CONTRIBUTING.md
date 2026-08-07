# Katkı Rehberi — Nameweaver

## Geliştirme ortamı
```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

## Testler
```bash
.venv\Scripts\python -m pytest tests/ -v
```

## Sürüm & yayın
- Sürümü **yalnızca** [`version.py`](version.py) içinde tanımla.
- Yayın: `git tag vX.Y.Z && git push origin vX.Y.Z` → GitHub Actions installer üretip Release oluşturur.
- Değişiklikleri [`CHANGELOG.md`](CHANGELOG.md) içine yaz.

## Commit mesajları
Kısa, açıklayıcı ve emir kipinde (ör. "Add dark theme toggle").
