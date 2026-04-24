#!/usr/bin/env python3
"""OsTv UI — v0.0.4 (читабельний layout)

Keys: Enter=launch, S=stop, P=ping, Q=quit
"""
import asyncio
import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Static, Footer, Header
from textual.containers import Container

SOCK = Path("/run/ostv/brain.sock")
DEFAULT_YT_URL = "https://www.youtube.com/watch?v=YE7VzlLtp-4"


async def rpc_call(method, params=None):
    try:
        reader, writer = await asyncio.open_unix_connection(str(SOCK))
    except Exception as e:
        return {"error": f"connect: {e}"}
    try:
        req = {"method": method, "params": params or {}, "id": 1}
        writer.write((json.dumps(req) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=10)
        return json.loads(line) if line else {"error": "empty"}
    except asyncio.TimeoutError:
        return {"error": "timeout"}
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


ICON_CONTENT = """

   Y o u T u b e


      > PLAY

""".strip("\n")


class OsTvApp(App):
    TITLE = "OsTv"
    SUB_TITLE = "v0.0.4"

    CSS = """
    Screen {
        background: black;
        color: white;
    }
    #icon {
        width: 30;
        height: 9;
        border: solid white;
        background: black;
        color: red;
        content-align: center middle;
        margin: 3 0 0 0;
    }
    #icon:focus {
        border: double yellow;
        color: yellow;
    }
    #hint {
        width: 100%;
        height: 3;
        content-align: center middle;
        color: white;
        background: black;
        margin-top: 1;
    }
    #status {
        dock: bottom;
        height: 3;
        background: black;
        color: green;
        padding: 1 2;
    }
    """

    BINDINGS = [
        ("enter", "launch", "Launch"),
        ("s", "stop", "Stop"),
        ("p", "ping", "Ping"),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(ICON_CONTENT, id="icon")
        yield Static("Fokus on icon + ENTER to play. S = stop.", id="hint")
        yield Static("Ready.", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#icon").focus()

    def _set_status(self, msg: str) -> None:
        try:
            self.query_one("#status", Static).update(msg)
        except Exception:
            pass

    async def action_launch(self) -> None:
        self._set_status("> Launching YouTube...")
        resp = await rpc_call("play_youtube", {"url": DEFAULT_YT_URL})
        if "error" in resp:
            self._set_status(f"X {resp['error']}")
        else:
            r = resp.get("result", {})
            self._set_status(f"OK pid={r.get('pid')} - press S to stop")

    async def action_stop(self) -> None:
        resp = await rpc_call("stop")
        self._set_status(f"stop: {resp}")

    async def action_ping(self) -> None:
        resp = await rpc_call("ping")
        self._set_status(f"ping: {resp}")


if __name__ == "__main__":
    OsTvApp().run()
