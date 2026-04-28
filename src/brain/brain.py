#!/usr/bin/env python3
"""OsTv Brain — v0.0.3 PoC

Методи (JSON-RPC over /run/ostv/brain.sock):
  ping(), status(), focus_ui()
  play_url(url), play_youtube(url), stop()
  search_youtube(query, limit=12)  — NEW (yt-dlp ytsearchN:query)
  search_all(query)                — NEW (агрегатор, поки тільки youtube)
"""
import asyncio
import glob
import json
import os
import logging
from pathlib import Path


def _detect_xauth() -> tuple[str, str]:
    """Повертає (DISPLAY, XAUTHORITY) для поточної X-сесії.
    Для kiosk з user tv (startx) — auth у /tmp/serverauth.XXX.
    Для legacy GDM (dromanyuk) — /run/user/1000/gdm/Xauthority.
    """
    # Спершу пошук kiosk auth
    auth_files = sorted(glob.glob("/tmp/serverauth.*"),
                         key=lambda p: os.path.getmtime(p), reverse=True)
    for f in auth_files:
        if os.access(f, os.R_OK):
            return (":0", f)
    # Fallback GDM
    gdm = "/run/user/1000/gdm/Xauthority"
    if os.path.exists(gdm):
        return (":0", gdm)
    # Last resort user home
    for home in ("/home/tv", "/home/dromanyuk"):
        xa = f"{home}/.Xauthority"
        if os.path.exists(xa):
            return (":0", xa)
    return (":0", "")

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

SOCK = Path("/run/ostv/brain.sock")
LOG_FILE = Path("/var/log/ostv/brain.log")

handlers = [logging.StreamHandler()]
try:
    handlers.append(logging.FileHandler(LOG_FILE))
except PermissionError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=handlers,
)
log = logging.getLogger("brain")

current_mpv: asyncio.subprocess.Process | None = None

# === HISTORY ===
import time
import secrets

HISTORY_FILE = Path("/var/lib/ostv/history.json")
HISTORY_MAX = 200          # tail-trim
HISTORY_FINISHED_PCT = 0.95
current_history_id: str | None = None
_history_tracker_task: asyncio.Task | None = None


def _history_load() -> dict:
    if not HISTORY_FILE.exists():
        return {"version": 1, "items": []}
    try:
        with open(HISTORY_FILE) as f:
            d = json.load(f)
        if "items" not in d:
            d = {"version": 1, "items": []}
        return d
    except Exception as e:
        log.warning(f"history load failed: {e}")
        return {"version": 1, "items": []}


def _history_save(data: dict) -> None:
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = HISTORY_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, HISTORY_FILE)
    except Exception as e:
        log.warning(f"history save failed: {e}")


def _history_create(*, title: str, source: str, original_url: str,
                    stream_url: str | None = None, thumbnail: str | None = None,
                    query: str | None = None, extra: dict | None = None,
                    resume_position: float = 0.0) -> str:
    h = _history_load()
    hid = f"hist_{int(time.time())}_{secrets.token_hex(3)}"
    now = int(time.time())
    rec = {
        "id": hid,
        "title": title or "(без назви)",
        "source": source,
        "original_url": original_url,
        "stream_url": stream_url,
        "thumbnail": thumbnail,
        "query": query,
        "position_sec": float(resume_position or 0),
        "duration_sec": 0.0,
        "started_at": now,
        "last_watched": now,
        "finished": False,
        "extra": extra or {},
    }
    # Прибираємо дубль того самого original_url якщо є — оновимо через resume замість
    items = [it for it in h["items"] if it.get("original_url") != original_url]
    items.insert(0, rec)
    h["items"] = items[:HISTORY_MAX]
    _history_save(h)
    log.info(f"history: created {hid} '{title[:40]}' src={source}")
    return hid


def _history_update_position(hid: str, position: float, duration: float = 0.0) -> None:
    if not hid:
        return
    h = _history_load()
    found = False
    for it in h["items"]:
        if it["id"] == hid:
            it["position_sec"] = float(position)
            if duration > 0:
                it["duration_sec"] = float(duration)
            it["last_watched"] = int(time.time())
            if duration > 0 and position / duration >= HISTORY_FINISHED_PCT:
                it["finished"] = True
            found = True
            break
    if found:
        _history_save(h)


def _history_get(hid: str) -> dict | None:
    h = _history_load()
    for it in h["items"]:
        if it["id"] == hid:
            return it
    return None


async def _mpv_query(prop: str) -> float | None:
    """Запит властивості mpv через IPC. Повертає float або None."""
    sock_path = "/run/ostv/mpv.sock"
    if not os.path.exists(sock_path):
        return None
    try:
        reader, writer = await asyncio.open_unix_connection(sock_path)
        req = json.dumps({"command": ["get_property", prop]}) + "\n"
        writer.write(req.encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=1.5)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        d = json.loads(line)
        if d.get("error") == "success":
            v = d.get("data")
            return float(v) if v is not None else None
    except Exception:
        return None
    return None


async def _history_track_loop():
    """Бекграунд-поллінг mpv time-pos/duration → пише в активний history record."""
    global current_history_id
    log.info("history tracker: started")
    try:
        while True:
            await asyncio.sleep(3)
            if not current_history_id:
                continue
            if not current_mpv or current_mpv.returncode is not None:
                continue
            pos = await _mpv_query("time-pos")
            dur = await _mpv_query("duration")
            if pos is not None and pos > 0:
                _history_update_position(current_history_id, pos, dur or 0)
    except asyncio.CancelledError:
        log.info("history tracker: cancelled")
        raise
    except Exception as e:
        log.error(f"history tracker crashed: {e}")


def _history_ensure_tracker():
    global _history_tracker_task
    if _history_tracker_task is None or _history_tracker_task.done():
        _history_tracker_task = asyncio.create_task(_history_track_loop())


async def _history_finalize(hid: str):
    """Викликається після exit mpv: фіксує фінальну позицію."""
    if not hid:
        return
    pos = await _mpv_query("time-pos")  # zazvychay None бо mpv mert
    if pos is not None:
        _history_update_position(hid, pos)
    # mark finished is handled by update_position when pos/dur >= 95%
    log.info(f"history: finalized {hid}")


async def _restore_focus():
    try:
        env = os.environ.copy()
        disp, auth = _detect_xauth()
        env["DISPLAY"] = disp
        if auth:
            env["XAUTHORITY"] = auth
        proc = await asyncio.create_subprocess_exec(
            "wmctrl", "-a", "OsTv",
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    except Exception as e:
        log.warning(f"restore focus failed: {e}")


async def _watch_mpv_exit(proc: asyncio.subprocess.Process):
    global current_history_id
    await proc.wait()
    log.info(f"mpv (pid={proc.pid}) exited rc={proc.returncode}")
    if current_history_id:
        await _history_finalize(current_history_id)
        current_history_id = None
    await _restore_focus()


# === TOOLS ===

async def tool_ping() -> dict:
    return {"ok": True, "msg": "pong", "version": "0.0.3"}


async def tool_status() -> dict:
    if current_mpv and current_mpv.returncode is None:
        return {"playing": True, "pid": current_mpv.pid}
    return {"playing": False}


async def tool_focus_ui() -> dict:
    await _restore_focus()
    return {"ok": True}


async def _kill_mpv():
    global current_mpv
    if current_mpv and current_mpv.returncode is None:
        log.info(f"Killing previous mpv pid={current_mpv.pid}")
        current_mpv.terminate()
        try:
            await asyncio.wait_for(current_mpv.wait(), timeout=2)
        except asyncio.TimeoutError:
            current_mpv.kill()
            await current_mpv.wait()


async def tool_play_url(url: str, fullscreen: bool = True, quality: str = "1080p",
                        title: str | None = None, source: str | None = None,
                        thumbnail: str | None = None, query: str | None = None,
                        resume_position: float = 0.0,
                        season: int | None = None, episode: int | None = None,
                        translator: str | None = None) -> dict:
    global current_mpv, current_history_id

    original_url = url  # запам'ятовуємо ВХІДНИЙ url — для resume HDRezka сторінки
    extra: dict = {}

    # Auto-detect HDRezka film page URL → extract stream first
    is_hdrezka = any(host in url for host in ("rezka.ag", "hdrezka.ag", "hdrezka.cc"))
    if (is_hdrezka and "/films/" in url) or (is_hdrezka and "/series/" in url):
        log.info(f"play_url: auto-extracting HDRezka → {url} (s={season},e={episode})")
        ex = await tool_extract_hdrezka(url=url, quality=quality,
                                         translator=translator,
                                         season=season, episode=episode)
        if not ex.get("ok"):
            # Якщо це серіал без season/episode — повертаємо seasons/episodes для UI picker
            if ex.get("error") == "series_needs_season_episode":
                ep = await tool_hdrezka_episodes(url)
                if ep.get("ok"):
                    return {"ok": False, "needs_episode_picker": True,
                            "title": ep.get("title") or title,
                            "thumbnail": ep.get("thumbnail") or thumbnail,
                            "translator_id": ep.get("translator_id"),
                            "translator_name": ep.get("translator_name"),
                            "seasons": ep.get("seasons", []),
                            "episodes": ep.get("episodes", {}),
                            "page_url": url}
            return ex
        url = ex["url"]
        if not source:
            source = "hdrezka"
        if not title and ex.get("title"):
            title = ex["title"]
        extra["quality"] = ex.get("quality") or quality
        if ex.get("translator_id") is not None:
            extra["translator_id"] = ex["translator_id"]
        if ex.get("season") is not None:
            extra["season"] = ex["season"]
            extra["episode"] = ex["episode"]
            # Додаємо до title епізод щоб у history було видно
            if title and (ex.get("season") or ex.get("episode")):
                title = f"{title} · S{ex['season']:02d}E{ex['episode']:02d}"
        log.info(f"extracted stream: {url[:80]}")

    # Auto-detect YouTube
    if not source:
        if any(h in original_url for h in ("youtube.com", "youtu.be")):
            source = "youtube"
        elif original_url.startswith("/") or original_url.startswith("file://"):
            source = "local"
        else:
            source = "direct"

    await _kill_mpv()

    env = os.environ.copy()
    disp, auth = _detect_xauth()
    env["DISPLAY"] = disp
    if auth:
        env["XAUTHORITY"] = auth

    cmd = [
        "mpv",
        "--no-config",                    # не читаємо user config
        "--input-default-bindings=yes",   # але залишаємо default keybinds (esc=quit, space=pause)
        "--input-vo-keyboard=yes",
        "--vo=gpu", "--hwdec=no",
        "--cache=yes", "--cache-secs=30",
        f"--fullscreen={'yes' if fullscreen else 'no'}",
        "--input-ipc-server=/run/ostv/mpv.sock",
        "--msg-level=all=warn",
        "--keep-open=no",                 # exit одразу після EOF
    ]
    if resume_position and resume_position > 5:
        cmd.append(f"--start={int(resume_position)}")
    cmd.append(url)

    log.info(f"Starting mpv: {url[:80]}")
    current_mpv = await asyncio.create_subprocess_exec(
        *cmd, env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    asyncio.create_task(_watch_mpv_exit(current_mpv))

    # History entry — створюємо завжди (навіть з placeholder title)
    current_history_id = _history_create(
        title=title or original_url[-60:],
        source=source,
        original_url=original_url,
        stream_url=url,
        thumbnail=thumbnail,
        query=query,
        extra=extra,
        resume_position=resume_position,
    )
    _history_ensure_tracker()

    return {"ok": True, "pid": current_mpv.pid, "url": url, "history_id": current_history_id}


async def tool_play_youtube(url: str, fullscreen: bool = True,
                            title: str | None = None, thumbnail: str | None = None,
                            query: str | None = None) -> dict:
    return await tool_play_url(url=url, fullscreen=fullscreen, source="youtube",
                               title=title, thumbnail=thumbnail, query=query)


async def tool_stop() -> dict:
    global current_mpv
    if current_mpv and current_mpv.returncode is None:
        pid = current_mpv.pid
        await _kill_mpv()
        return {"ok": True, "stopped_pid": pid}
    return {"ok": False, "reason": "not playing"}


async def tool_search_youtube(query: str, limit: int = 12) -> dict:
    """Пошук YouTube через yt-dlp ytsearchN:query."""
    if not query.strip():
        return {"ok": False, "error": "empty query"}
    cmd = [
        "yt-dlp",
        f"ytsearch{limit}:{query}",
        "--dump-json",
        "--flat-playlist",
        "--no-warnings",
        "--skip-download",
        "--socket-timeout", "10",
    ]
    log.info(f"yt-dlp search: {query} (limit={limit})")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "error": "yt-dlp timeout"}

    if proc.returncode != 0:
        err = stderr.decode(errors="ignore")[:300]
        return {"ok": False, "error": f"yt-dlp rc={proc.returncode}: {err}"}

    videos = []
    for line in stdout.decode(errors="ignore").strip().split("\n"):
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        vid = d.get("id")
        if not vid:
            continue
        videos.append({
            "id": vid,
            "title": d.get("title") or "(без назви)",
            "url": d.get("url") or f"https://www.youtube.com/watch?v={vid}",
            "thumbnail": d.get("thumbnail") or f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
            "duration": d.get("duration"),
            "channel": d.get("channel") or d.get("uploader") or "",
            "source": "youtube",
        })
    log.info(f"yt-dlp search: {len(videos)} results")
    return {"ok": True, "videos": videos, "query": query}


# =========================
#    AI CHAT (Claude API)
# =========================

CLAUDE_MODEL = os.environ.get("OSTV_CLAUDE_MODEL", "claude-haiku-4-5")

AI_TOOLS_SCHEMA = [
    {
        "name": "search_all",
        "description": "Пошук фільмів/відео у всіх джерелах (YouTube + парсери). Повертає список результатів з title, url, thumbnail.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "пошуковий запит"},
                "limit": {"type": "integer", "default": 8},
            },
            "required": ["query"],
        },
    },
    {
        "name": "play_url",
        "description": "Запустити плеєр (mpv) з URL. Працює з YouTube, m3u8, mp4 та всім чим володіє yt-dlp.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "fullscreen": {"type": "boolean", "default": True},
            },
            "required": ["url"],
        },
    },
    {
        "name": "stop",
        "description": "Зупинити поточний плеєр",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "status",
        "description": "Поточний стан плеєра (чи щось грає)",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "launch_terminal",
        "description": "Відкрити системний термінал (xterm)",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "kbd_layout",
        "description": "Керування розкладкою клавіатури",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["toggle", "us", "ua", "query"]}
            },
        },
    },
]

AI_SYSTEM_PROMPT = """Ти — AI-агент у OsTv, домашній ТВ-операційній системі.
Твоя задача — допомагати юзеру керувати ТВ: шукати й запускати відео/фільми/музику,
розповідати про вміст, керувати системою.

Правила:
- Відповідай тією мовою, якою пише юзер (частіше — українська).
- Коли юзер каже "знайди X" — виклич search_all("X").
- Коли каже "увімкни Y" / "запусти Y" / "давай X" — спочатку search_all, потім play_url з першого релевантного результату. У відповіді зазнач що саме запускаєш.
- Якщо запит неоднозначний — переліч 2-3 варіанти й запитай.
- Будь стислим: 1-3 речення у відповіді.
- Емодзі використовуй помірно (▶ для play, 🔍 для пошуку, ✓ для успіху).
"""


def _load_secret(key: str) -> str | None:
    """Читає ключ з env або /etc/ostv/secrets.env"""
    v = os.environ.get(key)
    if v:
        return v
    try:
        with open("/etc/ostv/secrets.env") as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}="):
                    v = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return v or None
    except Exception:
        return None
    return None


def _load_anthropic_key() -> str | None:
    return _load_secret("ANTHROPIC_API_KEY")


# ============================================================
#  AI PROVIDER CONFIG
# ============================================================

AI_CONF_PATH = "/etc/ostv/ai.conf"

# default моделі для кожного провайдера
DEFAULT_MODELS = {
    "claude_cli":  "claude-haiku-4-5",
    "claude_api":  "claude-haiku-4-5",
    "openai":      "gpt-4o-mini",
    "gemini":      "gemini-2.0-flash",
    "openrouter":  "anthropic/claude-haiku-4-5",
    "ollama":      "qwen2.5:3b",
}

# дефолтні base_url (тільки де треба)
DEFAULT_BASE_URLS = {
    "openai":     "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama":     "http://localhost:11434",
}

# мапа secret-keys для кожного провайдера
PROVIDER_KEY_NAME = {
    "claude_api":  "ANTHROPIC_API_KEY",
    "openai":      "OPENAI_API_KEY",
    "gemini":      "GEMINI_API_KEY",
    "openrouter":  "OPENROUTER_API_KEY",
    # claude_cli і ollama — без ключа
}


def _load_ai_config() -> dict:
    """Читає /etc/ostv/ai.conf (TOML). Якщо нема — дефолт claude_cli."""
    cfg = {"provider": "claude_cli", "model": DEFAULT_MODELS["claude_cli"], "base_url": None}
    try:
        try:
            import tomllib  # py3.11+
        except ImportError:
            import tomli as tomllib  # type: ignore
        with open(AI_CONF_PATH, "rb") as f:
            data = tomllib.load(f)
        ai = data.get("ai", {}) if isinstance(data, dict) else {}
        prov = ai.get("provider", "claude_cli")
        if prov not in DEFAULT_MODELS:
            log.warning(f"unknown provider '{prov}' in ai.conf — fallback claude_cli")
            prov = "claude_cli"
        cfg["provider"] = prov
        cfg["model"] = ai.get("model", DEFAULT_MODELS[prov])
        cfg["base_url"] = ai.get("base_url") or DEFAULT_BASE_URLS.get(prov)
    except FileNotFoundError:
        # back-compat — env-змінна або дефолт
        prov = os.environ.get("OSTV_AI_BACKEND", "claude_cli")
        if prov == "claude-cli":
            prov = "claude_cli"
        elif prov == "anthropic-sdk":
            prov = "claude_api"
        if prov in DEFAULT_MODELS:
            cfg["provider"] = prov
            cfg["model"] = DEFAULT_MODELS[prov]
            cfg["base_url"] = DEFAULT_BASE_URLS.get(prov)
    except Exception as e:
        log.warning(f"ai.conf parse error: {e}")
    return cfg


def _save_ai_config(provider: str, model: str | None = None, base_url: str | None = None) -> None:
    """Пише /etc/ostv/ai.conf з мінімальним TOML."""
    if provider not in DEFAULT_MODELS:
        raise ValueError(f"unknown provider: {provider}")
    model = model or DEFAULT_MODELS[provider]
    base_url = base_url or DEFAULT_BASE_URLS.get(provider) or ""
    lines = ["[ai]\n", f'provider = "{provider}"\n', f'model = "{model}"\n']
    if base_url:
        lines.append(f'base_url = "{base_url}"\n')
    try:
        with open(AI_CONF_PATH, "w") as f:
            f.writelines(lines)
        log.info(f"ai.conf saved: provider={provider} model={model}")
    except PermissionError:
        log.warning(f"cannot write {AI_CONF_PATH} (no permission)")
        raise


def _save_secret(key: str, value: str) -> None:
    """Атомарно вписує/оновлює key=value у /etc/ostv/secrets.env."""
    path = "/etc/ostv/secrets.env"
    lines: list[str] = []
    found = False
    try:
        with open(path) as f:
            for line in f:
                if line.startswith(f"{key}="):
                    lines.append(f'{key}={value}\n')
                    found = True
                else:
                    lines.append(line)
    except FileNotFoundError:
        pass
    if not found:
        lines.append(f'{key}={value}\n')
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.writelines(lines)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    log.info(f"secret saved: {key}=*** ({len(value)} chars)")


CLAUDE_CLI_SYSTEM_PROMPT = """Ти — AI-агент OsTv, домашньої ТВ-ОС.
Керуєш медіа й системою через Bash tool.

ДОСТУПНІ КОМАНДИ (викликай через Bash):
  /opt/ostv/bin/brain.sh ping
  /opt/ostv/bin/brain.sh status
  /opt/ostv/bin/brain.sh search_all '{"query":"назва","limit":5}'
  /opt/ostv/bin/brain.sh search_youtube '{"query":"X","limit":5}'
  /opt/ostv/bin/brain.sh search_hdrezka '{"query":"X","limit":5}'
  /opt/ostv/bin/brain.sh play_url '{"url":"..."}'
  /opt/ostv/bin/brain.sh stop
  /opt/ostv/bin/brain.sh volume '{"action":"up"}'  # up|down|mute|query
  /opt/ostv/bin/brain.sh launch_terminal
  /opt/ostv/bin/brain.sh kbd_layout '{"action":"toggle"}'

ПРАВИЛА:
- Відповідай українською (якщо юзер пише іншою — на тій самій).
- Коли юзер каже "знайди X" — виклич search_all.
- Коли "увімкни Y" — спочатку search_all, потім play_url з першого результату.
- HDRezka URL (rezka.ag/films/...) → play_url сам зробить extract автоматично.
- Відповідай стисло: 1-3 речення.
- Без fluff типу "я виконаю...": просто виконуй і звітуй коротко.
"""


def _build_contextual_prompt(messages: list) -> str:
    """Перетворює conversation history у prompt для claude -p.
    Останнє user-повідомлення — основне. Попередня історія — контекст."""
    if not messages:
        return ""
    if len(messages) == 1:
        return messages[0].get("content", "")

    # Multi-turn: формуємо з попередніх ходів контекст
    lines = ["Попередня розмова:"]
    for m in messages[:-1]:
        role = "Користувач" if m.get("role") == "user" else "Ти"
        content = (m.get("content") or "").strip()
        if content:
            lines.append(f"[{role}]: {content}")
    last_user = messages[-1].get("content", "")
    lines.append("")
    lines.append(f"Новий запит користувача: {last_user}")
    return "\n".join(lines)


async def _get_state_snapshot() -> str:
    """Коротка сводка поточного стану для AI context."""
    parts = []
    # mpv state
    s = await tool_status()
    if s.get("playing"):
        parts.append(f"mpv: грає (pid={s.get('pid')})")
    else:
        parts.append("mpv: не грає")
    # volume
    try:
        v = await tool_volume(action="query")
        if v.get("ok"):
            parts.append(f"гучність: {v['volume_percent']}%" + (" (muted)" if v.get("muted") else ""))
    except Exception:
        pass
    # installed apps count
    try:
        a = await tool_list_apps()
        if a.get("ok"):
            parts.append(f"AI-apps: {len(a.get('apps', []))}")
    except Exception:
        pass
    return " · ".join(parts)


async def _ai_chat_via_cli(messages: list) -> dict:
    """Запит через `claude -p` з повною conversation історією і state snapshot."""
    if not os.path.exists("/usr/bin/claude"):
        return {"ok": False, "error": "claude CLI не встановлено"}

    env = os.environ.copy()
    env.setdefault("HOME", "/home/tv")

    prompt = _build_contextual_prompt(messages)
    state = await _get_state_snapshot()
    sys_prompt = CLAUDE_CLI_SYSTEM_PROMPT + f"\n\nПОТОЧНИЙ СТАН: {state}"

    cmd = [
        "/usr/bin/claude",
        "-p", prompt,
        "--allowedTools", "Bash",
        "--append-system-prompt", sys_prompt,
        "--output-format", "json",
        "--max-turns", "6",
    ]
    log.info(f"claude -p: {len(messages)} msg(s), last: {messages[-1].get('content','')[:60]}")
    proc = await asyncio.create_subprocess_exec(
        *cmd, env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "error": "claude CLI timeout 60s"}

    if proc.returncode != 0:
        err = stderr.decode(errors="ignore")[:400]
        return {"ok": False, "error": f"claude rc={proc.returncode}: {err}"}

    try:
        data = json.loads(stdout.decode(errors="ignore"))
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"parse: {e}", "raw": stdout.decode(errors="ignore")[:500]}

    reply = data.get("result") or data.get("text") or ""
    return {
        "ok": True,
        "reply": reply,
        "actions": [],  # CLI не expose internal tool calls окремо — тільки final result
        "backend": "claude-cli",
        "stop_reason": data.get("subtype", "end"),
    }


async def _ai_chat_openai_compat(messages: list, system: str, model: str,
                                  base_url: str, api_key: str,
                                  provider_label: str = "openai") -> dict:
    """OpenAI-compatible chat (працює для openai та openrouter)."""
    import urllib.request, urllib.error
    msgs = [{"role": "system", "content": system}]
    for m in messages:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            msgs.append({"role": m["role"], "content": m["content"]})
    body = {"model": model, "messages": msgs, "max_tokens": 1024}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if provider_label == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/Denromvas/ostv"
        headers["X-Title"] = "OsTv"
    try:
        def _do():
            req = urllib.request.Request(
                f"{base_url}/chat/completions",
                data=json.dumps(body).encode(),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode()
        raw = await asyncio.to_thread(_do)
        data = json.loads(raw)
        reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"ok": True, "reply": reply, "actions": [],
                "backend": provider_label, "model": model}
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")[:300]
        return {"ok": False,
                "error": f"{provider_label} HTTP {e.code}: {body}",
                "backend": provider_label}
    except Exception as e:
        return {"ok": False, "error": f"{provider_label}: {e}", "backend": provider_label}


async def _ai_chat_gemini(messages: list, system: str, model: str, api_key: str) -> dict:
    """Gemini REST API."""
    import urllib.request, urllib.error
    contents = []
    for m in messages:
        role = m.get("role")
        if role not in ("user", "assistant") or not m.get("content"):
            continue
        contents.append({
            "role": "user" if role == "user" else "model",
            "parts": [{"text": m["content"]}],
        })
    body = {
        "contents": contents,
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {"maxOutputTokens": 1024},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    try:
        def _do():
            req = urllib.request.Request(url,
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode()
        raw = await asyncio.to_thread(_do)
        data = json.loads(raw)
        cand = (data.get("candidates") or [{}])[0]
        parts = cand.get("content", {}).get("parts") or [{}]
        reply = "".join(p.get("text", "") for p in parts)
        return {"ok": True, "reply": reply, "actions": [], "backend": "gemini", "model": model}
    except urllib.error.HTTPError as e:
        return {"ok": False,
                "error": f"gemini HTTP {e.code}: {e.read().decode(errors='ignore')[:300]}",
                "backend": "gemini"}
    except Exception as e:
        return {"ok": False, "error": f"gemini: {e}", "backend": "gemini"}


async def _ai_chat_ollama(messages: list, system: str, model: str, base_url: str) -> dict:
    """Ollama локальний (HTTP /api/chat)."""
    import urllib.request, urllib.error
    msgs = [{"role": "system", "content": system}]
    for m in messages:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            msgs.append({"role": m["role"], "content": m["content"]})
    body = {"model": model, "messages": msgs, "stream": False}
    try:
        def _do():
            req = urllib.request.Request(
                f"{base_url}/api/chat",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read().decode()
        raw = await asyncio.to_thread(_do)
        data = json.loads(raw)
        reply = data.get("message", {}).get("content", "")
        return {"ok": True, "reply": reply, "actions": [], "backend": "ollama", "model": model}
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"ollama unreachable ({base_url}): {e}",
                "backend": "ollama"}
    except Exception as e:
        return {"ok": False, "error": f"ollama: {e}", "backend": "ollama"}


async def tool_ai_chat(messages: list, system: str | None = None, backend: str | None = None) -> dict:
    """AI chat. Backend (provider) береться з ai.conf або з аргументу.
    Підтримувані: claude_cli (default, OAuth), claude_api (Anthropic SDK з ключем),
    openai, gemini, openrouter, ollama (тільки text-чат, без tool-use).
    Tool-use повноцінно працює тільки в claude_cli/claude_api.
    """
    if not messages:
        return {"ok": False, "error": "no messages"}

    cfg = _load_ai_config()
    # back-compat: алias-и старих назв
    alias = {"claude-cli": "claude_cli", "anthropic-sdk": "claude_api"}
    provider = alias.get(backend, backend) if backend else cfg["provider"]
    model    = cfg["model"]   if not backend else (cfg["model"] if backend in ("", None) else DEFAULT_MODELS.get(provider, cfg["model"]))
    base_url = cfg["base_url"] or DEFAULT_BASE_URLS.get(provider)
    sys_prompt = system or AI_SYSTEM_PROMPT

    # === claude_cli (OAuth) ===
    if provider == "claude_cli":
        return await _ai_chat_via_cli(messages)

    # === openai / openrouter (OpenAI-compatible) ===
    if provider in ("openai", "openrouter"):
        key = _load_secret(PROVIDER_KEY_NAME[provider])
        if not key:
            return {"ok": False,
                    "error": f"Немає {PROVIDER_KEY_NAME[provider]}. Settings → AI API key.",
                    "backend": provider}
        return await _ai_chat_openai_compat(messages, sys_prompt, model,
                                            base_url, key, provider_label=provider)

    # === gemini ===
    if provider == "gemini":
        key = _load_secret("GEMINI_API_KEY")
        if not key:
            return {"ok": False,
                    "error": "Немає GEMINI_API_KEY. Settings → AI API key.",
                    "backend": "gemini"}
        return await _ai_chat_gemini(messages, sys_prompt, model, key)

    # === ollama (без ключа, локальний) ===
    if provider == "ollama":
        return await _ai_chat_ollama(messages, sys_prompt, model, base_url)

    # === claude_api (Anthropic SDK з tool-use) ===
    if not ANTHROPIC_AVAILABLE:
        return {"ok": False, "error": "anthropic SDK не встановлено", "backend": provider}

    api_key = _load_anthropic_key()
    if not api_key:
        return {
            "ok": False,
            "error": "Немає ANTHROPIC_API_KEY. Вставте у /etc/ostv/secrets.env: "
                     "ANTHROPIC_API_KEY=sk-ant-...",
        }

    client = Anthropic(api_key=api_key)
    # sys_prompt вже defined вище

    # Claude expects messages as list of {role, content} з текстом або array of blocks
    claude_messages: list = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant"):
            continue
        if content:
            claude_messages.append({"role": role, "content": content})

    actions: list = []

    for iteration in range(6):  # max 6 tool-use iterations
        try:
            resp = await asyncio.to_thread(
                client.messages.create,
                model=model,
                max_tokens=1024,
                system=sys_prompt,
                tools=AI_TOOLS_SCHEMA,
                messages=claude_messages,
            )
        except Exception as e:
            return {"ok": False, "error": f"Claude API: {e}", "actions": actions}

        if resp.stop_reason == "tool_use":
            # Додаємо assistant message з tool_use
            claude_messages.append({
                "role": "assistant",
                "content": [b.model_dump() for b in resp.content],
            })

            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    tname = block.name
                    tinput = block.input or {}
                    log.info(f"AI tool_use: {tname}({list(tinput.keys())})")

                    if tname in TOOLS:
                        try:
                            result = await TOOLS[tname](**tinput)
                        except Exception as e:
                            result = {"error": str(e)}
                    else:
                        result = {"error": f"unknown tool: {tname}"}

                    actions.append({"name": tname, "input": tinput, "result_summary": _summarize_result(result)})
                    # Обрізаємо result для контексту (thumbnail base64 тощо)
                    result_json = json.dumps(result, ensure_ascii=False)[:3000]
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_json,
                    })

            claude_messages.append({"role": "user", "content": tool_results})
            continue

        # Фінал — text response
        text_parts = [b.text for b in resp.content if b.type == "text"]
        return {
            "ok": True,
            "reply": "\n".join(text_parts).strip(),
            "actions": actions,
            "stop_reason": resp.stop_reason,
            "model": model,
            "backend": "claude_api",
        }

    return {"ok": False, "error": "max iterations", "actions": actions}


def _summarize_result(result) -> str:
    """Коротка репрезентація для UI (не повний JSON)"""
    if not isinstance(result, dict):
        return str(result)[:80]
    if result.get("videos"):
        n = len(result["videos"])
        first = result["videos"][0].get("title", "")[:60] if n else ""
        return f"{n} results, first: {first}"
    if result.get("results"):
        return f"{len(result['results'])} results"
    if "pid" in result:
        return f"pid={result['pid']}"
    keys = list(result.keys())[:3]
    return ",".join(keys)


async def tool_volume(action: str = "up", step: int = 5) -> dict:
    """Керує гучністю через pactl (PulseAudio API, emulated by pipewire-pulse).
    action: up | down | mute | query | set
    """
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XDG_RUNTIME_DIR", "/run/user/1500")
    SINK = "@DEFAULT_SINK@"

    async def _run(*cmd) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            *cmd, env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        return proc.returncode, (out + err).decode(errors="ignore")

    async def _get_vol() -> int:
        _, out = await _run("pactl", "get-sink-volume", SINK)
        import re
        m = re.search(r"(\d+)%", out)
        return int(m.group(1)) if m else 0

    if action == "up":
        cur = await _get_vol()
        target = min(100, cur + step)
        await _run("pactl", "--", "set-sink-volume", SINK, f"{target}%")
    elif action == "down":
        cur = await _get_vol()
        target = max(0, cur - step)
        await _run("pactl", "--", "set-sink-volume", SINK, f"{target}%")
    elif action == "mute":
        await _run("pactl", "set-sink-mute", SINK, "toggle")
    elif action == "set":
        target = max(0, min(100, step))
        await _run("pactl", "--", "set-sink-volume", SINK, f"{target}%")
    elif action != "query":
        return {"ok": False, "error": f"unknown action: {action}"}

    # Read current state
    _, vol_out = await _run("pactl", "get-sink-volume", SINK)
    _, mute_out = await _run("pactl", "get-sink-mute", SINK)
    import re
    m = re.search(r"(\d+)%", vol_out)
    vol_percent = int(m.group(1)) if m else 0
    muted = "yes" in mute_out.lower()
    return {
        "ok": True,
        "volume_percent": vol_percent,
        "muted": muted,
        "action": action,
    }


# =========================
#   Self-modifying: apps registry + AI-generated modules
# =========================

APPS_DIR = "/opt/ostv/apps"
PENDING_DIR = "/var/lib/ostv/pending"


async def tool_list_apps() -> dict:
    """Сканує /opt/ostv/apps/*/manifest.json і повертає список додатків."""
    apps = []
    if not os.path.isdir(APPS_DIR):
        return {"ok": True, "apps": []}
    for entry in sorted(os.listdir(APPS_DIR)):
        manifest_p = os.path.join(APPS_DIR, entry, "manifest.json")
        if not os.path.isfile(manifest_p):
            continue
        try:
            with open(manifest_p, encoding="utf-8") as f:
                manifest = json.load(f)
            manifest["_id"] = entry
            apps.append(manifest)
        except Exception as e:
            log.warning(f"bad manifest {manifest_p}: {e}")
    return {"ok": True, "apps": apps}


SELF_MOD_SYSTEM_PROMPT = """Ти — AI-конструктор модулів OsTv. Користувач описує бажаний додаток.
Твоя задача — згенерувати повний скелет нового OsTv-модуля і зберегти його у /var/lib/ostv/pending/<id>/.

Створи ці файли у pending/:
  manifest.json — {
    "name": "короткий_ідентифікатор_snake_case",
    "display_name": "Людська Назва",
    "version": "0.1.0",
    "description": "опис",
    "color": "#RRGGBB",
    "sprite": [16 рядків по 16 символів: R=колір, W=білий, .=прозоре],
    "commands": ["search", "play"]
  }
  parser.py — Python CLI з sub-commands search/play, повертає JSON на stdout
  README.md — опис що робить модуль

Використовуй Bash tool щоб створити директорію і записати файли.
УСІ команди на бекенді OsTv доступні через: /opt/ostv/bin/brain.sh <method> [json_params]
Наприклад можеш тестувати парсер одразу.

Після створення — повертай JSON (через останнє повідомлення):
{"module_name": "...", "pending_id": "...", "files": ["manifest.json","parser.py","README.md"], "ready_to_approve": true}

Правила:
- Код Python 3.10+, без важких залежностей (тільки requests + bs4 якщо треба парсити).
- Не використовуй subprocess для небезпечних речей.
- parser.py приймає --limit, --json flags.
- Коротко в chat — юзер побачить структурований результат.
"""


async def tool_propose_module(description: str) -> dict:
    """Викликає Claude щоб згенерував новий модуль за описом.
    Claude створює файли у /var/lib/ostv/pending/<uuid>/.
    Далі викликається tool_approve_module(pending_id) якщо юзер погоджується.
    """
    import uuid as _uuid
    os.makedirs(PENDING_DIR, exist_ok=True)
    pending_id = str(_uuid.uuid4())[:8]
    pending_path = os.path.join(PENDING_DIR, pending_id)
    os.makedirs(pending_path, exist_ok=True)

    full_prompt = (
        f"Створи OsTv-модуль: {description}\n\n"
        f"Pending директорія: {pending_path}\n"
        f"ID: {pending_id}\n\n"
        "Використай Bash щоб створити файли. Повертай JSON summary."
    )

    env = os.environ.copy()
    env.setdefault("HOME", "/home/tv")

    cmd = [
        "/usr/bin/claude", "-p", full_prompt,
        "--allowedTools", "Bash,Write,Read",
        "--append-system-prompt", SELF_MOD_SYSTEM_PROMPT,
        "--output-format", "json",
        "--max-turns", "10",
    ]
    log.info(f"propose_module: {description[:80]} → {pending_id}")
    proc = await asyncio.create_subprocess_exec(
        *cmd, env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "error": "claude timeout 180s", "pending_id": pending_id}

    if proc.returncode != 0:
        return {"ok": False, "error": stderr.decode(errors="ignore")[:300], "pending_id": pending_id}

    try:
        claude_resp = json.loads(stdout.decode(errors="ignore"))
    except json.JSONDecodeError:
        claude_resp = {"result": stdout.decode(errors="ignore")[:500]}

    # Збираємо список файлів які з'явились
    files = []
    if os.path.isdir(pending_path):
        files = sorted(os.listdir(pending_path))

    return {
        "ok": True,
        "pending_id": pending_id,
        "pending_path": pending_path,
        "files": files,
        "claude_reply": claude_resp.get("result", ""),
        "ready_to_approve": bool(files),
    }


async def tool_approve_module(pending_id: str) -> dict:
    """Переміщує pending модуль у /opt/ostv/apps/<name>/."""
    pending_path = os.path.join(PENDING_DIR, pending_id)
    if not os.path.isdir(pending_path):
        return {"ok": False, "error": f"pending {pending_id} не знайдено"}

    manifest_p = os.path.join(pending_path, "manifest.json")
    if not os.path.isfile(manifest_p):
        return {"ok": False, "error": "manifest.json відсутній"}

    try:
        with open(manifest_p, encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        return {"ok": False, "error": f"bad manifest: {e}"}

    name = manifest.get("name", "").strip()
    if not name or not name.replace("_", "").replace("-", "").isalnum():
        return {"ok": False, "error": f"bad name: {name!r}"}

    target = os.path.join(APPS_DIR, name)
    if os.path.exists(target):
        return {"ok": False, "error": f"app {name} вже встановлений"}

    os.makedirs(APPS_DIR, exist_ok=True)
    import shutil
    shutil.move(pending_path, target)
    # Make parser.py executable
    parser_p = os.path.join(target, "parser.py")
    if os.path.isfile(parser_p):
        os.chmod(parser_p, 0o755)
    return {"ok": True, "installed_as": name, "path": target}


async def tool_delete_app(app: str) -> dict:
    """Видаляє встановлений app з /opt/ostv/apps/<app>/."""
    app_dir = os.path.join(APPS_DIR, app)
    if not os.path.isdir(app_dir):
        return {"ok": False, "error": f"app {app} не знайдено"}
    import shutil
    shutil.rmtree(app_dir)
    return {"ok": True, "deleted": app}


async def tool_app_details(app: str) -> dict:
    """Повертає manifest + вміст parser.py (для AI modify)."""
    app_dir = os.path.join(APPS_DIR, app)
    if not os.path.isdir(app_dir):
        return {"ok": False, "error": "not found"}
    out = {"ok": True, "name": app, "path": app_dir, "files": {}}
    for fname in ("manifest.json", "parser.py", "README.md"):
        fpath = os.path.join(app_dir, fname)
        if os.path.isfile(fpath):
            try:
                with open(fpath, encoding="utf-8") as f:
                    out["files"][fname] = f.read()
            except Exception as e:
                out["files"][fname] = f"<read error: {e}>"
    return out


MODIFY_SYSTEM_PROMPT = """Ти — AI-редактор модулів OsTv. Користувач просить змінити існуючий модуль.
Завдання: внести модифікацію у файли /opt/ostv/apps/<app>/ (manifest.json, parser.py, README.md).

Використовуй Bash/Read/Edit/Write tools напряму — файли owned by ostv, тобі потрібен sudo,
тож виклики: sudo cat, sudo tee.

Можеш також тестувати парсер: sudo -u tv /opt/ostv/venv/bin/python /opt/ostv/apps/<app>/parser.py --json search

Після модифікації повертай JSON через останнє повідомлення:
{"modified": true, "changes_summary": "..."}

Правила:
- Мінімальні зміни, зберігай робочий код.
- Якщо треба додати parameter (наприклад --city для Weather) — оновлюй argparse.
- Якщо оновлюєш manifest — зберігай валідний JSON.
"""


async def tool_modify_module(app: str, description: str) -> dict:
    """Просить Claude модифікувати installed app."""
    app_dir = os.path.join(APPS_DIR, app)
    if not os.path.isdir(app_dir):
        return {"ok": False, "error": "app not found"}

    prompt = (
        f"Модифікуй OsTv-модуль '{app}' (шлях: {app_dir}).\n\n"
        f"Запит користувача: {description}\n\n"
        "Прочитай існуючі файли, зроби мінімальну модифікацію, збережи, протестуй."
    )

    env = os.environ.copy()
    env.setdefault("HOME", "/home/tv")

    cmd = [
        "/usr/bin/claude", "-p", prompt,
        "--allowedTools", "Bash,Read,Write,Edit",
        "--append-system-prompt", MODIFY_SYSTEM_PROMPT,
        "--output-format", "json",
        "--max-turns", "12",
    ]
    log.info(f"modify_module: {app} ← {description[:80]}")
    proc = await asyncio.create_subprocess_exec(
        *cmd, env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=240)
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "error": "claude timeout"}

    if proc.returncode != 0:
        return {"ok": False, "error": stderr.decode(errors="ignore")[:300]}

    try:
        resp = json.loads(stdout.decode(errors="ignore"))
    except json.JSONDecodeError:
        resp = {"result": stdout.decode(errors="ignore")[:500]}

    return {
        "ok": True,
        "app": app,
        "claude_reply": resp.get("result", ""),
    }


async def tool_run_app(app: str, command: str = "search", args: list | None = None) -> dict:
    """Запускає parser.py з /opt/ostv/apps/<app>/."""
    app_dir = os.path.join(APPS_DIR, app)
    parser_p = os.path.join(app_dir, "parser.py")
    if not os.path.isfile(parser_p):
        return {"ok": False, "error": f"app {app} not found"}
    cmd = ["/opt/ostv/venv/bin/python", parser_p, "--json"]
    if command:
        cmd.append(command)
    if args:
        cmd.extend(args)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "error": "app timeout"}
    if proc.returncode != 0:
        return {"ok": False, "error": stderr.decode(errors="ignore")[:200]}
    try:
        data = json.loads(stdout.decode(errors="ignore"))
    except json.JSONDecodeError:
        data = stdout.decode(errors="ignore")
    return {"ok": True, "result": data}


async def tool_delete_pending(pending_id: str) -> dict:
    pending_path = os.path.join(PENDING_DIR, pending_id)
    if not os.path.isdir(pending_path):
        return {"ok": False, "error": "not found"}
    import shutil
    shutil.rmtree(pending_path)
    return {"ok": True}


# =========================
#     Local filesystem (Music, Photos, Videos, Files)
# =========================

async def tool_list_files(directory: str, extensions: list | None = None,
                          recursive: bool = False, limit: int = 200) -> dict:
    """Сканує директорію, повертає список файлів + піддиректорій."""
    import pathlib
    try:
        base = pathlib.Path(directory).expanduser().resolve()
    except Exception as e:
        return {"ok": False, "error": f"bad path: {e}"}
    if not base.is_dir():
        return {"ok": False, "error": f"not a directory: {base}"}

    exts_norm = None
    if extensions:
        exts_norm = {e.lower().lstrip(".") for e in extensions}

    files = []
    dirs = []

    def walk():
        if recursive:
            return base.rglob("*")
        return base.iterdir()

    for p in walk():
        try:
            if p.is_dir():
                dirs.append({
                    "name": p.name,
                    "path": str(p),
                    "is_dir": True,
                })
            elif p.is_file():
                ext = p.suffix.lower().lstrip(".")
                if exts_norm and ext not in exts_norm:
                    continue
                stat = p.stat()
                files.append({
                    "name": p.name,
                    "path": str(p),
                    "size_mb": round(stat.st_size / 1024 / 1024, 2),
                    "ext": ext,
                    "mtime": int(stat.st_mtime),
                    "is_dir": False,
                })
                if len(files) >= limit:
                    break
        except (PermissionError, OSError):
            continue

    files.sort(key=lambda x: x["name"].lower())
    dirs.sort(key=lambda x: x["name"].lower())
    return {
        "ok": True,
        "directory": str(base),
        "parent": str(base.parent) if base.parent != base else None,
        "dirs": dirs,
        "files": files,
        "count": len(files),
    }


async def tool_play_playlist(files: list, mode: str = "video",
                             fullscreen: bool = True, shuffle: bool = False) -> dict:
    """Запускає mpv із списком файлів. mode: video|audio|image."""
    global current_mpv
    await _kill_mpv()

    if not files:
        return {"ok": False, "error": "empty playlist"}

    env = os.environ.copy()
    disp, auth = _detect_xauth()
    env["DISPLAY"] = disp
    if auth:
        env["XAUTHORITY"] = auth

    cmd = [
        "mpv", "--no-config",
        "--input-default-bindings=yes",
        "--input-conf=/opt/ostv/mpv.input.conf",
        f"--fullscreen={'yes' if fullscreen else 'no'}",
        "--input-ipc-server=/run/ostv/mpv.sock",
        "--msg-level=all=warn",
        "--keep-open=no",
    ]
    if mode == "audio":
        # аудіо — показуємо cover art якщо є; або force-window для візуалізації
        cmd.extend(["--force-window=yes", "--image-display-duration=inf"])
    elif mode == "image":
        cmd.extend([
            "--image-display-duration=5",
            "--loop-playlist=inf",
            "--osc=no",
        ])
    if shuffle:
        cmd.append("--shuffle")

    cmd.extend(files)
    log.info(f"play_playlist: mode={mode} count={len(files)} first={files[0][:80]}")
    current_mpv = await asyncio.create_subprocess_exec(
        *cmd, env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    asyncio.create_task(_watch_mpv_exit(current_mpv))
    return {"ok": True, "pid": current_mpv.pid, "count": len(files), "mode": mode}


async def tool_mpv_control(action: str) -> dict:
    """Керує запущеним mpv через IPC socket.
    action: pause | resume | toggle | next | prev | seek_fwd_10 | seek_back_10
    """
    import asyncio as _a
    sock_path = "/run/ostv/mpv.sock"
    if not os.path.exists(sock_path):
        return {"ok": False, "error": "mpv not running"}

    commands = {
        "pause": ["set_property", "pause", True],
        "resume": ["set_property", "pause", False],
        "toggle": ["cycle", "pause"],
        "next": ["playlist-next"],
        "prev": ["playlist-prev"],
        "seek_fwd_10": ["seek", 10],
        "seek_back_10": ["seek", -10],
    }
    if action not in commands:
        return {"ok": False, "error": f"unknown action: {action}"}

    try:
        reader, writer = await _a.open_unix_connection(sock_path)
        req = json.dumps({"command": commands[action]}) + "\n"
        writer.write(req.encode())
        await writer.drain()
        line = await _a.wait_for(reader.readline(), timeout=2)
        writer.close()
        try:
            return {"ok": True, "mpv_response": json.loads(line)}
        except json.JSONDecodeError:
            return {"ok": True, "raw": line.decode(errors="ignore")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def tool_history_list(limit: int = 50, include_finished: bool = True) -> dict:
    """Список історії перегляду (новіші перші). include_finished=False приховує >95% переглянуті."""
    h = _history_load()
    items = h.get("items", [])
    if not include_finished:
        items = [it for it in items if not it.get("finished")]
    items = sorted(items, key=lambda it: it.get("last_watched", 0), reverse=True)
    return {"ok": True, "items": items[:limit], "total": len(h.get("items", []))}


async def tool_history_get(id: str) -> dict:
    rec = _history_get(id)
    if not rec:
        return {"ok": False, "error": "not found"}
    return {"ok": True, "item": rec}


async def tool_history_resume(id: str, fullscreen: bool = True) -> dict:
    """Відновлює перегляд: re-extract URL якщо треба + mpv --start=position."""
    rec = _history_get(id)
    if not rec:
        return {"ok": False, "error": "not found"}
    pos = float(rec.get("position_sec", 0) or 0)
    # якщо переглянуто — починаємо з нуля
    if rec.get("finished"):
        pos = 0
    src = rec.get("source", "direct")
    orig = rec.get("original_url")
    title = rec.get("title")
    thumb = rec.get("thumbnail")
    query = rec.get("query")
    extra = rec.get("extra") or {}
    quality = extra.get("quality") or "1080p"

    if src == "hdrezka":
        # Передаємо ОРИГІНАЛЬНИЙ page URL — play_url сам re-extract'не свіжий потік
        return await tool_play_url(
            url=orig, fullscreen=fullscreen, quality=quality,
            title=title, source="hdrezka", thumbnail=thumb,
            query=query, resume_position=pos,
        )
    elif src == "youtube":
        return await tool_play_url(
            url=orig, fullscreen=fullscreen,
            title=title, source="youtube", thumbnail=thumb,
            query=query, resume_position=pos,
        )
    elif src in ("local", "direct"):
        return await tool_play_url(
            url=orig, fullscreen=fullscreen,
            title=title, source=src, thumbnail=thumb,
            query=query, resume_position=pos,
        )
    else:
        return {"ok": False, "error": f"unknown source: {src}"}


async def tool_history_remove(id: str) -> dict:
    h = _history_load()
    n0 = len(h["items"])
    h["items"] = [it for it in h["items"] if it["id"] != id]
    if len(h["items"]) == n0:
        return {"ok": False, "error": "not found"}
    _history_save(h)
    return {"ok": True, "removed": id}


async def tool_history_clear(only_finished: bool = False) -> dict:
    h = _history_load()
    if only_finished:
        kept = [it for it in h["items"] if not it.get("finished")]
        removed = len(h["items"]) - len(kept)
        h["items"] = kept
    else:
        removed = len(h["items"])
        h["items"] = []
    _history_save(h)
    return {"ok": True, "removed": removed}


async def tool_ai_status() -> dict:
    """Health-check AI підсистеми + список доступних провайдерів."""
    cfg = _load_ai_config()
    out: dict = {"ok": True, "provider": cfg["provider"], "model": cfg["model"],
                 "base_url": cfg["base_url"]}

    # Backward-compat keys (use ce фронт)
    out["claude_cli"] = os.path.exists("/usr/bin/claude")
    out["claude_cli_auth"] = False
    if out["claude_cli"]:
        try:
            cred = "/home/tv/.claude/.credentials.json"
            out["claude_cli_auth"] = os.path.exists(cred) and os.path.getsize(cred) > 50
        except Exception:
            pass
    out["anthropic_sdk"] = ANTHROPIC_AVAILABLE
    out["anthropic_key"] = bool(_load_anthropic_key())

    # Список усіх провайдерів + чи готовий кожен
    providers = {}
    providers["claude_cli"] = {
        "name": "Claude CLI (OAuth)",
        "ready": out["claude_cli"] and out["claude_cli_auth"],
        "needs_key": False,
    }
    providers["claude_api"] = {
        "name": "Anthropic API",
        "ready": out["anthropic_sdk"] and out["anthropic_key"],
        "needs_key": True, "key_var": "ANTHROPIC_API_KEY",
    }
    for prov, kvar in (("openai", "OPENAI_API_KEY"),
                       ("gemini", "GEMINI_API_KEY"),
                       ("openrouter", "OPENROUTER_API_KEY")):
        providers[prov] = {
            "name": prov.capitalize(),
            "ready": bool(_load_secret(kvar)),
            "needs_key": True, "key_var": kvar,
        }
    # Ollama: ready якщо socket localhost:11434 відповідає (швидкий перевір без важкого імпорту)
    ollama_ready = False
    try:
        import socket as _s
        with _s.create_connection(("localhost", 11434), timeout=1):
            ollama_ready = True
    except Exception:
        pass
    providers["ollama"] = {"name": "Ollama (local)", "ready": ollama_ready, "needs_key": False}

    out["providers"] = providers
    cur = providers.get(cfg["provider"], {})
    out["healthy"] = cur.get("ready", False)
    out["preferred"] = cfg["provider"]   # back-compat alias
    return out


async def tool_ai_set_provider(provider: str, model: str | None = None,
                                api_key: str | None = None,
                                base_url: str | None = None) -> dict:
    """Зберігає вибір провайдера у /etc/ostv/ai.conf і (якщо передано api_key) у secrets.env."""
    if provider not in DEFAULT_MODELS:
        return {"ok": False, "error": f"unknown provider: {provider}",
                "available": list(DEFAULT_MODELS.keys())}
    try:
        _save_ai_config(provider, model=model, base_url=base_url)
    except PermissionError as e:
        return {"ok": False, "error": f"cannot write {AI_CONF_PATH}: {e}"}
    if api_key and provider in PROVIDER_KEY_NAME:
        try:
            _save_secret(PROVIDER_KEY_NAME[provider], api_key)
        except PermissionError as e:
            return {"ok": False, "error": f"cannot write secrets.env: {e}",
                    "config_saved": True}
    return {"ok": True, "provider": provider,
            "model": model or DEFAULT_MODELS[provider],
            "base_url": base_url or DEFAULT_BASE_URLS.get(provider)}


async def tool_ai_test(backend: str | None = None) -> dict:
    """Real ping до моделі: відправляє "ping" і чекає короткої відповіді. Latency у мс."""
    import time as _time
    t0 = _time.time()
    try:
        r = await asyncio.wait_for(
            tool_ai_chat(messages=[{"role": "user", "content": "respond exactly: pong"}],
                         backend=backend),
            timeout=30,
        )
    except asyncio.TimeoutError:
        return {"ok": False, "error": "timeout 30s", "latency_ms": int((_time.time()-t0)*1000)}
    dt = int((_time.time()-t0)*1000)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error", "?"), "latency_ms": dt,
                "backend": r.get("backend") or backend}
    reply = (r.get("reply") or "").strip()
    return {"ok": True, "latency_ms": dt, "reply": reply[:60],
            "backend": r.get("backend") or backend, "model": r.get("model") or CLAUDE_MODEL}


async def tool_ai_reauth(provider: str = "claude_cli") -> dict:
    """Re-authentication flow.
    - claude_cli: запускає xterm з 'claude' (юзер виконує OAuth login в браузері)
    - anthropic-sdk: повертає інструкцію — ключ ставиться в Settings → API key
    """
    if provider == "claude_cli":
        env = os.environ.copy()
        disp, auth = _detect_xauth()
        env["DISPLAY"] = disp
        if auth:
            env["XAUTHORITY"] = auth
        # запускаємо xterm з claude → юзер сам логиниться
        cmd = [
            "xterm", "-fa", "JetBrains Mono", "-fs", "14", "-fullscreen",
            "-bg", "#000000", "-fg", "#41ff7a",
            "-title", "OsTv — Claude Reauth",
            "-e", "/usr/bin/claude",
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            asyncio.create_task(_watch_xterm_exit(proc))
            return {"ok": True, "pid": proc.pid,
                    "note": "у термінал введи /login та слідуй інструкціям OAuth"}
        except FileNotFoundError:
            return {"ok": False, "error": "xterm не встановлений"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    elif provider in ("anthropic-sdk", "claude_api", "anthropic"):
        return {"ok": False,
                "note": "API key reauth вручну — у Settings → Anthropic API key, або "
                        "echo 'ANTHROPIC_API_KEY=sk-ant-...' >> /etc/ostv/secrets.env"}
    return {"ok": False, "error": f"unknown provider: {provider}"}


async def tool_update_check() -> dict:
    """Перевірити чи є новіша версія OsTv на GitHub. Не ставить нічого."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", "/opt/ostv/scripts/update.sh", "--check",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        out = stdout.decode(errors="ignore")
        # Витягуємо останній рядок-JSON
        last_json = None
        for line in out.strip().split("\n")[::-1]:
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    last_json = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        if last_json:
            return last_json
        return {"ok": False, "error": "no JSON output", "stderr": stderr.decode(errors="ignore")[:200]}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def tool_update_apply(force: bool = False) -> dict:
    """Запустити апдейт OsTv до latest з GitHub. Detached — UI рестартує сам."""
    args = ["sudo", "-n", "/opt/ostv/scripts/update.sh"]
    if force:
        args.append("--force")
    log.info(f"update_apply: {' '.join(args)}")
    try:
        # Detached щоб ми не залежали від цього процесу
        await asyncio.create_subprocess_exec(
            "setsid", "bash", "-c",
            f"nohup {' '.join(args)} >>/var/log/ostv-update.log 2>&1 &",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"ok": True, "started": True,
                "note": "оновлення триває — лог /var/log/ostv-update.log; UI рестартує сам"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def tool_power(action: str = "reboot") -> dict:
    """Power-керування. action: reboot | shutdown | suspend | logout"""
    valid = {"reboot", "shutdown", "poweroff", "suspend", "logout"}
    action = action.lower()
    if action not in valid:
        return {"ok": False, "error": f"unknown action: {action} (expected one of {valid})"}

    if action == "reboot":
        cmd = ["sudo", "-n", "/usr/bin/systemctl", "reboot"]
    elif action in ("shutdown", "poweroff"):
        cmd = ["sudo", "-n", "/usr/bin/systemctl", "poweroff"]
    elif action == "suspend":
        cmd = ["sudo", "-n", "/usr/bin/systemctl", "suspend"]
    elif action == "logout":
        cmd = ["pkill", "-TERM", "-u", "tv", "openbox-session"]

    log.info(f"POWER: {action} → {' '.join(cmd)}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            # Power дія почалась — машина завершується
            return {"ok": True, "action": action, "note": "executing"}
        if proc.returncode != 0:
            return {"ok": False, "action": action,
                    "error": stderr.decode(errors="ignore")[:200]}
        return {"ok": True, "action": action}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def tool_reload_ui(hard: bool = True) -> dict:
    """Перезапуск UI. hard=True: kill+detached relaunch ostv-ui (для нової збірки бінарника).
       hard=False: підказка клієнту що треба window.location.reload() — фронт сам це робить."""
    if not hard:
        return {"ok": True, "soft": True, "hint": "client should window.location.reload()"}

    disp, auth = _detect_xauth()
    auth_line = f"export XAUTHORITY={auth}\n" if auth else ""
    relaunch = "/tmp/ostv-relaunch.sh"
    script = f"""#!/bin/bash
sleep 1
export DISPLAY={disp}
{auth_line}export XDG_RUNTIME_DIR=/run/user/$(id -u tv)
export GDK_DEBUG=gl-disable
export WEBKIT_DISABLE_COMPOSITING_MODE=1
export WEBKIT_DISABLE_DMABUF_RENDERER=1
export LIBGL_ALWAYS_SOFTWARE=1
export MESA_LOADER_DRIVER_OVERRIDE=llvmpipe
exec /opt/ostv/bin/ostv-ui >/home/tv/.local/share/ostv/ui-reload.log 2>&1
"""
    try:
        with open(relaunch, "w") as f:
            f.write(script)
        os.chmod(relaunch, 0o755)
    except Exception as e:
        return {"ok": False, "error": f"write relaunch script: {e}"}

    # Detached spawn — survives parent (Brain) і не вмирає при kill старого UI
    log.info(f"reload_ui: spawning detached relaunch script {relaunch}")
    try:
        await asyncio.create_subprocess_exec(
            "setsid", "bash", "-c", f"nohup {relaunch} >/dev/null 2>&1 &",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        return {"ok": False, "error": f"spawn detached: {e}"}

    # Дамо дочірньому встигнути від'єднатись
    await asyncio.sleep(0.3)
    # Вбиваємо поточний UI
    log.info("reload_ui: killing current ostv-ui")
    try:
        await asyncio.create_subprocess_exec(
            "pkill", "-9", "-f", "/opt/ostv/bin/ostv-ui",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except Exception as e:
        return {"ok": True, "warning": f"pkill failed: {e}"}
    return {"ok": True, "hard": True, "note": "ui restart in ~1s"}


async def tool_launch_terminal(shell: str = "bash") -> dict:
    """Запускає xterm fullscreen з bash. При exit — фокус повертається на OsTv."""
    env = os.environ.copy()
    disp, auth = _detect_xauth()
    env["DISPLAY"] = disp
    if auth:
        env["XAUTHORITY"] = auth

    cmd = [
        "xterm",
        "-fa", "JetBrains Mono",
        "-fs", "14",
        "-fullscreen",
        "-bg", "#000000",
        "-fg", "#e0e0e0",
        "-title", "OsTv Terminal",
        "-e", shell, "-i",
    ]
    log.info("launching xterm fullscreen")
    proc = await asyncio.create_subprocess_exec(
        *cmd, env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    asyncio.create_task(_watch_xterm_exit(proc))
    return {"ok": True, "pid": proc.pid}


async def _watch_xterm_exit(proc):
    await proc.wait()
    log.info(f"xterm (pid={proc.pid}) exited")
    await _restore_focus()


async def tool_kbd_layout(action: str = "toggle") -> dict:
    """Перемикає keyboard layout через setxkbmap. action: 'toggle'|'us'|'ua'|'query'"""
    env = os.environ.copy()
    disp, auth = _detect_xauth()
    env["DISPLAY"] = disp
    if auth:
        env["XAUTHORITY"] = auth

    async def _run(cmd: list[str]) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            *cmd, env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        return proc.returncode, out.decode(errors="ignore")

    # query current
    rc, out = await _run(["setxkbmap", "-query"])
    current = "us"
    for line in out.splitlines():
        if line.startswith("layout:"):
            current = line.split(":", 1)[1].strip().split(",")[0]
            break

    if action == "query":
        return {"ok": True, "current": current}

    if action == "toggle":
        target = "ua" if current == "us" else "us"
    elif action in ("us", "ua"):
        target = action
    else:
        return {"ok": False, "error": f"unknown action: {action}"}

    rc, _ = await _run(["setxkbmap", "-layout", target])
    return {"ok": rc == 0, "layout": target, "was": current}


HDREZKA_PARSER = "/opt/ostv/parsers/hdrezka/hdrezka.py"


async def _hdrezka_exec(*args, timeout=30) -> dict:
    if not os.path.exists(HDREZKA_PARSER):
        return {"ok": False, "error": f"parser missing: {HDREZKA_PARSER}"}
    proc = await asyncio.create_subprocess_exec(
        "/opt/ostv/venv/bin/python", HDREZKA_PARSER, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "error": "hdrezka timeout"}
    if proc.returncode != 0:
        return {"ok": False, "error": stderr.decode(errors="ignore")[:300]}
    try:
        return json.loads(stdout.decode(errors="ignore"))
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"parse: {e}"}


async def tool_search_hdrezka(query: str, limit: int = 8) -> dict:
    data = await _hdrezka_exec("search", query, "--limit", str(limit))
    if data.get("ok"):
        return {"ok": True, "videos": data.get("videos", []), "source": "hdrezka", "mirror": data.get("mirror")}
    return data


async def tool_extract_hdrezka(url: str, quality: str = "1080p", translator: str | None = None,
                                season: int | None = None, episode: int | None = None) -> dict:
    args = ["extract", url, "--quality", quality]
    if translator:
        args += ["--translator", str(translator)]
    if season is not None:
        args += ["--season", str(season)]
    if episode is not None:
        args += ["--episode", str(episode)]
    return await _hdrezka_exec(*args, timeout=45)


async def tool_hdrezka_episodes(url: str) -> dict:
    """Повертає seasons/episodes для серіалу (або is_series=False для фільму)."""
    return await _hdrezka_exec("info", url, timeout=45)


FILMIX_PARSER = "/opt/ostv/parsers/filmix/filmix.py"


async def _filmix_exec(*args, timeout=30) -> dict:
    if not os.path.exists(FILMIX_PARSER):
        return {"ok": False, "error": f"parser missing: {FILMIX_PARSER}"}
    proc = await asyncio.create_subprocess_exec(
        "/opt/ostv/venv/bin/python", FILMIX_PARSER, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "error": "filmix timeout"}
    if proc.returncode != 0:
        return {"ok": False, "error": stderr.decode(errors="ignore")[:300]}
    try:
        return json.loads(stdout.decode(errors="ignore"))
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"parse: {e}"}


async def tool_search_filmix(query: str, limit: int = 8) -> dict:
    return await _filmix_exec("search", query, "--limit", str(limit))


async def tool_extract_filmix(url: str, quality: str = "1080p") -> dict:
    return await _filmix_exec("extract", url, "--quality", quality, timeout=45)


async def tool_search_all(query: str, limit: int = 8) -> dict:
    """Паралельно пошук у всіх джерелах (YouTube + HDRezka + Filmix)."""
    tasks = {
        "youtube": asyncio.create_task(tool_search_youtube(query=query, limit=limit)),
        "hdrezka": asyncio.create_task(tool_search_hdrezka(query=query, limit=limit)),
        "filmix":  asyncio.create_task(tool_search_filmix(query=query, limit=limit)),
    }
    done = {k: await t for k, t in tasks.items()}

    results = []
    for src_name, res in done.items():
        if res.get("ok"):
            results.extend(res.get("videos", []))

    return {
        "ok": True,
        "results": results,
        "query": query,
        "sources": {k: v.get("ok", False) for k, v in done.items()},
    }


TOOLS = {
    "ping": tool_ping,
    "status": tool_status,
    "focus_ui": tool_focus_ui,
    "play_url": tool_play_url,
    "play_youtube": tool_play_youtube,
    "stop": tool_stop,
    "search_youtube": tool_search_youtube,
    "search_hdrezka": tool_search_hdrezka,
    "extract_hdrezka": tool_extract_hdrezka,
    "hdrezka_episodes": tool_hdrezka_episodes,
    "search_filmix": tool_search_filmix,
    "extract_filmix": tool_extract_filmix,
    "search_all": tool_search_all,
    "kbd_layout": tool_kbd_layout,
    "volume": tool_volume,
    "power": tool_power,
    "reload_ui": tool_reload_ui,
    "history_list": tool_history_list,
    "history_get": tool_history_get,
    "history_resume": tool_history_resume,
    "history_remove": tool_history_remove,
    "history_clear": tool_history_clear,
    "update_check": tool_update_check,
    "update_apply": tool_update_apply,
    "list_files": tool_list_files,
    "play_playlist": tool_play_playlist,
    "mpv_control": tool_mpv_control,
    "launch_terminal": tool_launch_terminal,
    "ai_chat": tool_ai_chat,
    "ai_status": tool_ai_status,
    "ai_test": tool_ai_test,
    "ai_reauth": tool_ai_reauth,
    "ai_set_provider": tool_ai_set_provider,
    "list_apps": tool_list_apps,
    "propose_module": tool_propose_module,
    "approve_module": tool_approve_module,
    "delete_pending": tool_delete_pending,
    "run_app": tool_run_app,
    "app_details": tool_app_details,
    "modify_module": tool_modify_module,
    "delete_app": tool_delete_app,
}


async def handle_client(reader, writer):
    log.info("client connected")
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                req = json.loads(line)
            except json.JSONDecodeError as e:
                writer.write((json.dumps({"error": f"bad json: {e}"}) + "\n").encode())
                await writer.drain()
                continue

            method = req.get("method")
            params = req.get("params") or {}
            req_id = req.get("id")
            log.info(f"<- {method} {list(params.keys())}")
            try:
                if method not in TOOLS:
                    resp = {"error": f"unknown method: {method}", "id": req_id}
                else:
                    result = await TOOLS[method](**params)
                    resp = {"result": result, "id": req_id}
            except TypeError as e:
                resp = {"error": f"bad params: {e}", "id": req_id}
            except Exception as e:
                log.exception("tool failed")
                resp = {"error": str(e), "id": req_id}

            writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode())
            await writer.drain()
    except ConnectionResetError:
        pass
    finally:
        writer.close()


async def main():
    SOCK.parent.mkdir(parents=True, exist_ok=True)
    if SOCK.exists():
        SOCK.unlink()
    server = await asyncio.start_unix_server(handle_client, path=str(SOCK))
    os.chmod(SOCK, 0o660)
    try:
        import grp
        gid = grp.getgrnam("ostv").gr_gid
        os.chown(SOCK, os.geteuid() if os.geteuid() != 0 else 0, gid)
    except (KeyError, PermissionError):
        pass
    log.info(f"OsTv Brain v0.0.3 listening on {SOCK}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("shutdown")
