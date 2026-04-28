#!/usr/bin/env python3
"""HDRezka CLI parser — v0.3.0 (advanced_search + series-aware extract)

Usage:
  hdrezka.py search "query" [--limit 10] [--mirror URL]
  hdrezka.py info <url>                                  — series → seasons/episodes
  hdrezka.py extract <url> [--quality 1080p] [--translator ID] [--season N] [--episode M]

Stdout — JSON.
  search: {"ok", "videos": [{"id","title","url","thumbnail","year","type","source","rating"}]}
  info:   {"ok", "is_series", "seasons": [...], "episodes": {1: [...]}, "translator_id"}
  extract:{"ok", "url", "title", "quality", "translator_id"}

Потребує: pip install HdRezkaApi requests beautifulsoup4
"""
import json
import argparse
import sys
import re

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


def _category_kind(cat) -> str:
    """category.series → 'series', category.film → 'film', category.anime → 'anime'."""
    s = str(cat or "").lower()
    if "series" in s: return "series"
    if "film" in s:   return "film"
    if "anime" in s:  return "anime"
    return ""


def _kind_from_url(url: str) -> str:
    if "/series/" in url:    return "series"
    if "/animation/" in url: return "anime"
    if "/films/" in url:     return "film"
    return ""


def _year_from_title(title: str) -> str:
    m = re.search(r'\((\d{4})\)', title or "")
    return m.group(1) if m else ""


def _try_search(mirror, query, limit):
    """Пробує advanced_search (з постером/категорією), fallback fast_search."""
    try:
        s = HdRezkaSearch(mirror)
    except Exception as e:
        return None, "init: " + str(e)
    # advanced_search має постер + category
    if hasattr(s, "advanced_search"):
        try:
            res = s.advanced_search(query)
            if res:
                # advanced_search вертає вкладений список — flatten
                flat = []
                for x in res:
                    if isinstance(x, list):
                        flat.extend(x)
                    else:
                        flat.append(x)
                return ("advanced", flat[:limit]), None
        except Exception as e:
            pass  # fallthrough
    try:
        res = s.fast_search(query)
        return ("fast", (res or [])[:limit]), None
    except Exception as e:
        return None, str(e)


def search(query, limit=10, mirror=None):
    last_err = "unknown"
    mirrors = [mirror] if mirror else DEFAULT_MIRRORS
    for m in mirrors:
        out, err = _try_search(m, query, limit)
        if out is not None:
            kind, results = out
            videos = []
            for r in results:
                try:
                    if isinstance(r, dict):
                        title = (r.get("title") or "").strip()
                        url = r.get("url") or ""
                        thumb = r.get("image") or r.get("thumbnail") or r.get("poster") or ""
                        cat = r.get("category")
                        rating = r.get("rating")
                    else:
                        title = (getattr(r, "title", "") or "").strip()
                        url = getattr(r, "url", "") or ""
                        thumb = getattr(r, "image", "") or getattr(r, "thumbnail", "") or getattr(r, "poster", "") or ""
                        cat = getattr(r, "category", None)
                        rating = getattr(r, "rating", None)
                    if not url or not title:
                        continue
                    item_id = ""
                    m_id = re.search(r'/(\d+)-', url)
                    if m_id:
                        item_id = m_id.group(1)
                    kind_str = _category_kind(cat) or _kind_from_url(url)
                    videos.append({
                        "id": item_id,
                        "title": title,
                        "url": url,
                        "thumbnail": thumb,
                        "year": _year_from_title(title),
                        "type": kind_str,           # film | series | anime
                        "rating": rating,
                        "mirror": m,
                        "source": "hdrezka",
                    })
                except Exception:
                    continue
            return {"ok": True, "videos": videos, "mirror": m, "search_kind": kind}
        last_err = err or "no results"
    return {
        "ok": False,
        "error": f"усі mirror'и недоступні: {last_err}. Потрібен VPN?",
    }


UA_MARKERS = ("україн", "украин", "ukrainian", "укр дубляж", "дубляж (укр")


def _find_ua_translator(translators: dict):
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


def _is_series(rezka) -> bool:
    """Вгадує чи це серіал (за type або наявністю seriesInfo)."""
    try:
        t = str(getattr(rezka, "type", "") or "").lower()
        if "tv_series" in t or "series" in t:
            return True
    except Exception:
        pass
    try:
        si = getattr(rezka, "seriesInfo", None)
        if isinstance(si, dict) and si:
            return True
    except Exception:
        pass
    return False


def info(url):
    """Для series повертає список сезонів/епізодів. Для фільмів — type=film."""
    try:
        rezka = HdRezkaApi(url)
    except Exception as e:
        return {"ok": False, "error": f"HdRezkaApi init: {e}"}
    if not getattr(rezka, "ok", False):
        return {"ok": False, "error": f"rezka not ok: {rezka.exception}"}

    if not _is_series(rezka):
        return {
            "ok": True,
            "is_series": False,
            "title": rezka.name or "",
            "year": str(getattr(rezka, "releaseYear", "") or ""),
            "thumbnail": getattr(rezka, "thumbnail", "") or "",
        }

    # Series — ВИКОРИСТОВУЄМО episodesInfo (full list з translators per episode)
    ei = getattr(rezka, "episodesInfo", None) or []
    if not ei:
        return {"ok": False, "error": "episodesInfo empty"}

    seasons_list: list = []
    episodes_dict: dict = {}
    # Збираємо мапу translator_id → translator_name + кількість епізодів де він доступний
    translator_stats: dict = {}  # tid: {"name": str, "count": int}

    for season_block in ei:
        sid = season_block.get("season")
        sname = season_block.get("season_text") or f"Сезон {sid}"
        seasons_list.append({"id": int(sid), "name": str(sname)})
        eps = []
        for ep in season_block.get("episodes", []):
            eps.append({
                "id": int(ep.get("episode", 0)),
                "name": str(ep.get("episode_text", "") or f"Серія {ep.get('episode')}"),
                "translators": [int(t["translator_id"]) for t in ep.get("translations", [])
                                if "translator_id" in t],
            })
            for t in ep.get("translations", []):
                tid = int(t["translator_id"])
                translator_stats.setdefault(tid, {"name": t.get("translator_name", ""), "count": 0})
                translator_stats[tid]["count"] += 1
        episodes_dict[str(sid)] = eps

    # Обираємо translator: UA-маркер з найбільшим count; fallback — найпопулярніший
    ua_cand = [(tid, info["count"]) for tid, info in translator_stats.items()
               if any(m in info["name"].lower() for m in UA_MARKERS)]
    if ua_cand:
        ua_cand.sort(key=lambda x: x[1], reverse=True)
        chosen_tid = ua_cand[0][0]
    elif translator_stats:
        all_sorted = sorted(translator_stats.items(), key=lambda x: x[1]["count"], reverse=True)
        chosen_tid = all_sorted[0][0]
    else:
        return {"ok": False, "error": "no translators with episodes"}

    return {
        "ok": True,
        "is_series": True,
        "title": rezka.name or "",
        "year": str(getattr(rezka, "releaseYear", "") or ""),
        "thumbnail": getattr(rezka, "thumbnail", "") or "",
        "translator_id": str(chosen_tid),
        "translator_name": translator_stats[chosen_tid]["name"],
        "seasons": seasons_list,
        "episodes": episodes_dict,
        "translators_available": [
            {"id": tid, "name": info["name"], "count": info["count"]}
            for tid, info in translator_stats.items()
        ],
    }


def extract(url, quality="1080p", translator=None, season=None, episode=None, require_ua=True):
    """Повертає direct stream URL.
    Для серіалу обов'язково потрібні season+episode (інакше HdRezkaApi.getStream падає).
    """
    try:
        rezka = HdRezkaApi(url)
    except Exception as e:
        return {"ok": False, "error": f"HdRezkaApi init: {e}"}
    if not getattr(rezka, "ok", False):
        return {"ok": False, "error": f"rezka not ok: {rezka.exception}"}

    is_series = _is_series(rezka)
    trs = rezka.translators or {}

    # Translator
    used_tr = translator
    if not used_tr:
        ua_tr = _find_ua_translator(trs)
        if ua_tr:
            used_tr = ua_tr
        elif require_ua:
            names = [info.get("name", str(tid)) if isinstance(info, dict) else str(info)
                     for tid, info in trs.items()]
            return {"ok": False, "error": "Немає української озвучки",
                    "translators_available": names, "title": rezka.name or ""}
        else:
            used_tr = next(iter(trs.keys()), None)
            if not used_tr:
                return {"ok": False, "error": "no translators available"}

    if is_series and (season is None or episode is None):
        return {"ok": False, "error": "series_needs_season_episode",
                "is_series": True, "translator_id": str(used_tr)}

    try:
        kwargs = {"translation": used_tr}
        if is_series:
            kwargs["season"] = int(season)
            kwargs["episode"] = int(episode)
        stream = rezka.getStream(**kwargs)
    except Exception as e:
        return {"ok": False, "error": f"getStream: {e}"}

    try:
        m3u8 = stream(quality)
    except KeyError:
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
        "translator_id": str(used_tr),
        "season": int(season) if season is not None else None,
        "episode": int(episode) if episode is not None else None,
    }


def main():
    p = argparse.ArgumentParser(prog="hdrezka")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--mirror")

    i = sub.add_parser("info")
    i.add_argument("url")

    e = sub.add_parser("extract")
    e.add_argument("url")
    e.add_argument("--quality", default="1080p")
    e.add_argument("--translator")
    e.add_argument("--season", type=int)
    e.add_argument("--episode", type=int)
    e.add_argument("--any-lang", action="store_true")

    args = p.parse_args()
    if args.cmd == "search":
        out = search(args.query, args.limit, args.mirror)
    elif args.cmd == "info":
        out = info(args.url)
    elif args.cmd == "extract":
        out = extract(args.url, args.quality, args.translator,
                      args.season, args.episode, require_ua=not args.any_lang)
    else:
        out = {"ok": False, "error": "unknown command"}
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
