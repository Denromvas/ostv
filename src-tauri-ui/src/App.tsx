import { useEffect, useState, useCallback, useRef, memo, useMemo } from "react";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";

// ============ Types ============
type Screen = "boot" | "home" | "youtube" | "hdrezka" | "settings" | "addapp" | "music" | "photos" | "files";

// ============ Settings storage ============
interface OsTvSettings {
  scanlines: boolean;
  theme: "default" | "amber" | "green";
  crtEffects: boolean;
}

const DEFAULT_SETTINGS: OsTvSettings = {
  scanlines: false,
  theme: "default",
  crtEffects: false,
};

function loadSettings(): OsTvSettings {
  try {
    const raw = localStorage.getItem("ostv.settings");
    return raw ? { ...DEFAULT_SETTINGS, ...JSON.parse(raw) } : DEFAULT_SETTINGS;
  } catch {
    return DEFAULT_SETTINGS;
  }
}

function saveSettings(s: OsTvSettings) {
  localStorage.setItem("ostv.settings", JSON.stringify(s));
}

interface AppConfig {
  id: string;
  name: string;
  color: string;
  sprite: string[];
  stub?: boolean;
  screen?: Screen;
}

interface VideoResult {
  id: string;
  title: string;
  url: string;
  thumbnail?: string;
  duration?: number;
  channel?: string;
  source?: string;
}

// ============ Data ============
const APPS: AppConfig[] = [
  {
    id: "youtube",
    name: "YouTube",
    color: "#ff0033",
    screen: "youtube",
    sprite: [
      "RRRRRRRRRRRRRRRR",
      "RRRRRRRRRRRRRRRR",
      "RRRRRWWRRRRRRRRR",
      "RRRRRWWWWRRRRRRR",
      "RRRRRWWWWWWRRRRR",
      "RRRRRWWWWRRRRRRR",
      "RRRRRWWRRRRRRRRR",
      "RRRRRRRRRRRRRRRR",
      "RRRRRRRRRRRRRRRR",
    ],
  },
  {
    id: "hdrezka", name: "HDRezka", color: "#00d084", screen: "hdrezka",
    sprite: [
      "................", "..RRRRRRRRRRRR..", "..R..........R..",
      "..R.WWWWWWWW.R..", "..R.W.W..W.W.R..", "..R.WWWWWWWW.R..",
      "..R..........R..", "..RRRRRRRRRRRR..", "................",
    ],
  },
  {
    id: "filmix", name: "Filmix", color: "#ffaa00", stub: true,
    sprite: [
      "................", "...RR.RR.RR.....", "...RR.RR.RR.....",
      "..RRRRRRRRRR....", "..RRRWWWWRRR....", "..RRRRRRRRRR....",
      "...RR.RR.RR.....", "...RR.RR.RR.....", "................",
    ],
  },
  {
    id: "music", name: "Music", color: "#9945ff", screen: "music",
    sprite: [
      "................", ".....RR.........", "....RRRR........",
      "...RRRRRR.......", "...RRRRRR.......", "...RRRRRR.......",
      "...RRRRRR.......", "..RRR.RRR.......", ".RRR...RR.......",
    ],
  },
  {
    id: "gallery", name: "Photos", color: "#00b3ff", screen: "photos",
    sprite: [
      "................", "..RRRRRRRRRRRR..", "..R..........R..",
      "..R..W...WWW.R..", "..R.WWW..WWW.R..", "..R..W..WWWW.R..",
      "..R.....WWWW.R..", "..RRRRRRRRRRRR..", "................",
    ],
  },
  {
    id: "files", name: "Files", color: "#ffaa55", screen: "files",
    sprite: [
      "................",
      "..RRRRR.........",
      "..R...RRRRRRRR..",
      "..R..........R..",
      "..R..........R..",
      "..R..........R..",
      "..R..........R..",
      "..RRRRRRRRRRRR..",
      "................",
    ],
  },
  {
    id: "terminal", name: "Terminal", color: "#00ff77",
    sprite: [
      "RRRRRRRRRRRRRRRR",
      "RRRRRRRRRRRRRRRR",
      "RR.RR..........R",
      "RRR.RR.........R",
      "RRRR.RR........R",
      "RRR.RR.........R",
      "RR.RR..........R",
      "RRRRRRRRRRRRRRRR",
      "RRRRRRRRRRRRRRRR",
    ],
  },
  {
    id: "settings", name: "Settings", color: "#888888",
    screen: "settings",
    sprite: [
      "................", "....RR..RR......", "...RRRRRRRR.....",
      "..RRR.WW.RRR....", "..RR.WWWW.RR....", "..RRR.WW.RRR....",
      "...RRRRRRRR.....", "....RR..RR......", "................",
    ],
  },
];

// ============ Pixel Sprite ============
const PixelSprite = memo(function PixelSprite({ sprite, color, size = 10 }: { sprite: string[]; color: string; size?: number }) {
  const w = sprite[0].length;
  const h = sprite.length;
  // useMemo — rects НЕ перераховуються якщо sprite/color не змінились
  const rects = useMemo(() =>
    sprite.flatMap((row, y) =>
      row.split("").map((ch, x) =>
        ch === "." ? null : (
          <rect key={`${x}-${y}`} x={x} y={y} width={1} height={1}
                fill={ch === "W" ? "#ffffff" : color} />
        )
      )
    ),
  [sprite, color]);
  return (
    <svg width={w * size} height={h * size} viewBox={`0 0 ${w} ${h}`}
         style={{ imageRendering: "pixelated", shapeRendering: "crispEdges" }}>
      {rects}
    </svg>
  );
});

// ============ Keyboard Layout ============
function useKbdLayout() {
  const [layout, setLayout] = useState("us");
  const refresh = useCallback(async () => {
    try {
      const r = await invoke<any>("brain_call", { method: "kbd_layout", params: { action: "query" } });
      if (r?.result?.current) setLayout(r.result.current);
    } catch {}
  }, []);
  const toggle = useCallback(async () => {
    try {
      const r = await invoke<any>("brain_call", { method: "kbd_layout", params: { action: "toggle" } });
      if (r?.result?.layout) setLayout(r.result.layout);
    } catch {}
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  return { layout, toggle };
}

// ============ Clock ============ (self-contained — не тригерить parent re-render)
const Clock = memo(function Clock() {
  const [clock, setClock] = useState("");
  useEffect(() => {
    const tick = () => {
      const d = new Date();
      setClock(`${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return <span className="clock">{clock}</span>;
});

// ============ Home ============
function HomeScreen({ onOpen, onAddApp }: { onOpen: (app: AppConfig) => void; onAddApp: () => void }) {
  const [focusedIdx, setFocusedIdx] = useState(0);
  const [status, setStatus] = useState("▸ READY");
  const { layout, toggle: toggleLayout } = useKbdLayout();

  // dynamic apps від Brain (self-modified). Polling кожні 5с — нові apps з'являються без ручного refresh.
  const [dynamicApps, setDynamicApps] = useState<AppConfig[]>([]);
  useEffect(() => {
    let cancelled = false;
    const fetchApps = async () => {
      try {
        const r = await invoke<any>("brain_call", { method: "list_apps", params: {} });
        if (cancelled) return;
        const apps = (r?.result?.apps || []).map((a: any): AppConfig => ({
          id: `dyn_${a.name}`,
          name: a.display_name || a.name,
          color: a.color || "#888",
          sprite: a.sprite || Array(9).fill("................"),
          ...(({installed: a.name}) as any),
        }));
        setDynamicApps(prev => {
          // Оновлюємо тільки якщо насправді змінилося (уникаємо re-render)
          if (prev.length !== apps.length || prev.some((p, i) => p.id !== apps[i]?.id)) {
            return apps;
          }
          return prev;
        });
      } catch {}
    };
    fetchApps();
    const id = setInterval(fetchApps, 5000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // AddApp "+" pseudo-icon завжди остання
  const addAppIcon: AppConfig = useMemo(() => ({
    id: "__add_app__",
    name: "+ ADD APP",
    color: "#00d084",
    sprite: [
      "................",
      "................",
      ".......WW.......",
      ".......WW.......",
      ".......WW.......",
      "...WWWWWWWWWW...",
      "...WWWWWWWWWW...",
      ".......WW.......",
      ".......WW.......",
      ".......WW.......",
      "................",
      "................",
      "................",
      "................",
      "................",
      "................",
    ],
  }), []);

  const allApps = useMemo(() => [...APPS, ...dynamicApps, addAppIcon], [dynamicApps, addAppIcon]);

  const activate = useCallback(async (app: AppConfig) => {
    if (app.id === "__add_app__") {
      onAddApp();
      return;
    }
    if (app.screen) {
      onOpen(app);
      return;
    }
    if (app.id === "terminal") {
      setStatus("▶ LAUNCHING TERMINAL...");
      try {
        const r = await invoke<any>("brain_call", {
          method: "launch_terminal",
          params: {},
        });
        setStatus(r?.error ? `✗ ${r.error}` : `✓ TERMINAL (pid=${r?.result?.pid})`);
      } catch (e) {
        setStatus(`✗ ${e}`);
      }
      return;
    }
    // Dynamic app — run parser.py
    const installed = (app as any).installed;
    if (installed) {
      setStatus(`▶ ${app.name}...`);
      try {
        const r = await invoke<any>("brain_call", {
          method: "run_app",
          params: { app: installed, command: "search" },
        });
        const data = r?.result?.result;
        if (Array.isArray(data) && data.length) {
          const first = data[0];
          setStatus(`✓ ${first.thumbnail || ""} ${first.title || ""} — ${first.subtitle || ""}`);
        } else {
          setStatus(`✓ ${JSON.stringify(data).slice(0, 120)}`);
        }
      } catch (e) {
        setStatus(`✗ ${e}`);
      }
      return;
    }
    if (app.stub) {
      setStatus(`⚙  ${app.name.toUpperCase()} — буде парсером у Docker (stub)`);
      return;
    }
  }, [onOpen, onAddApp]);

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      const cols = 3;
      if (e.key === "ArrowRight") setFocusedIdx(i => Math.min(allApps.length - 1, i + 1));
      else if (e.key === "ArrowLeft") setFocusedIdx(i => Math.max(0, i - 1));
      else if (e.key === "ArrowDown") setFocusedIdx(i => Math.min(allApps.length - 1, i + cols));
      else if (e.key === "ArrowUp") setFocusedIdx(i => Math.max(0, i - cols));
      else if (e.key === "Enter") activate(allApps[focusedIdx]);
      else if (e.key === "l" || e.key === "L") toggleLayout();
      else if (e.key === "q" || e.key === "Q") invoke("exit_app").catch(() => {});
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [focusedIdx, activate, toggleLayout, allApps]);

  return (
    <>
      <header className="tv-header">
        <div className="logo-block">
          <span className="logo">OsTv</span>
          <span className="logo-ver">v0.1.0</span>
        </div>
        <div className="header-center">◉ HOME</div>
        <div className="header-right">
          <span className="net-status">● ONLINE</span>
          <span className="kbd-badge" onClick={toggleLayout} title="L — toggle layout">
            {layout.toUpperCase()}
          </span>
          <Clock />
        </div>
      </header>

      <main className="stage">
        <div className="section-title">▸ ДОДАТКИ</div>
        <div className="grid">
          {allApps.map((a, idx) => (
            <div key={a.id}
                 className={`icon-card ${idx === focusedIdx ? "focused" : ""} ${a.stub ? "stub" : ""}`}
                 onClick={() => { setFocusedIdx(idx); activate(a); }}
                 onMouseEnter={() => setFocusedIdx(idx)}
                 style={{ animationDelay: `${idx * 80}ms` }}>
              <div className="sprite-wrap">
                <PixelSprite sprite={a.sprite} color={a.color} size={idx === focusedIdx ? 14 : 10} />
              </div>
              <div className="icon-label">{a.name}</div>
              {a.stub && <div className="badge">STUB</div>}
              {(a as any).installed && <div className="badge" style={{background: "#00d084", color: "#000"}}>AI</div>}
            </div>
          ))}
        </div>
      </main>

      <div className="status-bar">
        <span className="prompt">ostv@home ~</span>
        <span className="status-text">{status}</span>
      </div>

      <footer className="tv-footer">
        <span>←→↑↓ NAV</span>
        <span>[ENTER] OPEN</span>
        <span>[L] {layout.toUpperCase()}</span>
        <span>[Q] QUIT</span>
      </footer>
    </>
  );
}

// ============ Generic Source Screen (YouTube / HDRezka) ============
interface SourceScreenProps {
  onBack: () => void;
  title: string;
  brainMethod: string;   // "search_youtube" | "search_hdrezka"
  accentColor: string;
  placeholder: string;
}

function SourceScreen({ onBack, title, brainMethod, accentColor, placeholder }: SourceScreenProps) {
  const { layout, toggle: toggleLayout } = useKbdLayout();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<VideoResult[]>([]);
  const [focusedIdx, setFocusedIdx] = useState(-1);
  const [searching, setSearching] = useState(false);
  const [status, setStatus] = useState("▸ Введіть запит, Enter — пошук. Esc — назад. K — екранна клавіатура.");
  const [oskOpen, setOskOpen] = useState(false);
  const [launching, setLaunching] = useState<{title: string; detail?: string} | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const doSearch = useCallback(async () => {
    const q = query.trim();
    if (!q) { setStatus("✗ Порожній запит"); return; }
    setSearching(true);
    setStatus(`🔍 ${brainMethod}: ${q}...`);
    try {
      const resp = await invoke<any>("brain_call", {
        method: brainMethod,
        params: { query: q, limit: 12 },
      });
      const r = resp?.result;
      if (!r || r.ok === false) {
        setStatus(`✗ ${r?.error || resp?.error || "search failed"}`);
        setResults([]);
      } else {
        setResults(r.videos || []);
        setFocusedIdx(r.videos?.length ? 0 : -1);
        setStatus(`✓ Знайдено ${r.videos?.length || 0} — ←→↑↓ Enter`);
      }
    } catch (e) {
      setStatus(`✗ ${e}`);
    } finally {
      setSearching(false);
    }
  }, [query, brainMethod]);

  const play = useCallback(async (v: VideoResult) => {
    const shortTitle = v.title.slice(0, 60);
    setLaunching({ title: shortTitle, detail: "витягую потік..." });
    setStatus(`▶ ${shortTitle}...`);
    try {
      const r = await invoke<any>("brain_call", {
        method: "play_url",
        params: { url: v.url },
      });
      const err = r?.result?.error || r?.error;
      if (err) {
        setLaunching(null);
        setStatus(`✗ ${err}`);
        return;
      }
      setLaunching({ title: shortTitle, detail: "mpv стартує..." });
      // Even after invoke returns, mpv потребує ~2-3 сек на відкриття. Тримаємо overlay.
      setTimeout(() => setLaunching(null), 3500);
      setStatus(`✓ Playing — [S]top, [Esc] back`);
    } catch (e) {
      setLaunching(null);
      setStatus(`✗ ${e}`);
    }
  }, []);

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (e.key === "Escape") { onBack(); return; }
      if (e.key === "s" || e.key === "S") {
        invoke("brain_call", { method: "stop", params: {} }).catch(() => {});
        return;
      }
      // Alt+L — toggle layout (L alone може ввійти в input)
      if ((e.altKey || focusedIdx !== -1) && (e.key === "l" || e.key === "L")) {
        toggleLayout();
        return;
      }
      // K — open OSK (якщо не всередині input, інакше Alt+K)
      if ((e.altKey && (e.key === "k" || e.key === "K")) ||
          (focusedIdx !== -1 && (e.key === "k" || e.key === "K"))) {
        setOskOpen(true);
        return;
      }
      if (focusedIdx === -1) {
        // input focused — Enter starts search
        if (e.key === "Enter") doSearch();
        // ArrowDown → перший result
        else if (e.key === "ArrowDown" && results.length) {
          setFocusedIdx(0);
          (document.activeElement as HTMLElement)?.blur();
        }
      } else {
        const cols = 4;
        if (e.key === "Enter") play(results[focusedIdx]);
        else if (e.key === "ArrowRight") setFocusedIdx(i => Math.min(results.length - 1, i + 1));
        else if (e.key === "ArrowLeft") setFocusedIdx(i => Math.max(0, i - 1));
        else if (e.key === "ArrowDown") setFocusedIdx(i => Math.min(results.length - 1, i + cols));
        else if (e.key === "ArrowUp") {
          if (focusedIdx < cols) {
            setFocusedIdx(-1);
            inputRef.current?.focus();
          } else {
            setFocusedIdx(i => i - cols);
          }
        }
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [focusedIdx, results, doSearch, play, onBack, toggleLayout]);

  return (
    <>
      <header className="tv-header">
        <div className="logo-block">
          <span className="back-btn" onClick={onBack}>← OsTv</span>
          <span className="logo" style={{ color: accentColor }}>{title}</span>
        </div>
        <div className="header-center">▶ SEARCH</div>
        <div className="header-right">
          <span className="net-status">● ONLINE</span>
          <span className="kbd-badge" onClick={toggleLayout} title="Alt+L — toggle layout">
            {layout.toUpperCase()}
          </span>
          <Clock />
        </div>
      </header>

      <div className="search-bar-wrap">
        <span className="search-icon">🔍</span>
        <input
          ref={inputRef}
          className={`search-input ${focusedIdx === -1 ? "focused" : ""}`}
          placeholder={placeholder}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setFocusedIdx(-1)}
          autoFocus
        />
        <button className="search-btn" onClick={() => setOskOpen(true)} title="K — OSK">
          ⌨
        </button>
        <button className="search-btn" onClick={doSearch} disabled={searching}>
          {searching ? "..." : "GO"}
        </button>
      </div>
      {oskOpen && (
        <OnScreenKeyboard
          value={query}
          onChange={setQuery}
          onSubmit={() => { setOskOpen(false); doSearch(); }}
          onClose={() => setOskOpen(false)}
        />
      )}
      {launching && <LaunchOverlay title={launching.title} detail={launching.detail} />}

      <main className="stage results-stage">
        {results.length === 0 && !searching && (
          <div className="hint-empty">
            Введіть запит зверху, натисніть <span className="kbd">ENTER</span> — пошук через yt-dlp.
          </div>
        )}
        {searching && <div className="hint-empty">⏳ Пошук...</div>}
        <div className="results-grid">
          {results.map((v, idx) => (
            <div key={v.id}
                 className={`video-card ${idx === focusedIdx ? "focused" : ""}`}
                 onClick={() => { setFocusedIdx(idx); play(v); }}
                 onMouseEnter={() => setFocusedIdx(idx)}
                 style={{ animationDelay: `${idx * 40}ms` }}>
              <div className="video-thumb" style={{
                backgroundImage: v.thumbnail ? `url(${v.thumbnail})` : undefined,
                background: !v.thumbnail ? `linear-gradient(135deg, ${accentColor}33, #000)` : undefined,
              }}>
                {!v.thumbnail && <span style={{fontSize: 32, color: accentColor}}>{(v.title || "?").slice(0, 2).toUpperCase()}</span>}
                {v.duration && <span className="video-duration">{fmtDuration(v.duration)}</span>}
                {(v as any).rating && <span className="video-duration" style={{left: 6, right: "auto"}}>★ {(v as any).rating}</span>}
              </div>
              <div className="video-title">{v.title}</div>
              {(v.channel || (v as any).year) && <div className="video-channel">▸ {v.channel || (v as any).year}</div>}
            </div>
          ))}
        </div>
      </main>

      <div className="status-bar">
        <span className="prompt">ostv@{title.toLowerCase()} ~</span>
        <span className="status-text">{status}</span>
      </div>

      <footer className="tv-footer">
        <span>[ESC] BACK</span>
        <span>←→↑↓ NAV</span>
        <span>[ENTER] {focusedIdx === -1 ? "SEARCH" : "PLAY"}</span>
        <span>[S] STOP</span>
        <span>[ALT+L] {layout.toUpperCase()}</span>
      </footer>
    </>
  );
}

function fmtDuration(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

// ============ Launch Overlay (loading indicator) ============
const LaunchOverlay = memo(function LaunchOverlay({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="launch-overlay">
      <div className="launch-box">
        <div className="launch-title">▶ {title}</div>
        {detail && <div className="launch-detail">{detail}</div>}
        <div className="launch-bar"><div className="launch-bar-fill" /></div>
        <div className="launch-spinner">
          <span>█</span><span>▓</span><span>▒</span><span>░</span><span>▒</span><span>▓</span>
        </div>
      </div>
    </div>
  );
});

// ============ On-Screen Keyboard ============
const OSK_LAYOUTS = {
  en: [
    ["1","2","3","4","5","6","7","8","9","0"],
    ["q","w","e","r","t","y","u","i","o","p"],
    ["a","s","d","f","g","h","j","k","l","-"],
    ["z","x","c","v","b","n","m",",",".","?"],
    ["UA","␣","⌫","⏎"],
  ],
  ua: [
    ["1","2","3","4","5","6","7","8","9","0"],
    ["й","ц","у","к","е","н","г","ш","щ","з"],
    ["х","ї","ф","і","в","а","п","р","о","л"],
    ["д","ж","є","я","ч","с","м","и","т","ь"],
    ["EN","␣","⌫","⏎"],
  ],
};

interface OSKProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit?: () => void;
  onClose: () => void;
}

function OnScreenKeyboard({ value, onChange, onSubmit, onClose }: OSKProps) {
  const [lang, setLang] = useState<"en" | "ua">("en");
  const [row, setRow] = useState(1); // на q/й початок (skip numbers)
  const [col, setCol] = useState(0);

  const layout = OSK_LAYOUTS[lang];
  const clampCol = useCallback((r: number, c: number) => {
    const maxC = layout[r].length - 1;
    return Math.max(0, Math.min(maxC, c));
  }, [layout]);

  const pressKey = useCallback((key: string) => {
    if (key === "⌫") onChange(value.slice(0, -1));
    else if (key === "␣") onChange(value + " ");
    else if (key === "⏎") { onSubmit?.(); }
    else if (key === "UA") setLang("ua");
    else if (key === "EN") setLang("en");
    else onChange(value + key);
  }, [value, onChange, onSubmit]);

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      e.stopPropagation();
      if (e.key === "Escape") { e.preventDefault(); onClose(); return; }
      if (e.key === "ArrowRight") {
        e.preventDefault();
        setCol(c => clampCol(row, c + 1));
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        setCol(c => clampCol(row, c - 1));
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setRow(r => {
          const nr = Math.min(layout.length - 1, r + 1);
          setCol(c => clampCol(nr, c));
          return nr;
        });
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setRow(r => {
          const nr = Math.max(0, r - 1);
          setCol(c => clampCol(nr, c));
          return nr;
        });
      } else if (e.key === "Enter") {
        e.preventDefault();
        pressKey(layout[row][col]);
      } else if (e.key === "Backspace") {
        e.preventDefault();
        onChange(value.slice(0, -1));
      } else if (e.key.length === 1) {
        // Physical keyboard typing — append too
        e.preventDefault();
        onChange(value + e.key);
      }
    }
    window.addEventListener("keydown", handler, { capture: true });
    return () => window.removeEventListener("keydown", handler, { capture: true } as any);
  }, [row, col, layout, pressKey, value, onChange, onClose, clampCol]);

  return (
    <div className="osk-overlay" onClick={onClose}>
      <div className="osk" onClick={(e) => e.stopPropagation()}>
        <div className="osk-display">{value || <span className="osk-placeholder">Введіть запит...</span>}<span className="osk-caret">_</span></div>
        <div className="osk-grid">
          {layout.map((rowKeys, rIdx) => (
            <div key={rIdx} className="osk-row">
              {rowKeys.map((key, cIdx) => {
                const focused = rIdx === row && cIdx === col;
                const special = ["UA","EN","␣","⌫","⏎"].includes(key);
                const wide = key === "␣" ? 5 : (key === "⏎" ? 3 : (key === "⌫" ? 3 : 1));
                return (
                  <button
                    key={cIdx}
                    className={`osk-key ${focused ? "focused" : ""} ${special ? "special" : ""}`}
                    style={{ flexGrow: wide }}
                    onClick={() => { setRow(rIdx); setCol(cIdx); pressKey(key); }}
                    onMouseEnter={() => { setRow(rIdx); setCol(cIdx); }}
                  >
                    {key}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
        <div className="osk-hint">
          ←→↑↓ NAV · [ENTER] press · [ESC] close · {lang.toUpperCase()}
        </div>
      </div>
    </div>
  );
}


// ============ Media Browser (Music, Photos, Files) ============
interface FileItem {
  name: string; path: string; ext: string; size_mb: number;
  is_dir: boolean; mtime?: number;
}

interface MediaBrowserProps {
  onBack: () => void;
  title: string;
  accentColor: string;
  rootPath: string;
  extensions?: string[];
  mode: "audio" | "image" | "mixed";  // mixed — files manager (no filter, any file)
  icon: string;  // "🎵" | "🖼" | "📁"
}

function MediaBrowserScreen({ onBack, title, accentColor, rootPath, extensions, mode, icon }: MediaBrowserProps) {
  const [currentDir, setCurrentDir] = useState(rootPath);
  const [items, setItems] = useState<FileItem[]>([]);
  const [parent, setParent] = useState<string | null>(null);
  const [focused, setFocused] = useState(0);
  const [status, setStatus] = useState("▸ завантаження...");
  const [launching, setLaunching] = useState<string | null>(null);

  const load = useCallback(async (dir: string) => {
    setStatus(`📂 ${dir}...`);
    try {
      const r = await invoke<any>("brain_call", {
        method: "list_files",
        params: {
          directory: dir,
          extensions: mode === "mixed" ? null : extensions,
          recursive: false,
          limit: 300,
        },
      });
      const data = r?.result;
      if (!data?.ok) {
        setStatus(`✗ ${data?.error || "error"}`);
        return;
      }
      const mixed: FileItem[] = [
        ...(data.dirs || []).map((d: any) => ({ ...d, ext: "", size_mb: 0 })),
        ...(data.files || []),
      ];
      setItems(mixed);
      setParent(data.parent || null);
      setFocused(0);
      setStatus(`${icon} ${data.count} файлів у ${data.directory.split("/").pop() || data.directory}`);
    } catch (e) { setStatus(`✗ ${e}`); }
  }, [mode, extensions, icon]);

  useEffect(() => { load(currentDir); }, [currentDir, load]);

  const openItem = useCallback(async (item: FileItem) => {
    if (item.is_dir) {
      setCurrentDir(item.path);
      return;
    }
    // For image mode — play all images in current dir as slideshow
    // For audio — play single або всю папку
    // For mixed — detect by ext
    let filesToPlay: string[] = [];
    let playMode: "audio" | "image" | "video" = "video";
    const audioExts = ["mp3", "flac", "m4a", "ogg", "opus", "wav", "aac"];
    const imageExts = ["jpg", "jpeg", "png", "webp", "gif", "bmp"];
    const videoExts = ["mp4", "mkv", "webm", "avi", "mov"];

    if (mode === "image") {
      filesToPlay = items.filter(i => !i.is_dir && imageExts.includes(i.ext)).map(i => i.path);
      const startIdx = filesToPlay.indexOf(item.path);
      if (startIdx > 0) {
        filesToPlay = [...filesToPlay.slice(startIdx), ...filesToPlay.slice(0, startIdx)];
      }
      playMode = "image";
    } else if (mode === "audio") {
      filesToPlay = items.filter(i => !i.is_dir && audioExts.includes(i.ext)).map(i => i.path);
      const startIdx = filesToPlay.indexOf(item.path);
      if (startIdx > 0) {
        filesToPlay = [...filesToPlay.slice(startIdx), ...filesToPlay.slice(0, startIdx)];
      }
      playMode = "audio";
    } else {
      // mixed / files — single file, auto-detect mode
      filesToPlay = [item.path];
      if (imageExts.includes(item.ext)) playMode = "image";
      else if (audioExts.includes(item.ext)) playMode = "audio";
      else if (videoExts.includes(item.ext)) playMode = "video";
      else {
        setStatus(`⚙ ${item.ext} — not playable`);
        return;
      }
    }

    if (filesToPlay.length === 0) {
      setStatus("✗ нічого грати");
      return;
    }
    setLaunching(item.name);
    try {
      await invoke<any>("brain_call", {
        method: "play_playlist",
        params: { files: filesToPlay, mode: playMode, fullscreen: true },
      });
      setTimeout(() => setLaunching(null), 3000);
      setStatus(`▶ ${filesToPlay.length} items (${playMode})`);
    } catch (e) {
      setLaunching(null);
      setStatus(`✗ ${e}`);
    }
  }, [mode, items]);

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (e.key === "Escape") { onBack(); return; }
      const cols = 4;
      if (e.key === "ArrowRight") { e.preventDefault(); setFocused(i => Math.min(items.length - 1, i + 1)); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); setFocused(i => Math.max(0, i - 1)); }
      else if (e.key === "ArrowDown") { e.preventDefault(); setFocused(i => Math.min(items.length - 1, i + cols)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setFocused(i => Math.max(0, i - cols)); }
      else if (e.key === "Enter") { e.preventDefault(); if (items[focused]) openItem(items[focused]); }
      else if (e.key === "Backspace" && parent) { e.preventDefault(); setCurrentDir(parent); }
      else if (e.key === "s" || e.key === "S") {
        invoke("brain_call", { method: "stop", params: {} }).catch(() => {});
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [focused, items, parent, openItem, onBack]);

  return (
    <>
      <header className="tv-header">
        <div className="logo-block">
          <span className="back-btn" onClick={onBack}>← OsTv</span>
          <span className="logo" style={{ color: accentColor }}>{title}</span>
        </div>
        <div className="header-center">{icon} {currentDir.split("/").slice(-2).join("/")}</div>
        <div className="header-right"><Clock /></div>
      </header>

      <main className="stage">
        <div className="section-title">{parent && <span>▸ [Backspace] up</span>}{" "}▸ {items.length} ITEMS</div>
        <div className="results-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
          {items.length === 0 && <div className="hint-empty">порожньо</div>}
          {items.map((item, idx) => (
            <div key={item.path}
                 className={`video-card ${idx === focused ? "focused" : ""}`}
                 onClick={() => { setFocused(idx); openItem(item); }}
                 onMouseEnter={() => setFocused(idx)}>
              <div className="video-thumb" style={{
                background: item.is_dir ? `linear-gradient(135deg, ${accentColor}66, #000)` : `linear-gradient(135deg, #222, #000)`,
              }}>
                <span style={{ fontSize: 48 }}>{item.is_dir ? "📁" : (
                  item.ext === "jpg" || item.ext === "png" || item.ext === "jpeg" || item.ext === "webp" ? "🖼" :
                  item.ext === "mp3" || item.ext === "flac" || item.ext === "m4a" ? "🎵" :
                  item.ext === "mp4" || item.ext === "mkv" || item.ext === "webm" ? "🎬" :
                  "📄"
                )}</span>
                {item.size_mb > 0 && <span className="video-duration">{item.size_mb.toFixed(1)} MB</span>}
              </div>
              <div className="video-title">{item.name}</div>
            </div>
          ))}
        </div>
      </main>

      <div className="status-bar">
        <span className="prompt">ostv@{title.toLowerCase()} ~</span>
        <span className="status-text">{status}</span>
      </div>

      <footer className="tv-footer">
        <span>[ESC] BACK</span>
        <span>[BKSP] UP</span>
        <span>←→↑↓ NAV</span>
        <span>[ENTER] OPEN</span>
        <span>[S] STOP</span>
      </footer>

      {launching && <LaunchOverlay title={launching} detail={`${mode} plaуer...`} />}
    </>
  );
}


// ============ Settings Screen ============
function SettingsScreen({ onBack, settings, onChange }: {
  onBack: () => void;
  settings: OsTvSettings;
  onChange: (s: OsTvSettings) => void;
}) {
  const [focused, setFocused] = useState(0);
  const [brainVersion, setBrainVersion] = useState<string>("?");
  const [apiKeyStatus, setApiKeyStatus] = useState<string>("?");
  const [apps, setApps] = useState<any[]>([]);

  const reloadApps = useCallback(async () => {
    try {
      const r = await invoke<any>("brain_call", { method: "list_apps", params: {} });
      setApps(r?.result?.apps || []);
    } catch {}
  }, []);
  useEffect(() => { reloadApps(); }, [reloadApps]);

  const deleteApp = useCallback(async (name: string) => {
    if (!confirm(`Видалити модуль "${name}"?`)) return;
    try {
      await invoke("brain_call", { method: "delete_app", params: { app: name } });
      reloadApps();
    } catch {}
  }, [reloadApps]);

  useEffect(() => {
    invoke<any>("brain_call", { method: "ping", params: {} })
      .then((r) => setBrainVersion(r?.result?.version || "?"))
      .catch(() => setBrainVersion("offline"));
    // Test AI (spawn тільки ping, не реальне спілкування)
    invoke<any>("brain_call", {
      method: "ai_chat",
      params: { messages: [{ role: "user", content: "ping" }] },
    })
      .then((r) => {
        if (r?.result?.ok) setApiKeyStatus("✓ встановлено");
        else if (r?.result?.error?.includes("ANTHROPIC_API_KEY")) setApiKeyStatus("✗ не встановлено");
        else setApiKeyStatus(`? ${r?.result?.error?.slice(0, 40)}`);
      })
      .catch(() => setApiKeyStatus("offline"));
  }, []);

  const rows = [
    { label: "CRT Scanlines", value: settings.scanlines ? "ON" : "OFF",
      onToggle: () => onChange({ ...settings, scanlines: !settings.scanlines }) },
    { label: "Theme", value: settings.theme.toUpperCase(),
      onToggle: () => {
        const order: OsTvSettings["theme"][] = ["default", "amber", "green"];
        const idx = order.indexOf(settings.theme);
        onChange({ ...settings, theme: order[(idx + 1) % order.length] });
      } },
    { label: "Brain version", value: brainVersion, onToggle: () => {} },
    { label: "Anthropic API key", value: apiKeyStatus, onToggle: () => {} },
  ];

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (e.key === "Escape") { onBack(); return; }
      if (e.key === "ArrowDown") { e.preventDefault(); setFocused(i => Math.min(rows.length - 1, i + 1)); }
      if (e.key === "ArrowUp") { e.preventDefault(); setFocused(i => Math.max(0, i - 1)); }
      if (e.key === "Enter") { e.preventDefault(); rows[focused]?.onToggle(); }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [focused, rows, onBack]);

  return (
    <>
      <header className="tv-header">
        <div className="logo-block">
          <span className="back-btn" onClick={onBack}>← OsTv</span>
          <span className="logo" style={{ color: "#888" }}>Settings</span>
        </div>
        <div className="header-center">⚙ CONFIG</div>
        <div className="header-right"><Clock /></div>
      </header>
      <main className="stage">
        <div className="section-title">▸ СИСТЕМА</div>
        <div className="settings-list">
          {rows.map((r, i) => (
            <div key={i}
                 className={`settings-row ${i === focused ? "focused" : ""}`}
                 onClick={() => { setFocused(i); r.onToggle(); }}
                 onMouseEnter={() => setFocused(i)}>
              <span className="settings-label">{r.label}</span>
              <span className="settings-value">{r.value}</span>
            </div>
          ))}
        </div>

        {apps.length > 0 && (
          <>
            <div className="section-title" style={{ marginTop: 28 }}>▸ AI-МОДУЛІ ({apps.length})</div>
            <div className="settings-list">
              {apps.map((a) => (
                <div key={a.name} className="settings-row">
                  <span className="settings-label">
                    <span style={{ color: a.color, marginRight: 10 }}>●</span>
                    {a.display_name || a.name}
                    <span style={{ color: "#666", marginLeft: 10, fontSize: 13 }}>v{a.version}</span>
                  </span>
                  <button className="search-btn" style={{ background: "#c01c28", color: "#fff", padding: "6px 14px" }}
                          onClick={() => deleteApp(a.name)}>DELETE</button>
                </div>
              ))}
            </div>
          </>
        )}
      </main>
      <div className="status-bar">
        <span className="prompt">ostv@settings ~</span>
        <span className="status-text">▸ ENTER toggles. ESC back.</span>
      </div>
      <footer className="tv-footer">
        <span>[ESC] BACK</span>
        <span>↑↓ NAV</span>
        <span>[ENTER] TOGGLE</span>
      </footer>
    </>
  );
}


// ============ Add App Wizard ============
function AddAppScreen({ onBack }: { onBack: () => void }) {
  const [description, setDescription] = useState("");
  const [phase, setPhase] = useState<"idle" | "generating" | "preview" | "installing" | "done">("idle");
  const [pending, setPending] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const generate = useCallback(async () => {
    const desc = description.trim();
    if (!desc) return;
    setError(null);
    setPhase("generating");
    try {
      const r = await invoke<any>("brain_call", {
        method: "propose_module",
        params: { description: desc },
      });
      const data = r?.result;
      if (!data?.ok) { setError(data?.error || r?.error || "generation failed"); setPhase("idle"); return; }
      setPending(data);
      setPhase("preview");
    } catch (e) { setError(String(e)); setPhase("idle"); }
  }, [description]);

  const approve = useCallback(async () => {
    if (!pending?.pending_id) return;
    setPhase("installing");
    try {
      const r = await invoke<any>("brain_call", {
        method: "approve_module",
        params: { pending_id: pending.pending_id },
      });
      if (r?.result?.ok) setPhase("done");
      else setError(r?.result?.error || "install failed");
    } catch (e) { setError(String(e)); }
  }, [pending]);

  useEffect(() => {
    function h(e: KeyboardEvent) { if (e.key === "Escape") onBack(); }
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onBack]);

  return (
    <>
      <header className="tv-header">
        <div className="logo-block">
          <span className="back-btn" onClick={onBack}>← OsTv</span>
          <span className="logo" style={{ color: "#00d084" }}>+ ADD APP</span>
        </div>
        <div className="header-center">⚙ AI WIZARD</div>
        <div className="header-right"><Clock /></div>
      </header>

      <main className="stage" style={{ maxWidth: 900 }}>
        {phase === "idle" && (
          <>
            <div className="section-title">▸ ОПИШІТЬ ДОДАТОК</div>
            <textarea
              className="search-input"
              rows={4}
              placeholder={"Наприклад:\n- плеєр Радіо NV через stream URL\n- курс долара NBU API з історією 7 днів\n- додаток для Twitch стрімів"}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              autoFocus
              style={{ width: "100%", marginBottom: 20, minHeight: 140, resize: "vertical" }}
            />
            <button className="search-btn" onClick={generate} disabled={!description.trim()}>
              ▶ ГЕНЕРУВАТИ
            </button>
            {error && <div style={{ color: "#c01c28", marginTop: 20 }}>✗ {error}</div>}
          </>
        )}

        {phase === "generating" && (
          <div className="launch-box" style={{ margin: "40px auto" }}>
            <div className="launch-title">◉ CLAUDE ГЕНЕРУЄ МОДУЛЬ</div>
            <div className="launch-detail">пише parser.py + manifest.json (1-3 хв)...</div>
            <div className="launch-bar"><div className="launch-bar-fill" /></div>
            <div className="launch-spinner">
              <span>█</span><span>▓</span><span>▒</span><span>░</span><span>▒</span><span>▓</span>
            </div>
          </div>
        )}

        {phase === "preview" && pending && (
          <>
            <div className="section-title">▸ ГОТОВО: {pending.pending_id}</div>
            <div style={{ padding: 20, border: "2px solid var(--accent)", background: "#1a1400" }}>
              <div style={{ marginBottom: 14 }}>📁 Файли:</div>
              <ul style={{ paddingLeft: 20, lineHeight: 1.8 }}>
                {pending.files?.map((f: string) => <li key={f}>📄 {f}</li>)}
              </ul>
              {pending.claude_reply && (
                <>
                  <div style={{ marginTop: 20, marginBottom: 8 }}>💬 Claude:</div>
                  <div style={{ padding: 10, background: "#000", fontSize: 14, whiteSpace: "pre-wrap" }}>
                    {pending.claude_reply.slice(0, 400)}
                  </div>
                </>
              )}
            </div>
            <div style={{ marginTop: 20, display: "flex", gap: 12 }}>
              <button className="search-btn" onClick={approve}>✓ ВСТАНОВИТИ</button>
              <button className="search-btn" style={{ background: "#444", color: "#fff" }} onClick={onBack}>✗ СКАСУВАТИ</button>
            </div>
          </>
        )}

        {phase === "installing" && (
          <div className="launch-box" style={{ margin: "40px auto" }}>
            <div className="launch-title">⚙ ВСТАНОВЛЕННЯ...</div>
            <div className="launch-bar"><div className="launch-bar-fill" /></div>
          </div>
        )}

        {phase === "done" && (
          <>
            <div className="section-title">▸ УСТАНОВЛЕНО ✓</div>
            <div style={{ padding: 20, color: "var(--green)" }}>
              Модуль встановлено. Через кілька секунд він з'явиться на головному екрані.
            </div>
            <button className="search-btn" onClick={onBack}>← НА ГОЛОВНУ</button>
          </>
        )}
      </main>

      <footer className="tv-footer">
        <span>[ESC] BACK</span>
      </footer>
    </>
  );
}

// ============ AI Chat Sidebar ============
interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  actions?: any[];
}

function AiChatSidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [open]);

  useEffect(() => {
    listRef.current?.scrollTo(0, listRef.current.scrollHeight);
  }, [messages, loading]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;
    const newMsgs: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(newMsgs);
    setInput("");
    setLoading(true);
    try {
      const resp = await invoke<any>("brain_call", {
        method: "ai_chat",
        params: { messages: newMsgs.map(m => ({ role: m.role, content: m.content })) },
      });
      const r = resp?.result;
      if (r?.ok) {
        setMessages([...newMsgs, {
          role: "assistant",
          content: r.reply || "(пусто)",
          actions: r.actions,
        }]);
      } else {
        setMessages([...newMsgs, {
          role: "assistant",
          content: `✗ ${r?.error || resp?.error || "помилка"}`,
        }]);
      }
    } catch (e) {
      setMessages([...newMsgs, { role: "assistant", content: `✗ ${e}` }]);
    } finally {
      setLoading(false);
    }
  }, [input, messages, loading]);

  const handleKey = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  }, [send, onClose]);

  return (
    <aside className={`ai-sidebar ${open ? "open" : ""}`}>
      <div className="ai-header">
        <span className="ai-title">◉ CLAUDE</span>
        <button className="ai-close" onClick={onClose}>✕</button>
      </div>

      <div className="ai-messages" ref={listRef}>
        {messages.length === 0 && (
          <div className="ai-hint">
            <div>Привіт! Я AI-агент OsTv.</div>
            <div>Можу знайти й увімкнути відео, керувати системою.</div>
            <div style={{ marginTop: 12, color: "#666" }}>
              Приклади:<br/>
              "знайди big buck bunny"<br/>
              "увімкни музику для роботи"<br/>
              "відкрий термінал"
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`ai-msg ${m.role}`}>
            <div className="ai-msg-role">{m.role === "user" ? "YOU" : "CLAUDE"}</div>
            <div className="ai-msg-content">{m.content}</div>
            {m.actions && m.actions.length > 0 && (
              <div className="ai-actions">
                {m.actions.map((a, j) => (
                  <div key={j} className="ai-action">
                    🔧 {a.name}({a.result_summary || "..."})
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="ai-msg assistant">
            <div className="ai-msg-role">CLAUDE</div>
            <div className="ai-msg-content thinking">⋯ думаю</div>
          </div>
        )}
      </div>

      <div className="ai-input-wrap">
        <textarea
          ref={inputRef}
          className="ai-input"
          placeholder="Введіть запит... (Enter — send, Shift+Enter — newline, Esc — close)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKey}
          rows={2}
          disabled={loading}
        />
        <button className="ai-send" onClick={send} disabled={loading || !input.trim()}>
          ▶
        </button>
      </div>
    </aside>
  );
}


// ============ Connection Banner ============
const ConnectionBanner = memo(function ConnectionBanner() {
  const [online, setOnline] = useState(true);
  useEffect(() => {
    let cancelled = false;
    const ping = async () => {
      try {
        const r = await invoke<any>("brain_call", { method: "ping", params: {} });
        if (!cancelled) setOnline(Boolean(r?.result?.ok));
      } catch {
        if (!cancelled) setOnline(false);
      }
    };
    ping();
    const id = setInterval(ping, 4000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);
  if (online) return null;
  return <div className="conn-banner">⚠ Brain disconnected — перезапускаю... (systemctl restart ostv-brain)</div>;
});

// ============ Screen Saver ============
const ScreenSaver = memo(function ScreenSaver({ onWake }: { onWake: () => void }) {
  const [time, setTime] = useState("");
  useEffect(() => {
    const tick = () => {
      const d = new Date();
      setTime(`${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  useEffect(() => {
    function h() { onWake(); }
    window.addEventListener("keydown", h);
    window.addEventListener("mousemove", h);
    window.addEventListener("click", h);
    return () => {
      window.removeEventListener("keydown", h);
      window.removeEventListener("mousemove", h);
      window.removeEventListener("click", h);
    };
  }, [onWake]);
  return (
    <div className="screensaver">
      <div className="screensaver-clock">{time}</div>
      <div className="screensaver-hint">OsTv</div>
    </div>
  );
});

// ============ Root App ============
export default function App() {
  const [screen, setScreen] = useState<Screen>("boot");
  const [aiOpen, setAiOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [settings, setSettings] = useState<OsTvSettings>(loadSettings);
  const [idle, setIdle] = useState(false);

  useEffect(() => { saveSettings(settings); }, [settings]);

  // Idle detection → screen saver (5 min без activity)
  useEffect(() => {
    let lastActivity = Date.now();
    const IDLE_MS = 5 * 60 * 1000;
    const bump = () => { lastActivity = Date.now(); if (idle) setIdle(false); };
    const check = setInterval(() => {
      if (Date.now() - lastActivity > IDLE_MS) setIdle(true);
    }, 10000);
    window.addEventListener("keydown", bump);
    window.addEventListener("mousemove", bump);
    window.addEventListener("click", bump);
    return () => {
      clearInterval(check);
      window.removeEventListener("keydown", bump);
      window.removeEventListener("mousemove", bump);
      window.removeEventListener("click", bump);
    };
  }, [idle]);

  useEffect(() => {
    const t = setTimeout(() => setScreen("home"), 1500);
    return () => clearTimeout(t);
  }, []);

  const openApp = useCallback((app: AppConfig) => {
    if (app.screen) setScreen(app.screen);
  }, []);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 1500);
  }, []);

  // Global media keys + AI toggle + Home button
  useEffect(() => {
    async function vol(action: string) {
      try {
        const r = await invoke<any>("brain_call", {
          method: "volume",
          params: { action, step: 5 },
        });
        const v = r?.result;
        if (v?.ok) {
          showToast(v.muted ? "🔇 MUTED" : `🔊 ${v.volume_percent}%`);
        }
      } catch {}
    }

    function handler(e: KeyboardEvent) {
      // AI toggle: ` або Alt+A
      if (e.key === "`" || (e.altKey && (e.key === "a" || e.key === "A"))) {
        e.preventDefault();
        setAiOpen(v => !v);
        return;
      }
      // Media keys — працюють глобально
      switch (e.key) {
        case "AudioVolumeUp":
          e.preventDefault(); vol("up"); return;
        case "AudioVolumeDown":
          e.preventDefault(); vol("down"); return;
        case "AudioVolumeMute":
          e.preventDefault(); vol("mute"); return;
        case "MediaPlayPause":
        case "MediaStop":
          e.preventDefault();
          invoke("brain_call", { method: "stop", params: {} }).catch(() => {});
          showToast("■ STOPPED");
          return;
        case "HomePage":
        case "Home":
          // Home button (але Home у input — не перехоплюємо)
          if (document.activeElement?.tagName !== "INPUT" &&
              document.activeElement?.tagName !== "TEXTAREA") {
            e.preventDefault();
            setScreen("home");
            setAiOpen(false);
            return;
          }
          break;
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [showToast]);

  if (screen === "boot") {
    return (
      <div className="boot-screen">
        <div className="boot-logo">OsTv</div>
        <div className="boot-sub">loading kernel...</div>
        <div className="boot-progress">
          <div className="boot-bar" />
        </div>
      </div>
    );
  }

  return (
    <div className={`app theme-${settings.theme} ${settings.scanlines ? "with-scanlines" : ""}`}>
      <div className="scanlines" />
      <ConnectionBanner />
      {idle && <ScreenSaver onWake={() => setIdle(false)} />}
      {screen === "home" && <HomeScreen onOpen={openApp} onAddApp={() => setScreen("addapp")} />}
      {screen === "addapp" && <AddAppScreen onBack={() => setScreen("home")} />}
      {screen === "youtube" && (
        <SourceScreen
          onBack={() => setScreen("home")}
          title="YouTube"
          brainMethod="search_youtube"
          accentColor="#ff0033"
          placeholder="Наприклад: дюна трейлер, coding with claude, big buck bunny..."
        />
      )}
      {screen === "hdrezka" && (
        <SourceScreen
          onBack={() => setScreen("home")}
          title="HDRezka"
          brainMethod="search_hdrezka"
          accentColor="#00d084"
          placeholder="Наприклад: матриця, дюна 2, brat, fargo серіал..."
        />
      )}
      {screen === "music" && (
        <MediaBrowserScreen
          onBack={() => setScreen("home")}
          title="Music"
          accentColor="#9945ff"
          rootPath="/home/tv/Music"
          extensions={["mp3", "flac", "m4a", "ogg", "opus", "wav", "aac"]}
          mode="audio"
          icon="🎵"
        />
      )}
      {screen === "photos" && (
        <MediaBrowserScreen
          onBack={() => setScreen("home")}
          title="Photos"
          accentColor="#00b3ff"
          rootPath="/home/tv/Photos"
          extensions={["jpg", "jpeg", "png", "webp", "gif", "bmp"]}
          mode="image"
          icon="🖼"
        />
      )}
      {screen === "files" && (
        <MediaBrowserScreen
          onBack={() => setScreen("home")}
          title="Files"
          accentColor="#ffaa55"
          rootPath="/home/tv"
          mode="mixed"
          icon="📁"
        />
      )}
      {screen === "settings" && (
        <SettingsScreen
          onBack={() => setScreen("home")}
          settings={settings}
          onChange={setSettings}
        />
      )}
      <AiChatSidebar open={aiOpen} onClose={() => setAiOpen(false)} />
      {!aiOpen && (
        <div className="ai-fab" onClick={() => setAiOpen(true)} title="Alt+A або `">
          ◉
        </div>
      )}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
