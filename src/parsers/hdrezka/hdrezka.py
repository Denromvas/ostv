#!/usr/bin/env python3
"""HDRezka CLI parser — v0.2.0 (real extraction via HdRezkaApi pkg)

Usage:
  hdrezka.py search "query" [--limit 10] [--mirror URL]
  hdrezka.py extract <url> [--quality 1080p] [--translator "Оригінал"]

Stdout — JSON:
  search: {"ok", "videos": [{"id","title","url","thumbnail","year","type","source"}]}
  extract: {"ok", "url", "title", "quality", "translator"}

Потребує: pip install HdRezkaApi requests beautifulsoup4
"""
import json
import argparse
import sys

try:
    from HdRezkaApi import HdRezkaApi, HdRezkaSearch
except ImportError:
    print(json.dumps({"ok": False, "error": "HdRezkaApi not installed"}))
    sys.exit(1)

DEFAULT_MIRRORS = [
    "https://rezka.ag",
    "https://hdrezka.ag",
    "https://hdrezka.cc",
]


def _try_search(mirror, query, limit, advanced=False):
    try:
        s = HdRezkaSearch(mirror)
        if advanced and hasattr(s, "advanced_search"):
            results = s.advanced_search(query)
        else:
            results = s.fast_search(query)
    except Exception as e:
        return None, str(e)
    return results, None


def _get(obj, key, default=""):
    """Підтримка як dict так і об'єкта."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def search(query, limit=10, mirror=None):
    last_err = "unknown"
    mirrors = [mirror] if mirror else DEFAULT_MIRRORS
    for m in mirrors:
        res, err = _try_search(m, query, limit)
        if res is not None:
            videos = []
            for r in (res or [])[:limit]:
                try:
                    url = _get(r, "url", "") or ""
                    # id можна вивести з URL: /films/xxx/12345-title-...
                    item_id = ""
                    import re
                    m_id = re.search(r'/(\d+)-', url)
                    if m_id:
                        item_id = m_id.group(1)
                    videos.append({
                        "id": item_id or str(_get(r, "id", "") or ""),
                        "title": (_get(r, "title", "") or "").strip(),
                        "url": url,
                        "thumbnail": _get(r, "thumbnail", "") or _get(r, "poster", "") or "",
                        "year": str(_get(r, "year", "") or ""),
                        "type": str(_get(r, "type", "") or ""),
                        "rating": _get(r, "rating", ""),
                        "mirror": m,
                        "source": "hdrezka",
                    })
                except Exception:
                    continue
            return {"ok": True, "videos": videos, "mirror": m}
        last_err = err or "no results"
    return {
        "ok": False,
        "error": f"усі mirror'и недоступні: {last_err}. Потрібен VPN?",
    }


UA_MARKERS = ("україн", "украин", "ukrainian", "укр дубляж", "дубляж (укр")


def _find_ua_translator(translators: dict):
    """Шукає найбільш український варіант перекладу.
    translators: {id: {"name": "...", "premium": bool}}
    Повертає translator_id або None.
    """
    if not translators:
        return None
    for tid, info in translators.items():
        name_str = ""
        if isinstance(info, dict):
            name_str = str(info.get("name", "")).lower()
        else:
            name_str = str(info).lower()
        if any(m in name_str for m in UA_MARKERS):
            return tid
    return None


def extract(url, quality="1080p", translator=None, require_ua=True):
    """Повертає direct stream URL (m3u8/mp4) для mpv.
    За замовчуванням — пріоритет на українську озвучку. Якщо нема — error.
    """
    try:
        rezka = HdRezkaApi(url)
    except Exception as e:
        return {"ok": False, "error": f"HdRezkaApi init: {e}"}

    if not getattr(rezka, "ok", False):
        return {"ok": False, "error": f"rezka not ok: {rezka.exception}"}

    trs = rezka.translators or {}
    try:
        if translator:
            used_tr = translator
            stream = rezka.getStream(translation=translator)
        else:
            ua_tr = _find_ua_translator(trs)
            if ua_tr:
                used_tr = ua_tr
                stream = rezka.getStream(translation=ua_tr)
            elif require_ua:
                names = []
                for tid, info in trs.items():
                    if isinstance(info, dict):
                        names.append(info.get("name", str(tid)))
                    else:
                        names.append(str(info))
                return {
                    "ok": False,
                    "error": "Немає української озвучки",
                    "translators_available": names,
                    "title": rezka.name or "",
                }
            else:
                used_tr = next(iter(trs.keys())) if trs else None
                if not used_tr:
                    return {"ok": False, "error": "no translators available"}
                stream = rezka.getStream(translation=used_tr)
    except Exception as e:
        return {"ok": False, "error": f"getStream: {e}"}

    try:
        m3u8 = stream(quality)
    except KeyError:
        # quality не доступна — беремо максимальну доступну
        try:
            available = sorted(stream.videos.keys(), reverse=True) if hasattr(stream, "videos") else []
            if not available:
                return {"ok": False, "error": "no video qualities"}
            quality = available[0]
            m3u8 = stream(quality)
        except Exception as e:
            return {"ok": False, "error": f"quality fallback: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"stream extract: {e}"}

    # m3u8 може бути list (fallback mirrors) або str
    if isinstance(m3u8, (list, tuple)):
        primary = str(m3u8[0]) if m3u8 else ""
        mirrors = [str(u) for u in m3u8]
    else:
        primary = str(m3u8)
        mirrors = [primary]

    return {
        "ok": True,
        "url": primary,
        "mirrors": mirrors,
        "title": rezka.name or "",
        "quality": quality,
        "translator": str(used_tr),
    }


def main():
    p = argparse.ArgumentParser(prog="hdrezka")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--mirror")

    e = sub.add_parser("extract")
    e.add_argument("url")
    e.add_argument("--quality", default="1080p")
    e.add_argument("--translator")
    e.add_argument("--any-lang", action="store_true", help="не вимагати UA озвучку")

    args = p.parse_args()

    if args.cmd == "search":
        out = search(args.query, args.limit, args.mirror)
    elif args.cmd == "extract":
        out = extract(args.url, args.quality, args.translator, require_ua=not args.any_lang)
    else:
        out = {"ok": False, "error": "unknown command"}

    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
