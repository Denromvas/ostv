# Filmix APK reverse — research notes

**Status:** initial static recon (apktool 2.7.0, ProGuard-obfuscated)
**APKs:** filmixapp-2.1.5.apk, filmixapp-2.2.13.apk (latest)
**Decompiled to:** /tmp/filmix-decompiled/app-2.2.13/

## Static facts

### App identity
- Package: `net.filmix.filmix`
- Custom URL schemes: `fx://...`, `filmix://...`
- Deep-link hosts: `fx.app`, `filmix.biz`, `hd.vb`

### Real API host
**`https://filmixapp.cyou`** (NOT filmix.me/.co/.life — це публічні домени для людей; mobile app ходить на cyou).

### API endpoints (`/api/v2/`)
Знайдено 30+ методів через grep по smali:

| Endpoint | Призначення |
|---|---|
| `/api/v2/search` | пошук |
| `/api/v2/suggest?<q>` | автокомпліт |
| `/api/v2/last-searched` | історія пошуку |
| `/api/v2/post/<id>` | деталі фільму (head/episodes/streams) |
| `/api/v2/post/rate` | оцінка |
| `/api/v2/popular` | головна |
| `/api/v2/top_views` | топ |
| `/api/v2/catalog?orderby=&orderdir=` | каталог |
| `/api/v2/category_list` | жанри |
| `/api/v2/favourites` | обрані |
| `/api/v2/toggle_fav/<id>` | додати/видалити з обраного |
| `/api/v2/deferred` | відкладені |
| `/api/v2/toggle_wl/<id>` | watchlist toggle |
| `/api/v2/history` | історія |
| `/api/v2/history_clean` | очистити |
| `/api/v2/history/remove` | видалити окремий |
| `/api/v2/add_watched` | відмітити переглянутим |
| `/api/v2/user_profile` | профіль |
| `/api/v2/check_update` | оновлення |
| `/api/v2/playlist-items/` | плейлисти |
| `/api/v2/notifications/all` | список |
| `/api/v2/notifications/clean` | очистити |
| `/api/v2/notifications/read` | прочитані |
| `/api/v2/notifications/readall` | mark all |
| `/api/v2/person/<id>` | актор/режисер |
| `/api/v2/change_server` | мб для CDN failover |

### Custom HTTP headers
Явно знайдені у smali:
- `X-APP-NO-ANIME`, `X-APP-NO-INDIAN`, `X-APP-NO-KOREAN`, `X-APP-NO-RUSSIAN`, `X-APP-NO-TURKISH`, `X-APP-NO-UKRAINIAN`
  → юзерські фільтри (показано/приховано контент по країнах)
- `FX-CHAN-UPDATER` — трекінг updater channel
- `FX-NOTIFY` — для FCM/notification flow

**Важливо**: `X-FX-Token` НЕ знайдено серед явних рядків. Auth-ключ або обчислюється runtime (HMAC?), або обфусковано як constant у DEX bytecode.

### AES використання
Знайдено import-и:
- `AES/CBC/PKCS5Padding`
- `AES/ECB/NoPadding`
- `AES/GCM/NoPadding`
- `AES/CTR/NoPadding`
- `AES/GCM-SIV/NoPadding`

Ключі/IV — НЕ як hardcoded ASCII strings. Обчислюються runtime
(ймовірно з device fingerprint + signing cert). Класична anti-RE практика.

### False positives (виглядали як ключі — але ні)
- `A0Z3xqYpIQveL5MM` — це **ім'я класу** (ProGuard rename), 16 chars збіглись випадково
- `5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b` — параметр SEC256 curve (стандартна криптографія, не наш)
- `3071c8717539de5d5353f4c8cd59a032` — Room DB schema hash

## Що потрібно для повного parser'а

Static recon недостатній — Filmix runtime'но генерує auth headers і шифрує тіло запитів.
**Наступні кроки** (вимагає Android-пристрій або емулятор):

1. **Frida + APK на емуляторі**:
   - Hook `javax.crypto.Cipher.doFinal()` — побачити plain payload + AES key + IV
   - Hook `okhttp3.Request.Builder.header()` — побачити ВСІ headers що ставляться
   - Hook `okhttp3.Request.Builder.url()` — побачити все query параметри

2. **MITM через mitmproxy + SSL pinning bypass**:
   - `frida-trace -U -p <PID> -j '*!OkHttpClient*'` для tracing
   - bypass: `objection patchapk -s filmixapp.apk` або `frida-server` + ssl-bypass-pinning script
   - захопити raw HTTPS запити з усіма headers

3. **JADX-GUI** для більш зручного reading (apktool дає smali — нечитаємий; jadx дає декомпільований Java/Kotlin)

4. Зразу побачимо:
   - Як формується auth token (HMAC/JWT/симетричний?)
   - Чи треба device-id, install-id, signing cert hash
   - Формат payload (mostly application/json чи AES-encrypted blob)
   - Як отримати stream URL з `/api/v2/post/<id>` — поле `played` чи `videos`?

## Stub parser (поточний)

`/mnt/e/OsTv/src/parsers/filmix/filmix.py` — повертає чесну помилку про необхідність
повного reverse engineering з Frida.

## Часовий estimate

- Initial recon (static, apktool) — **зроблено** (~30 хв)
- Frida hooks + key extraction — **4-6 годин** з реальним пристроєм
- Python parser implementation + tests — **2-3 години**
- Total: ~1 робочий день

## Альтернатива

Не реверсити — використати `yt-dlp` extension чи готовий public reverse:
- https://github.com/k0son/filmixapi (Python wrapper) — якщо ще живий
- https://github.com/ — пошук "filmixapp.cyou api" може дати community-парсер
