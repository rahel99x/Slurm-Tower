"""Real ncurses preserves fragmented mouse framing and the following key."""
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import sys
import time

import pytest


CHILD = r'''
import curses, json, os, time
from pathlib import Path
from tower import screen
from tower.config import Config
from tower.controller import App
from tower.layout import Glyphs
from tower.model import Job, Store
from tower.views import Views

result = {"events": []}
def main(window):
    curses.raw()
    curses.set_escdelay(25)
    curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
    curses.mouseinterval(0)
    window.keypad(True)
    cfg = Config({"animations": False, "startup_animation": False, "gpu_sampling": False})
    store = Store(persist=False)
    store.jobs = [Job("7", "training", "cpu", "RUNNING", cpus=4)]
    app = App(store, None, None, cfg, "test", interactive=False)
    views = Views(Glyphs(False), cfg)
    app.views_ref = views
    cache = screen._FrameCache()
    cache.rebuild(app, views, store, None, 160, 40)
    reader = screen._InputReader(window)
    Path(os.environ["TOWER_PTY_READY"]).touch()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not app.quit:
        window.timeout(5 if reader.escape else 100)
        event = reader.read(curses)
        if reader.escape:
            Path(os.environ["TOWER_PTY_PREFIX"]).touch()
        if event is None or event[0] is None:
            continue
        result["events"].append(event[0])
        if event[0] == "mouse":
            Path(os.environ["TOWER_PTY_WARMUP"]).touch()
        elif event[0] == "esc":
            Path(os.environ["TOWER_PTY_ESCAPED"]).touch()
        screen._apply_input(app, event, cache.hits, curses)
        if app.tab != "jobs":
            raise AssertionError("Mouse bytes activated " + app.tab)
    result.update(tab=app.tab, selected_id=app.selected_id, quit=app.quit)
    if app.research:
        app.research.close()

curses.wrapper(main)
with open(os.environ["TOWER_PTY_RESULT"], "w") as file:
    json.dump(result, file)
'''


@pytest.mark.skipif(os.name != "posix", reason="A POSIX pseudo-terminal is required")
@pytest.mark.parametrize("terminal", ["screen", "xterm-256color"])
@pytest.mark.parametrize("scenario", ["escape-120ms", "sgr-middle-120ms", "escape-300ms"])
def test_fragmented_report_through_real_curses_and_app_keeps_jobs_page(tmp_path, terminal, scenario):
    pytest.importorskip("curses")
    pty = pytest.importorskip("pty")
    fcntl = pytest.importorskip("fcntl")
    termios = pytest.importorskip("termios")
    script, ready, result, prefix, warmup_seen, escaped = (tmp_path / name for name in
        ("child.py", "ready", "result.json", "prefix", "warmup", "escaped"))
    script.write_text(CHILD)
    root = Path(__file__).resolve().parents[1]
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 160, 0, 0))
    environment = dict(os.environ, TERM=terminal, LC_ALL="C.UTF-8", PYTHONPATH=str(root),
                       TOWER_PTY_READY=str(ready), TOWER_PTY_RESULT=str(result),
                       TOWER_PTY_PREFIX=str(prefix), TOWER_PTY_WARMUP=str(warmup_seen),
                       TOWER_PTY_ESCAPED=str(escaped))
    process = subprocess.Popen([sys.executable, str(script)], cwd=root, env=environment,
                               stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    output = bytearray()
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], .01)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        if not ready.exists() and b"could not find terminal" in output:
            pytest.skip("The requested terminal description is unavailable")
        assert ready.exists(), output.decode("utf-8", "replace")
        warmup = b"\x1b[<35;82;25M"
        report = b"\x1b[MCr9" if scenario != "sgr-middle-120ms" else warmup
        split = 1 if scenario != "sgr-middle-120ms" else 9
        os.write(master, warmup + report[:split])
        # Ncurses may own a partial SGR prefix internally. Its warmup event
        # establishes that the child is reading; raw Escape also has a prefix
        # acknowledgement before the timed fragment gap begins.
        acknowledgement = warmup_seen if scenario == "sgr-middle-120ms" else prefix
        while not acknowledgement.exists() and process.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], .005)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        assert acknowledgement.exists(), output.decode("utf-8", "replace")
        time.sleep(.3 if scenario == "escape-300ms" else .12)
        if scenario == "escape-300ms":
            while not escaped.exists() and process.poll() is None and time.monotonic() < deadline:
                if select.select([master], [], [], .005)[0]:
                    try:
                        output.extend(os.read(master, 65536))
                    except OSError:
                        break
            assert escaped.exists(), "The late-fragment case did not exercise Escape recovery"
        os.write(master, report[split:] + b"q")
        while time.monotonic() < deadline:
            if select.select([master], [], [], .05)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
            elif process.poll() is not None:
                break
        process.wait(timeout=1)
        assert process.returncode == 0, output.decode("utf-8", "replace")
        captured = json.loads(result.read_text())
        expected = ["mouse", "esc", "mouse", "q"] if scenario == "escape-300ms" else ["mouse", "mouse", "q"]
        assert captured["events"] == expected
        assert captured["tab"] == "jobs" and captured["quit"]
        if scenario != "escape-300ms":
            assert captured["selected_id"] == "7"
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=2)
        os.close(master)
