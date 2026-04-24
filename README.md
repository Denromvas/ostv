# OsTv

> **Самомодифікована ТВ-ОС з AI-агентом.** Замість важкого Android TV — легкий Linux-kiosk,
> де додатки = CLI-утиліти, а Claude керує ними через природню мову.
> Стилістика 8-біт (Dendy × Claude Code). RAM ~280 МБ ядро, ~680 МБ total system.

![OsTv](https://img.shields.io/badge/status-PoC%20working-green) ![License](https://img.shields.io/badge/license-MIT-blue) ![Platform](https://img.shields.io/badge/platform-Ubuntu%2022.04%2B-orange)

---

## TL;DR

- **Фронтенд:** Tauri 2 (Rust) + React/TypeScript — fullscreen kiosk вікно
- **Ядро (Brain):** Python asyncio + JSON-RPC через UNIX socket
- **AI:** Claude через `claude -p` CLI (OAuth, не потребує API key) з tool-use через `brain.sh`
- **Медіа:** `mpv` + `yt-dlp` + парсери у Python (HDRezka real stream, Filmix TODO)
- **Self-modifying:** користувач каже *"хочу додаток для курсу валют"* → Claude генерує парсер → апрувить → іконка з'являється в Home grid
- **Fullscreen kiosk:** Openbox + `getty@tty1 --autologin tv` (без GDM/GNOME)

---

## Швидка установка

На чистій Ubuntu 22.04+ / Debian 12+:

```bash
# Download release
wget https://github.com/<USER>/ostv/releases/download/v0.1.0/ostv-release-v0.1.0.tar.gz
tar -xzf ostv-release-v0.1.0.tar.gz

# Install
sudo bash release/install.sh --local ostv-release-v0.1.0.tar.gz

# Post-install: залогіни Claude OAuth
sudo -u tv bash -c 'claude'  # → /login

# Reboot у kiosk
sudo reboot
```

Rollback (назад до GDM+GNOME):
```bash
sudo bash release/install.sh --rollback
sudo reboot
```

---

## Що вміє

### Основне
- 🎬 **HDRezka** — пошук і запуск фільмів з direct m3u8/mp4, **тільки українська озвучка** (auto-filter)
- 📺 **YouTube** через `yt-dlp` — пошук + play. Підтримує streams, playlists.
- 🎵 **Music** — локальні .mp3/.flac/.ogg/.opus з `/home/tv/Music/`. Playlist mode, auto-play folder.
- 🖼 **Photos** — slideshow JPG/PNG/WebP з `/home/tv/Photos/` (5 с/кадр, loop).
- 📁 **Files** — файловий менеджер з browse будь-якої директорії, auto-detect media type.
- 💻 **Terminal** — xterm fullscreen (escape hatch до системи).
- ⚙ **Settings** — theme, scanlines, перелік AI-модулів, DELETE buttons.

### AI
- 💬 **AI Sidebar** (`` ` `` або Alt+A) — slide-in 38% справа, чат із Claude:
  - "увімкни матрицю" → search + play
  - "зроби тихіше" — пам'ятає контекст, викликає volume
  - "створи додаток Radio NV" → Claude генерує парсер + встановлює
  - "у Weather додай вибір міст" → Claude редагує existing parser

### Пульт
- AirMouse USB / будь-яка HID клавіатура
- Media keys (Vol +/-, Mute, PlayPause, Home) → toast notifications
- Alt+Shift toggle keyboard layout (UA/EN)

### Self-modifying
- `propose_module(description)` — Claude генерує new app (manifest + parser.py + README)
- `approve_module(pending_id)` — install у `/opt/ostv/apps/<name>/`
- `modify_module(app, description)` — Claude редагує existing app
- `delete_app(app)` — remove
- UI полінг кожні 5 с → нові іконки з'являються автоматично

---

## Архітектура

```
┌─────────────────────────────────────────────┐
│ Tauri 2 UI (React + TS)                    │  fullscreen via openbox
│ • Home grid, screens (YouTube/HDRezka/...)  │  kiosk session (user tv)
│ • AI sidebar, OSK, Settings                │
│ • IPC: invoke("brain_call", {...})         │
└────────────────────┬────────────────────────┘
                     │ UNIX socket JSON-RPC
                     │ /run/ostv/brain.sock
                     ▼
┌─────────────────────────────────────────────┐
│ Brain daemon (Python asyncio)               │  systemd ostv-brain.service
│ 24 tools: play_url, search_*, ai_chat,      │  user tv:ostv
│ propose_module, volume, launch_terminal,    │
│ list_files, play_playlist, kbd_layout…      │
└───┬─────────────────────┬───────────────────┘
    │                     │
    ▼ subprocess          ▼ spawn
┌──────────┐      ┌───────────────┐
│ mpv      │      │ claude -p …   │  OAuth auth
│ parsers  │      │  --allowedTools│  (spawns bash.sh)
│ yt-dlp   │      │  Bash          │
└──────────┘      └───────────────┘
```

### Структура репо

```
OsTv/
├── docs/TZ.md              — повне технічне завдання (27+ розділів)
├── src/                    — runtime source
│   ├── brain/brain.py      — 24 tools Python asyncio server
│   ├── parsers/            — парсери (hdrezka, filmix)
│   └── bin/brain.sh        — bash wrapper для Claude Bash tool
├── src-tauri-ui/           — Tauri 2 React app
│   ├── src/App.tsx         — головний UI
│   └── src-tauri/          — Rust backend + tauri.conf
├── scripts/                — installation automation
│   ├── install-ostv.sh     — master installer
│   ├── build-release.sh    — pack tarball
│   └── lib/                — етапи 00–08
├── dist/                   — pre-built releases
│   ├── ostv-ui             — Tauri binary (standalone, 9.5 МБ)
│   └── ostv-release-v0.1.0.tar.gz
├── journals/               — log прогресу розробки
├── LICENSE                 — MIT
└── README.md
```

---

## Розробка

### Brain

```bash
cd src/brain
./brain.py  # або через systemd: systemctl start ostv-brain

# Test tools:
/opt/ostv/bin/brain.sh ping
/opt/ostv/bin/brain.sh search_all '{"query":"матриця","limit":5}'
/opt/ostv/bin/brain.sh ai_chat '{"messages":[{"role":"user","content":"знайди дюну"}]}'
```

### UI

```bash
cd src-tauri-ui
npm install
npm run tauri dev       # hot reload
# or
npm run tauri build     # release binary
```

### Release

```bash
bash scripts/build-release.sh 0.1.1
# → dist/ostv-release-v0.1.1.tar.gz готовий до дистрибуції
```

---

## Hardware вимоги

| Компонент | Мінімум | Рекоменд. | Тестувалось |
|-----------|---------|-----------|-------------|
| CPU | x86_64 2 cores SSE4.2 | Intel N100 / Ryzen 3500U+ | **Intel i5-2400 (2011)** ✓ |
| RAM | 2 ГБ | 8 ГБ | 10 ГБ DDR3 ✓ |
| Disk | 8 ГБ SSD | 32 ГБ SSD | SSD 228 ГБ |
| GPU | будь-який з VDPAU/VA-API H.264 | GT 1030+ / Intel UHD / Radeon RX 550 | **NVIDIA GT 630 (Fermi)** ✓ software WebKit (тупить), nouveau VDPAU limited |
| Аудіо | HDMI/analog | PipeWire 0.3.48+ | HDMI NVIDIA ✓ |

На старому GT 630 Fermi — UI працює через software llvmpipe (WebKit ~20 FPS), відео грає SW-decode 1080p H.264 (60% одного ядра). Для 4K HEVC/AV1 потрібен апгрейд GPU до GT 1030+.

---

## Roadmap

### PoC (v0.1.0, поточна) — готово ✓
- [x] Kiosk session (Openbox + autologin)
- [x] Brain systemd service, 24 tools
- [x] Tauri 2 UI з 9 іконками
- [x] HDRezka real stream з UA-фільтром
- [x] YouTube через yt-dlp
- [x] Local Music / Photos / Files
- [x] AI sidebar через Claude OAuth (claude-p)
- [x] Self-modifying: propose/approve/modify/delete
- [x] Auto-refresh, loading overlay, screen saver
- [x] Installer + release tarball

### v0.2 — production polish
- [ ] Filmix parser (reverse mobile API)
- [ ] Voice input (USB mic + whisper.cpp)
- [ ] HDRezka series/episodes
- [ ] AI chat persist across reboots
- [ ] USB auto-mount у Files
- [ ] Music ID3 metadata (artist/album)
- [ ] Cinema Portal integration (REST bridge)

### v1.0 — prod
- [ ] Yocto/Buildroot custom image
- [ ] OSTree OTA оновлення
- [ ] Mobile companion app (Flutter)
- [ ] Cloud sync налаштувань
- [ ] ARM image для Raspberry Pi 4/5

Повний список — див. [`docs/TZ.md`](docs/TZ.md) §25 Roadmap + §28 Інтеграції.

---

## Credits

- **Tauri** — Rust framework
- **HdRezkaApi** — Python пакет для HDRezka streams
- **yt-dlp** — спільнота
- **Claude Code** — AI assistant
- **Денис Романюк** — автор і головний користувач

MIT License — robити що хочеш, fork/modify/sell.

---

## Статус

**PoC розгорнуто та тестується на 192.168.88.29** (HP Pro 3500 Series, Intel i5-2400, NVIDIA GT 630 nouveau).
Домашня мережа Дениса, повсякденне використання. Public release: коли стабілізуємо після 1-2 тижнів use.
