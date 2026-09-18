# Changelog

Bu projedeki tüm önemli değişiklikler bu dosyada tutulur.
Biçim [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) temellidir ve
[Semantic Versioning](https://semver.org/lang/tr/) izler.

## [Unreleased]

## [0.1.32] - 2026-09-18
### Changed
- **Katalog artık "kurulu" iddia etmiyor**: Installed filtresi, detay panelindeki "Installed:" satırı, "Run →" butonu (ve tablodaki sağ tık Run), "kurulu önce" sıralaması kaldırıldı. Ölçülen sebep: tek bir kurulu dosya (`qwen2.5:3b`) üç katalog satırını "kurulu" gösteriyordu (`Qwen2.5-3B`, `Qwen2.5-3B-Instruct`, `Qwen2.5-3B-Instruct-AWQ`) — üstelik AWQ satırı yerelde çalışmayan bir format olduğu hâlde. Katalog şimdi yalnızca "indirebilir miyim + donanımıma uyar mı" sorusunu yanıtlıyor; "neye sahibim, neyi çalıştırabilirim" My Models sayfasında. Katalog satırındaki **Runs** trafik ışığı duruyor (hangi motorun çalıştırabileceğini söyler, kurulu olduğunu değil).

- **Arama artık kelime tabanlı**: sorgu parçalara ayrılır ve her parça ayraçlardan arındırılmış ad+yayıncı içinde aranır — `qwen 3b` → Qwen2.5-3B, `llama3.1` → Llama-3.1-8B, `deepseek r1 7b` → DeepSeek-R1-Distill-Qwen-7B. Önceden düz alt dizi aramasıydı; ölçülen hâli: `qwen` 333 sonuç ama `qwen 3b`, `llama3.1`, `nomic embed`, `mixtral 8x7b` **0 sonuç**. Fazla kelime artık sonucu daraltır, yok saymaz; kural eskisinin üstkümesi olduğu için önceden çalışan hiçbir arama bozulmaz (`3b` hâlâ 13b'yi de bulur).
- **Katalog varsayılan olarak yerelde çalıştırılamayan formatları gizliyor**: 161 giriş (mlx 72 · awq 65 · gptq 24) — Download'ı hiç açılamayan satırlardı. Filtre çubuğundaki **"Runnable only"** anahtarı (varsayılan açık, config'e yazılır) hepsini geri getirir, yani katalogda ulaşılamayan bir şey kalmaz. Varsayılan görünüm **1043 → 882** model.

### Fixed
- **My Models'ta Run butonu "…" olarak kırpılıyordu**: Run kolonu `ResizeToContents` ile ölçülüyordu, ama o kolonda tablo öğesi değil **widget** var — Qt onu bir kez ölçüyor, tema stylesheet'i fontu/dolguyu değiştirince kolon eski genişlikte kalıp buton kendi metnine sığmıyordu. Kolon artık doğrudan butonların `sizeHint`'inden ölçülüyor (satırlar her çizildiğinde yeniden), başlığı da boş değil (**Run**). Ayrıca **Remove…** / **Show in Catalog** kapalıyken neden kapalı olduklarını tooltip söylüyor (satır seçili değil / satır katalogda yok).
- **Bir motor modeli artık tek katalog satırına bağlanıyor**: `models.match_installed_ids` tek sahip kuralıyla çalışıyor — bir id'ye birden çok ad uyuyorsa **en sade ad** kazanır, diğerleri eşleşmez. Taban model ile instruct sürümü birbirini dışlar (`-Base` ↔ `:instruct` eşleşmez); Ollama'nın çıplak tag'i instruction-tuned dosya sayıldığı için `Llama-3.1-8B-Instruct` ↔ `llama3.1:8b` eşleşmeye devam eder.
- **Silme yolu katı ve format kapılı**: `runner.installed_model_ids(strict=True)` yalnız aynı tuning kelimelerine sahip adı eşler ve AWQ/GPTQ gibi yerelde tutulamayan formatlar silme yoluna hiç girmez; onay penceresi silinecek dosyaları motor id'siyle tek tek listeler. Önceden `Qwen2.5-3B-Instruct-AWQ` satırındaki Remove, `qwen2.5:3b` dosyalarını silebilirdi (geri dönüşsüz).
- **AWQ/GPTQ girişi bir motor modeli sahiplenemez**: eşleştirmeye yalnız motorların çalıştırabildiği formatlar girer ve eşleşme satır başına uygulanır — aynı adı taşıyan uyumlu kardeşi kendi eşleşmesini uyumsuz satıra devredemez.


### Added
- **İnen GGUF, HuggingFace'in yayınladığı SHA256 ile doğrulanıyor**: hash repo listesinden (`lfs.oid`) okunup indirmeye geçiriliyor; uyuşmazsa dosya silinir ve hiçbir şey kurulmaz, hash yoksa sonuç açıkça "not verified (no published hash)" der. `download_gguf` bu kontrolü zaten destekliyordu ama **hiçbir çağıran hash vermiyordu** — yani her GGUF doğrulanmadan iniyordu.

## [0.1.31] - 2026-09-18
### Added
- **My Models sayfası**: indirdiğin ve çalıştırabildiğin modeller katalogdan ayrı bir sayfada. Liste **motorların kendi bildirdiğinden** üretilir (Ollama `/api/tags`: boyut, parametre, quant, motorun kendi `capabilities`'i; LM Studio `/v1/models`; sunucu kapalıysa disk taraması) — katalog yalnızca zenginleştirme, eşleşme tutmazsa satır "katalogda yok" der ve yine çalıştırılabilir. **Run artık burada** (satır başına bir tık) ve sağ tık menüsünde kısayol olarak duruyor; katalog detayındaki buton "Run →" olup seni bu sayfaya getiriyor. Motor kapalıysa satır yerine "başlat" uyarısı görünür; başlık altında "Refresh" var.
- Sidebar'da gerçek görünüm sistemi: **Model Catalog** ve **My Models** sekmeleri (`QStackedWidget`). Katalog filtresi yalnız katalog sayfasında görünür. HuggingFace katalog güncellemesi yapan eski buton artık **"Update Catalog"** adıyla duruyor (eskiden "Model Catalog" yazıyordu ama sayfa açmıyordu).
- Muhtemel kurulum ayrı bir durum olarak gösteriliyor: detay panelinde "Probably Ollama (id: …)", "Installed" filtresi ve "kurulu önce" sıralaması bu modelleri de kapsıyor; Run hangi motor id'sini çalıştıracağını tooltip'te yazıyor.

### Changed
- **Model indirme tek diyalog**: eskiden sırayla dört soru soruluyordu — güvenilmez kaynak uyarısı, kaynak listesi, "Ollama kapalı, başlatılsın mı?", sonra tag istemi — ve her cevap bir sonraki soru görünmeden veriliyordu. Yeni `DownloadSourceDialog` hepsini tek ekranda topluyor: kaynak seçenekleri (hazır motorlar önce, durumlarıyla: `ready` / `off — will be started first`), yalnız Ollama'ya ait **tag alanı** (tahminle dolu, düzenlenebilir) ve güvenilmez yayıncı uyarısı **satır içi** — onay kutusu işaretlenmeden Download düğmesi açılmıyor. Kaynak seçimine göre tek satır açıklama ne olacağını söylüyor; GGUF'ta repo/dosya seçimi (ve quant) eskisi gibi bir sonraki adımda.
- My Models'te motor uyarıları sıkıştırıldı: kapalı motorların hepsi tek satırda, her biri kendi **Start** düğmesiyle; eksik motorlar ayrı ve soluk tek satır. Önceden 4 motorlu bir makinede 3 ayrı kart tabloyu aşağı itiyordu.

### Fixed
- **Ollama tag tahmini düzeldi**: `DeepSeek-R1-Distill-Qwen-7B` artık `deepseekr1distillqwen:7b` (geçersiz) değil `deepseek-r1:7b` öneriyor. Kütüphane adlandırması HuggingFace adından farklı: yayıncı öneki, provenance/ayar kelimeleri (`distill`, `instruct`…) atılıyor ve sürüm ayrı kelimeyse birleştiriliyor (`Llama-3.1-8B` → `llama3.1:8b`) ama ikinci bir aile kelimesi tireyle bağlanıyor (`Qwen2.5-Coder-7B` → `qwen2.5-coder:7b`). `models.ollama_tag_candidates` birden çok aday döndürüyor ve diyalog hepsini seçilebilir sunuyor.
- **Motor popup'ındaki satırlar artık kendi motorundan güncelleniyor**: popup satırları yenilenirken konuma göre eşleştiriliyordu (`zip(providers, actions)`) ve zaten çalışmıyordu — `QWidgetAction` ilk verilen widget'ı koruduğu için yeni satır hiç görünmüyordu. Sonuç: algılama listesi değiştiğinde bir satır başka motorun durumunu gösterebiliyordu ve popup içindeki "Starting…/Stopping…" hiç çıkmıyordu. Satırlar artık motor adına bağlı (`_ProviderRow`, yerinde güncelleme) ve yalnızca kendi motorundan güncelleniyor; kaybolan motor son satırını koruyor.
- **Kurulu-model eşleştirmesi**: katalog adı ile motorun kendi model id'si arasındaki fark artık kayboluyor. `models.match_installed_ids` iki geçişli çalışıyor — birebir eşleşen giriş motor id'sini "sahiplenir", artakalan id'leri kapsama (subset) eşleşmesi alır ve "muhtemelen kurulu" olarak işaretlenir. Böylece `DeepSeek-R1-Distill-Qwen-7B` ↔ `deepseek-r1:7b` gibi adlar ve `nomic-embed-text-v1.5` ↔ `nomic-embed-text:latest` gibi boyut token'ı olmayan adlar görünür; `gemma-2-2b-jpn-it` ise `gemma2:2b`'yi çalmaya devam edemez (v0.1.14 koruması korunuyor).
- **Embedding modelleri artık sohbet için sunulmuyor**: `models.is_chat_model` ile Run yolu (detay paneli, sağ tık menüsü, `_on_run_requested`) kapatıldı; "Runs" trafik ışığı bu modellerde "No chat" diyor ve analiz notu nedenini yazıyor. Önceden bir embedder kuruluysa Run açılıp motor tarafında hata veriyordu.
## [0.1.30] - 2026-09-18
### Changed
- **Kullanıcıya görünür davranış değişikliği yok** — bu sürüm kalite, test ve derleme altyapısını taşır; arayüz ve model akışları 0.1.29 ile aynı.
- Sürüm metadatası senkronlandı: `pyproject.toml`, `nameweaver.iss` ve `file_version_info.txt` 0.1.12'de kalmıştı; artık `version.py` ile aynı. (Yayınlar etkilenmemişti: `release.yml` ve `build.bat` sürümü git tag'inden enjekte ediyor. Ama elle `ISCC nameweaver.iss` çalıştıran biri 0.1.12 installer üretiyordu.)
- `ruff format` tüm ağaca uygulandı: satır sonları artık formatter'ın; elle satır bölme bırakıldı.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) sürüm kontrolüne alındı; CHANGELOG'daki 0.1.26–0.1.29 boşluğu kapatıldı.

### Added
- **CI kapıları**: `ruff check .` ve `ruff format --check .` (bloklayıcı), çekirdek modüller için **bloklayıcı `mypy`** (PyQt katmanı bilgilendirici), testler `--cov` ile ve **%58 kapsam tabanıyla**.
- **Arayüz testleri** (`tests/test_ui_smoke.py`, 17 test): ana pencere ve birincil akış (donanım → skorlama → skora göre sıralı tablo), detay paneli aksiyon kuralları (GGUF indirilebilir · Run yalnızca kuruluyken · AWQ/GPTQ'da ikisi de kapalı), tüm widget/diyalogların kurulması, ve güncelleyicinin doğrulanmamış installer'ı çalıştırmayı reddetmesi. Qt offscreen platformda koşar (masaüstü oturumu gerekmez).
- **Güncelleme ve motor kontrolü testleri** (`tests/test_updater.py` 22 test, `tests/test_provider_control.py` 11 → 29 test): sürüm karşılaştırma, `.exe` asset seçimi, atlanan sürüm deposu, `UpdateChecker`'ın dört kararı; kur komutu allowlist'i (üretmediği komutu reddeder, yalnızca Linux `curl|sh` kabuktan geçer) ve model silme yolları.
- Test kapsamı %34 → **%59** (updater %25 → %39, `provider_control` %30 → %51).

## [0.1.29] - 2026-09-10
### Reverted
- 0.1.26–0.1.28'de eklenen **canlı HuggingFace arama** geri alındı (`2cf57c3`): arama kutusu, `HFSearchWorker`, kırpılmış-sorgu/URL fallback'leri ve filtre çubuğundaki sonuç-gösterme yardımcısı kaldırıldı. Katalog yeniden v0.1.25 davranışında: popular/trending taraması + yalnızca **yüklenmiş modeller üzerinde** filtre araması.
- Not: 0.1.26–0.1.28 installer'ları yayınlandığı için bu sürümler **bir geri adım**; kullanıcı tarafında görünür işlev kaybı yok, özellik zaten istenen davranış değildi.

## [0.1.28] - 2026-09-10
### Fixed
- HF araması: yapıştırılan **tam HuggingFace URL'si veya `owner/name` kimliği** artık arama uç noktasına düz metin olarak gönderilmiyor — repo kimliği ayrıştırılıp model doğrudan çekiliyor, yalnızca isabet yoksa metin aramasına düşülüyor.
- HF araması: eklenen sonuçlar artık aktif **PC-Load / Min-TPS / Fit** filtrelerinin arkasında kalıp listenin dibine düşmüyor; katalog aranan ada filtrelenip donanım filtreleri temizleniyor.

### Added
- HF araması: boyut token'ı olmayan (ör. `...-Flash-Base`) modellerin boyutu `safetensors.total` üzerinden tahmin ediliyor.

## [0.1.27] - 2026-09-10
### Fixed
- HF araması: HuggingFace araması birebir olduğu için hafif yanlış bir ad (ör. var olmayan `DeepSeek-V4.1-Flash-Base`) sıfır sonuç döndürüyordu. `search_catalog` artık sırayla: birebir sorgu → sondaki değişken ekleri (`Base`/`Instruct`/`GGUF`/`FP8`/`MLX`…) kırpılmış sorgu → bir segment daha kırpılmış sorgu deniyor, böylece yakın isim gerçek repoyu buluyor.

## [0.1.26] - 2026-09-10
### Added
- Katalog artık yalnızca ilk ~300 popular/trending modelle sınırlı değil: filtrenin üstünde ayrı ve açıkça etiketlenmiş **"HuggingFace'te ara"** satırı HF üzerinde canlı arama yapıp bulunanları kataloğa ekliyor (`hf_api.search_catalog`, `HFSearchWorker`).
- `HFSearchWorker` bulunanları cache'e **ekliyor** (üzerine yazmıyor) ve kaç yeni model eklendiğini bildiriyor.

## [0.1.25] - 2026-09-04
### Changed
- Vision olmayan bir modele resim gönderince gelen ham "HTTP 400 Bad Request" yerine artık net mesaj: "Bu model resim okuyamaz — qwen2.5vl / llava / gemma3-vision gibi bir vision model kullan." (Resimsiz 400'ler eskisi gibi ham gösterilir.)

## [0.1.24] - 2026-09-04
### Fixed
- Otomatik güncelleme "kapanıyor ama kurmuyor": installer artık `/VERYSILENT` yerine **`/SILENT` (görünür ilerleme) + `/FORCECLOSEAPPLICATIONS`** ile çalıştırılıyor — çalışan uygulama zorla kapatılıp kurulum tamamlanıyor ve hata olursa görünür oluyor. (Not: bu düzeltmenin etkili olması için v0.1.24 bir kez **elle** kurulmalı; sonraki güncellemeler otomatik çalışır.)

## [0.1.23] - 2026-09-04
### Added
- Chat cilası: mesaj **avatarları** (sen/asistan yuvarlak ikon), balonlara **hafif gölge** + ferah boşluk, **zaman damgası**, ve **"düşünüyor" animasyonu** (ilk token gelene kadar yanıp sönen noktalar).
- **Resim sürükle-bırak**: görseli pencereye bırakarak ekle. Image butonu artık **her modelde açık**; vision değilse tek seferlik uyarı verir ama denemene izin verir.
- Input kutusu **yuvarlak** ve içerikle **otomatik büyüyor** (max yükseklikte durur).

## [0.1.22] - 2026-09-04
### Added
- Chat baştan tasarlandı — **balon arayüzü**: kullanıcı sağda (vurgu rengi), asistan solda; yuvarlak köşe, avatar/etiket.
- **Kod blokları**: monospace + kutu + **kod-başına Copy** butonu; pygments varsa syntax highlighting, yoksa düz (graceful).
- **Zengin Markdown**: tablo, sıralı/sırasız liste, başlık, alıntı, link, kalın/italik/inline-kod (hepsi güvenli/escape'li).
- **Streaming göstergesi**: yazarken yanıp sönen imleç; token akışında verimli güncelleme (bitince markdown'a dönüşür).
- **Mesaj-başına aksiyonlar** (asistan): Copy, Regenerate, 👍/👎.
- **Canlı istatistik**: token/sn ve toplam kelime; **boş-durum** karşılaması; sadece en alttaysan otomatik-scroll.

## [0.1.21] - 2026-08-24
### Fixed
- Chat gönderince çökme (`QTextCursor has no attribute MovePosition`) düzeltildi — PyQt6 enum adı `MoveOperation` olmalıydı. Streaming artık sorunsuz.

## [0.1.20] - 2026-08-24
### Added
- Zengin chat: **konuşma geçmişi** (multi-turn — model önceki mesajları hatırlar), **Markdown/kod bloğu render**, vision modellerine (qwen2.5vl/llava/gemma3-vision) **resim yükleme** (normal modellerde buton kapalı), ve kontroller: **system prompt**, **Stop**, **Regenerate**, **Copy last**, **Clear**. Enter gönderir, Shift+Enter yeni satır.

## [0.1.19] - 2026-08-24
### Reverted
- "My Models" (v0.1.18) geri alındı — istenmedi.

## [0.1.17] - 2026-08-24
### Fixed
- "Installed" filtresi artık her açılışta **kapalı** başlıyor (tüm modeller görünür); istersen elle açarsın. Önceki oturumdan işaretli kalmıyor.

### Changed
- Yerel motorların çalıştıramayacağı formatlar (AWQ/GPTQ) için detay panelinde ve sağ tık menüsünde **Download ve Run kapatıldı**; tooltip/not "GGUF sürümünü kullan" diyor. Böylece AWQ satırında boşuna indirme/çalıştırma denenmiyor.

## [0.1.16] - 2026-08-24
### Changed
- Chat penceresinde artık **yalnızca modeli gerçekten içeren, çalışan motorlar** seçilebiliyor. Modeli içermeyen bir motoru seçip 404 alma durumu kalktı; model çalışan hiçbir motorda yoksa net "önce indir" / "motoru başlat" uyarısı çıkar.
- LM Studio model kaldırma: dosya LM Studio'nun model klasöründe bulunamazsa (LM Studio kendi yönettiği modeller) artık kafa karıştırıcı "not found on disk" yerine, kullanıcıyı **LM Studio → My Models**'tan silmeye yönlendiren net bir mesaj gösteriliyor. (Ollama kaldırma ve klasördeki gerçek GGUF dosyalarını silme aynen çalışıyor.)

## [0.1.15] - 2026-08-24
### Fixed
- Parametre sayısı ayrıştırma hatası: "135M" gibi milyon (ve "83K" bin) değerleri artık milyar sayılmıyor. SmolLM-135M artık "135.0 B / Huge / 42 GB" yerine doğru şekilde küçük görünüyor.

### Added
- Model kaldırma: tabloda sağ tık → "Remove from …" ile kurulu modeli motordan sil (Ollama API delete; LM Studio disk klasörü, güvenli kontrol + onay). Kaldırınca liste yenilenir.
- "Hangi motorda kurulu" görünürlüğü: detay panelinde **Installed:** satırı motor adlarını gösteriyor; sağ tık menüsü de "Remove from Ollama/LM Studio" diye yazıyor.
- Detay panelinde **Runs** durumu: AWQ/GPTQ gibi çalışmayan formatlar için "won't run on your local engines (they run GGUF)" notu — "No engine" ile Run Mode/Fit arasındaki çelişki giderildi.

## [0.1.14] - 2026-08-24
### Fixed
- Kurulu-model eşleştirmesindeki yanlış pozitif giderildi: `gemma-2-2b-jpn-it` gibi bir varyant, sende kurulu olan farklı bir modele (`gemma2:2b`) artık yanlışlıkla "yüklü" eşleşmiyor. Eşleşme boyut + kimlik token'larına (aile/sürüm/varyant) bakıyor; sadece jenerik etiketleri (instruct/chat/quant/format) ve yayıncı önekini yok sayıyor.
- `_pick_ollama_candidate` çökmesi (`NameError: 're' is not defined`) düzeltildi — Ollama'ya indirme/pull artık çökmüyor.

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
