# Nameweaver — Mimari & Proje Yapısı Dokümantasyonu

> **Nameweaver**: LLM modellerini senin donanımına "doğru boyutlandıran" (right-size) bir PyQt6 masaüstü uygulaması.
> Sürüm: `0.1.29` · Lisans: MIT © 2026 thealps01-netizen · Platform hedefi: Windows (kod çok-platform hazır)

---

## 1. Uygulama Ne Yapar? (Özet)

Nameweaver, yüzlerce açık kaynak LLM modelini bir katalogda toplar, **senin bilgisayarının donanımını otomatik tespit eder** (CPU/RAM/GPU/VRAM/bellek bant genişliği), ve her modelin bu donanımda **ne kadar iyi çalışacağını** puanlayarak sıralar. Ardından:

- Modeli yerel motorlara (**Ollama / LM Studio / llama.cpp / Docker Model Runner**) **indirir**,
- **çalıştırır** ve içinde **sohbet** etmeni sağlar (streaming, çok-turlu geçmiş, vision/resim, Markdown+kod render),
- HuggingFace'ten kataloğu **canlı günceller**,
- kendini GitHub Releases üzerinden **otomatik günceller**.

Çekirdek değer: "Bu modeli açsam PC'm kaldırır mı? Ne kadar hızlı olur? Hangi quant'ı seçmeliyim?" sorularına **tek bakışta** cevap vermek.

---

## 2. Katmanlı Mimari

Uygulama net bir **çekirdek (saf mantık) / UI (PyQt)** ayrımına sahiptir. Çekirdek modüller PyQt'ye bağımlı değildir ve doğrudan test edilir; UI katmanı bunları QThread worker'ları üzerinden çağırır.

```
┌──────────────────────────────────────────────────────────────────────┐
│  UI KATMANI (PyQt6)                                                     │
│  app.py (MainWindow, QStackedWidget: Catalog | My Models)               │
│         ── widgets/*  ── dialogs.py ── themes.py                        │
│         │                                                               │
│         │ sinyaller / slotlar                                           │
│         ▼                                                               │
│  workers.py  (QThread'ler — tüm ağır iş arka planda)                    │
└─────────┬──────────────────────────────────────────────────────────────┘
          │ çağırır (PyQt'siz, saf Python)
          ▼
┌──────────────────────────────────────────────────────────────────────┐
│  ÇEKİRDEK MANTIK KATMANI                                                │
│  hw.py         → donanım tespiti (CPU/RAM/GPU/VRAM/bant genişliği)      │
│  models.py     → model kataloğu + LlmModel veri modeli + bellek tahmini │
│  scoring.py    → fit/skor motoru (run mode, TPS, fit level, sıralama)   │
│  providers.py  → motor tespiti (kurulu mu / çalışıyor mu / kaç model)   │
│  provider_ctrl → motor başlat/durdur/kur/model sil                     │
│  runner.py     → inference (Ollama & OpenAI-uyumlu streaming chat)      │
│  downloader.py → model indirme (Ollama pull / HF GGUF)                 │
│  hf_api.py     → HuggingFace katalog güncelleme + cache                 │
│  cfg.py        → config (JSON) + logging                                │
│  updater.py    → otomatik güncelleme (GitHub Releases)                 │
└──────────────────────────────────────────────────────────────────────┘
          │ veri kaynağı
          ▼
   data/models.json  (~925 model, gömülü katalog)  +  HF cache (kullanıcı dizini)
```

**Neden bu ayrım?** Çekirdek modüller "thread-safe" ve saf olduğu için (`SystemSpecs.detect()` her thread'den çağrılabilir), UI donmadan ağır işleri worker'lara atabiliyor ve mantık PyQt olmadan pytest ile test edilebiliyor.

---

## 3. Dosya Dosya Detaylı Referans

### 3.1 Giriş Noktası & Ana Pencere

#### `app.py` (~94 KB — en büyük dosya, tüm UI orkestrasyonu)
Uygulamanın kalbi. Sorumlulukları:

- **`_acquire_single_instance()`** — Tek örnek kilidi (aynı anda iki Nameweaver açılmasını engeller).
- **`_install_crash_handler()`** — Global `sys.excepthook`; yakalanmamış hataları loglar ve kullanıcıya gösterir (projedeki **tek** crash handler — eski `crash_handler.py` silinmiş).
- **`_setup_dpi()`** — Yüksek DPI/ölçekleme ayarı.
- **Özel çerçevesiz pencere bileşenleri**: `_RoundedPanel`, `_GradientTitleBar`, `_SidebarWidget`, `_gradient_sep()` — yuvarlak köşeli, gradyanlı, özel başlık çubuklu modern görünüm (`paintEvent` ile elle çizim).
- **`MainWindow(QMainWindow)`** — Asıl uygulama penceresi. İçindeki başlıca akışlar:
  - **Tema**: `_apply_theme`, `_set_theme`, `_show_theme_picker`, Windows DWM koyu başlık çubuğu (`_apply_dwm_dark_title_bar`, `_set_title_bar_color`).
  - **Donanım akışı**: `_start_detection` → `_on_hardware_detected` → `_on_gpu_selection_changed` (GPU'ları etkinleştir/devre dışı bırak).
  - **Motor akışı**: `_on_providers_detected`, `_on_engine_start_requested/_finished`, `_on_engine_stop_requested/_finished`, `_on_engine_install_requested`.
  - **Skorlama akışı**: `_start_scoring` → `_on_scoring_complete`; `_on_preference_changed` (hız↔kalite tercih kaydırıcısı).
  - **HF güncelleme**: `_start_hf_update`, `_on_hf_progress/_finished/_error`.
  - **Filtreleme & seçim**: `_apply_filters`, `_reset_to_dashboard`, `_on_model_selected`.
  - **İndir/çalıştır çözümleme**: `_pick_ollama_candidate`, `_resolve_gguf_repo` (kataloğ adı → gerçek motor kimliği / HF repo eşleştirmesi — 404'leri önlemek için kritik mantık).
  - **Kapanış**: `closeEvent` pencereyi anında gizler, thread'lere paralel dur sinyali yollar, sınırlı bekler (v0.1.4 donma düzeltmesi).
  - Üst bilgi kartları: `_make_stat_card`, `_update_stat_cards`.

---

### 3.2 Çekirdek Mantık Modülleri

#### `hw.py` (~34 KB) — Donanım Tespiti
Çok-platform, çok-vendor donanım keşfi. **PyQt'siz**, her thread'den güvenli.

- **`SystemSpecs`** (dataclass): `total_ram_gb`, `available_ram_gb`, `cpu_name`, `total_cpu_cores`, `has_gpu`, `gpu_vram_gb`, `total_gpu_vram_gb`, `gpu_count`, `gpu_backend`, `unified_memory`, `gpus: list[GpuInfo]`, `gpu_bandwidth_gbps`.
  - `detect()` → CPU/RAM + GPU tespitini çalıştırır.
  - `with_overrides(ram, vram, cores)` → **donanım simülasyonu** için kopya üretir ("bende 64 GB olsa ne olurdu?").
- **`GpuInfo`** (dataclass): `name`, `vram_gb`, `backend`, `count`, `unified_memory`, `bandwidth_gbps`, `vendor`, `pci_id`, `integrated`, `enabled`.
- **`GpuBackend`** (Enum): CUDA/ROCm/Metal/Vulkan vb.
- **Vendor-spesifik dedektörler**: `_detect_nvidia` (nvidia-smi + bant genişliği hesabı), `_detect_apple_silicon` (unified memory), `_detect_windows_gpu` (WMI), `_detect_linux_gpu`, `_try_rocm_vram` (AMD), `_try_intel_arc_sysfs`, `_detect_ascend` (Huawei).
- **Bant genişliği**: `GPU_BANDWIDTH_TABLE` (llmfit `hardware.rs`'ten alınmış GB/s tablosu), `_lookup_bandwidth`, `_compute_nvidia_bandwidth_gbps` (bus width × mem clock).
- **Çoklu-GPU yardımcıları**: `enabled_gpus`, `enabled_vram_gb`, `effective_bandwidth_gbps`, `has_mixed_backends`, `apply_disabled_list` (kullanıcının kapattığı GPU'lar).

#### `models.py` (~21 KB) — Model Veri Modeli & Katalog
- **`LlmModel`** (dataclass) — Bir modelin tam spesifikasyonu:
  `name, provider, parameter_count("7B"/"8x7B"/"135M"), ram_gb, vram_gb, format, quantization, n_layers, attention_heads, hidden_dim, vocab_size, ctx_length, use_case, capabilities[], expert_count, active_experts, license, release_date, base_model`.
  - `params_b()` — "7B"→7.0, "135M"→0.135, "8x7B"→56.0 çevirimi (v0.1.15'te M/K/B ayrımı düzeltildi).
  - `is_moe()`, `active_params_b()` — MoE (uzman karışımı) modeller.
  - `estimate_disk_gb()`, `estimate_memory_gb(quant, ctx)`, `_kv_cache_gb()` — quant + KV cache dahil bellek tahmini.
  - `best_quant_for_budget()` — bütçeye sığan en iyi quant.
  - `get_use_case()`, `has_capability()`.
- **Enum'lar**: `UseCase`, `ModelFormat`, `Capability`, `KvQuant`.
- **Kaynak güveni & uyumluluk**:
  - `is_official_provider`, `base_model_owner`, `is_reupload` (bartowski/TheBloke gibi yeniden yükleyenleri tespit), `is_trusted_source` — güven rozetleri için.
  - `is_engine_compatible` / `_supported_formats` — AWQ/GPTQ gibi yerel motorların çalıştıramadığı formatları işaretler.
  - `size_class(params_b)` → Tiny/Small/Medium/Large/XL/Huge.
- **İsim eşleştirme** (kurulu model tespitinin kalbi): `normalize_model_name`, `_size_token`, `_core_tokens`, `_names_match`, `name_matches_installed` — `Llama-3.1-8B-Instruct` ↔ `llama3.1:8b` eşleşmesi; boyut + kimlik token'larına bakar, jenerik etiketleri yok sayar (v0.1.5 & v0.1.14 yanlış-pozitif düzeltmeleri).
- **Katalog yükleme**: `load_models` (gömülü `data/models.json`), `load_cached_models` (HF cache), `merge_models`, `load_all_models` (ikisini birleştirir).

#### `scoring.py` (~25 KB) — Fit & Skor Motoru
Her modeli donanıma göre analiz eden çekirdek. **En kritik iş mantığı burada.**
- **`ModelFit`** (dataclass): `model, fit_level, run_mode, memory_required_gb, memory_available_gb, utilization_pct, score, score_components, estimated_tps, best_quant, notes[], installed, installed_providers[], likely_providers[], engine_ids{}` (`engine_ids` motor id'lerini taşır; muhtemel eşleşmeler yalnız My Models'ta kullanılır).
- **`rank_models`** yalnız TOO_TIGHT sona atar + seçili sütuna göre sıralar; **kurulu olmak sıralamayı etkilemez** (katalog bir alışveriş listesidir, "neye sahibim" My Models'ta).
  - `analyze(model, specs, ...)` — Ana giriş; bir modeli tam analiz eder.
- **`FitLevel`** (Enum): TOO_TIGHT → ... → PERFECT (rank + `short_hint`).
- **`RunMode`** (Enum): CPU_ONLY / GPU / offload vb. — `_determine_run_mode`.
- **`ScoreComponents`**: `quality`, `speed`, `fit` (üç bileşen).
- **Skor hesabı**: `_quality_score`, `_speed_score`, `_fit_score`, `_weighted_score`, `_compute_scores`.
- **Hız tahmini**: `_estimate_tps` (bant genişliği tavanı × gerçekçi 0.55 verimlilik katsayısı, 300 tok/s tavan — v0.1.9), `_cpu_tps_estimate`.
- **Kullanıcı dostu göstergeler**: `pc_comfort` → Effortless/Comfortable/Demanding/Heavy/Too much (v0.1.8), `runnability` → 🟢/🟡/🔴 trafik ışığı (v0.1.9).
- **Sıralama & tercih**: `apply_preference(fits, preference)` (0=hız, 1=kalite), `rank_models`, `analyze_all` (tüm kataloğu skorlar), `SortColumn` (Enum).

#### `providers.py` (~11 KB) — Motor Tespiti (salt-okunur)
Kurulu ve/veya çalışan yerel inference motorlarını keşfeder.
- **`ProviderStatus`** (dataclass): motor adı, durum, model listesi, `model_count`.
- **`ProviderState`** (Enum): kurulu değil / kurulu ama kapalı / çalışıyor.
- Dedektörler: `detect_ollama` (HTTP API), `detect_lm_studio` (HTTP + **disk taraması** — sunucu kapalıyken bile kurulu modelleri görür, v0.1.12), `detect_llamacpp`, `detect_docker_model_runner`, `detect_all_providers`.
- **`list_installed_models()`** — motorların **kendi bildirdiği** kurulu modeller (`InstalledModel`): Ollama `/api/tags` (boyut, parametre, quant, motorun kendi `capabilities`'i), LM Studio `/v1/models` + `.gguf` disk taraması (sunucu kapalıysa `reported_by_engine=False` → listelenir ama çalıştırılamaz). Katalogdan bağımsızdır; My Models sayfası bunu kullanır.
- Kurulum tespiti: `_ollama_is_installed`, `_lmstudio_is_installed`, `_docker_is_installed` + installer URL'leri.
- LM Studio disk mantığı: `_lmstudio_models_dir` (`settings.json`'daki `downloadsFolder`'ı okur), `_scan_lmstudio_disk_models`.

#### `provider_control.py` (~20 KB) — Motor Kontrolü (yan-etkili)
Motorları başlat/durdur/kur ve model sil.
- **Başlat**: `start_ollama_service` (`ollama serve`, **CREATE_NO_WINDOW** ile — v0.1.10 cmd penceresi düzeltmesi), `start_lmstudio_server`, `open_lmstudio_app`, `start_docker_model_runner`, `start_provider(action_key)`.
- **Durdur**: `stop_ollama_service`, `stop_lmstudio_server`, `stop_docker_model_runner`, `stop_provider`. `_wait_for_http_ready` / `_wait_for_http_gone` ile hazır/kapandı bekler.
- **Kurulum**: `suggested_install_command`, `open_installer_page`, `run_install_command` (allowlist: `_known_install_commands`).
- **Model silme**: `remove_model` → `_remove_ollama` (API delete), `_remove_lmstudio` (disk + güvenli kontrol; LM Studio yönetiyorsa kullanıcıyı "My Models"a yönlendirir — v0.1.16).
- Windows'ta tüm konsol çağrıları `_hidden_startupinfo` / gizli pencereyle sarmalanır.

#### `runner.py` (~11 KB) — Inference / Chat
Model çalıştırma ve streaming sohbet.
- **Ollama**: `run_ollama`, `chat_ollama` (Ollama chat API, çok-turlu).
- **OpenAI-uyumlu** (LM Studio, Docker): `_run_openai_compatible`, `run_lm_studio`, `run_docker_model_runner`.
- **SSE streaming**: `_post_stream`, `_parse_sse_data`.
- **Mesaj biçimleri**: `_build_messages`, `_to_ollama_messages`, `_to_openai_messages` (system prompt + geçmiş + resim desteği).
- **Yönlendirme**: `chat_model`, `run_model`, `available_providers_for_model`, `installed_model_ids` — modeli **gerçekten içeren** çalışan motora yönlendirir; Ollama'ya kataloğ adı değil gerçek tag (`gemma2:2b`) gönderir (v0.1.13 404 düzeltmesi).

#### `downloader.py` (~9 KB) — Model İndirme
- `pull_ollama(...)` — Ollama pull, ilerleme callback'i (`emit`), 300 sn timeout (v0.1.13).
- `download_gguf(...)` — HuggingFace'ten GGUF dosyası indirme (`_build_hf_request` token desteği). `expected_sha256` verilirse akış sırasında hash hesaplanır ve **uyuşmazsa dosya silinir** (`list_gguf_files` HF'nin `lfs.oid` değerini `sha256` olarak taşır, `sha256_for_file` ile seçilir).
- `list_gguf_files(repo_id)` — Repodaki GGUF varyantlarını listeler (quant seçimi için).

#### `hf_api.py` (~16 KB) — HuggingFace Katalog Güncelleme
- **`HuggingFaceAPI`** sınıfı: `search_models`, `fetch_trending`, `fetch_popular`, `fetch_model_config`, `convert_to_llm_model` (HF entry → `LlmModel`).
- **Çıkarım yardımcıları**: `extract_param_count`, `infer_use_case`, `infer_capabilities`, `infer_ctx_length`, `estimate_memory_gb`.
- **Cache**: `cache_path`, `save_cache` (atomik yazım — v0.1.4), `read_cache_meta`, `update_catalog`.
- Not: v0.1.26'da eklenen "canlı HF arama" özelliği son commit'te **v0.1.25 davranışına geri alındı** (git log: `2cf57c3`).

#### `cfg.py` (~5 KB) — Config & Logging
- `config_dir()`, `log_dir()` — kullanıcı-başına dizinler.
- **`AppConfig`** (dataclass, JSON'a serileşir): `theme, window_width/height/x/y, splitter_sizes, last_sort_column/order, filters, hw_overrides, check_updates_on_start, hf_token, last_hf_update, disabled_gpus, score_preference`. `validate()` tüm değerleri güvenli aralığa clamp'ler.
- `load_config` — **bozuk dosya kurtarma** (yedekler, defaults'a döner), `save_config` — **atomik** (temp + `os.replace`).
- `setup_logging` — projedeki **tek** log kurulumu.

#### `updater.py` (~27 KB) — Otomatik Güncelleme
GitHub Releases tabanlı kendi kendini güncelleme.
- **`UpdateChecker(QObject)`** — arka planda son sürümü çeker (`_fetch_latest`, `_is_newer`, `_parse`), yeni sürüm sinyali yayar.
- **`InstallerDownloader(QObject)`** — installer'ı indirir.
- **Diyaloglar**: `UpdateDialog` (güncelle/atla/sonra), `DownloadProgressDialog`, `_ErrorDialog` — hepsi `_DraggableDialog` + `_Panel` (özel çizim) tabanlı.
- **`prompt_and_install(tag, url, notes)`** — indir → **SHA256 doğrula** (sidecar yoksa/eşleşmezse iptal — v0.1.13) → installer'ı `/SILENT /FORCECLOSEAPPLICATIONS` ile çalıştır (v0.1.24).
- "Atlanan sürüm" `update_skip.json`'da tutulur (app config şemasından bağımsız — v0.1.2).

---

### 3.3 UI Katmanı

#### `workers.py` (~12 KB) — Arka Plan Thread'leri (QThread)
UI'yı dondurmadan ağır işleri çalıştırır; sonuçları sinyalle döner:
| Worker | Görev |
|---|---|
| `HardwareWorker` | `SystemSpecs.detect()` |
| `ProviderWorker` | tek seferlik motor tespiti |
| `InstalledModelsWorker` | My Models için motorların kurulu modellerini toplama (HTTP + disk) |
| `ProviderPoller` | periyodik motor durumu (varsayılan 10 sn) |
| `ProviderStartWorker` / `ProviderStopWorker` | motor başlat/durdur |
| `ScoringWorker` | `analyze_all` katalog skorlama |
| `ModelLoadWorker` | katalog yükleme |
| `InferenceWorker` | streaming chat (cancel destekli) |
| `DownloadWorker` | model indirme (cancel + ilerleme + `expected_sha256`) |
| `InstalledModelsWorker` | motorların kurulu model listesi (HTTP + disk, UI thread'i bloklamadan) |
| `HFUpdateWorker` | HF katalog güncelleme |

#### `widgets/` — Yeniden Kullanılabilir UI Bileşenleri
| Dosya | Sınıf(lar) | Görev |
|---|---|---|
| `model_table.py` | `ModelTableModel`, `ModelFilterProxy`, `ModelTableView` | Ana model tablosu (Qt Model/View); filtre-proxy ile sıralama+süzme, sağ-tık menüsü (indir/çalıştır/sil) |
| `detail_panel.py` | `DetailPanel`, `ScoreBar` | Seçili model detayları + Match/Fit skor çubukları; aksiyonu **Download** (Run bilinçli olarak yok — çalıştırma My Models'ta) |
| `comparison.py` | `ComparisonDialog` | Modelleri yan yana karşılaştırma |
| `chat_dialog.py` | `ChatDialog`, `_Bubble`, `_CodeBlock`, `_highlight_code` | Balon arayüzlü sohbet; avatar, zaman damgası, "düşünüyor" animasyonu, kod-başına Copy, pygments highlight, resim sürükle-bırak |
| `download_dialog.py` | `DownloadDialog`, **`DownloadSourceDialog`**, `GgufPickerDialog`, `GgufMirrorPickerDialog` | `DownloadSourceDialog` indirme kararını tek ekranda toplar (kaynak + Ollama tag + güven onayı); diğerleri ilerleme ve GGUF varyant/ayna seçimi (`_detect_quant`) |
| `engine_status.py` | `EngineStatusPill`, `_ProviderRow` | Motor durumu "pill"i (`_overall_state`, `_pick_primary`); popup satırları motor adına bağlı ve **yerinde** güncellenir |
| `filter_bar.py` | `FilterBar` | Üst filtre çubuğu (use case, boyut, PC Load, arama, min TPS) — katalogda "kurulu" filtresi yok |
| `hw_sim.py` | `HardwareSimPanel` | Donanım simülasyonu (RAM/VRAM/çekirdek override) |
| `markdown_render.py` | `md_to_html`, `split_segments`, `_inline`, `_table_html` | Güvenli Markdown→HTML (tablo/liste/kod, escape'li) |
| `status_bar.py` | `AppStatusBar` | Alt durum çubuğu |
| `my_models.py` | `MyModelsView` | **My Models** sayfası — motorların bildirdiği kurulu modeller (boyut/parametre/quant, katalog bağlantısı), satır başına **Run**, Remove/Show in Catalog |
| `system_bar.py` | `SystemBar`, `_SysCard` | Üstte sistem donanım kartları |

#### `dialogs.py` (~11 KB)
- `AboutDialog` — Hakkında + "Güncellemeleri Denetle" butonu (v0.1.4).
- `AlertDialog` — Genel uyarı diyaloğu. İkisi de sürüklenebilir, temalı.

#### `themes.py` (~19 KB)
- **`ThemeColors`** (dataclass) — bir temanın tüm renkleri.
- `get_theme(name)` — 6 tema: **dark, light, dracula, nord, gruvbox, solarized**.
- `generate_qss(colors)` — temadan Qt Style Sheet üretir.

---

### 3.4 Veri

#### `data/models.json` (~925 model)
Gömülü model kataloğu. Her giriş `LlmModel` alanlarıyla birebir eşleşir (name, provider, parameter_count, ram_gb, vram_gb, format, quantization, n_layers, attention_heads, hidden_dim, vocab_size, ctx_length, use_case, capabilities, expert_count, active_experts, license, release_date). PyInstaller ile `.exe` içine paketlenir (`Nameweaver.spec` → `datas`).

#### `tools/`
- `convert_llmfit_models.py` + `llmfit_raw_models.json` — llmfit ham verisini `models.json` formatına çevirir (kataloğun kaynağı).
- `make_icon.py` — `nameweaver.ico` üretir (build sırasında çalışır).

---

### 3.5 Test (`tests/` — 17 test dosyası, 341 test, ~3.520 satır)
`pytest` + `pytest-qt`. Kapsam tabanı **%58** (ölçülen %60; `tests/` ve `tools/` raporun dışında).

**Saf çekirdek (PyQt'siz):** `test_hw.py`, `test_models.py`, `test_model_classification.py`, `test_scoring.py` (en büyük — 427 satır), `test_providers.py`, `test_provider_control.py`, `test_runner.py`, `test_downloader.py`, `test_hf_api.py`, `test_engine_status.py`, `test_markdown_render.py`, `test_themes.py`, `test_version.py`.

**UI smoke (`test_ui_smoke.py`, 24 test):** PyQt katmanını offscreen platformda ( `conftest.py` → `QT_QPA_PLATFORM=offscreen`) kurar. Kapsananlar: ana pencerenin açılışı ve birincil akış (specs → skorlama worker'ı → Score sütununa göre sıralı tablo), `DetailPanel` aksiyon kuralları (GGUF'ta Download açık · Run yalnızca kuruluyken açık · AWQ/GPTQ'da ikisi de kapalı), her widget ve diyaloğun kurulması (Qt API'si yeniden adlandırıldığında ilk burada kırılır), `InstallerDownloader`'ın sidecar yokken ya da hash uyuşmazken installer'ı **çalıştırmayı reddetmesi**, f-string'lerde açılmamış `{{`/`}}` kaçışı taraması, **Catalog ↔ My Models** sayfa geçişi (`QStackedWidget`, filtre çubuğu yalnız katalogda) ve motor popup satırlarının kendi motorundan güncellenmesi. Updater testleri `file://` URL kullanır — ağ gerekmez.

**My Models (`test_my_models.py`, 12 test):** motor listelerinin ayrıştırılması (`/api/tags` alanları, LM Studio disk taraması, `capabilities: ["embedding"]`) + sayfanın satır kuralları (embedder'da Run kapalı, katalogda olmayan model yine çalıştırılabilir, boş durum, motor kapalıysa Start).

**İndirme seçimi (`test_download_source_dialog.py`, 14 test):** hangi kaynakların sunulduğu ve sırası (hazır önce, kurulu değilse hiç), Ollama tag ön-doldurması, güvenilmez yayıncıda onay kutusu kapısı, tag boşaltılınca Download'ın kapanması.

**Güncelleme kararı (`test_updater.py`, 22 test):** sürüm ayrıştırma/karşılaştırma, `.exe` asset seçimi, atlanan sürüm deposu, ve `UpdateChecker._run()`'ın dört kararı (yeni sürüm → teklif · atlanmış → sessiz · asset yok → sessiz · ağ yok → `check_failed`).

**Motor kontrolü (`test_provider_control.py`, 29 test):** `run_install_command` allowlist kapısı (üretmediği komutu reddeder), argv vs `shell=True` ayrımı (yalnızca Linux `curl|sh`), platform → paket yöneticisi eşlemesi, ve `remove_model` yolları (Ollama DELETE, 404, erişilemez motor, LM Studio "My Models" yönlendirmesi, gerçek klasör silme). `conftest.py` ortak fixture'ları sağlar.

---

## 4. Derleme & Dağıtım Hattı

```
version.py (tek sürüm kaynağı)
     │
     ▼
build.bat / release.yml
  1. pip install -r requirements-dev.txt
  2. python tools/make_icon.py           → nameweaver.ico
  3. sürümü file_version_info.txt + version.py'ye enjekte et
  4. pyinstaller Nameweaver.spec         → dist/Nameweaver/Nameweaver.exe (onedir)
  5. ISCC nameweaver.iss                  → installer/Nameweaver_Setup.exe
  6. (CI) SHA256 üret + GitHub Release oluştur
```

- **`Nameweaver.spec`** — PyInstaller yapılandırması. `data/` ve `nameweaver.ico` gömülür; kullanılmayan Qt modülleri (WebEngine, Multimedia, 3D, Charts…) + numpy/PIL/tkinter **hariç tutulur** (küçük exe). Manifest (`nameweaver.manifest`: DPI/UAC/OS uyumu) ve `file_version_info.txt` gömülür.
- **`nameweaver.iss`** — Inno Setup installer betiği (`/DAppVersion` ile sürüm alır).
- **`build.bat`** — Yerel Windows derleme; Inno Setup'ı PATH + yaygın konumlarda arar, yoksa portable exe bırakır.

### CI/CD (`.github/workflows/`)
- **`test.yml`** — her push (main) ve PR'da, windows-latest + Python 3.11: **`ruff check .`** + **`ruff format --check .`** (bloklayıcı) → **`mypy`** (bloklayıcı, `[tool.mypy] files` = çekirdek modüller) → **`mypy .`** (bilgilendirici; PyQt katmanının Qt-stub `union-attr` gürültüsü) → **`pytest tests/ --cov=. --cov-fail-under=58`** — **PR kapısı**.
- **`release.yml`** — `v*.*.*` tag push'unda: test → sürüm enjekte → icon → PyInstaller → Inno Setup → SHA256 → **GitHub Release** (otomatik notlar).

> ⚠️ **Bilinen tuzak** (hafızadan): Dev makinesi Python 3.14, CI Python 3.11. 3.12+ sözdizimi (ör. f-string `{}` içinde backslash) yerelde geçer ama CI/release build'i kırar. Sürüm çıkmadan önce buna dikkat.

---

## 5. Sürüm & Otomatik Güncelleme Döngüsü

1. Geliştirmede sürümün tek kaynağı `version.py`; **yayında kaynak git tag'i**: `git tag v0.1.x` + `git push origin v0.1.x`. Tag ile `version.py` aynı olmalı — workflow tag'deki sürümü `version.py` + `file_version_info.txt` içine enjekte eder. `pyproject.toml` ve `nameweaver.iss` içindeki sürümler yalnızca **elle** çalıştırılan araçlar için varsayılandır.
2. `release.yml` tetiklenir, GitHub Release + installer + SHA256 üretir.
3. Uygulama her açılışta `updater.py::UpdateChecker` ile son sürümü kontrol eder.
4. Yeni sürüm varsa `UpdateDialog` → indir → **SHA256 doğrula** → `/SILENT /FORCECLOSEAPPLICATIONS` ile kur.

---

## 6. Kullanıcı Akışı (Uçtan Uca)

```
Açılış
  → tek örnek kilidi + crash handler + tema
  → HardwareWorker: donanımı tespit et  ─────────────┐
  → ProviderWorker: motorları tespit et              │
  → ModelLoadWorker: kataloğu yükle (json + HF cache)│
  → ScoringWorker: her modeli donanıma göre skorla ◄─┘ (SystemSpecs)
  → tablo skora göre sıralı gösterilir (🟢/🟡/🔴, boyut, PC Load)
Görünümler (sidebar): Model Catalog = tablo + detay + donanım simülasyonu;
                       My Models = motorların kendi listesi (Run burada).
Kullanıcı:
  → filtreler / arar / hız↔kalite kaydırıcısını oynatır → yeniden sıralanır
  → bir model seçer → DetailPanel (Match/Fit, quant, TPS, bellek, güven rozeti)
  → İndir → DownloadSourceDialog (kaynak + Ollama tag + güven onayı, tek ekran)
            → DownloadWorker: Ollama pull / LM Studio GGUF / HF GGUF
  → My Models → Run (motorun kendi id'si) → ChatDialog (InferenceWorker: streaming, çok-turlu, vision)
  → My Models → Remove… / Show in Catalog
Arka planda:
  → ProviderPoller (10 sn) motor durumunu tazeler
  → UpdateChecker yeni sürüm varsa uyarır
Kapanış:
  → pencere anında gizlenir, thread'lere paralel dur, config atomik kaydedilir
```

---

## 7. Bağımlılıklar

**Runtime** (`requirements.txt`): `PyQt6>=6.6.0`, `psutil>=5.9.0`, `qtawesome>=1.3.0` (ikonlar). *Opsiyonel*: `pygments` (kod highlight — yoksa düz metin fallback).
**Geliştirme** (`requirements-dev.txt`): + `pytest`, `pytest-qt`, `pytest-cov`, `ruff`, `mypy`, `Pillow` (icon), `pyinstaller`.
**Standart kütüphane ağı**: `urllib` (harici SDK yok — HTTP çağrıları elle yapılır, hafif kalır).

---

## 8. Tasarım İlkeleri & Dikkat Çeken Kararlar

- **Saf çekirdek / PyQt UI ayrımı** → test edilebilirlik + thread güvenliği.
- **Harici ağır SDK yok** → küçük exe, hızlı açılış (`urllib`, elle SSE parsing).
- **Graceful degradation** → pygments yoksa düz kod; motor kapalıysa net yönlendirme; GPU tespiti çok-vendor fallback zinciri.
- **Yanlış-pozitif eşleştirmeye karşı sağlamlık** → kurulu model tespiti boyut + kimlik token'larıyla (defalarca sertleştirildi: v0.1.5/0.1.14/0.1.15).
- **Güvenlik** → indirilen installer SHA256 doğrulanır; güvenilmeyen kaynak/format uyarıları; config bozulmaya karşı atomik + kurtarmalı.
- **Tek sürüm kaynağı** (`version.py`) → CI tüm yerlere enjekte eder.

---

## 9. Hızlı Başvuru — Modül Haritası

| Katman | Modül | Tek cümlelik görev |
|---|---|---|
| Giriş | `app.py` | MainWindow + tüm UI orkestrasyonu |
| Çekirdek | `hw.py` | Donanım tespiti (CPU/RAM/GPU/bant genişliği) |
| Çekirdek | `models.py` | LlmModel + katalog + bellek tahmini + isim eşleştirme |
| Çekirdek | `scoring.py` | Fit/skor motoru (run mode, TPS, sıralama) |
| Çekirdek | `providers.py` | Motor tespiti (salt-okunur) |
| Çekirdek | `provider_control.py` | Motor başlat/durdur/kur + model sil |
| Çekirdek | `runner.py` | Streaming inference/chat |
| Çekirdek | `downloader.py` | Ollama pull / HF GGUF indirme |
| Çekirdek | `hf_api.py` | HF katalog güncelleme + cache |
| Çekirdek | `cfg.py` | Config (JSON) + logging |
| Çekirdek | `updater.py` | Otomatik güncelleme (GitHub Releases) |
| UI | `workers.py` | QThread arka plan işleri |
| UI | `widgets/*` | Tablo, detay, chat, filtre, sistem çubuğu vb. |
| UI | `dialogs.py`, `themes.py` | About/Alert + 6 tema |
| Veri | `data/models.json` | ~925 modellik gömülü katalog |
| Build | `Nameweaver.spec`, `*.iss`, `build.bat` | PyInstaller + Inno Setup hattı |
| CI | `.github/workflows/*` | Test kapısı + release otomasyonu |
```
