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
- Geliştirmede sürümü **yalnızca** [`version.py`](version.py) içinde tanımla; yayında
  sürüm **git tag'inden** gelir ve CI onu `version.py` + `file_version_info.txt` içine
  enjekte eder → tag ile `version.py` aynı olmalı.
- Yayın öncesi `pyproject.toml` ve `nameweaver.iss` varsayılan sürümünü de güncelle
  (elle çalıştırılan araçlar bunları okur).
- Yayın: `git tag vX.Y.Z && git push origin vX.Y.Z` → GitHub Actions installer üretip Release oluşturur.
- **Yayınlanan her sürüm** için [`CHANGELOG.md`](CHANGELOG.md) içine girdi yaz — tag
  atıp not yazmamak, kullanıcıya giden değişikliğin tek kaydını GitHub'ın otomatik
  commit listesine bırakır.

## Commit mesajları
Kısa, açıklayıcı ve emir kipinde (ör. "Add dark theme toggle").
