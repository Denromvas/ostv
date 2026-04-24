# Технічне завдання: OsTv

> **Версія:** 0.1
> **Дата:** 2026-04-24
> **Автор:** Denis Romanyuk
> **Робоча назва:** OsTv (TV-OS з AI-first CLI архітектурою)
> **Ліцензія:** MIT (планується)
> **Статус:** Pre-development (формування ТЗ)

---

## Зміст

1. [Загальні відомості](#1-загальні-відомості)
2. [Контекст і проблематика](#2-контекст-і-проблематика)
3. [Цільова аудиторія та сценарії використання](#3-цільова-аудиторія-та-сценарії-використання)
4. [Цілі та не-цілі](#4-цілі-та-не-цілі)
5. [Архітектура системи](#5-архітектура-системи)
6. [Функціональні вимоги (FR)](#6-функціональні-вимоги-fr)
7. [Нефункціональні вимоги (NFR)](#7-нефункціональні-вимоги-nfr)
8. [Базова ОС та завантаження](#8-базова-ос-та-завантаження)
9. [Графічний стек та композитор](#9-графічний-стек-та-композитор)
10. [UI — "Terminal 8-bit"](#10-ui--terminal-8-bit)
11. [AI-оркестратор (Brain)](#11-ai-оркестратор-brain)
12. [CLI Router та sandbox](#12-cli-router-та-sandbox)
13. [Application Layer — CLI-модулі в контейнерах](#13-application-layer--cli-модулі-в-контейнерах)
14. [Відтворення медіа: mpv + парсери](#14-відтворення-медіа-mpv--парсери)
15. [Парсери сайтів як обгортки](#15-парсери-сайтів-як-обгортки)
16. [Пульт та введення](#16-пульт-та-введення)
17. [Голосове керування](#17-голосове-керування)
18. [Self-modifying агент](#18-self-modifying-агент)
19. [Безпека, ізоляція, дозволи](#19-безпека-ізоляція-дозволи)
20. [Системні вимоги (hardware)](#20-системні-вимоги-hardware)
21. [Оновлення (OTA)](#21-оновлення-ota)
22. [Логування, телеметрія, діагностика](#22-логування-телеметрія-діагностика)
23. [Конфігурація користувача](#23-конфігурація-користувача)
24. [Тестування та критерії приймання](#24-тестування-та-критерії-приймання)
25. [Етапи розробки (Roadmap)](#25-етапи-розробки-roadmap)
26. [Ризики та відкриті питання](#26-ризики-та-відкриті-питання)
27. [Глосарій](#27-глосарій)

---

## 1. Загальні відомості

### 1.1. Назва проекту
**OsTv** — робоча назва. Ребрендинг на Етапі 4 (варіанти: `Pixel`, `NESOS`, `CRT`, `Nebula`, `TuxedoTV`).

### 1.2. Коротка мета
Створити операційну систему для телевізора / медіаприставки, де:

1. **Додатки = CLI-утиліти** (YouTube, HDRezka, Filmix, Spotify, Погода — всі мають консольний інтерфейс з JSON-виводом).
2. **Керування через намір, а не через клік** — ШІ-агент перехоплює голос/текст і транслює у послідовність CLI-викликів.
3. **Візуал — ретро-термінал** — стилістика 8-біт / Dendy / Claude Code блоки: квадратики, пікселі, анімації "глітч", термінальні курсори.
4. **Жодних важких веб-додатків** — замість браузера на 2 ГБ RAM запускаємо `mpv` + Python-парсер на 30 МБ.
5. **Самовдосконалення** — користувач каже "хочу додаток для Twitch" → агент пише парсер, пакує в контейнер, додає іконку. ОС росте разом з користувачем.

### 1.3. Унікальна цінність

| Існуюче рішення | Проблема | Що робить OsTv |
|-----------------|----------|----------------|
| Android TV | Важкий, реклама, трекінг Google, повільно на слабкому залізі | Linux+CLI, < 300 МБ RAM для UI, 100% open source |
| Apple TV | Закрита екосистема, лише платні додатки | Open, парсери безкоштовних/піратських джерел |
| WebOS / Tizen | Закриті SDK, обмежені додатки | Будь-який CLI-скрипт = додаток |
| Kodi | Важкий UI, складна конфігурація | Легкий TUI, ШІ робить конфігурацію сам |
| Chrome/Firefox kiosk | 2+ ГБ RAM, реклама, DRM-болячки | 80 МБ `mpv` + парсер — швидше в 10 разів |

**Головна фішка:** ОС, яка переписує сама себе під користувача. Не магазин додатків, а агент який виготовляє додатки на льоту.

### 1.4. Робочі назви файлів і шляхів

- Корінь системи: звичайний Linux root (`/`)
- Домашня директорія TV-користувача: `/home/tv/`
- Конфіги: `/etc/ostv/` (системні), `/home/tv/.config/ostv/` (користувацькі)
- Логи: `/var/log/ostv/`
- CLI-модулі: `/opt/ostv/apps/<app-name>/` (кожен має `manifest.json` + бінарник/скрипт)
- Контейнери: Docker named `ostv-<app-name>`
- Парсери: `/opt/ostv/parsers/<site>/` (окремий Docker-образ)
- Системний демон (AI/Router): `/usr/bin/ostv-brain` + systemd unit `ostv-brain.service`
- UI: `/usr/bin/ostv-ui` + systemd user unit `ostv-ui.service`
- IPC socket: `/run/ostv/brain.sock` (UNIX socket для JSON-RPC між UI та Brain)
- mpv control socket: `/run/ostv/mpv.sock`
- AI API ключі: `/etc/ostv/secrets.env` (0600, owner `ostv-brain`)

---

## 2. Контекст і проблематика

### 2.1. Чому це з'явилося

Ринок TV-ОС у 2026 поділений між великими вендорами (Google, Samsung, LG, Apple, Xiaomi). Усі вони:
- Важкі (від 500 МБ RAM мінімум для "ідляка").
- Закриті для кастомізації.
- Збирають телеметрію, показують рекламу навіть у платних планах.
- Не відкриті до "саморобних" додатків — magazin app store gatekeeping.
- Повільні на старому залізі (мінімум Cortex-A55, 2 ГБ RAM).

Паралельно існує ніша:
- Ентузіасти, які ставлять Kodi/LibreELEC/OSMC на Raspberry Pi або старі міні-ПК.
- Користувачі, які хочуть "просто щоб відкрився фільм з Rezka" без лазіння по сайту з рекламою.
- Люди, які мають Claude Code / ChatGPT Plus і розуміють силу ШІ-агентів — хочуть це ж на ТВ.

**OsTv цілить у цю нішу:** технічно грамотні користувачі, які хочуть контроль, швидкість, і прикольний UI.

### 2.2. Додатковий драйвер — саморобна ОС як AI-first експеримент

Сучасні LLM досягли рівня, коли вони можуть:
- Писати парсери з мінімальним промптом.
- Дебажити CLI-утиліти за логами.
- Конфігурувати systemd units.
- Робити Dockerfile для довільного сервісу.

Claude Code вже показав що "AI-агент з правами на систему" — це life-changing UX. Питання: **а що, якщо ТВ-ОС побудувати навколо того самого агента?** Не допоміжний віджет "Siri", а саме ядро UX.

### 2.3. Історичний контекст

Концепт "текст-як-інтерфейс" був ще в 80-х (BBS, curses, ncurses). Інструменти типу Textual, Bubble Tea, Ratatui у 2024-2025 зробили TUI красивими. Claude Code довів, що CLI + AI = продуктивно.

OsTv — це зведення трьох трендів: AI-агенти, красивий TUI, і open-source медіа-екосистема (mpv, yt-dlp, FreeTube, Stremio).

---

## 3. Цільова аудиторія та сценарії використання

### 3.1. Портрети користувачів

**П1. Технічний ентузіаст (пріоритет)**
- 25-45 років, працює в IT / адмін / dev.
- Має старий ПК або малинку під ТВ.
- Знає про Kodi/Plex але хоче щось "своє".
- Полюбляє експерименти, готовий писати скрипти.
- Цінує відсутність реклами і автономність.

**П2. Родина ентузіаста**
- Члени сім'ї користувача П1.
- Не хочуть лазити в термінал — хочуть "увімкни Дюну".
- Мають бути задоволені якістю картинки і швидкістю реакції.

**П3. Ретро-гіки / stylophiles**
- Люди, які кайфують від ретро-естетики.
- Використовують CRT-монітори, 8-біт шрифти, `cmatrix`, DOS-моди.
- Готові терпіти певні незручності заради вайбу.

### 3.2. Ключові сценарії (User Stories)

**US-01. Запуск фільму голосом**
> Сценарій: Юзер лежить на дивані. Каже "Увімкни Дюну 2". За ≤ 4 с на екрані починається фільм (2160p→1080p, HW-декод, без реклами).
> Ролі: AI-агент → hdrezka-parser → mpv
> Критерій успіху: час від голосу до першого кадру ≤ 4000 мс на цільовому залізі.

**US-02. Запуск без інтернету**
> Сценарій: Інтернет відвалився. Юзер натискає кнопку "Home" на пульті. Бачить сітку встановлених додатків у 8-біт стилі. Стрілками обирає "Медіатека" → переглядає локальні файли.
> Критерій: UI не залежить від AI API — пульт працює завжди.

**US-03. Пошук із пульта**
> Сценарій: Пульт без мікрофона. Юзер тисне "Home" → "Пошук" → бачить екранну клавіатуру (теж у 8-біт) → вводить "матриця" стрілочками → агент паралельно запитує всі парсери → показує результати зі всіх джерел одразу.

**US-04. Самовдосконалення ОС**
> Сценарій: Юзер каже "Я хочу дивитися Twitch на цій ОС". Агент каже "Такого додатку немає, але я можу написати. Потрібен дозвіл на встановлення нового контейнера. Ок?" Юзер каже "Так". Через 1-3 хвилини з'являється іконка "Twitch" на головному екрані і працює.
> Критерій: Весь процес не вимагає клавіатури (лише пульт + голос).

**US-05. Відновлення після збою**
> Сценарій: Оновлення ОС зламало mpv. Юзер каже "Не грають фільми". Агент читає `journalctl -u ostv-brain`, бачить помилку, встановлює потрібний пакет або робить rollback OTA-образу.
> Критерій: AI має доступ до діагностичних команд (whitelist) і може виконувати обмежений recovery.

**US-06. Ретро-експірієнс**
> Сценарій: Юзер переходить пультом між іконками. Кожна іконка — це куб з пікселів. При наведенні куб "розлітається" (анімація 150мс) і знову збирається. Біля активної іконки блимає `_` курсор. При натисканні "ОК" іконка розсипається на текст `> launching youtube-app...` і запускається додаток.

---

## 4. Цілі та не-цілі

### 4.1. Цілі (v1.0)

- [C1] ОС завантажується менш ніж за 10 с з холодного старту на SSD.
- [C2] UI споживає < 150 МБ RAM в idle.
- [C3] Відтворення 1080p H.264 з HW-декодуванням (VDPAU/VA-API).
- [C4] Голосове і пультове керування — обидва працюють.
- [C5] Встановлено принаймні 5 CLI-модулів з коробки: YouTube, HDRezka, Filmix, mpv, локальна медіатека.
- [C6] AI-агент може виконувати whitelist команд (понад 30 базових дій).
- [C7] Self-modification працює для CLI-модулів (не системних оновлень).
- [C8] Fallback: без інтернету ОС залишається функціональною для локальної медіатеки.

### 4.2. Не-цілі (v1.0)

- [NC1] Не робимо Netflix / Disney+ / HBO Max — у них важкий DRM (Widevine L1), не пройде через парсери. Можна розглянути через Kiosk Chromium у v1.5+.
- [NC2] Не робимо ігровий режим (Steam, Retroarch) — окремий проект.
- [NC3] Не робимо TV-тюнер / DVB-T2 — ніша занадто вузька.
- [NC4] Не робимо мобільний додаток-компаньйон у v1 (хоча IPC протокол дозволить його додати).
- [NC5] Не робимо підтримку пʼятьох-десяти мов UI — v1 тільки українська + англійська.

---

## 5. Архітектура системи

### 5.1. Огляд шарів

```
┌────────────────────────────────────────────────────────────┐
│  UI Layer (Presentation)                                   │
│  ─ Python + Textual (PoC) / Qt-QML (prod)                 │
│  ─ Сітка іконок, пошук, результати, плеєр-оверлей         │
│  ─ Анімації "8-біт"                                        │
└───────────────────────┬────────────────────────────────────┘
                        │ JSON-RPC over UNIX socket
                        │ /run/ostv/brain.sock
                        ▼
┌────────────────────────────────────────────────────────────┐
│  AI Layer (ostv-brain daemon)                              │
│  ─ Приймає наміри користувача (текст/голос)               │
│  ─ Звертається до LLM (Claude/Gemini API або Ollama)      │
│  ─ Парсить function calls → список CLI-команд             │
│  ─ Передає в CLI Router                                    │
└───────────────────────┬────────────────────────────────────┘
                        │ validate & dispatch
                        ▼
┌────────────────────────────────────────────────────────────┐
│  CLI Router (усередині ostv-brain)                         │
│  ─ Перевіряє команду проти whitelist                      │
│  ─ Запускає в potribнiй ізоляції (docker exec, nspawn)    │
│  ─ Повертає JSON-результат в UI                            │
└───────────────────────┬────────────────────────────────────┘
                        │ shell / docker exec
                        ▼
┌────────────────────────────────────────────────────────────┐
│  Application Layer                                         │
│  ─ mpv (системний, не контейнер — для швидкості)          │
│  ─ Парсери: hdrezka-cli, filmix-cli, youtube-cli (Docker) │
│  ─ Утиліти: weather-cli, system-info-cli (Docker)         │
│  ─ Кожен = CLI з JSON-виводом                              │
└────────────────────────────────────────────────────────────┘
```

### 5.2. Основні процеси

| Процес | Тип | Опис |
|--------|-----|------|
| `ostv-ui` | systemd user service (graphical session) | UI, Wayland Weston-client |
| `ostv-brain` | systemd system service | AI-демон, IPC сервер, CLI Router |
| `ostv-input` | systemd system service | Обробник пульта / evdev → команди в Brain |
| `ostv-voice` *(опц.)* | systemd user service | STT (whisper) → текст у Brain |
| `mpv` | дочірній процес від brain | Плеєр (запускається і вбивається по команді) |
| `docker` containers | керуються через Docker daemon | Парсери та утиліти |

### 5.3. IPC між UI та Brain

UNIX-сокет `/run/ostv/brain.sock`, протокол — JSON-RPC 2.0.

**Методи UI → Brain:**
- `intent.send` — відправити намір ("play dune 2 on rezka")
- `app.list` — отримати список встановлених додатків
- `app.icon` — отримати спрайт іконки (base64 PNG або ASCII art)
- `command.execute` — прямий виклик CLI (без AI, для пультового режиму)
- `system.status` — стан системи, ресурси
- `voice.toggle` — увімкнути/вимкнути мікрофон

**Події Brain → UI (notifications):**
- `intent.progress` — прогрес виконання наміру
- `intent.result` — результат (JSON з картками, списком, посиланням на відео)
- `app.installed` — нова іконка встановлена
- `system.alert` — помилка, попередження
- `mpv.state` — стан плеєра (play/pause/ended)

### 5.4. Події та цикл наміру

```
User Voice/Text
   │
   ▼
ostv-voice (STT) → тексту
   │
   ▼
UI → intent.send(text="увімкни матрицю") → Brain
   │
   ▼
Brain → LLM API
   Prompt: "Ти — AI ТВ-агента. Доступні інструменти:
           search_movie(query, source), play_url(url),
           show_grid(results), ..."
   │
   ▼
LLM → function_call: [
   {"name": "search_movie", "args": {"query": "матриця"}},
]
   │
   ▼
CLI Router → validate → docker exec ostv-hdrezka-cli search --query "матриця"
   │
   ▼
JSON результат → Brain → LLM продовжує:
   "Ось 3 варіанти. Показуємо сітку:"
   function_call: show_grid(results=[...])
   │
   ▼
Brain → intent.result(cards=[...]) → UI
   │
   ▼
UI рендерить 8-бітну сітку карток
   │
   ▼
User натискає "ОК" на картці → UI → command.execute("hdrezka-cli play --id 123")
   │
   ▼
Brain → docker exec ostv-hdrezka-cli play --id 123 → повертає stream URL
   │
   ▼
Brain → запускає `mpv --fullscreen --input-ipc-server=... <url>`
   │
   ▼
mpv.state: "playing" → UI ховається, відео на екран
```

---

## 6. Функціональні вимоги (FR)

### FR-1. Завантаження та старт
- FR-1.1. Система має завантажуватися з виключеного стану ≤ 10 с на SSD, ≤ 15 с на HDD.
- FR-1.2. Після завантаження одразу показується головний екран (не login screen).
- FR-1.3. Немає консольного greeter — користувач логіниться автоматично в акаунт `tv` (passwordless на цьому акаунті допустимо для kiosk-режиму).

### FR-2. Головний екран
- FR-2.1. Сітка іконок: 4×3 або 5×3 залежно від роздільної здатності.
- FR-2.2. Кожна іконка — "квадратиковий спрайт" з власною анімацією.
- FR-2.3. Перехід між іконками — стрілочками пульта (up/down/left/right).
- FR-2.4. Активна іконка виділяється блиманням курсора і мікро-анімацією (dev, див. [10.3](#103-анімації)).
- FR-2.5. Кнопка "OK" — запуск відповідного додатку.
- FR-2.6. Кнопка "Back" — закрити поточний додаток, повернутися на головний.
- FR-2.7. Кнопка "Home" — примусове повернення на головний екран.
- FR-2.8. Кнопка "Menu" або long-press "OK" — контекстне меню (властивості, видалити, перемістити).

### FR-3. Голосовий ввід
- FR-3.1. Кнопка "Voice" на пульті активує мікрофон (push-to-talk).
- FR-3.2. Під час запису на екрані візуалізація (пульсуючий квадрат).
- FR-3.3. STT транскрибує → текст відправляється в Brain.
- FR-3.4. Якщо немає інтернету і немає локальної моделі — показати повідомлення "голос недоступний" і перейти в ручний режим.

### FR-4. Пошук
- FR-4.1. Окрема іконка "Пошук" на головному екрані.
- FR-4.2. Екранна клавіатура 8-біт (навігація стрілками, OK — ввести літеру, Back — видалити).
- FR-4.3. Пошук агрегує результати з усіх встановлених парсерів паралельно.
- FR-4.4. Результати групуються за джерелом (YouTube, HDRezka, Filmix, локальна медіатека).
- FR-4.5. Кожна картка показує: назву, рік, постер (8-біт), джерело, якість (720p/1080p/4K).

### FR-5. Відтворення
- FR-5.1. Плеєр — `mpv`, запускається з IPC-сокетом.
- FR-5.2. Підтримка HW-декодування (`--hwdec=auto` або явно `vdpau`/`vaapi`).
- FR-5.3. Команди пульта передаються в mpv через IPC (pause, seek, volume).
- FR-5.4. По завершенню відео UI автоматично повертається на результати пошуку.
- FR-5.5. Підтримка субтитрів (SRT, SUB, WebVTT).

### FR-6. AI-оркестратор
- FR-6.1. Демон `ostv-brain` завантажує API ключ з `/etc/ostv/secrets.env` на старті.
- FR-6.2. Реєструє доступні function calls на старті (скан `/opt/ostv/apps/*/manifest.json`).
- FR-6.3. Тримає контекст розмови протягом однієї сесії (до наступного reboot або `clear context`).
- FR-6.4. Fallback: якщо API недоступний — перемикає на локальну Ollama (якщо встановлена).
- FR-6.5. Якщо ні API ні локальна LLM не доступні — переходить у "пультовий-only" режим.

### FR-7. CLI Router та sandbox
- FR-7.1. Кожна команда від AI проходить валідацію: regex match або список дозволених.
- FR-7.2. Заборонені команди: `rm -rf`, `mkfs`, `dd`, `shutdown`, `mount`, `chroot`, рефлексивний виклик `ostv-brain`.
- FR-7.3. Всі виклики логуються в `/var/log/ostv/commands.log` з timestamp і stdout/stderr.
- FR-7.4. Команди з `self-modification` класу вимагають підтвердження користувача (UI показує prompt на екрані).

### FR-8. CLI-модулі
- FR-8.1. Кожен модуль має `manifest.json` зі структурою:
  ```json
  {
    "name": "hdrezka",
    "version": "0.1.0",
    "icon": "icons/hdrezka.pixel.json",
    "container": "ostv/hdrezka-cli:latest",
    "commands": [
      {"name": "search", "args": ["query", "limit"], "desc": "Пошук фільмів"},
      {"name": "play", "args": ["id"], "returns": "url"}
    ],
    "permissions": ["network"]
  }
  ```
- FR-8.2. Кожен модуль має віддавати JSON у stdout і писати помилки в stderr.
- FR-8.3. Exit-коди: 0 = success, 1 = not found, 2 = network error, 3 = parse error, 4 = other.

### FR-9. Self-modification
- FR-9.1. AI може запропонувати створити новий модуль на запит користувача.
- FR-9.2. Процес: (1) User intent → (2) AI draft manifest + Dockerfile + parser code → (3) UI показує діфф → (4) User confirms → (5) Brain будує образ локально → (6) Реєструє модуль → (7) Додає іконку.
- FR-9.3. Новий модуль за замовчуванням у "sandboxed" режимі (без hostname networking, тільки public network).
- FR-9.4. Користувач може видалити модуль з UI (Menu → Uninstall).

### FR-10. Контейнери
- FR-10.1. Docker (v1) або Podman (v2, rootless).
- FR-10.2. Образ кожного модуля — базується на `python:3.12-slim` або `alpine` (для мінімального розміру).
- FR-10.3. Обмеження ресурсів: кожен модуль — не більше 256 МБ RAM, 1 CPU (через cgroups).
- FR-10.4. Мережа: тільки `bridge`, тільки вихідні підключення. Вхідних портів не відкриваємо.

### FR-11. Пульт
- FR-11.1. Стандартний AirMouse (USB 2.4 ГГц) бачиться як клавіатура — використовуємо `evdev`.
- FR-11.2. Мапінг клавіш:
  | Клавіша | Дія |
  |---------|-----|
  | Arrow keys | Навігація |
  | Enter | OK/Confirm |
  | Esc/Back | Back |
  | F1/Home | Головний екран |
  | F3/Menu | Контекстне меню |
  | F5 (mic) | Voice |
  | Vol+/Vol- | Гучність |
  | PgUp/PgDn | Скрол у списках |
- FR-11.3. Підтримка ІЧ-пульта через `lirc` — опційно, через config.
- FR-11.4. Event bus: один шлях — все через Brain. Не дозволяємо прямі wayland shortcuts.

### FR-12. OTA-оновлення (v1.5+)
- FR-12.1. OSTree атомарні образи системи.
- FR-12.2. Rollback через menu або автоматично при 3 failed boots.
- FR-12.3. Оновлення парсерів — через `docker pull` (не вимагає перезавантаження).

### FR-13. Системна інформація
- FR-13.1. Іконка "Info" показує: використання CPU/RAM/Disk/Network, температуру, версію ОС.
- FR-13.2. Доступна діагностика: `journalctl | last 50`, перезапуск сервісу, перезавантаження.

---

## 7. Нефункціональні вимоги (NFR)

### NFR-1. Продуктивність
- NFR-1.1. Час відгуку UI (натиснув кнопку → візуальна зміна) ≤ 100 мс.
- NFR-1.2. Час від намір → перший AI function call ≤ 800 мс (хмарний API з EU endpoint).
- NFR-1.3. Час від команди `play` → перший кадр ≤ 3000 мс для YouTube, ≤ 4000 мс для HDRezka.
- NFR-1.4. Паралельний пошук по 3+ парсерах — результати ≤ 5 с.
- NFR-1.5. UI має плавну анімацію навіть під час завантаження відео (не блокувати UI-тред).

### NFR-2. Ресурси
- NFR-2.1. Споживання RAM в idle:
  - UI: ≤ 150 МБ
  - Brain: ≤ 100 МБ (без завантаженого LLM)
  - Idle загалом: ≤ 400 МБ
- NFR-2.2. Споживання RAM під час відтворення 1080p: ≤ 800 МБ
- NFR-2.3. Розмір кореневої ФС (без кешу/логів):
  - PoC (Ubuntu base): ≤ 2 ГБ
  - Prod (Yocto): ≤ 600 МБ
- NFR-2.4. Розмір одного парсер-контейнера: ≤ 150 МБ.

### NFR-3. Надійність
- NFR-3.1. Brain має авто-рестартуватися при падінні (systemd `Restart=on-failure`).
- NFR-3.2. UI так само.
- NFR-3.3. Падіння парсера не валить ОС — просто показується помилка юзеру.
- NFR-3.4. Mean Time Between Failures (MTBF) ≥ 24 години безперервної роботи.

### NFR-4. Безпека
- NFR-4.1. API ключі зберігаються з правами `0600 root:root` (або `ostv:ostv`).
- NFR-4.2. Жодних команд AI не виконуються без проходження whitelist.
- NFR-4.3. Контейнери — rootless (Podman у v2).
- NFR-4.4. Новий модуль від self-modification — обов'язково дозволи користувача.

### NFR-5. UX
- NFR-5.1. Від моменту вмикання ТВ до готовності дивитися фільм — ≤ 30 с.
- NFR-5.2. Кнопки на пульті мають тактильний зворотний зв'язок (звук кліку) через системний звук.
- NFR-5.3. Усі повідомлення — українською (первинна) + англійська як fallback.

### NFR-6. Сумісність
- NFR-6.1. Мінімальна підтримка: x86_64 з SSE4.2.
- NFR-6.2. Опційна підтримка: ARM64 (Raspberry Pi 4/5) у v2.
- NFR-6.3. GPU: хоча б один з — NVIDIA з VDPAU, Intel з VA-API, AMD з VA-API.
- NFR-6.4. Аудіо — PipeWire (основне) або PulseAudio (fallback).

### NFR-7. Розробка
- NFR-7.1. Всі скрипти і конфіги — у Git-репозиторії.
- NFR-7.2. CI збирає Docker-образи парсерів при комітах.
- NFR-7.3. `./scripts/dev-run.sh` запускає повну систему на дев-машині без переустановки.
- NFR-7.4. Покриття тестами основних модулів — ≥ 60% (у v1).

---

## 8. Базова ОС та завантаження

### 8.1. PoC фаза: Ubuntu 24.04 / Debian 12 minimal

**Причина вибору:** знайома екосистема, швидкий `apt`, величезна документація, підтримка NVIDIA драйверів.

**Процес створення образу:**
1. `debootstrap --variant=minbase` → базовий rootfs ~120 МБ.
2. Додаємо пакети: `mpv`, `python3`, `docker.io`, `weston`, `cage`, `alsa-utils`, `pipewire`.
3. Власні юніти systemd для `ostv-brain`, `ostv-ui`, `ostv-input`.
4. Пакуємо в ISO або directly на диск.

### 8.2. Prod фаза: Yocto Project або Buildroot

**Yocto:**
- Плюси: промисловий стандарт, великий спільнот, підтримка apps через меш `meta-ostv`.
- Мінуси: крута крива навчання, довгі збірки (30+ хв).

**Buildroot:**
- Плюси: простий, `make menuconfig` як у ядрі, швидка збірка (10-15 хв).
- Мінуси: менше пакетів, слабша підтримка складних стеків.

**Рекомендація:** Buildroot для PoC→v1, Yocto для прод-грід сценаріїв (ТВ-бокси, Smart TV).

### 8.3. Bootloader та ядро

- Bootloader: `systemd-boot` (простий UEFI) або `GRUB2` для legacy BIOS.
- Ядро: 6.1 LTS (LTS до 2027) або 6.6 LTS.
- Modules: NVIDIA driver (open version 560+), Intel i915, AMD amdgpu.
- initramfs мінімальний — лише потрібні модулі для root.

### 8.4. Sequence завантаження

```
UEFI → systemd-boot → kernel → initramfs → systemd PID 1
  ↓
systemd targets: basic.target → multi-user.target → graphical.target
  ↓
ostv-brain.service  (system)
ostv-input.service  (system)
weston.service      (system, user=tv)
  └─ ostv-ui (child of weston, автостарт через weston.ini)
  └─ ostv-voice (user service, опц.)
```

Ціль: 10 с від натискання Power до UI.

---

## 9. Графічний стек та композитор

### 9.1. Wayland + Weston (або cage)

**Weston:** reference Wayland compositor від Collabora. Стабільний, легкий, підтримує kiosk режим.

**Cage:** мінімалістичний kiosk-compositor (один fullscreen client). Ідеально для TV — у нас завжди один додаток на екрані.

**Вибір PoC:** Weston з kiosk config. Вибір prod: cage, якщо UI-фреймворк дозволить.

### 9.2. Конфігурація Weston для TV

`/etc/weston.ini`:
```ini
[core]
idle-time=0           ; не гасити екран
repaint-window=16     ; 60 fps

[shell]
background-color=0xff000000
panel-position=none
locking=false

[output]
name=HDMI-A-1
mode=1920x1080@60     ; форсуємо 1080p
transform=normal
```

### 9.3. DRM/KMS прямо без композитора?

Для мінімального overhead можна розглянути варіант: UI малює напряму в DRM framebuffer без Wayland композитора. Це економить ~30 МБ RAM і 1-2% CPU.

**Рішення:** у v1 залишаємо Weston. DRM direct — оптимізація для v2 на вимогливому залізі (SBC, Cortex-A53).

### 9.4. Підтримка HDR

- Наразі Linux HDR стек сирий (kernel 6.8+, але не все працює).
- Фіксуємо: v1 — тільки SDR.
- v2+ — дивимось стан gamescope HDR та wlroots HDR.

---

## 10. UI — "Terminal 8-bit"

### 10.1. Концепція

Візуально ОС має виглядати як TUI-програма в повноекранному режимі, АЛЕ:
- Не ASCII-art — а великі блоки (як у Dendy спрайти).
- Не чорно-зелений — палітра 16 кольорів як у NES/Dendy.
- Курсор, що блимає.
- Анімації через кадри (як спрайти, 2-4 кадри на стан).

### 10.2. Фреймворк

**PoC:** Python + [Textual](https://textual.textualize.io/)
- Швидкий старт.
- Підтримує CSS-подібну стилізацію.
- Має анімації, перехід фокуса, сітки.
- Мінус: працює через термінал (потрібен termcap-емулятор або pseudo-TTY в Weston).
  - Рішення: запускаємо `foot` (легкий Wayland-термінал) у Weston, всередині foot — Textual app.

**Prod-варіант 1:** Go + [Bubble Tea](https://github.com/charmbracelet/bubbletea)
- Швидше за Python, менше RAM.
- Красиві стилі з Lip Gloss.

**Prod-варіант 2:** Qt/QML з піксельним шрифтом і вимкненим anti-aliasing
- Максимальний контроль.
- GPU-accelerated анімації.
- Мінус: важчий (~80 МБ).

### 10.3. Анімації

Основні стани іконки:
- **idle** (неактивний): статичний спрайт.
- **focused** (курсор на іконці): легка "пульсація" 2 кадри, блимаючий курсор поруч.
- **hover-enter** (момент переходу курсора): "глітч" анімація (blocks scatter → reassemble), 150 мс, 5-6 кадрів.
- **launching** (натиснули OK): spritesheet "розсипається на текст" + overlay `> launching [app-name]...` на 300 мс.

### 10.4. Палітра

**Первинна:** Dendy / NES колірна палітра 54 кольорів (з них практично використовується 16-24).

Основні:
- `#000000` (фон чорний)
- `#FFFFFF` (текст білий)
- `#FF0000` (акцент червоний — "запис"/помилки)
- `#00FF00` (акцент зелений — "ок"/прогрес)
- `#FFA500` (акцент оранжевий — ретро-жовтий у дусі Claude)
- `#4A90E2` (акцент синій — інформаційний)

**Опційна альтернатива:** монохром янтарний (як CRT-термінал 80-х) — можна включити у Settings.

### 10.5. Шрифт

- Основний: `Press Start 2P` (безкоштовний, OFL) або `PxPlus IBM VGA` (класичний CRT).
- Моноширинний, розмір 16-32 pt залежно від роздільної здатності.
- Anti-aliasing: **вимкнено** (щоб "пікселі" були різкі).

### 10.6. Спрайти іконок

Формат зберігання: кастомний JSON з матрицею блоків.

Приклад `icons/youtube.pixel.json`:
```json
{
  "name": "youtube",
  "size": [12, 12],
  "palette": {
    "R": "#FF0000",
    "W": "#FFFFFF",
    ".": "transparent"
  },
  "frames": [
    {
      "name": "idle",
      "pixels": [
        "....RRRRR...",
        "..RRRRRRRRR.",
        ".RRRR.WRR.R.",
        ".RRRR.WWR.R.",
        ".RRRR.WWRR..",
        ".RRRR.WRRR..",
        ".RRRR..RR...",
        ".RRRRRRR....",
        "..RRRRRRR...",
        "...RRRRRR...",
        "....RRRRR...",
        ".....RRR...."
      ]
    },
    {"name": "focus", "pixels": [...]}
  ]
}
```

UI-рендер просто малює матрицю блоків. Дозволяє AI самому "намалювати" іконку для нового модуля (просто згенерувавши правильну матрицю).

### 10.7. Екрани

1. **Home** — сітка іконок.
2. **Search** — поле вводу + екранна клавіатура + результати.
3. **Results** — сітка карток (постер + назва + метадата).
4. **Player overlay** — ледь помітний HUD поверх mpv (назва, прогрес-бар).
5. **Voice listening** — повноекранна анімація "слухаю" + транскрипт.
6. **Self-modify confirm** — діфф пропонованих змін + Y/N.
7. **Settings** — список опцій (палітра, мова, мережа).
8. **System info** — ресурси, журнали.

---

## 11. AI-оркестратор (Brain)

### 11.1. Технологія

Python 3.12 + `asyncio`. Причина: швидкий prototyping, чудові SDK для Claude/Gemini, легко писати function calling.

Prod-можливість: перехід на Go (менше RAM, кращий startup).

### 11.2. Модель

**Default:** Claude Haiku 4.5 — швидка (100 tok/s), дешева, підтримує function calling.

**Альтернативи:**
- Gemini 2.5 Flash (Google AI Studio) — безкоштовний tier до ліміту.
- GPT-4o mini.
- Локально: Ollama з `qwen2.5:3b` або `llama3.2:3b` (CPU: 5-10 tok/s на i5-2400, прийнятно для коротких команд).

### 11.3. System prompt

```
Ти — AI-агент OsTv, ТВ-операційної системи. Твоя задача — перетворити намір
користувача на послідовність викликів доступних CLI-інструментів.

Доступні інструменти (function calls):
- search_movie(query: str, source: str = "all") — пошук фільмів
- play_url(url: str, title: str) — запустити mpv
- search_youtube(query: str) — пошук на YouTube
- show_cards(cards: list) — показати сітку результатів у UI
- show_text(text: str) — короткий текст на екрані
- volume_set(level: int) — гучність 0-100
- system_info() — отримати стан системи
- mpv_control(action: str) — pause/resume/stop/seek

Правила:
1. Відповідай українською (якщо user сам не написав англійською).
2. Якщо запит неоднозначний — показуй вибір через show_cards, не вигадуй.
3. При виконанні дій завжди повідомляй користувача (через show_text).
4. Не вигадуй інструменти, яких немає в списку. Якщо функції бракує —
   скажи користувачу "такої можливості немає, хочете додати?" і тоді
   ініціюй self-modification flow (окрема функція `propose_new_module`).
```

### 11.4. Function calling

Структура запиту (OpenAI-style tool use / Claude tool_use):

```python
tools = [
    {
        "name": "search_movie",
        "description": "Пошук фільму в усіх парсерах",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "source": {"type": "string", "enum": ["all", "rezka", "filmix", "youtube", "local"]}
            },
            "required": ["query"]
        }
    },
    # ... інші tools
]
```

### 11.5. Контекст сесії

- Тримаємо останні 20 повідомлень.
- Після `clear` або reboot — очищаємо.
- Для self-modification flow тримаємо окремий контекст (перенесений через "user approved").

### 11.6. Локальний fallback (Ollama)

```
if cloud_api_ok():
    use_cloud()
elif ollama_running():
    use_ollama(model="qwen2.5:3b")
else:
    enter_manual_mode()
```

На i5-2400 Ollama з 3B моделлю виконує function call за 3-8 с — прийнятно для fallback, але не для default UX.

### 11.7. Таймаути та retry

- Cloud API: 10 с timeout, 2 retries з експоненційним бекофом.
- Ollama: 30 с timeout, без retry.
- Якщо все зафейлилось — UI бачить `intent.result(error=...)` і показує "вибачте, щось не так, спробуйте ще раз".

---

## 12. CLI Router та sandbox

### 12.1. Whitelist формат

Кожна команда опис:

```yaml
# /etc/ostv/whitelist.yaml
- cmd: "mpv"
  args_pattern: "--fullscreen --hwdec=\\w+ .+"
  max_duration_sec: 36000
  allow_env: ["DISPLAY", "WAYLAND_DISPLAY"]

- cmd: "docker exec ostv-hdrezka-cli hdrezka"
  args_pattern: "(search|play|info) .+"
  max_duration_sec: 30

- cmd: "yt-dlp"
  args_pattern: "--get-url --format [\\w\\+]+ https://.+"
  max_duration_sec: 15

- cmd: "journalctl"
  args_pattern: "-u ostv-\\w+ -n \\d+"
  max_duration_sec: 5

- cmd: "systemctl"
  args_pattern: "(status|restart) ostv-\\w+"
  max_duration_sec: 10
  require_confirmation: true
```

### 12.2. Процес виконання

```
1. AI генерує → [{"tool": "search_movie", "args": {...}}]
2. Brain мапить → "docker exec ostv-hdrezka-cli hdrezka search --query \"...\""
3. CLI Router: regex match проти whitelist → OK
4. Check resource limits → OK
5. subprocess.run(..., timeout=30, capture_output=True)
6. Parse stdout як JSON → передає у контекст AI
7. Log: timestamp, cmd, exit_code, duration в /var/log/ostv/commands.log
```

### 12.3. Заборонений список (blacklist у коді)

Навіть якщо whitelist пропускає, блокуємо:
- `rm -rf /`, `rm -rf /*`
- `dd if=`, `mkfs.`
- `>/etc/passwd`, `>/etc/shadow`
- `:(){ :|:& };:` (fork bomb)
- `nc -l`, `netcat -l` (listening sockets)
- `curl | sh`, `wget | bash`

### 12.4. Self-modification isolation

Коли AI хоче створити новий модуль:
- Docker-build відбувається в каталозі `/var/lib/ostv/pending/<uuid>/`.
- `Dockerfile`, `entrypoint.py`, `manifest.json` пишуться як файли.
- Користувач бачить у UI повний вміст кожного файлу перед підтвердженням.
- Після confirm: build → tag → install.
- Можна "undo" видаливши образ і запис у `/opt/ostv/apps/`.

---

## 13. Application Layer — CLI-модулі в контейнерах

### 13.1. Структура типового модуля

```
/opt/ostv/apps/hdrezka/
├── manifest.json
├── icon.pixel.json
├── Dockerfile            (зберігаємо для can-rebuild)
└── src/
    ├── hdrezka.py
    └── requirements.txt
```

Docker-образ: `ostv/hdrezka-cli:0.1.0`.

### 13.2. Типовий CLI інтерфейс парсера

```bash
$ docker exec ostv-hdrezka-cli hdrezka search --query "дюна" --limit 5 --json
[
  {"id": "12345", "title": "Дюна", "year": 2021, "quality": "1080p", "poster": "https://..."},
  {"id": "12346", "title": "Дюна. Частина друга", "year": 2024, "quality": "4K", "poster": "https://..."}
]

$ docker exec ostv-hdrezka-cli hdrezka play --id 12346 --quality 1080p --json
{
  "url": "https://stream.rezka.../file.m3u8",
  "subtitles": [{"lang": "uk", "url": "https://.../uk.vtt"}],
  "duration_sec": 9480
}
```

### 13.3. Постійно запущені vs on-demand

- **Парсери:** on-demand. `docker start` при першому виклику, `docker stop` через 5 хв бездіяльності.
- **mpv:** запускається тільки під час відтворення.
- **Brain, UI, Input:** постійно.
- **Voice:** опц. постійно (якщо юзер ввімкнув push-to-talk always-on).

### 13.4. Обмеження ресурсів

```bash
docker run -d \
  --name ostv-hdrezka-cli \
  --memory 256m \
  --cpus 1 \
  --network bridge \
  --read-only \
  --tmpfs /tmp \
  ostv/hdrezka-cli:0.1.0
```

---

## 14. Відтворення медіа: mpv + парсери

### 14.1. mpv конфіг

`/etc/ostv/mpv.conf`:
```
# Вікно
fullscreen=yes
cursor-autohide=500
osc=no                # no on-screen controller (UI робить свій)
osd-level=0

# Відео
vo=gpu
gpu-context=wayland
hwdec=auto-safe
hwdec-codecs=all

# Аудіо
ao=pipewire
audio-channels=auto

# Кеш для стрімінгу
cache=yes
cache-secs=30
demuxer-max-bytes=100M

# IPC
input-ipc-server=/run/ostv/mpv.sock
```

### 14.2. Керування через IPC

```python
import socket, json

sock = socket.socket(socket.AF_UNIX)
sock.connect("/run/ostv/mpv.sock")

# Пауза
sock.send(b'{"command": ["set_property", "pause", true]}\n')

# Seek +30 секунд
sock.send(b'{"command": ["seek", 30]}\n')

# Гучність
sock.send(b'{"command": ["set_property", "volume", 50]}\n')
```

### 14.3. Запуск відео

```python
def play(url: str, title: str, subs_url: str | None = None):
    cmd = ["mpv", url, f"--title={title}", "--force-window=yes"]
    if subs_url:
        cmd += [f"--sub-file={subs_url}"]
    proc = subprocess.Popen(cmd, env={"WAYLAND_DISPLAY": "wayland-0"})
    return proc.pid
```

### 14.4. Callback на завершення

Окремий тред слухає mpv IPC на event `end-file`. При спрацьовуванні — закриваємо вікно mpv, повертаємо UI на передній план.

---

## 15. Парсери сайтів як обгортки

### 15.1. Принцип "headless frontend"

Парсер емулює веб-клієнта:
1. Виконує HTTP-запит (з потрібними headers, cookies).
2. Парсить відповідь (BeautifulSoup / regex / json).
3. Формує результат у нашому внутрішньому форматі.

### 15.2. Парсер 1 — YouTube (через yt-dlp)

Не пишемо свого — використовуємо готове:

```bash
# Пошук
yt-dlp "ytsearch10:дюна трейлер" --dump-json --flat-playlist
# → JSON з відео

# Пряме посилання
yt-dlp "https://youtube.com/watch?v=..." --get-url -f "best[height<=1080]"
# → URL потоку
```

**Плюси:** yt-dlp оновлюється комʼюніті швидко (коли YouTube щось ламає).
**Мінуси:** великий (~20 МБ), але один раз на всю ОС.

### 15.3. Парсер 2 — HDRezka

Пишемо свій Python-скрипт. Оскільки сайт часто змінює структуру, тримаємо парсер в окремому контейнері, щоб легко оновлювати без чіпання ОС.

Приклад скелету:

```python
# src/hdrezka.py
import requests
from bs4 import BeautifulSoup
import click, json

BASE = "https://rezka.ag"

@click.group()
def cli(): pass

@cli.command()
@click.option('--query', required=True)
@click.option('--limit', default=10)
def search(query, limit):
    resp = requests.get(f"{BASE}/search/", params={"q": query},
                        headers={"User-Agent": "Mozilla/5.0 ..."})
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for item in soup.select(".b-content__inline_item")[:limit]:
        results.append({
            "id": item.get("data-id"),
            "title": item.select_one(".b-content__inline_item-link a").text,
            "year": item.select_one(".year").text.strip("()"),
            "poster": item.select_one("img")["src"],
        })
    print(json.dumps(results, ensure_ascii=False))

@cli.command()
@click.option('--id', required=True)
@click.option('--quality', default='1080p')
def play(id, quality):
    # ... логіка витягування m3u8
    print(json.dumps({"url": stream_url}))

if __name__ == '__main__':
    cli()
```

### 15.4. Парсер 3 — Filmix

Filmix складніший — має свій JS-захист. Розглядаємо:
- Варіант А: HTTP парсинг + розбір шифрованих плейлистів (середньо складно).
- Варіант Б: Запускати headless Chromium всередині контейнера (важко, ~300 МБ).

**Рішення:** A, орієнтуємось на існуючі open-source проєкти (є кілька на GitHub).

### 15.5. Локальна медіатека

Парсер, що сканує `/home/tv/media/` і виводить файли як картки:

```bash
$ local-media list --dir /home/tv/media
[
  {"path": "/home/tv/media/movies/dune.mkv", "title": "dune", "size_mb": 4800},
  ...
]

$ local-media play --path "/home/tv/media/movies/dune.mkv"
{"url": "file:///home/tv/media/movies/dune.mkv"}
```

Може теж бути контейнером, але тоді потрібно монтувати `/home/tv/media/` bind-mount `:ro`.

### 15.6. Агрегований пошук

Коли користувач пошукає "матриця", UI паралельно викликає 4+ парсери:

```python
async def unified_search(query):
    tasks = [
        call_parser("youtube", query),
        call_parser("hdrezka", query),
        call_parser("filmix", query),
        call_parser("local", query),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return group_by_source(results)
```

Таймаут — 5 с на кожен парсер. Хто не встиг — пропускаємо (ресурс має бути еластичним).

---

## 16. Пульт та введення

### 16.1. Первинна підтримка: USB AirMouse

Більшість AirMouse (моделі на базі чіпів Nordic nRF24) бачаться в Linux як HID-клавіатура. Перевірити:

```bash
ls /dev/input/by-id/
# usb-Sycreader_RF_Receiver-if01-event-kbd
```

Читаємо через `evdev` (Python lib):

```python
from evdev import InputDevice, categorize, ecodes

dev = InputDevice('/dev/input/by-id/usb-Sycreader_RF_Receiver-if01-event-kbd')
for event in dev.read_loop():
    if event.type == ecodes.EV_KEY:
        key = categorize(event)
        # Відправляємо в Brain через IPC
```

### 16.2. Опційна ІЧ-підтримка: LIRC

Якщо ТВ має ІЧ-приймач (наприклад, в старих міні-ПК з Windows MCE-ресівером):

```bash
apt install lirc
# /etc/lirc/lircd.conf.d/<remote>.lircd.conf
```

`irw` показує натиснуті кнопки. Мапинг → в ostv-input.

### 16.3. Кастомний радіопульт (майбутнє)

Якщо захочеться зробити свій пульт:
- Arduino Pro Mini + модуль nRF24L01 або 433 МГц приймач.
- UART → USB.
- ostv-input читає `/dev/ttyUSB0`, мапить коди → клавіші.

### 16.4. Екранна клавіатура

Окремий екран UI (викликається, коли фокус на input field). Навігація стрілками:
```
┌─ A B C D E F G H I J ─┐
│ K L M N O P Q R S T   │
│ U V W X Y Z 1 2 3 4   │
│ 5 6 7 8 9 0 ␣ ⌫ ↵     │
└───────────────────────┘
```

Анімації: при фокусі клавіша "зростає" на 10% + підсвічується.

### 16.5. Bluetooth-пульт (v1.5+)

Стандартна Android TV Remote Protocol — ні, закрите.
BLE HID — так, бачиться як клавіатура, інтеграція як і USB.

---

## 17. Голосове керування

### 17.1. STT (Speech-to-Text)

**Варіант 1: Локально через whisper.cpp**
- `ggml-small.bin` (~500 МБ).
- На i5-2400: 2-3 с для 5-секундного запиту.
- Якість українською — прийнятна (small модель), для medium/large треба сильніше залізо.

**Варіант 2: Хмарний — OpenAI Whisper API або Deepgram**
- Деепграм має безкоштовний tier 45 000 хвилин.
- Швидко, якісно.
- Потребує інтернет.

**За замовчуванням:** Whisper API (якщо користувач ввів ключ), fallback на whisper.cpp локально.

### 17.2. Мікрофон

- Аудіоустрій: USB мікрофон або мікрофон самого AirMouse (є моделі з вбудованим).
- PipeWire: налаштовуємо default source.
- Push-to-talk: кнопка "Voice" на пульті утримує мікрофон активним.

### 17.3. TTS (Text-to-Speech) — опційно

Для коротких відповідей AI "Запускаю фільм Дюна". Використовуємо:
- Local: `piper-tts` (~50 МБ модель укр).
- Cloud: ElevenLabs (дороге), OpenAI TTS.

**У v1 — TTS немає.** Відповідь виводиться як текст на екрані.

### 17.4. Wake-word (v2+)

"Hey, TV" або "Слухай, OsTv". Через Porcupine (comercial але free tier) або OpenWakeWord (open source, 16 МБ моделі).

---

## 18. Self-modifying агент

### 18.1. Концепція

Найунікальніша частина OsTv. AI має інструмент `propose_new_module` — коли зрозуміло, що функціонал не покривається існуючими модулями.

### 18.2. Flow

```
User: "Хочу дивитися Twitch стріми"
  │
  ▼
AI аналізує: шукає в /opt/ostv/apps/*/manifest.json → не знаходить twitch
  │
  ▼
AI вирішує: запропонувати створити. Викликає propose_new_module(...)
  │
  ▼
Brain відкриває "creation session":
  1. AI генерує скаффолд: Dockerfile, src/twitch.py, manifest.json, icon.pixel.json
  2. UI показує "Створення модуля Twitch" + список файлів (скролабельно)
  3. UI: кнопки [переглянути] [схвалити] [скасувати]
  │
  ▼
User натискає "переглянути" → бачить код
User натискає "схвалити"
  │
  ▼
Brain:
  1. docker build -t ostv/twitch-cli:0.1.0 /var/lib/ostv/pending/<uuid>/
  2. Копіює файли в /opt/ostv/apps/twitch/
  3. Реєструє в каталозі (перезчитує manifest'и)
  4. Відправляє UI подію app.installed
  │
  ▼
UI рендерить нову іконку на головному екрані
  │
  ▼
User каже "Увімкни Twitch, стрім mohiiganparadise"
  │
  ▼
AI має новий tool `twitch_search` (з manifest) — викликає
```

### 18.3. Обмеження

- Тільки whitelist базових Python бібліотек у Dockerfile: `requests`, `beautifulsoup4`, `click`, `yt-dlp`.
- Заборонені: `subprocess`, `os.system`, `ctypes`, `socket.bind`.
- Перевірка статичним аналізом (bandit) перед білдом.
- Якщо модуль падає 3 рази підряд — автоматично deactivate з попередженням.

### 18.4. Що НЕ можна self-modify

- Системні сервіси (`ostv-brain`, `ostv-ui`, `ostv-input`).
- Ядро Linux, пакети базової ОС.
- `/etc/ostv/whitelist.yaml` (захищений).
- Секрети (`/etc/ostv/secrets.env`).

AI може лише створювати нові CLI-модулі, які підпадають під загальну архітектуру.

### 18.5. Пісочниця build'у

`docker build` відбувається з обмеженнями:
- Мережа: тільки pypi.org, github.com, raw.githubusercontent.com.
- Час: до 120 с.
- Розмір кінцевого образу: до 500 МБ.

Якщо щось з цього порушено — білд скасовується.

---

## 19. Безпека, ізоляція, дозволи

### 19.1. Користувачі системи

- `root` — тільки system services.
- `ostv` — власник Brain, CLI Router (можливо з sudo для `docker` і `systemctl`).
- `tv` — UI юзер, без sudo. Чистий графічний сеанс.

### 19.2. Permissions model

```
tv      ─UI─→ brain.sock (лише JSON-RPC)
brain   ─exec─→ docker (сокет), mpv, systemd-run (обмежено)
brain   ─read─→ /etc/ostv/* (config, secrets)
root    ─everything─→ (тільки системні сервіси)
```

### 19.3. Secret management

- API ключі, токени → `/etc/ostv/secrets.env`, `0600 root:ostv`.
- Brain читає як read-only.
- Ніколи не передаються в UI ні в контейнери (AI robi власний запит).

### 19.4. Network policy

- Контейнери парсерів — тільки outbound, без listening.
- Можливо використати `iptables` правило DROP на INPUT для контейнерних мереж.
- Лише локальна 0.0.0.0:{порти ostv daemons} — на loopback (`127.0.0.1`).
- Зовнішніх сервісів НЕ виставляємо.

### 19.5. Physical access

ОС — для домашнього використання. Якщо хтось має фізичний доступ — все відкрито. Не робимо disk encryption у v1.

---

## 20. Системні вимоги (hardware)

### 20.1. Мінімальні вимоги

| Компонент | Мінімум |
|-----------|---------|
| CPU | x86_64, 2 ядра, SSE4.2, ~2 GHz |
| RAM | 2 ГБ |
| Диск | 8 ГБ (рекомендовано SSD) |
| GPU | Будь-який з HW-декодом H.264 через VDPAU/VA-API |
| Ethernet/Wi-Fi | 100 Мбіт+ |
| USB | 2 (для пульта і мишки/клавіатури при налагодженні) |

На таких характеристиках: 720p/1080p H.264 HW, AI тільки cloud API.

### 20.2. Рекомендовано

| Компонент | Рекоменд. |
|-----------|-----------|
| CPU | Intel N100/N305 або Ryzen 5 3500U+ |
| RAM | 8 ГБ |
| Диск | SSD 64 ГБ |
| GPU | Intel UHD (N100), GT 1030, Radeon RX 550 |
| Мережа | Gigabit |

На таких — 4K HEVC плавно, локальна LLM як fallback, комфортна швидкодія.

### 20.3. Цільова машина прототипу (наявна)

**HP Pro 3500 Series**, розміщений на 192.168.88.29:
- Intel Core i5-2400 (Sandy Bridge, 4 ядра, 3.1 GHz)
- NVIDIA GeForce GT 630 (GF108 Fermi) — VDPAU feature set D
- 9.7 ГБ DDR3 RAM
- Realtek RTL8111 Gigabit
- SSD 228 ГБ (171 ГБ вільно)
- Поточна ОС: Ubuntu GamePack 22.04

**Очікування на цьому залізі:**
| Контент | HW-підтримка | Очікувано |
|---------|--------------|-----------|
| 1080p H.264 | VDPAU ✓ | плавно |
| 1080p HEVC | ✗ (Fermi без HEVC) | SW-декод на CPU — може гратися, з артефактами при >15 Mbps |
| 4K H.264 | VDPAU ✓ (до 4K за специфікацією, практично залежить від bitrate) | межово — при 40+ Mbps можуть бути дропи |
| 4K HEVC | ✗ | SW-декод не встигне на i5-2400, заїкатиметься |
| 4K AV1 | ✗ | навіть не намагаємось |

**Висновок:** машина OK для PoC і для 90% реального вжитку (1080p). Для 4K HEVC рекомендувати апгрейд GPU до GT 1030 (якщо потрібно HDMI 2.0b для 4K@60).

### 20.4. SBC варіант (v2)

Raspberry Pi 5 (4-8 ГБ) — може бути цільовим hardware для випуску "готової TV-OS плати".

---

## 21. Оновлення (OTA)

### 21.1. Система оновлень (v1)

Простий механізм: Debian/Ubuntu пакет `ostv-system`, який оновлюється через `apt` з власного репозиторію.

Парсери оновлюються через `docker pull` (швидко, без перезавантаження).

### 21.2. OSTree (v2+)

Атомарні образи: уся коренева FS — це OSTree commit. Оновлення — атомарний switch + reboot. Rollback за 1 команду.

### 21.3. Автооновлення

- Перевірка раз на добу.
- Завантаження в фоні (після 02:00).
- Застосування після перезавантаження.
- Можна вимкнути в Settings.

### 21.4. Оновлення пропозицій AI моделей

System prompt може змінюватись з новими функціями. Зберігаємо окремо в `/etc/ostv/prompt.txt`, оновлюється з версією ОС.

---

## 22. Логування, телеметрія, діагностика

### 22.1. Логи

- `/var/log/ostv/brain.log` — AI логі (запити, function calls, відповіді).
- `/var/log/ostv/commands.log` — виконані CLI.
- `/var/log/ostv/ui.log` — події UI (натискання клавіш, перехід екранів).
- Кожен по 10 МБ, ротація через `logrotate`.

### 22.2. journalctl

systemd services логуються через journald. Доступно:

```bash
journalctl -u ostv-brain -n 100 --no-pager
```

### 22.3. Діагностичний екран

В Settings є екран "Діагностика":
- Live перегляд логів.
- Перезапуск сервісу кнопкою.
- "Надіслати логи розробнику" → gzip + upload на server.

### 22.4. Телеметрія (opt-in)

**За замовчуванням ВИМКНЕНО.** У welcome screen пропонуємо:
- Тільки сirror statistics (startup time, crash reports).
- Анонімний UUID машини.
- Жодного контенту користувача (назви фільмів, запити).
- Self-hosted endpoint (наприклад, 188.191.238.48/ostv-telemetry, як зроблено для winmux на Pop!_OS 192.168.88.28).

---

## 23. Конфігурація користувача

### 23.1. Файл користувацької конфігурації

`/home/tv/.config/ostv/config.toml`:

```toml
[general]
lang = "uk"                  # або "en"
theme = "dendy-classic"      # або "amber-crt", "claude-code"
auto_update = true

[ai]
provider = "claude"          # claude | gemini | openai | ollama
model = "claude-haiku-4-5"
max_tokens = 2048

[voice]
enabled = true
stt_backend = "cloud"        # cloud | whisper-cpp
tts_enabled = false

[remote]
ir = false
usb_hid = true

[display]
resolution = "1920x1080"
refresh = 60
hdr = false
```

### 23.2. Секрети

`/etc/ostv/secrets.env` (НЕ в user config):

```
CLAUDE_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
DEEPGRAM_API_KEY=...
```

### 23.3. UI для конфігу

- Не всі параметри доступні з UI — тільки "часті" (тема, мова, гучність default).
- Повний доступ — через SSH / текстовий редактор.

---

## 24. Тестування та критерії приймання

### 24.1. Unit-тести

- Brain: pytest для function call parsing, whitelist validation.
- Парсери: тести з fixture HTML (не мок, реально запис з сайту).

### 24.2. Integration-тести

- Запуск UI у nested Weston (з host).
- Sendкейь через `wlrctl` або `ydotool`.
- Перевірка станів.

### 24.3. End-to-end (E2E)

- Скрипт на Playwright + QEMU: завантажує ISO, імітує клавіші пульта, перевіряє що UI реагує.
- Основні сценарії US-01..US-06 з §3.2.

### 24.4. Acceptance criteria v1.0

- [AC-1] ОС завантажується за ≤ 10 с на SSD.
- [AC-2] 1080p YouTube грає з HW-декодом.
- [AC-3] 1080p HDRezka грає.
- [AC-4] Голосом "увімкни дюну" — фільм стартує ≤ 4 с після кінця фрази.
- [AC-5] Пультом можна навігувати без торкання клавіатури 100% задач.
- [AC-6] Self-modification: створення тестового парсера (наприклад, для "хабр-стрім") від запиту до запуску — ≤ 2 хв.
- [AC-7] Rollback оновлення — ≤ 30 с.
- [AC-8] Crash Brain не валить UI (UI бачить error і показує "AI offline, manual only").

---

## 25. Етапи розробки (Roadmap)

### Етап 0 — ТЗ та дослідження (поточний)
**Термін:** 1-2 тижні.
- [ ] Завершити ТЗ (цей документ).
- [ ] Прочитати документацію Textual, Bubble Tea, Weston.
- [ ] Експерименти з mpv + yt-dlp на цільовому залізі.
- [ ] Визначитись з UI-фреймворком (Textual vs Qt).

### Етап 1 — "Hello World" PoC
**Термін:** 2-3 тижні.
- [ ] Ubuntu 24.04 minimal на 192.168.88.29.
- [ ] Написати `ostv-brain` найпростіший: сокет + 1 tool = "play_youtube(url)".
- [ ] Написати UI на Textual з 1 іконкою "YouTube".
- [ ] Кнопка OK → Brain → yt-dlp → mpv.
- [ ] Перевірити що грає 1080p HW-декодом.

### Етап 2 — "Реальні парсери"
**Термін:** 3-4 тижні.
- [ ] Парсер HDRezka в контейнері.
- [ ] Парсер Filmix.
- [ ] Локальна медіатека.
- [ ] Агрегований пошук.
- [ ] Екранна клавіатура.
- [ ] Пультове керування (evdev + AirMouse).

### Етап 3 — "ШІ в повну силу"
**Термін:** 3-4 тижні.
- [ ] Інтеграція Claude API з function calling.
- [ ] Системний prompt з усіма tools.
- [ ] Голосовий ввід (Whisper API).
- [ ] Fallback на Ollama.
- [ ] Self-modification MVP (на обмеженому прикладі).

### Етап 4 — "Ретро-стиль та UX"
**Термін:** 2-3 тижні.
- [ ] Спрайти іконок у 8-біт.
- [ ] Анімації (focus, hover, launch).
- [ ] Пробна публікація відео демо.
- [ ] Визначитись з назвою/брендом.

### Етап 5 — "Yocto та приладне залізо"
**Термін:** 4+ тижнів.
- [ ] Перехід на Buildroot або Yocto.
- [ ] Образ для Raspberry Pi 5.
- [ ] OTA via OSTree.
- [ ] Release v1.0.

### Етап 6 — Підтримка спільноти
- [ ] Публічний Git.
- [ ] Документація для модуль-девів.
- [ ] "App store" — репозиторій перевірених community-парсерів.

---

## 26. Ризики та відкриті питання

### 26.1. Технічні ризики

| # | Ризик | Вплив | Мітігація |
|---|-------|-------|-----------|
| R1 | NVIDIA driver + Wayland проблеми на старих GPU (Fermi) | Середній | Може знадобитися X11 fallback або зміна GPU на прототипі |
| R2 | HDRezka/Filmix міняють структуру сайту → парсери ламаються | Високий | Контейнерна модель оновлень; community maintainers |
| R3 | Claude/Gemini API rate limits | Середній | Локальний Ollama fallback |
| R4 | Self-modification генерує небезпечний код | Високий | Статичний аналіз + користувацький confirm + sandbox build |
| R5 | Latency голос→дія > 4 с — UX страждає | Середній | Streaming API responses, preload парсерів |
| R6 | 4K HEVC не грається на старому GPU | Низький | Чесно прописано в requirements; автоматичне fallback на нижчу роздільну |

### 26.2. Юридичні ризики

| # | Ризик | Мітигація |
|---|-------|-----------|
| L1 | Парсинг піратських сайтів (HDRezka, Filmix) — сумнівна легальність | Публікуємо парсери окремо, не в основному образі. Образ системи не містить цих парсерів — користувач сам встановлює через self-mod |
| L2 | DRM-контент (Netflix, Disney+) | Не робимо. NC1 чітко заборонено в v1 |
| L3 | Claude/Gemini TOS — комерційне використання | В open source можна, але при продажу hardware ТВ-боксів треба перечитати ToS |

### 26.3. Відкриті питання

- **Q1.** Використовувати Docker чи Podman у PoC? (Docker простіше, Podman — rootless, безпечніше)
- **Q2.** Textual чи Qt для UI? (Textual — швидше прототипувати, Qt — красивіше, але важче)
- **Q3.** Ollama vs llama.cpp напряму? (Ollama простіше, llama.cpp — більше контролю над ресурсами)
- **Q4.** Автозапуск mpv прямо з Brain чи через окремий "player service"? (з Brain — простіше; окремо — можна перезапускати без Brain)
- **Q5.** Як обробляти багатомовні fields у manifest (укр+англ)? (i18n JSON structure?)
- **Q6.** Версіонування парсерів: централізоване чи кожен сам? (Планується — централізовано через `ostv-app-index` репозиторій)

---

## 27. Глосарій

| Термін | Визначення |
|--------|------------|
| **OsTv** | Назва проекту |
| **Brain** | AI-демон, ядро системи (`ostv-brain`) |
| **CLI Router** | Підсистема Brain, що валідує та запускає CLI-команди |
| **Parser (парсер)** | CLI-утиліта в контейнері, що "витягує" дані з веб-сайту |
| **Module (модуль)** | Додаток OsTv = парсер + манiфест + іконка |
| **Self-modification** | Здатність AI створювати нові модулі на запит користувача |
| **Intent (намір)** | Природномовний запит користувача, що перетворюється AI на CLI-виклики |
| **Function call** | Спосіб LLM викликати "інструмент" (структурований JSON у відповіді) |
| **AirMouse** | Пульт з USB-дongle на 2.4 ГГц, бачиться як клавіатура+миша |
| **VDPAU** | Video Decode and Presentation API for Unix (NVIDIA) |
| **VA-API** | Video Acceleration API (Intel/AMD) |
| **IPC** | Inter-Process Communication — обмін між процесами |
| **TUI** | Terminal UI — UI що працює в текстовому режимі |
| **Kiosk mode** | Режим роботи одного додатку на весь екран |
| **OSTree** | Атомарна файлова система для непереривних OTA-оновлень |

---

## 28. Інтеграції та майбутні розширення

Розділ додано після завершення PoC (2026-04-24) — реальний досвід показав напрямки росту.

### 28.1. Cinema Portal integration
У Дениса вже працює Flutter-додаток `cinema.denromvas.website` з мобільним/веб-інтерфейсом
кіно-бази з TMDB, watchlist, AI-рекомендаціями. OsTv і Cinema Portal можуть:

- ділити один HDRezka-парсер (Brain як backend для Flutter app теж)
- Cinema Portal → "Дивитись на ТБ" кнопка → REST-запит на Brain → mpv на ТБ
- OsTv → Cinema Portal watchlist → синхронна черга перегляду
- Спільний TMDB cache + thumbnails

Імплементація:
- `ostv-brain` експонує HTTP endpoint (додатково до UNIX socket) на `:8765` у внутрішній мережі
- Tauri app зберігає JWT для auth
- CORS дозволяє `denromvas.website` origin

### 28.2. Mobile companion app (Android/iOS)
Flutter застосунок як **розширений пульт**:
- Full-text пошук з клавіатурою телефону → запит у OsTv Brain → результати на ТВ
- Voice input (телефон → STT → command → OsTv)
- Notifications ("фільм закінчився")
- Screen casting / remote view
- QR-pairing (телефон сканує код на ТВ → encrypted WebSocket handshake)

Transport: mDNS discovery + WebSocket over LAN.

### 28.3. Cloud sync (multi-device)
Коли OsTv працює у кількох місцях (дача, квартира, друзі):
- Налаштування користувача (theme, layout, API-keys) синхронізуються через self-hosted endpoint
- Install modules (weather_chernivtsi) переносяться між пристроями
- Watchlist синхронізується через Cinema Portal backend
- Self-hosted (без зовнішніх сервісів): Denis's Pop!_OS 192.168.88.28 як central server

### 28.4. Smart Home integration
Home Assistant API (у Дениса налаштований) → Brain tool:
- "приглуши світло у вітальні" → AI через Brain → HA REST API
- "увімкни фільм і приглуши світло" → одна команда, два tools
- OsTv Home screen показує стан лампочок/термостатів (nice-to-have dashboard)

### 28.5. Legal UA-контент
Альтернатива піратським HDRezka/Filmix:
- **megogo.net** / **oll.tv** — легальні UA стрімінги з UA-аудіо. Мають API.
- **1plus1.ua** / **Tyt.by UA** — архіви серіалів. Треба парсер.
- **Kyiv Digital** — прямі ТБ канали (HLS).
- **Public YouTube (Суспільне UA)** — канали 1+1, ICTV, СТБ, Новий канал — через yt-dlp уже працює.

### 28.6. Voice з пам'яттю
Коли буде USB-мікрофон:
- Wake-word ("Привіт, OsTv") через Porcupine / OpenWakeWord
- Whisper STT для української (faster-whisper small)
- AI sidebar слухає завжди у фоні, reagуе на wake
- Piper-TTS для UA-озвучених відповідей (опційно)

### 28.7. Hardware апгрейди поточного ПК
- **GT 1030 / RX 550 GPU** ($25-30 б/у) — WebKit GPU composite, плавний 60 FPS
- **USB-мікрофон** ($5-15) — Voice input
- **AirMouse з PTT мікрофоном** ($15-30) — інтегрований пульт+голос
- **4 ГБ RAM → 8/16 ГБ** — для паралельних парсерів/Docker

### 28.8. Дистрибуція
- **GitHub public repo** — code + releases
- **Landing page** `ostv.denromvas.website` — скріни, відео демо, install one-liner
- **Telegram channel** для updates + спільнота
- **APK/Deb репозиторій** для оновлень через apt
- **Prebuilt ARM image** (Raspberry Pi 4/5) — цільова ніша для "TV-бокс за $70"

### 28.9. Монетизація (опційно)
- Open source ядро, MIT license
- Donations: Buy Me a Coffee, моно-банка
- Paid **преміум-парсери** для легального контенту (Netflix/Disney+/HBO Max з Widevine) — якщо з'явиться партнерство
- Support contracts для бізнесу (public displays, готелі)

---

## Додатки (майбутні)

- **A. Приклади іконок у `.pixel.json` форматі**
- **B. Повний системний prompt AI**
- **C. Dockerfile шаблон для парсера**
- **D. API reference для модуль-розробників**
- **E. Скрипти автоматичного розгортання PoC на 192.168.88.29**
- **F. Real Filmix parser** (reverse mobile APK — окрема дослідницька робота)
- **G. Cinema Portal ↔ OsTv REST bridge**
- **H. Mobile companion Flutter скелет**
