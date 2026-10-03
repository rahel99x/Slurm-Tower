"""The application state and key handling, free of curses so tests can drive it: tabs, cursors, marks, sort and
filter, overlays (confirm, details, help), the log tab, and the actions with their confirmations."""
from __future__ import annotations

import time
import shlex
import math
from typing import Dict, List, Optional, Sequence

from . import clipboard, export
from .logs import LogSession
from .actions import Actions
from .model import Job, Store
from .sampler import Sampler
from .views import ANALYTICS_VIEWS, NODES_VIEWS, SORTS, TABS

KEY_LABELS = {"up": "↑", "down": "↓", "pgup": "PgUp", "pgdn": "PgDn", "home": "Home", "end": "End", "tab": "Tab", "btab": "S-Tab", "enter": "Enter",
              "esc": "Esc", "space": "Space"}
KEY_LABELS_ASCII = dict(KEY_LABELS, up="Up", down="Down")
THEMES = ["default", "mono", "high", "cb", "reader"]


class App:
    def __init__(self, store: Store, sampler: Optional[Sampler], actions: Optional[Actions], cfg, user: str, ascii_: bool = False, interactive: bool = True):
        self.store, self.sampler, self.actions, self.cfg, self.user = store, sampler, actions, cfg, user
        self.keymap: Dict[str, str] = cfg.keymap()
        self.labels = KEY_LABELS_ASCII if ascii_ else KEY_LABELS
        self._ascii_cfg = ascii_
        self.config_path = getattr(cfg, "path", "")
        self.interactive = interactive
        self.tab = "jobs"
        self.cursor: Dict[str, int] = {t: 0 for t, _ in TABS}
        self.top: Dict[str, int] = {t: 0 for t, _ in TABS}
        self.sort: Dict[str, str] = {"jobs": "state", "history": "end", "nodes": "name", "group": "user"}
        self.nodes_view = "mine"
        self.compare_ids: List[str] = []
        self.dep_ids: List[str] = []
        self.reverse: Dict[str, bool] = {}
        self.marks: set = set()
        self.filter, self.filter_edit = "", ""
        self.mode = "main"
        self.confirm: dict = {}
        self.detail_id: Optional[str] = None
        self.scroll = 0
        self.log_lines = int(cfg["log_lines"])
        self.log_job: Optional[str] = None
        self.logs = LogSession(max_bytes=int(cfg["log_max_mb"]) << 20)
        self.gpu = bool(cfg["gpu_sampling"])
        self.bell = bool(cfg["bell"])
        self.message, self.message_t = "", 0.0
        self.command_ok = True
        self.selected_id: Optional[str] = None
        self.visible_ids: List[str] = []
        self.tab_hits: list = []
        self.quit = False
        self.sel_anchor: Optional[int] = None             # line selection (screen rows) for copying
        self.sel_end: int = 0
        self.click_row: Optional[int] = None
        self.last_rows: list = []
        self.palette_edit = ""
        self.theme = cfg["theme"] if cfg["theme"] in THEMES else "default"
        self.plugins = None                                # PluginAPI (set by the cli)
        self.switch_profile: Optional[str] = None          # set by :profile <name>: the cli restarts with it
        self.profile_name = getattr(cfg, "profile_name", "")
        self.files = None                                  # the files reader (LocalFiles / RemoteFiles), set by the cli
        self.analytics_view = "job"
        self.analytics_job: Optional[str] = None
        days = list(cfg["analytics_days"]) or [1, 2, 7]
        self.days_options = days
        self.days_index = days.index(cfg["history_days"]) if cfg["history_days"] in days else 0
        self.state_dir = store.state_dir if store.persist else None
        self.views_ref = None                              # set by the screen: the Views instance (exports render through it)
        self.width = 120
        self.last_hits: list = []
        self.restore(store.load_ui())

    # ---- persistence -------------------------------------------------------------------------------
    def restore(self, ui: dict):
        for k in ("tab", "log_lines", "gpu", "bell"):
            if k in ui and k != "tab":
                setattr(self, k, ui[k])
        if ui.get("tab") in dict(TABS):
            self.tab = ui["tab"]
        if isinstance(ui.get("sort"), dict):
            self.sort.update({k: v for k, v in ui["sort"].items() if v in SORTS.get(k, [])})
        if ui.get("theme") in THEMES:
            self.theme = ui["theme"]
        if ui.get("analytics_view") in dict(ANALYTICS_VIEWS):
            self.analytics_view = ui["analytics_view"]
        if ui.get("nodes_view") in dict(NODES_VIEWS):
            self.nodes_view = ui["nodes_view"]
        if isinstance(ui.get("bookmarks"), dict):
            self.logs.bookmarks = {k: sorted(int(i) for i in v) for k, v in ui["bookmarks"].items() if isinstance(v, list)}
        self.logs.wrap = bool(ui.get("log_wrap", False))

    def save(self):
        self.store.save_ui(dict(tab=self.tab, log_lines=self.log_lines, gpu=self.gpu, bell=self.bell, sort=self.sort, theme=self.theme, analytics_view=self.analytics_view,
                                nodes_view=self.nodes_view, bookmarks=self.logs.bookmarks, log_wrap=self.logs.wrap))

    def analytics_days_value(self) -> float:
        return float(self.days_options[self.days_index])

    def set_theme(self, name: str):
        self.theme = name
        if self.views_ref is not None and hasattr(self.views_ref, "set_ascii"):
            self.views_ref.set_ascii(True if name == "reader" else self._ascii_cfg)
        self.say(f"theme {name}" + (" (plain text, no colour, no glyphs)" if name == "reader" else ""))

    @property
    def follow(self) -> bool:
        return self.logs.following

    # ---- helpers the views call --------------------------------------------------------------------
    def keys_help(self, action: str) -> str:
        keys = self.cfg["keys"].get(action, [])
        return "/".join(self.labels.get(k, k) for k in keys[:2]) if keys else "?"

    def clamp_cursor(self, tab: str, n: int) -> int:
        cur = max(0, min(self.cursor.get(tab, 0), n - 1)) if n else 0
        self.cursor[tab] = cur
        return cur

    def scroll_to(self, tab: str, cursor: int, visible: int, n: int) -> int:
        top = self.top.get(tab, 0)
        if cursor < top:
            top = cursor
        if cursor >= top + visible:
            top = cursor - visible + 1
        top = max(0, min(top, max(0, n - visible)))
        self.top[tab] = top
        return top

    def say(self, text: str):
        self.message, self.message_t = text, time.time()

    def fail(self, text: str):
        """Report a command failure independently of its human-readable wording."""
        self.command_ok = False
        self.say(text)

    def tick(self):
        """Housekeeping before each frame: expire the message, tell the sampler which job is selected."""
        if self.message and time.time() - self.message_t > 6:
            self.message = ""
        if self.sampler:
            self.sampler.select(self.selected_id if self.tab in ("jobs", "log") else None)
            self.sampler.gpu_sampling = self.gpu
            self.sampler.marks = set(self.marks)
            self.sampler.select_fin(self.detail_id if (self.mode == "details" and self.detail_id and not self.store.job(self.detail_id)) else None)
            self.sampler.select_trace(self.analytics_job if (self.tab == "analytics" and self.analytics_view == "job") else None)

    def selected_job(self) -> Optional[Job]:
        return self.store.job(self.selected_id) if self.selected_id else None

    def target_jobs(self) -> List[Job]:
        """The marked jobs when there are any (visible ones first), else the selected job."""
        if self.marks:
            jobs = [self.store.job(i) for i in self.visible_ids if i in self.marks]
            jobs += [self.store.job(i) for i in sorted(self.marks) if i not in self.visible_ids]
            return [j for j in jobs if j]
        j = self.selected_job()
        return [j] if j else []

    def target_ids(self) -> List[str]:
        """Marked ids, else the selected one (on the History tab the row under the cursor)."""
        if self.marks:
            return sorted(self.marks)
        if self.tab == "history":
            ids = [f.id for f in self.store.finished]
            return [ids[self.clamp_cursor("history", len(ids))]] if ids else []
        return [self.selected_id] if self.selected_id else []

    def pin_toggle(self, ids: List[str]):
        if not ids:
            self.fail("no job selected or marked")
            return
        states = [self.store.pin(i) for i in ids]
        self.store.event("tag", f"{'pinned' if states[0] else 'unpinned'} {' '.join(ids)}")
        self.say(f"{'pinned' if states[0] else 'unpinned'} {', '.join(ids[:4])}{' ...' if len(ids) > 4 else ''}")

    def chain_ids(self, jid: str) -> List[str]:
        """The job and everything that waits for it, nearest first."""
        from .deps import DepGraph
        return [jid] + DepGraph(self.store.jobs).downstream(jid)

    # ---- key handling ------------------------------------------------------------------------------
    def sync_selection(self):
        """The selected job follows the cursor even between two renders (keys can arrive faster than frames)."""
        if self.tab in ("jobs", "log") and self.visible_ids:
            cur = self.clamp_cursor("jobs", len(self.visible_ids))
            self.selected_id = self.visible_ids[cur]
        elif self.tab == "deps" and self.dep_ids:
            cur = self.clamp_cursor("deps", len(self.dep_ids))
            self.selected_id = self.dep_ids[cur]
        elif self.tab == "group" and getattr(self, "group_ids", []):
            self.selected_id = self.group_selected()

    def handle(self, key: str) -> None:
        """``key`` is a name: a-z A-Z 0-9 punctuation, or up down pgup pgdn home end tab btab enter esc space backspace."""
        self.sync_selection()
        if self.mode == "confirm":
            self.finish_confirm(key in ("y", "Y"))
            return
        if self.mode in ("help", "details"):
            if key in ("esc", "q", "enter") or self.keymap.get(key) in ("help", "details", "quit"):
                self.mode = "main"
            elif self.keymap.get(key) == "down":
                self.scroll += 1
            elif self.keymap.get(key) == "up":
                self.scroll = max(0, self.scroll - 1)
            return
        if self.mode == "filter":
            if key == "enter":
                if self.tab == "log":                      # on the Log tab the prompt is the search
                    self.logs.search, self.mode = self.filter_edit, "main"
                    self.logs.match = None
                    buf = self.logs.buffer(self.logs.path) if self.logs.path else None
                    i = self.logs.find_next(buf, backwards=True) if self.logs.search else None
                    self.say(f"{buf.count(self.logs.search) if buf and self.logs.search else 0} lines match '{self.logs.search}'" if self.logs.search else "search cleared")
                    return
                self.filter, self.mode = self.filter_edit, "main"
                self.cursor[self.tab] = 0
            elif key == "esc":
                if self.tab == "log":
                    self.logs.search, self.logs.match = "", None
                else:
                    self.filter = ""
                self.filter_edit, self.mode = "", "main"
            elif key == "backspace":
                self.filter_edit = self.filter_edit[:-1]
            elif len(key) == 1:
                self.filter_edit += key
            elif key == "space":
                self.filter_edit += " "
            return
        if self.mode == "palette":
            if key == "enter":
                line, self.palette_edit, self.mode = self.palette_edit, "", "main"
                self.run_command(line)
            elif key == "esc":
                self.palette_edit, self.mode = "", "main"
            elif key == "backspace":
                self.palette_edit = self.palette_edit[:-1]
            elif key == "tab":
                self.palette_edit = self.palette_complete(self.palette_edit)
            elif len(key) == 1:
                self.palette_edit += key
            elif key == "space":
                self.palette_edit += " "
            return
        action = self.keymap.get(key)
        if action is None:
            return
        if self.sel_anchor is not None and action in ("up", "down", "page_up", "page_down", "home", "end"):
            n = len(self.last_rows) or 1
            step = {"up": -1, "down": 1, "page_up": -10, "page_down": 10, "home": -n, "end": n}[action]
            self.sel_end = max(0, min(n - 1, self.sel_end + step))
            return
        n = len(self.visible_ids) if self.tab == "jobs" else None
        if action == "quit":
            if self.filter:
                self.filter = ""
                self.say("filter cleared")
            else:
                self.quit = True
        elif action == "clear":
            if self.sel_anchor is not None:
                self.sel_anchor = None; self.say("selection cancelled")
            elif self.filter:
                self.filter = ""; self.say("filter cleared")
            elif self.marks:
                self.marks.clear(); self.say("marks cleared")
        elif action == "help":
            self.mode, self.scroll = "help", 0
        elif action == "refresh":
            if self.sampler:
                self.sampler.refresh_all()
            self.say("sampling every source now")
        elif action in ("up", "down", "page_up", "page_down", "home", "end"):
            self.move(action)
            self.sync_selection()
        elif action == "next_tab":
            self.switch_tab(+1)
        elif action == "prev_tab":
            self.switch_tab(-1)
        elif action.startswith("tab_"):
            self.enter_tab(action[4:])
        elif action in ("view_prev", "view_next"):
            if self.tab == "analytics":
                keys = [k for k, _ in ANALYTICS_VIEWS]
                self.analytics_view = keys[(keys.index(self.analytics_view) + (1 if action == "view_next" else -1)) % len(keys)]
            elif self.tab == "nodes":
                keys = [k for k, _ in NODES_VIEWS]
                self.nodes_view = keys[(keys.index(self.nodes_view) + (1 if action == "view_next" else -1)) % len(keys)]
        elif action == "steps":
            self.open_details()
        elif action in ("days_more", "days_less"):
            self.set_days(self.days_index + (1 if action == "days_more" else -1))
        elif action == "visual":
            self.start_selection(self.cursor_row())
        elif action == "visual_all":
            self.sel_anchor, self.sel_end = 0, max(0, len(self.last_rows) - 1)
        elif action == "yank":
            self.yank()
        elif action == "export_text":
            self.export("text")
        elif action == "export_csv":
            self.export("csv")
        elif action == "export_json":
            self.export("json")
        elif action == "palette":
            self.mode, self.palette_edit = "palette", ""
        elif action == "theme":
            self.set_theme(THEMES[(THEMES.index(self.theme) + 1) % len(THEMES)])
        elif action == "mark":
            if self.tab in ("jobs", "deps") and self.selected_id:
                if self.selected_id in self.marks:
                    self.marks.discard(self.selected_id)
                else:
                    self.marks.add(self.selected_id)
                self.move("down")
                self.sync_selection()
        elif action == "pin":
            self.pin_toggle(self.target_ids())
        elif action == "resubmit":
            ids = self.target_ids()
            if ids:
                self.mode, self.palette_edit = "palette", f"resubmit {ids[0]} "
            else:
                self.say("no job selected")
        elif action == "mark_all":
            if self.tab == "jobs":
                self.marks.update(self.visible_ids)
                self.say(f"{len(self.marks)} marked")
        elif action == "unmark_all":
            self.marks.clear()
        elif action == "details":
            if self.tab in ("jobs", "group", "deps") and self.selected_id:
                self.open_details()
            elif self.tab == "history":
                ids = [f.id for f in self.store.finished]
                cur = self.clamp_cursor("history", len(ids))
                if ids:
                    self.analytics_job, self.analytics_view = ids[cur], "job"
                    self.enter_tab("analytics")
        elif action in ("cancel", "hold", "requeue", "top"):
            self.start_confirm(action)
        elif action == "log":
            if self.selected_id:
                self.log_job = self.selected_id
                self.logs.top = None
                self.enter_tab("log")
        elif action == "less":
            self.want_less = True                       # the screen opens less on the selected job
        elif action == "follow":
            buf = self.logs.buffer(self.logs.path) if self.logs.path else None
            if self.logs.following:
                self.logs.top = buf.clamp_top(max(0, buf.total - self.logs.page), self.logs.page) if buf else 0
                if self.logs.top is None:
                    self.logs.top = 0
                self.say("paused: arrows and PgUp/PgDn scroll, End or f follows again")
            else:
                self.logs.top = None
                self.say("following")
        elif action in ("find_next", "find_prev"):
            if self.tab == "log":
                buf = self.logs.buffer(self.logs.path) if self.logs.path else None
                i = self.logs.find_next(buf, backwards=(action == "find_prev"))
                self.say(f"match at line {i + 1}" if i is not None else (f"no match for '{self.logs.search}'" if self.logs.search else "no search: / sets one"))
        elif action == "wrap":
            self.logs.wrap = not self.logs.wrap
            self.say(f"long lines {'wrapped' if self.logs.wrap else 'cut'}")
        elif action == "stderr":
            if self.tab == "log":
                self.logs.which = "err" if self.logs.which == "out" else "out"
                self.logs.file_index, self.logs.top, self.logs.match = 0, None, None
                self.say(f"showing {'stderr' if self.logs.which == 'err' else 'stdout'}")
        elif action == "log_file":
            if self.tab == "log":
                jid = self.log_job or self.selected_id
                cands = self.logs.candidates.get(jid, (0, []))[1] if jid else []
                if not cands:
                    self.say("no other files of this job in its log directory (array tasks, steps, gpu-util-<id>.csv)")
                else:
                    self.logs.file_index = (self.logs.file_index + 1) % (len(cands) + 1)
                    self.logs.top, self.logs.match = None, None
                    self.say("stdout" if self.logs.file_index == 0 else f"file {self.logs.file_index + 1}/{len(cands) + 1}: {cands[self.logs.file_index - 1]}")
        elif action == "bookmark":
            if self.tab == "log" and self.logs.path:
                buf = self.logs.buffer(self.logs.path)
                i = self.logs.current_line(buf)
                if i is not None:
                    self.logs.last_bookmark = None
                    on = self.logs.toggle_bookmark(self.logs.path, i)
                    self.say(f"bookmark {'set' if on else 'removed'} at line {i + 1}")
        elif action == "bookmark_next":
            if self.tab == "log" and self.logs.path:
                buf = self.logs.buffer(self.logs.path)
                i = self.logs.next_bookmark(self.logs.path, self.logs.current_line(buf))
                if i is None:
                    self.say("no bookmarks in this file (m sets one)")
                else:
                    self.logs.match, self.logs.last_bookmark = None, i
                    self.logs.goto(i, buf)
                    self.logs.top = buf.clamp_top(i, self.logs.page) if buf else 0   # the bookmark at the top of the page
                    if self.logs.top is None:
                        self.logs.top = 0
                    self.say(f"bookmark at line {i + 1}")
        elif action.startswith("replay_"):
            self.replay_control(action[7:])
        elif action == "sort":
            opts = SORTS.get(self.tab, ["name"])
            cur = self.sort.get(self.tab, opts[0])
            self.sort[self.tab] = opts[(opts.index(cur) + 1) % len(opts)] if cur in opts else opts[0]
            self.say(f"sorted by {self.sort[self.tab]}")
        elif action == "reverse":
            self.reverse[self.tab] = not self.reverse.get(self.tab, False)
        elif action == "filter":
            self.mode, self.filter_edit = "filter", (self.logs.search if self.tab == "log" else self.filter)
        elif action == "gpu_toggle":
            self.gpu = not self.gpu
            self.say(f"GPU sampling {'on' if self.gpu else 'off'}")
        elif action == "bell_toggle":
            self.bell = not self.bell
            self.say(f"bell {'on' if self.bell else 'off'}")
        elif action == "log_lines":
            self.log_lines = min(60, self.log_lines + 4)
        elif action == "log_lines_less":
            self.log_lines = max(0, self.log_lines - 4)
        elif action == "source_toggle":
            if self.tab == "sources":
                names = sorted(self.store.health)
                cur = self.clamp_cursor("sources", len(names))
                if names:
                    h = self.store.health[names[cur]]
                    h.enabled = not h.enabled
                    h.error = ""
                    self.say(f"{h.name} {'enabled' if h.enabled else 'disabled'}")
        self.save()

    def open_details(self):
        """The details overlay of the selected job: scontrol and the steps of a running job, sacct -j of a finished one."""
        if self.tab == "history":
            ids = [f.id for f in self.store.finished]
            if not ids:
                return
            jid = ids[self.clamp_cursor("history", len(ids))]
        elif self.tab == "group":
            jid = self.group_selected()
        else:
            jid = self.selected_id
        if jid:
            self.detail_id, self.mode, self.scroll = jid, "details", 0
            if self.sampler and not self.store.job(jid):
                self.sampler.select_fin(jid)

    def group_selected(self) -> Optional[str]:
        ids = getattr(self, "group_ids", [])
        return ids[self.clamp_cursor("group", len(ids))] if ids else None

    def handle_action(self, action: str):
        """Run one key action by name (what the palette's wrap / bookmark commands do)."""
        key = next((k for k, a in self.keymap.items() if a == action), None)
        if key:
            self.handle(key)

    def move(self, action: str):
        if self.tab == "analytics":
            if self.analytics_view == "job":
                ids = [j.id for j in self.store.jobs if not j.pending]
                for i in self.store.series_jobs():
                    if i not in ids:
                        ids.append(i)
                if ids:
                    cur = ids.index(self.analytics_job) if self.analytics_job in ids else 0
                    step = {"up": -1, "down": 1, "page_up": -5, "page_down": 5, "home": -len(ids), "end": len(ids)}[action]
                    self.analytics_job = ids[max(0, min(len(ids) - 1, cur + step))]
            return
        if self.tab == "log":
            buf = self.logs.buffer(self.logs.path) if self.logs.path else None
            page = max(1, self.logs.page - 1)
            if action == "home":
                self.logs.top = 0 if buf and buf.total > self.logs.page else None
            elif action == "end":
                self.logs.top = None
            else:
                self.logs.scroll({"up": -1, "down": 1, "page_up": -page, "page_down": page}[action], buf)
            return
        tab = self.tab
        n = {"jobs": len(self.visible_ids), "history": len(self.store.finished), "sources": len(self.store.health), "group": len(getattr(self, "group_ids", [])),
             "deps": len(self.dep_ids)}.get(tab, 0)
        page = 10
        cur = self.cursor.get(tab, 0)
        cur = {"up": cur - 1, "down": cur + 1, "page_up": cur - page, "page_down": cur + page, "home": 0, "end": 10 ** 9}[action]
        self.cursor[tab] = max(0, min(cur, max(0, n - 1)))

    def switch_tab(self, d: int):
        keys = [t for t, _ in TABS]
        self.enter_tab(keys[(keys.index(self.tab) + d) % len(keys)])

    def enter_tab(self, name: str):
        """Switch tabs; entering Analytics from Jobs or History carries the job under the cursor along."""
        if name == "analytics" and self.tab == "jobs" and self.selected_id:
            self.analytics_job = self.selected_id
        elif name == "analytics" and self.tab == "history":
            ids = [f.id for f in self.store.finished]
            if ids:
                self.analytics_job = ids[self.clamp_cursor("history", len(ids))]
        self.tab = name
        self.sel_anchor = None

    def set_days(self, index: int):
        index = max(0, min(len(self.days_options) - 1, index))
        if index == self.days_index:
            return
        self.days_index = index
        days = self.analytics_days_value()
        if self.sampler:
            self.sampler.history_days = days
            self.sampler.last_run["finished"] = 0.0
            self.sampler.kick.set()
        self.say(f"history window {days:g} day{'s' if days != 1 else ''} (sacct refreshes)")

    # ---- selection, copy, export -------------------------------------------------------------------
    def cursor_row(self) -> int:
        """The screen row of the selected job (jobs tab) or of the last click, else the first body row."""
        if self.click_row is not None:
            return self.click_row
        for (y, kind, key) in getattr(self, "last_hits", []):
            if kind == "job" and key == self.selected_id:
                return y
        return min(4, max(0, len(self.last_rows) - 1))

    def start_selection(self, row: int):
        n = len(self.last_rows)
        if n == 0:
            return
        self.sel_anchor = self.sel_end = max(0, min(n - 1, row))

    def extend_selection(self, row: int):
        if self.sel_anchor is None:
            self.sel_anchor = self.click_row if self.click_row is not None else row
        self.sel_end = max(0, min(len(self.last_rows) - 1, row))

    def selection_text(self) -> str:
        if self.sel_anchor is None:
            return export.selection_text(self.last_rows, 0, len(self.last_rows) - 1) if self.last_rows else ""
        return export.selection_text(self.last_rows, self.sel_anchor, self.sel_end)

    def yank(self):
        text = self.selection_text()
        if not text:
            self.fail("nothing to copy")
            return
        cb = self.cfg["clipboard"]
        msg = clipboard.copy(text, self.state_dir, use_osc52=bool(cb.get("osc52", True)), use_tools=bool(cb.get("tools", True)))
        self.store.event("copy", msg)
        self.say(msg)
        self.sel_anchor = None

    def export(self, kind: str):
        if not self.views_ref:
            self.fail("export needs the screen")
            return
        snap = self.store.snapshot()
        name = f"{kind}-{self.tab}-{export.stamp()}"
        try:
            if kind == "report":
                from . import report
                path = export.write(self.state_dir, f"report-{export.stamp()}.txt", report.build(snap, self, self.views_ref, self.actions))
            elif kind == "text":
                path = export.write(self.state_dir, name + ".txt", export.tab_text(self.views_ref, snap, self, self.actions, max(120, self.width)))
            elif kind == "csv":
                content = export.tab_csv(self.views_ref, snap, self, self.actions)
                if content is None:
                    self.fail(f"no table to export on the {self.tab} tab (use text)")
                    return
                path = export.write(self.state_dir, name + ".csv", content)
            else:
                ids = sorted(self.marks) or ([self.analytics_job] if self.tab == "analytics" and self.analytics_job else ([self.selected_id] if self.selected_id else []))
                if self.tab == "history" and not self.marks:
                    fins = [f.id for f in self.store.finished]
                    if fins:
                        ids = [fins[self.clamp_cursor("history", len(fins))]]
                if not ids:
                    self.fail("no job selected or marked")
                    return
                path = export.write(self.state_dir, name + ".json", export.jobs_json(snap, ids, series_of=self.store.series_of))
        except OSError as e:
            self.fail(f"export failed: {e}")
            return
        self.store.event("export", f"exported {kind} to {path}")
        self.say(f"exported {path}")

    # ---- the command palette -----------------------------------------------------------------------
    COMMANDS = ["cancel", "hold", "release", "requeue", "top", "filter", "sort", "days", "tab", "view", "export", "copy", "gpu", "bell", "source",
                "theme", "refresh", "mark", "unmark", "log", "find", "profile", "eval", "advise", "compare", "tag", "untag", "pin", "note", "chain", "resubmit", "replay", "wrap",
                "bookmark", "help", "quit"]

    def commands(self) -> List[str]:
        return self.COMMANDS + sorted(self.plugins.commands) if self.plugins else self.COMMANDS

    def palette_hint(self) -> str:
        word = self.palette_edit.split(" ")[0]
        cmds = self.commands()
        if not self.palette_edit:
            return "commands: " + " ".join(cmds) + "   (Tab completes, Enter runs, Esc closes)"
        matches = [c for c in cmds if c.startswith(word)]
        hints = {"cancel": "cancel [ids | marked | all]", "hold": "hold [ids | marked]", "release": "release [ids | marked]", "requeue": "requeue [ids | marked]",
                 "top": "top [ids | marked]", "filter": "filter <text>", "sort": "sort <" + "|".join(SORTS.get(self.tab, ["name"])) + ">", "days": "days <" + "|".join(f"{d:g}" for d in self.days_options) + ">",
                 "tab": "tab <" + "|".join(t for t, _ in TABS) + ">", "view": "view <job|history|timeline|advisor|compare>", "export": "export <text|csv|json|report>", "copy": "copy [a b]  (screen rows, 1-based)",
                 "replay": "replay <pause|play|back|fwd|slower|faster|speed N|seek HH:MM|+60|50%>", "wrap": "wrap  (Log tab: wrap or cut long lines)", "bookmark": "bookmark  (Log tab: mark the current line; ' jumps)",
                 "gpu": "gpu <on|off>", "bell": "bell <on|off>", "source": "source <name> <on|off>", "theme": "theme <default|mono|high>", "mark": "mark <ids | all>", "unmark": "unmark [ids]",
                 "log": "log <id>", "find": "find <text>  (regular expression; N / P next / previous match)", "refresh": "refresh", "help": "help", "quit": "quit",
                 "profile": "profile <" + "|".join(self.cfg.profiles()) + ">  (restarts on that cluster)" if self.cfg.profiles() else "profile: none configured ([profiles.<name>] in the config)",
                 "eval": "eval <expression>  e.g. [j.id for j in running if j.cpu < 0.3]",
                 "advise": "advise [id | name]  (what the job should ask for: --mem --cpus-per-task --time)", "compare": "compare [ids | marked | clear]  (the Analytics compare view)",
                 "tag": "tag [ids] <tags...>  (on the marked or selected jobs; filter #tag finds them)", "untag": "untag [ids] <tags...>", "pin": "pin [ids]  (toggle: pinned jobs stay on top)",
                 "note": "note [id] <text>  (a note shown with the job; empty clears)", "chain": "chain <cancel|hold|release> [id]  (the job and everything downstream)",
                 "resubmit": "resubmit [id] [--mem 12G] [--time 03:00:00] [-c 4] [--gres gpu:a100:2] [-p gpu] [--dependency=] [--script PATH] [--advised]  (clone the job; sbatch --test-only previews it)"}
        if self.plugins:
            hints.update({k: v[1] for k, v in self.plugins.commands.items()})
        if word in hints and " " in self.palette_edit:
            return hints[word]
        return " ".join(matches) if matches else "unknown command"

    def palette_complete(self, text: str) -> str:
        if " " in text:
            return text
        matches = [c for c in self.commands() if c.startswith(text)]
        return matches[0] + " " if len(matches) == 1 else text

    def _ids_arg(self, args: List[str]) -> List[Job]:
        if not args or args == ["marked"]:
            return self.target_jobs()
        if args == ["all"]:
            return [self.store.job(i) for i in self.visible_ids if self.store.job(i)]
        out = []
        for a in args:
            j = self.store.job(a)
            if j:
                out.append(j)
        return out

    def run_command(self, line: str):
        self.command_ok = True
        parts = line.strip().split()
        if not parts:
            self.fail("empty command")
            return
        cmd, args = parts[0], parts[1:]
        cmds = self.commands()
        full = [c for c in cmds if c.startswith(cmd)]
        if cmd not in cmds and len(full) == 1:
            cmd = full[0]
        if cmd not in ("eval", "find", "filter", "note"):
            try:
                args = shlex.split(line.strip())[1:]
            except ValueError as exc:
                self.fail(f"command failed: {exc}")
                return
        if self.plugins and cmd in self.plugins.commands:
            fn = self.plugins.commands[cmd][0]
            try:
                msg = fn(self, args)
            except Exception as e:
                self.command_ok = False
                msg = f"{cmd} failed: {type(e).__name__}: {e}"
            if msg:
                self.say(str(msg))
            return
        if cmd in ("cancel", "hold", "release", "requeue", "top"):
            jobs = self._ids_arg(args)
            if not jobs or not self.actions:
                self.fail("no such job" if args else "no job selected or marked")
                return
            ok = [j for j in jobs if self.actions.applicable(cmd, j)[0]]
            if not ok:
                self.fail(self.actions.applicable(cmd, jobs[0])[1])
                return
            self.confirm, self.mode = dict(action=cmd, jobs=ok), "confirm"
        elif cmd == "filter":
            self.filter = " ".join(args)
            self.cursor[self.tab] = 0
            self.say(f"filter '{self.filter}'" if self.filter else "filter cleared")
        elif cmd == "sort":
            opts = SORTS.get(self.tab, ["name"])
            if args and args[0] in opts:
                self.sort[self.tab] = args[0]
                self.say(f"sorted by {args[0]}")
            else:
                self.fail("sort keys here: " + " ".join(opts))
        elif cmd == "days":
            try:
                d = float(args[0])
                if not math.isfinite(d) or d <= 0:
                    raise ValueError("days must be positive and finite")
            except (IndexError, ValueError):
                self.fail("days <" + "|".join(f"{x:g}" for x in self.days_options) + ">")
                return
            if d not in self.days_options:
                self.days_options.append(d)
                self.days_options.sort()
            self.set_days(self.days_options.index(d))
        elif cmd == "tab":
            if args and args[0] in dict(TABS):
                self.enter_tab(args[0])
            else:
                self.fail("tab <" + "|".join(t for t, _ in TABS) + ">")
        elif cmd == "view":
            if args and args[0] in dict(ANALYTICS_VIEWS):
                self.analytics_view = args[0]
                self.enter_tab("analytics")
            else:
                self.fail("view <job|history|timeline>")
        elif cmd == "export":
            if args and (len(args) != 1 or args[0] not in ("text", "csv", "json", "report")):
                self.fail("export <text|csv|json|report>")
                return
            self.export(args[0] if args else "text")
        elif cmd == "replay":
            self.replay_control(args[0] if args else "", " ".join(args[1:]))
        elif cmd == "wrap":
            self.handle_action("wrap")
        elif cmd == "bookmark":
            self.handle_action("bookmark")
        elif cmd == "copy":
            if len(args) == 2 and all(a.isdigit() for a in args):
                self.sel_anchor, self.sel_end = int(args[0]) - 1, int(args[1]) - 1
            self.yank()
        elif cmd == "gpu":
            if args and args not in (["on"], ["off"]):
                self.fail("gpu <on|off>")
                return
            self.gpu = (args[0] == "on") if args else (not self.gpu)
            self.say(f"GPU sampling {'on' if self.gpu else 'off'}")
        elif cmd == "bell":
            if args and args not in (["on"], ["off"]):
                self.fail("bell <on|off>")
                return
            self.bell = (args[0] == "on") if args else (not self.bell)
            self.say(f"bell {'on' if self.bell else 'off'}")
        elif cmd == "source":
            if len(args) == 2 and args[0] in self.store.health and args[1] in ("on", "off"):
                h = self.store.health[args[0]]
                h.enabled = args[1] == "on"
                h.error = ""
                self.say(f"{h.name} {'enabled' if h.enabled else 'disabled'}")
            else:
                self.fail("source <" + "|".join(sorted(self.store.health)) + "> <on|off>")
        elif cmd == "theme":
            if args and args[0] in THEMES:
                self.set_theme(args[0])
            else:
                self.fail("theme <" + "|".join(THEMES) + ">")
        elif cmd == "profile":
            if args and args[0] in self.cfg.profiles():
                if args[0] == self.profile_name:
                    self.say(f"already on profile {args[0]}")
                else:
                    self.switch_profile, self.quit = args[0], True
            else:
                self.fail("profile <" + "|".join(self.cfg.profiles()) + ">" if self.cfg.profiles() else "no profiles configured ([profiles.<name>] in the config)")
        elif cmd == "eval":
            payload = line.strip().split(None, 1)
            self.say(self.evaluate(payload[1] if len(payload) > 1 else ""))
        elif cmd == "advise":
            self.say(self.advise(args[0] if args else None))
        elif cmd == "compare":
            if args == ["clear"]:
                self.compare_ids = []
                self.say("comparison cleared")
                return
            elif args and args != ["marked"]:
                self.compare_ids = list(args)
            else:
                self.compare_ids = sorted(self.marks)
            if not self.compare_ids:
                self.fail("compare <ids> or mark jobs first")
                return
            self.analytics_view = "compare"
            self.enter_tab("analytics")
        elif cmd in ("tag", "untag"):
            ids = [a for a in args if self.store.job(a) or any(f.id == a for f in self.store.finished)]
            tags = [a for a in args if a not in ids]
            ids = ids or self.target_ids()
            if not ids or not tags:
                self.fail(f"{cmd} [ids] <tags...>")
                return
            for i in ids:
                self.store.tag(i, *tags, remove=(cmd == "untag"))
            self.store.event("tag", f"{cmd} {' '.join(ids)}: {' '.join(tags)}")
            self.say(f"{cmd}ged {', '.join(ids[:4])}{' ...' if len(ids) > 4 else ''}: {' '.join('#' + t.lstrip('#') for t in tags)}")
        elif cmd == "pin":
            self.pin_toggle(args or self.target_ids())
        elif cmd == "note":
            ids = [a for a in args[:1] if self.store.job(a) or any(f.id == a for f in self.store.finished)]
            text = " ".join(args[1:] if ids else args)
            ids = ids or self.target_ids()[:1]
            if not ids:
                self.fail("note [id] <text>")
                return
            self.store.note(ids[0], text)
            self.say(f"note on {ids[0]}: {text}" if text else f"note on {ids[0]} cleared")
        elif cmd == "resubmit":
            self.start_resubmit(args)
        elif cmd == "chain":
            verb = args[0] if args else ""
            if verb not in ("cancel", "hold", "release"):
                self.fail("chain <cancel|hold|release> [id]")
                return
            root = args[1] if len(args) > 1 else self.selected_id
            if not root or not self.store.job(root):
                self.fail("chain: no such job")
                return
            jobs = [j for j in (self.store.job(i) for i in self.chain_ids(root)) if j and self.actions and self.actions.applicable(verb, j)[0]]
            if not jobs:
                self.fail(f"nothing in the chain of {root} to {verb}")
                return
            self.confirm, self.mode = dict(action=verb, jobs=jobs), "confirm"
        elif cmd == "refresh":
            if self.sampler:
                self.sampler.refresh_all()
            self.say("sampling every source now")
        elif cmd == "mark":
            if args == ["all"]:
                self.marks.update(self.visible_ids)
            else:
                self.marks.update(a for a in args if self.store.job(a))
            self.say(f"{len(self.marks)} marked")
        elif cmd == "unmark":
            if args:
                self.marks.difference_update(args)
            else:
                self.marks.clear()
            self.say(f"{len(self.marks)} marked")
        elif cmd == "log":
            if args and self.store.job(args[0]):
                self.log_job, self.logs.top = args[0], None
                self.enter_tab("log")
            else:
                self.fail("log <id>")
        elif cmd == "find":
            self.logs.search, self.logs.match = " ".join(args), None
            if self.tab != "log":
                self.enter_tab("log")
            buf = self.logs.buffer(self.logs.path) if self.logs.path else None
            i = self.logs.find_next(buf, backwards=True) if self.logs.search else None
            self.say(f"{buf.count(self.logs.search) if buf and self.logs.search else 0} lines match" if self.logs.search else "search cleared")
        elif cmd == "help":
            self.mode, self.scroll = "help", 0
        elif cmd == "quit":
            self.quit = True
        else:
            self.fail(f"unknown command '{cmd}'")

    def replay_control(self, what: str, arg: str = "") -> None:
        rp = getattr(self, "replay", None)
        if rp is None:
            self.fail("not replaying (tower --replay FILE)")
            return
        c = rp.clock
        if what == "pause":
            self.say("paused" if c.toggle_pause() else "playing")
        elif what == "play":
            if c.paused:
                c.toggle_pause()
            self.say("playing")
        elif what == "back":
            c.skip(-60); self.say("60 s back")
        elif what == "fwd":
            c.skip(60); self.say("60 s forward")
        elif what == "slower":
            c.set_speed(max(0.1, c.speed / 2)); self.say(f"speed x{c.speed:g}")
        elif what == "faster":
            c.set_speed(min(1000, c.speed * 2)); self.say(f"speed x{c.speed:g}")
        elif what == "speed":
            try:
                c.set_speed(float(arg))
                self.say(f"speed x{c.speed:g}")
            except ValueError:
                self.fail("replay speed <n>")
        elif what == "seek":
            a = arg.strip()
            try:
                if a.endswith("%"):
                    c.seek(c.t0 + (c.t1 - c.t0) * float(a[:-1]) / 100)
                elif a.startswith(("+", "-")):
                    c.skip(float(a))
                elif ":" in a:
                    day = time.strftime("%Y-%m-%d", time.localtime(c.t0))
                    hhmm = a if a.count(":") == 2 else a + ":00"
                    t = time.mktime(time.strptime(f"{day}T{hhmm}", "%Y-%m-%dT%H:%M:%S"))
                    c.seek(t)
                else:
                    c.seek(c.t0 + float(a))
                self.say(f"at {time.strftime('%H:%M:%S', time.localtime(c.now()))}")
            except ValueError:
                self.fail("replay seek <HH:MM | +60 | -60 | 50% | seconds>")
        else:
            self.fail("replay <pause|play|back|fwd|slower|faster|speed N|seek ...>")
        if self.sampler:
            self.sampler.refresh_all()

    def evaluate(self, text: str) -> str:
        """An expression over the snapshot (see expr.py), as one line of text."""
        from .expr import Expr, ExprError, cluster_ns
        try:
            v = Expr(text)(cluster_ns(self.store.snapshot(), self.user, self.marks))
        except ExprError as e:
            self.command_ok = False
            return f"eval: {e}"
        if isinstance(v, (list, tuple, set)):
            v = [x.get("id", x) if isinstance(x, dict) else x for x in v]
        text = repr(v) if not isinstance(v, str) else v
        return text if len(text) < 300 else text[:297] + "..."

    def advise(self, what: Optional[str]) -> str:
        """The advisor's suggestion for a job id, a job name, or the selected job."""
        from . import advisor
        snap = self.store.snapshot()
        if what is None:
            ids = self.target_ids()
            what = ids[0] if ids else None
        if not what:
            self.command_ok = False
            return "advise <id | name>"
        j = self.store.job(what)
        if j and not j.pending:
            a = advisor.advise_running(j, snap["live"].get(j.id), self.store.series_of(j.id), snap["finished"])
            return f"{j.id} {j.name} so far: " + (a.summary(self.views_ref.g.dot if self.views_ref else "|") or "nothing to change yet")
        f = next((f for f in snap["finished"] if f.id == what), None)
        if f:
            a = advisor.advise_finished(f, snap["finished"])
            return f"{f.id} {f.name} ({f.state.lower()}): " + (a.summary(self.views_ref.g.dot if self.views_ref else "|") or "nothing to change") + (f"  -> {a.flags()}" if a.flags() else "")
        name = j.name if j else what
        advs = [a for a in advisor.advise_names(snap["finished"]) if a.name == name]
        if advs:
            a = advs[0]
            return f"{name} ({a.id}): " + (a.summary(self.views_ref.g.dot if self.views_ref else "|") or "nothing to change") + (f"  -> {a.flags()}" if a.flags() else "")
        self.command_ok = False
        return f"no finished run of '{what}' in the window and no such running job"

    def click(self, y: int, x: int, hits: Sequence, button: str = "left", shift: bool = False) -> None:
        """A mouse click: on the tab bar switches tabs, on a row selects it; a right or shift click extends the
        line selection from the last click to this row."""
        self.last_hits = list(hits)
        if button == "right" or shift:
            self.extend_selection(y)
            return
        self.click_row = y
        for (ty, x0, x1, key) in self.tab_hits:
            if y == ty and x0 <= x < x1:
                self.enter_tab(key)
                return
        for (hy, kind, key) in hits:
            if hy == y:
                if kind == "job":
                    if key in self.visible_ids:
                        self.cursor["jobs"] = self.visible_ids.index(key)
                elif kind == "fin":
                    ids = [f.id for f in self.store.finished]
                    if key in ids:
                        self.cursor["history"] = ids.index(key)
                elif kind == "source":
                    names = sorted(self.store.health)
                    if key in names:
                        self.cursor["sources"] = names.index(key)
                elif kind == "group":
                    ids = getattr(self, "group_ids", [])
                    if key in ids:
                        self.cursor["group"] = ids.index(key)
                elif kind == "dep":
                    if key in self.dep_ids:
                        self.cursor["deps"] = self.dep_ids.index(key)
                return

    # ---- confirmations -----------------------------------------------------------------------------
    def start_confirm(self, action: str):
        if self.tab not in ("jobs", "deps") or not self.actions:
            return
        if self.tab == "deps" and self.selected_id and not self.marks:
            jobs = [self.store.job(i) for i in self.chain_ids(self.selected_id)]
            jobs = [j for j in jobs if j]
        else:
            jobs = self.target_jobs()
        pend = [j for j in jobs if j.pending]
        if action == "hold" and pend and all(j.held for j in pend):
            action = "release"
        ok = [j for j in jobs if self.actions.applicable(action, j)[0]]
        if not ok:
            why = self.actions.applicable(action, jobs[0])[1] if jobs else "no job selected"
            self.fail(why)
            return
        self.confirm = dict(action=action, jobs=ok)
        self.mode = "confirm"

    def start_resubmit(self, args: List[str]):
        """Build the clone (sacct's submit line, else the record), apply the overrides, preview with sbatch --test-only, ask."""
        from . import advisor, resubmit
        self.mode, self.confirm = "main", {}
        try:
            over, words, switches = resubmit.parse_override_args(args)
            if len(words) > 1:
                raise ValueError("provide one job id; use --script PATH to replace its script")
        except ValueError as exc:
            self.fail(f"resubmit: {exc}")
            return
        jid = words[0] if words else (self.target_ids() or [None])[0]
        if not jid:
            self.fail("resubmit [id] [--mem ..] [--time ..] [-c ..] [--advised]")
            return
        if not self.actions:
            self.fail("no actions in this mode")
            return
        snap = self.store.snapshot()
        job = self.store.job(jid)
        fin = next((f for f in snap["finished"] if f.id == jid), None)
        if job is None and fin is None:
            self.fail(f"resubmit: no job {jid} in the queue or the history")
            return
        if "advised" in switches:
            adv = advisor.advise_running(job, snap["live"].get(jid), self.store.series_of(jid), snap["finished"]) if job and not job.pending else \
                (advisor.advise_finished(fin, snap["finished"]) if fin else None)
            if adv:
                if adv.mem_suggest:
                    over.setdefault("mem", adv.mem_suggest)
                if adv.cpus_suggest and adv.cpus_suggest != adv.cpus:
                    over.setdefault("cpus", str(adv.cpus_suggest))
                if adv.time_suggest:
                    over.setdefault("time", adv.time_suggest)
        try:
            info = self.actions.slurm.submit_info(jid)
        except Exception as e:                            # sacct without SubmitLine (older Slurm), or unreachable: the record will do
            info = {}
            self.store.event("resubmit", f"sacct submit line unavailable for {jid}: {e}", job_id=jid)
        details = snap["details"].get(jid, {})
        if job and not details:
            try:
                details = self.actions.slurm.details(jid)
            except Exception:
                details = {}
        try:
            clone = resubmit.build(jid, info, details, job=job, fin=fin, overrides=over)
            has_submission = resubmit.has_submission(clone.argv)
        except ValueError as exc:
            self.fail(f"resubmit: {exc}")
            return
        if not has_submission:
            self.fail("resubmit: " + (clone.notes[0] if clone.notes else "nothing to submit") + " (--script PATH)")
            return
        ok, output = self.actions.slurm.preview_submit(clone.argv, clone.workdir)
        if not ok:
            self.fail(f"resubmit preview failed: {output or 'sbatch --test-only did not succeed'}")
            return
        from .slurm import parse_test_only
        est, nodes = parse_test_only(output)
        if est:
            from .model import when
            clone.probe = f"sbatch --test-only: would start {when(est)}" + (f" on {nodes}" if nodes else "")
        else:
            clone.probe = "sbatch --test-only: " + (output.strip() or "validated; no start-time projection")
        self.confirm = dict(action="resubmit", jobs=[job] if job else [], clone=clone)
        self.mode = "confirm"

    def finish_confirm(self, yes: bool):
        self.mode = "main"
        if not yes:
            self.say("kept")
            return
        if self.confirm.get("action") == "resubmit":
            clone = self.confirm["clone"]
            ok, out, new_id = self.actions.resubmit(clone)
            self.command_ok = ok
            self.say(f"resubmitted {clone.id} as {new_id}" if ok and new_id else (f"submitted: {out}" if ok else f"resubmit failed: {out}"))
            if ok and new_id:
                self.store.tag(new_id, f"from-{clone.id.split('_')[0]}")
            if self.sampler:
                self.sampler.refresh_all()
            return
        ok, out = self.actions.run(self.confirm["action"], self.confirm["jobs"])
        self.command_ok = ok
        ids = ", ".join(j.id for j in self.confirm["jobs"][:4]) + (" ..." if len(self.confirm["jobs"]) > 4 else "")
        self.say(f"{self.confirm['action']} {ids}: " + ("sent" if ok else f"failed: {out}"))
        if ok:
            self.marks.difference_update(j.id for j in self.confirm["jobs"])
        if self.sampler:
            self.sampler.refresh_all()
