"""The tabs and overlays as rows of (text, style) segments.  ``compose`` returns the rows for the whole screen plus
the hit map (row index -> what the mouse would select)."""
from __future__ import annotations

import os
import re
import time
from typing import Dict, List, Optional, Sequence, Tuple

from . import clock
from . import layout as L
from . import charts
from .layout import Column, Glyphs, Row, bar, box, cut, gradient_bar, pad, rule, spark, table, vlen
from . import advisor
from .deps import DepGraph
from .model import Finished, Job, Step, compact, hms, human, secs, short_duration, stamp, when
from .remote import LocalFiles

TABS = [("jobs", "Jobs"), ("cluster", "Cluster"), ("history", "History"), ("analytics", "Analytics"), ("nodes", "Nodes"), ("group", "Group"), ("deps", "Deps"), ("log", "Log"), ("sources", "Sources"), ("research", "Research")]
ANALYTICS_VIEWS = [("job", "job series"), ("history", "history"), ("timeline", "timeline"), ("advisor", "advisor"), ("compare", "compare")]
NODES_VIEWS = [("mine", "my nodes"), ("map", "cluster map")]
LOG_ERROR = re.compile(r"\b(?:error|fatal|traceback|oom|killed|failed)\b", re.IGNORECASE)
LOG_WARNING = re.compile(r"\b(?:warn(?:ing)?|retry(?:ing)?|timeout)\b", re.IGNORECASE)
LOG_SUCCESS = re.compile(r"\b(?:done|complete(?:d)?|success(?:ful)?)\b", re.IGNORECASE)

JOB_COLS = [Column("id", "JOBID", 5, 16), Column("name", "NAME", 10, 30, flex=True), Column("part", "PART", 4, 9), Column("st", "ST", 2, 3),
            Column("where", "NODES", 6, 18, flex=True), Column("cpus", "CPU", 3, 4, ">"), Column("gpu", "GPU", 3, 8), Column("time", "ELAPSED/LIMIT", 8, 20),
            Column("left", "LEFT/WAIT", 9, 11, ">"), Column("cpu%", "CPU%", 4, 4, ">"), Column("eff", "EFF", 4, 5, ">"), Column("mem%", "MEM%", 4, 4, ">"),
            Column("gpu%", "GPU%", 4, 4, ">"), Column("flags", "FLAGS", 5, 12), Column("tags", "TAGS", 4, 14), Column("info", "INFO", 34, 60, flex=True)]
JOB_DROP = ("tags", "left", "flags", "gpu%", "mem%", "eff", "cpu%", "part", "gpu", "where", "st")
SORTS = {"jobs": ["state", "name", "id", "time", "priority"], "history": ["end", "name", "state", "elapsed", "cpu_eff", "mem_eff"],
         "nodes": ["name", "load"], "cluster": ["name"], "log": ["name"], "sources": ["name"], "group": ["user", "state", "name", "id", "time", "priority"], "deps": ["name"]}


def tail_lines(path: str, n: int, max_bytes: int = 131072, files=None) -> List[str]:
    if not path or n <= 0:
        return []
    files = files or LocalFiles()
    try:
        data, size = files.tail(path, max_bytes)
        data = data.decode("utf-8", "replace")
    except OSError:
        return []
    lines = data.splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]
    return [l.replace("\t", "    ") for l in lines[-n:]]


def stdout_path(job: Job, kv: dict, files=None, which: str = "StdOut") -> str:
    p = kv.get(which, "") if kv else ""
    if p:
        return p
    if files is not None and files.remote:
        return ""
    guess = os.path.join("logs", f"{job.name}-{job.id}.{'err' if which == 'StdErr' else 'out'}")
    return guess if os.path.exists(guess) else ""


class Views:
    def __init__(self, glyphs: Glyphs, cfg, files=None, plugins=None):
        self.g, self.cfg = glyphs, cfg
        self.th = cfg["thresholds"]
        self.gpu_types = cfg["gpu_types"]
        self.files = files or LocalFiles()
        self.plugins = plugins                             # PluginAPI or None: extra tabs and flags
        self.extra_tabs: Dict[str, object] = {}
        for key, title, render in (plugins.tabs if plugins else []):
            if key not in dict(TABS):
                TABS.append((key, title))
            self.extra_tabs[key] = render

    def set_ascii(self, ascii_: bool):
        """Reader mode: plain glyphs (the painter also drops colour)."""
        if ascii_ != self.g.ascii:
            self.g = Glyphs(ascii_)

    def visual_room(self, width: int, height: Optional[int], minimum: int = 18) -> bool:
        """Give dense visual panels room without displacing a selected table row on small screens."""
        return not self.g.ascii and width >= 72 and (height is None or height >= minimum)

    def composition(self, items: Sequence[Tuple[str, float, str]], width: int, title: str = "") -> List[Row]:
        """A measured distribution: counts remain readable when colour is unavailable."""
        if not any(value > 0 for _, value, _ in items):
            return []
        return charts.stacked_bar(self.g, items, width, title=title)

    @staticmethod
    def beside(panels: Sequence[List[Row]], widths: Sequence[int], gap: int = 2) -> List[Row]:
        """Join independent panels while retaining every segment's style and display width."""
        out: List[Row] = []
        for y in range(max((len(panel) for panel in panels), default=0)):
            row: Row = []
            for i, (panel, width) in enumerate(zip(panels, widths)):
                cell = L.clip_row(panel[y] if y < len(panel) else [], width)
                row += cell + [(" " * max(0, width - vlen(L.row_text(cell))), "")]
                if i < len(panels) - 1:
                    row.append((" " * gap, ""))
            out.append(row)
        return out

    def resource_cards(self, snap: dict, j: Job, width: int) -> List[Row]:
        """Three solid resource instruments, using only recorded CPU, peak RSS and elapsed time."""
        lv = snap["live"].get(j.id)
        cpu = (lv.rate if lv.rate is not None else lv.avg) if lv else None
        mem = lv.rss / j.mem_bytes if lv and lv.rss is not None and j.mem_bytes else None
        elapsed, limit = j.elapsed_s, j.limit_s
        used_time = elapsed / limit if elapsed is not None and limit else None
        efficiency = f"{100 * lv.avg:.1f}%" if lv and lv.avg is not None else "unknown"
        cpu_value = "waiting for a sample" if cpu is None else f"{100 * cpu:.0f}% {'now' if lv.rate is not None else 'average'}  ·  eff {efficiency}"
        cpu_note = (f"{cpu * j.cpus:.1f}/{j.cpus} cores  " + spark(self.g, snap["hist_cpu"].get(j.id, []), 10)) if cpu is not None else "sstat utilisation unknown"
        mem_value = f"{human(lv.rss)} / {human(j.mem_bytes)}" if lv and lv.rss is not None and j.mem_bytes else (f"{human(lv.rss)} used" if lv and lv.rss is not None else "memory sample unknown")
        mem_note = f"{100 * mem:.1f}% of requested memory" if mem is not None else "memory request unknown" if not j.mem_bytes else f"requested {human(j.mem_bytes)}"
        time_value = f"{j.elapsed or '?'} / {j.limit or '?'}"
        time_note = f"{hms(max(0, limit - elapsed))} remaining" if elapsed is not None and limit else "wall-time limit unknown"
        cards = [("CPU", cpu, cpu_value, cpu_note, "#22d3ee", "#3b82f6"),
                 ("PEAK MEMORY", mem, mem_value, mem_note, "#a78bfa", "#ec4899"),
                 ("WALL TIME", used_time, time_value, time_note, "#34d399", "#fbbf24")]
        cell = max(8, (width - 2 - 4) // 3)
        sizes = [cell, cell, max(8, width - 2 - 4 - cell * 2)]
        panels = []
        for (label, frac, value, note, start, end), size in zip(cards, sizes):
            inner = size - 4
            title = cut(" " + label + " ", size - 2, self.g.ascii)
            top = [("┌" + title + "─" * max(0, size - 2 - vlen(title)) + "┐", "dim")]
            def content(segments):
                segments = L.clip_row(segments, inner)
                return [("│ ", "dim")] + segments + [(" " * max(0, inner - vlen(L.row_text(segments))) + " │", "dim")]
            panel = [top, content([(cut(value, inner), "bold")]),
                     content(gradient_bar(self.g, frac, inner, start, end)),
                     content([(cut(note, inner), "dim")]), [("└" + "─" * (size - 2) + "┘", "dim")]]
            panels.append(panel)
        return [[(" ", "")] + row for row in self.beside(panels, sizes)]

    def node_resource_rows(self, nodes, width: int) -> List[Row]:
        """A categorical resource matrix; columns are measurements, never an implied time axis."""
        from .palette import gradient
        label_w = min(16, max(vlen(node.name) for node in nodes))
        cell_w = max(8, (width - label_w - 7) // 3)
        titles = ("CPU ALLOCATED", "LOAD / CORE", "MEMORY USED")
        out = [rule(self.g, width, "node resource matrix · measured percentages"),
               [(" " + " " * label_w + "  ", "")] + [(pad(cut(title, cell_w), cell_w) + ("  " if i < 2 else ""), "cyan+bold") for i, title in enumerate(titles)]]
        for node in nodes[:8]:
            values = (node.alloc / node.cpus if node.cpus else None,
                      node.load / node.cpus if node.cpus and node.load is not None else None,
                      (node.mem_total - node.mem_free) / node.mem_total if node.mem_total and node.mem_free is not None and node.mem_free <= node.mem_total else None)
            row: Row = [(" " + pad(cut(node.name, label_w), label_w) + "  ", "bold")]
            for i, value in enumerate(values):
                frac = max(0.0, min(1.0, value)) if value is not None else 0
                shade = gradient("#164e63", "#22d3ee", frac * 2) if frac < .5 else gradient("#22d3ee", "#fbbf24", (frac - .5) * 2)
                row += gradient_bar(self.g, value, cell_w - 8, "#164e63", shade)
                row.append((f" {100 * value:>4.0f}%  " if value is not None else "    ?   ", "bold" if value is not None else "dim"))
                if i < 2:
                    row.append(("  ", ""))
            out.append(row)
        out.append([("   Allocation is reserved CPU capacity; load is runnable work per core. ? means unobserved.", "dim")])
        return [L.clip_row(row, width) for row in out]

    # ---- shared pieces ----------------------------------------------------------------------------
    def header(self, snap: dict, app, width: int) -> List[Row]:
        jobs = snap["jobs"]
        running = [j for j in jobs if not j.pending]
        pending = [j for j in jobs if j.pending]
        tot_cpu, tot_gpu = sum(j.cpus for j in running), sum(j.gpus for j in running)
        ests = [j.est_start for j in pending if j.est_start not in ("N/A", "", "Unknown")]
        inv = snap.get("gpu_inventory", {})
        free = "  ".join(f"{t} {v['free']}/{v['total'] - v['down']}" for t, v in sorted(inv.items()) if t in self.gpu_types) or "n/a"
        sh = "  ".join(f"{s['account']} {s['fairshare']}" for s in snap.get("share", [])[:2]) or "n/a"
        acc = snap.get("account", {})
        age = clock.now() - snap["t_jobs"] if snap.get("t_jobs") else None
        who = app.user + (f"@{app.host_label}" if getattr(app, "host_label", "") else "") + (f" [{app.profile_name}]" if getattr(app, "profile_name", "") else "")
        if getattr(app, "demo", False):
            who += " [DEMO]"
        r1: Row = [(f" tower {self.g.dot} {who} {self.g.dot} {time.strftime('%H:%M:%S', time.localtime(clock.now()))}", "bold"),
                   ("   running ", ""), (str(len(running)), "green"), (f" ({tot_cpu} cpus, {tot_gpu} gpus)   pending ", ""), (str(len(pending)), "yellow")]
        rp = getattr(app, "replay", None)
        if rp is not None:
            c = rp.clock
            r1.append((f"   REPLAY {time.strftime('%m-%d %H:%M:%S', time.localtime(c.now()))} {g_speed(c)}" + ("  paused" if c.paused else ("  end" if c.at_end else "")), "magenta"))
        if ests:
            r1.append((f"   next start {when(min(ests))}", ""))
        if app.filter:
            r1.append((f"   filter '{app.filter}'", "magenta"))
        if app.marks:
            r1.append((f"   {len(app.marks)} marked", "magenta"))
        if not app.gpu:
            r1.append(("   GPU sampling off", "dim"))
        eng = getattr(app.store, "alerts", None)
        if eng is not None and eng.active_count():
            r1.append((f"   {'!' if self.g.ascii else '⚠'} {eng.active_count()} alert{'s' if eng.active_count() != 1 else ''}: " + cut(", ".join(eng.active_text()[:3]), 60, self.g.ascii), "red+bold"))
        if age is not None and age > 3 * self.cfg["intervals"]["jobs"] + 2:
            r1.append((f"   (data {int(age)}s old)", "yellow"))
        r2: Row = [(f" free GPUs: {free}    fair share: {sh}", "")]
        if acc:
            r2.append((f"    {acc['account']}: {acc['running']} running ({acc['cpus']} cpus, {acc['gpus']} gpus), {acc['pending']} pending", "dim"))
        budget_hint = ""
        bud = snap.get("budget", {})
        if bud and bud.get("limit"):
            bits = []
            for k in ("cpu", "gpu"):
                if bud["limit"].get(k):
                    bits.append(f"{k} {100 * bud['used'].get(k, 0) / bud['limit'][k]:.0f}%")
            if bits:
                budget_hint = f"    allocation {' '.join(bits)}"
                r2.append((budget_hint, "dim"))
        r2 = self.page_metrics(snap, app, width) or r2
        if budget_hint and width - vlen(L.row_text(r2)) >= vlen(budget_hint):
            r2.append((budget_hint, "dim"))
        tabs, tab_hits = self.tab_bar(snap, app, width)
        app.tab_hits = [(3 if rp is not None else 2, x0, x1, key) for x0, x1, key in tab_hits]
        rows = [r1, r2, tabs]
        if rp is not None:
            rows.insert(2, self.replay_bar(rp, width))
        bad = [h for h in snap.get("health", {}).values() if h.error and h.enabled]
        if bad:
            rows.append([(" sources: " + "; ".join(f"{h.name}: {cut(h.error, 60, self.g.ascii)}" for h in bad[:3]), "red")])
        return rows

    def tab_bar(self, snap: dict, app, width: int):
        """Fit a contiguous set of tabs, keeping the current page visible and mouse targets exact."""
        labels = []
        for key, title in TABS:
            n = {"jobs": len(snap["jobs"]), "history": len(snap.get("finished", [])), "nodes": len(snap.get("nodes", {})), "group": len(snap.get("group", [])),
                 "sources": sum(1 for h in snap.get("health", {}).values() if h.error)}.get(key)
            label = f" {title}" + (f" {n}" if n else "") + " "
            labels.append((key, label))
        active = next((i for i, (key, _) in enumerate(labels) if key == app.tab), 0)
        start = 0
        while start < active and 1 + sum(vlen(t) + 1 for _, t in labels[start:active + 1]) > width - 2:
            start += 1
        x = 1 + (2 if start else 0)
        tabs: Row = [(" < " if start else " ", "dim")]
        hits = []
        for i, (key, label) in enumerate(labels[start:], start):
            reserve = 2 if i < len(labels) - 1 else 0
            if x + vlen(label) > width - reserve and i > active:
                tabs.append((" >", "dim"))
                break
            label = cut(label, max(0, width - x - reserve), self.g.ascii)
            tabs.append((label, "rev+bold" if key == app.tab else "dim"))
            hits.append((x, x + vlen(label), key))
            tabs.append((" ", ""))
            x += vlen(label) + 1
        return L.clip_row(tabs, width), hits

    def page_metrics(self, snap: dict, app, width: int) -> Row:
        """The top ribbon answers the most useful questions for the current page, without extra rows."""
        jobs, finished = snap["jobs"], snap.get("finished", [])
        running = [j for j in jobs if not j.pending]
        inv = snap.get("gpu_inventory", {})
        health = list(snap.get("health", {}).values())
        items = []
        if app.tab == "jobs":
            rates = [lv.rate if lv.rate is not None else lv.avg for j in running
                     if (lv := snap.get("live", {}).get(j.id)) is not None]
            rates = [r for r in rates if r is not None]
            flags = sum(bool(self.flags_of(j, snap["live"].get(j.id), snap["gpu"].get(j.id), snap)[0]) for j in running)
            items = [("CPU mean", f"{100 * sum(rates) / len(rates):.0f}%" if rates else "waiting", "cyan"),
                     ("GPU free", str(sum(v["free"] for v in inv.values())) if inv else "unknown", "green"),
                     ("Check jobs", str(flags), "yellow" if flags else "green"),
                     ("Queue", str(sum(j.pending for j in jobs)), "yellow")]
        elif app.tab == "cluster":
            parts = snap.get("partitions", [])
            items = [("Partitions", str(len(parts)), "cyan"),
                     ("GPU free", str(sum(v["free"] for v in inv.values())) if inv else "unknown", "green"),
                     ("GPU used", str(sum(v["used"] for v in inv.values())) if inv else "unknown", "cyan"),
                     ("GPU down", str(sum(v["down"] for v in inv.values())) if inv else "unknown", "yellow")]
        elif app.tab in ("history", "analytics"):
            done = sum(f.state == "COMPLETED" for f in finished)
            eff = [f.cpu_eff for f in finished if f.cpu_eff is not None]
            items = [("Completed", f"{done}/{len(finished)}", "green"),
                     ("CPU eff", f"{100 * sum(eff) / len(eff):.0f}%" if eff else "unknown", "cyan"),
                     ("Core-hours", f"{sum(f.core_hours for f in finished):,.1f}", "cyan"),
                     ("GPU-hours", f"{sum(f.gpu_hours for f in finished):,.1f}", "magenta")]
        elif app.tab == "nodes":
            nodes = list(snap.get("nodes", {}).values())
            total, used = sum(n.cpus for n in nodes), sum(n.alloc for n in nodes)
            cells = list(snap.get("nodemap", {}).values())
            items = [("My nodes", str(len(nodes)), "cyan"), ("Cores busy", f"{used}/{total}", "cyan"),
                     ("Map nodes", str(len(cells)), "green"), ("Down", str(sum(n.down for n in cells)), "yellow")]
        elif app.tab == "group":
            group = snap.get("group", [])
            active = [j for j in group if not j.pending]
            items = [("Users", str(len({j.user for j in group})), "cyan"), ("Running", str(len(active)), "green"),
                     ("Pending", str(len(group) - len(active)), "yellow"), ("CPUs", str(sum(j.cpus for j in active)), "cyan")]
        elif app.tab == "deps":
            dependent = [j for j in jobs if j.dependency and j.dependency not in ("(null)", "N/A")]
            items = [("Dependent", str(len(dependent)), "magenta"), ("Held", str(sum(j.held for j in jobs)), "yellow"),
                     ("Pending", str(sum(j.pending for j in jobs)), "yellow"), ("Running", str(len(running)), "green")]
        elif app.tab == "log":
            jid = app.log_job or app.selected_id
            job = next((j for j in jobs if j.id == jid), None)
            items = [("Job", jid or "select one", "cyan"), ("Stream", "following" if app.logs.following else "paused", "green" if app.logs.following else "yellow"),
                     ("State", job.state.lower() if job else "waiting", "cyan"), ("Search", app.logs.search or "off", "magenta")]
        elif app.tab == "sources":
            enabled = [h for h in health if h.enabled]
            good = sum(bool(h.last_ok) and not h.error for h in enabled)
            items = [("Healthy", f"{good}/{len(enabled)}", "green"),
                     ("Errors", str(sum(bool(h.error) for h in enabled)), "red" if any(h.error for h in enabled) else "green"),
                     ("Sampling", str(sum(h.inflight for h in enabled)), "cyan"), ("Disabled", str(len(health) - len(enabled)), "dim")]
        return L.metrics(self.g, items, width)

    def replay_bar(self, rp, width: int) -> Row:
        """The scrub bar of a replay: position in the recording, its span, speed and state."""
        g = self.g
        c = rp.clock
        bar_w = max(10, min(60, width - 70))
        n = int(round(c.frac * bar_w))
        fmt = "%H:%M:%S"
        return [(" replay ", "magenta+bold"), (g.full * n, "magenta"), (g.empty * (bar_w - n), "dim"),
                (f" {time.strftime(fmt, time.localtime(c.now()))} of {time.strftime(fmt, time.localtime(c.t0))}..{time.strftime(fmt, time.localtime(c.t1))}  x{c.speed:g}"
                 + ("  paused" if c.paused else ("  end" if c.at_end else "")) + "   | pause  < > 60 s  { } speed", "dim")]

    def footer(self, app, width: int) -> Row:
        if app.mode == "filter":
            return [(f" filter: {app.filter_edit}", "magenta"), ("  Enter applies, Esc clears", "dim")]
        if app.mode == "palette":
            hint = app.palette_hint()
            return [(f" :{app.palette_edit}", "magenta"), (f"   {hint}" if hint else "", "dim")]
        if app.message:
            return [(cut(app.message, width - 1, self.g.ascii), "yellow")]
        k = app.keys_help
        if app.sel_anchor is not None:
            a, b = sorted((app.sel_anchor, app.sel_end))
            return [(f" selecting rows {a + 1}-{b + 1} ({b - a + 1} lines)   {k('yank')} copy  {k('up')}/{k('down')} extend  {k('visual_all')} all  Esc cancel", "magenta")]
        # Keep help and quit discoverable even when the page has many shortcuts.
        primary = {
            "jobs": f"{k('up')}/{k('down')} select  {k('mark')} mark  {k('details')} details  {k('log')} log  {k('filter')} filter",
            "history": f"{k('up')}/{k('down')} select  {k('details')} series  {k('sort')} sort  {k('filter')} filter",
            "log": f"{k('up')}/{k('down')} scroll  {k('follow')} follow  {k('filter')} search  {k('wrap')} wrap  {k('stderr')} stderr",
            "sources": f"{k('up')}/{k('down')} select  {k('source_toggle')} toggle  {k('refresh')} refresh",
            "analytics": f"{k('view_prev')}/{k('view_next')} view  {k('up')}/{k('down')} job  {k('days_more')}/{k('days_less')} days",
            "research": f"{k('view_prev')}/{k('view_next')} view  {k('up')}/{k('down')} job/cohort  PgUp/PgDn scroll  Enter tasks",
            "nodes": f"{k('view_prev')}/{k('view_next')} view  {k('sort')} sort  {k('refresh')} refresh",
            "group": f"{k('up')}/{k('down')} select  {k('sort')} sort  {k('filter')} filter",
            "deps": f"{k('up')}/{k('down')} select  {k('details')} details  {k('cancel')} cancel chain  {k('hold')} hold/release",
        }.get(app.tab, f"{k('next_tab')} next tab  {k('refresh')} refresh")
        common = f"{k('help')} help  {k('quit')} quit"
        if width >= 110:
            common = f"{k('palette')} commands  " + common
        available = max(0, width - vlen(common) - 3)
        return [(" " + pad(cut(primary, available, self.g.ascii), available), "dim"),
                ("  " + common, "cyan")]

    # ---- jobs tab ---------------------------------------------------------------------------------
    def flags_of(self, j: Job, lv, g, snap) -> Tuple[str, str]:
        flags, style = [], ""
        if j.pending:
            if j.held:
                flags.append("held"); style = "yellow"
            if j.dependency:
                flags.append("dep")
            return " ".join(flags), style
        old = (j.elapsed_s or 0) > 60 * self.th["warn_after_minutes"]
        if old and lv and lv.avg is not None and lv.avg < self.th["cpu"]:
            flags.append("!cpu"); style = "red"
        if old and lv and lv.rss is not None and j.mem_bytes and lv.rss / j.mem_bytes < self.th["mem"]:
            flags.append("!mem"); style = style or "yellow"
        if old and j.gpus and g:
            key = f"{j.id}:{g[0].node}:{g[0].index}"
            mean = snap.get("gpu_mean", {}).get(key)
            if mean is not None and mean / 100 < self.th["gpu"]:
                flags.append("!gpu"); style = "red"
        if j.limit_s and j.elapsed_s and j.limit_s - j.elapsed_s < 600:
            flags.append("ending"); style = style or "yellow"
        return " ".join(flags), style

    def plugin_flags(self, j: Job, snap: dict, app) -> List[Tuple[str, str]]:
        out = []
        for fn, st in (self.plugins.flags if self.plugins else []):
            try:
                text = fn(j, snap, app)
            except Exception:
                continue
            if text:
                out.append((str(text), st))
        return out

    def job_rows(self, snap: dict, app, actions=None) -> List[dict]:
        live, gpu = snap["live"], snap["gpu"]
        rows = []
        for j in snap["jobs"]:
            lv = live.get(j.id)
            g = gpu.get(j.id) or []
            mark = actions.mark(j) if actions else ""
            flags, fstyle = self.flags_of(j, lv, g, snap)
            for text, st in self.plugin_flags(j, snap, app):
                flags = (flags + " " + text).strip()
                fstyle = fstyle or st
            styles = {"flags": fstyle} if fstyle else {}
            if j.pending:
                info = j.reason
                if j.est_start not in ("N/A", "", "Unknown"):
                    info += f" {self.g.dot} est {when(j.est_start)}"
                info += f" {self.g.dot} prio {j.priority}"
                sub = stamp(j.submit)
                left = compact(clock.now() - sub) if sub else ""
                row = dict(job=j, id=j.id, name=j.name, part=j.partition, st="PD", where=f"{j.nodes} node{'s' if j.nodes != 1 else ''}", cpus=j.cpus, gpu=j.gpu_text,
                           time=f"-/{j.limit}", left=f"waited {left}" if left else "", info=info, flags=flags, _style="dim", _styles=styles,
                           **{"cpu%": "", "eff": "", "mem%": "", "gpu%": ""})
            else:
                gutil = (sum(s.util for s in g) / len(g)) if g else None
                shown = (lv.rate if lv.rate is not None else lv.avg) if lv else None
                st = {"RUNNING": "R", "COMPLETING": "CG", "CONFIGURING": "CF", "SUSPENDED": "S"}.get(j.state, j.state[:2])
                info = f"started {when(j.start)}"
                if j.state != "RUNNING":
                    info += f" {self.g.dot} {j.state.lower()}"
                left = compact(j.limit_s - j.elapsed_s) if (j.limit_s and j.elapsed_s is not None) else ""
                row = dict(job=j, id=j.id, name=j.name, part=j.partition, st=st, where=j.nodelist, cpus=j.cpus, gpu=j.gpu_text, time=f"{j.elapsed}/{j.limit}", left=left,
                           info=info, flags=flags, _style="", _styles=styles,
                           **{"cpu%": "" if shown is None else f"{100 * shown:.0f}", "eff": "" if (not lv or lv.avg is None) else f"{100 * lv.avg:.1f}",
                              "mem%": "" if (not lv or lv.rss is None or not j.mem_bytes) else f"{round(100 * lv.rss / j.mem_bytes)}",
                              "gpu%": "" if gutil is None else f"{gutil:.0f}"})
            if mark:
                row["info"] += f" {self.g.dot} {mark.upper()}"
                row["_style"] = "yellow"
            rec = snap.get("tags", {}).get(j.id, {})
            row["tags"] = " ".join(rec.get("tags", []))
            row["pinned"] = bool(rec.get("pinned"))
            if row["pinned"]:
                row["id"] = (self.g.pin if hasattr(self.g, "pin") else "^") + j.id
            if rec.get("note"):
                row["info"] += f" {self.g.dot} {rec['note']}"
            rows.append(row)
        key, rev = app.sort.get("jobs", "state"), app.reverse.get("jobs", False)
        if key == "name":
            rows.sort(key=lambda r: (r["name"], r["id"]), reverse=rev)
        elif key == "id":
            rows.sort(key=lambda r: r["id"], reverse=rev)
        elif key == "time":
            rows.sort(key=lambda r: -(r["job"].elapsed_s or -1), reverse=rev)
        elif key == "priority":
            rows.sort(key=lambda r: -r["job"].priority, reverse=rev)
        else:
            rows.sort(key=lambda r: (r["job"].pending, -r["job"].priority if r["job"].pending else r["job"].start), reverse=rev)
        rows.sort(key=lambda r: not r["pinned"])             # pinned first (a stable sort keeps the order within each group)
        for r in rows:
            r["id"] = r["job"].id                                # the pin glyph goes into the mark column, not the id
        flt = app.filter.lower()
        if flt:
            if flt.startswith("#"):
                rows = [r for r in rows if flt[1:] in r["tags"].lower().split()]
            else:
                rows = [r for r in rows if flt in r["name"].lower() or flt in r["id"].lower() or flt in r["part"].lower() or flt in r["info"].lower() or flt in r["tags"].lower()]
        return rows

    def selected_panel(self, snap: dict, j: Optional[Job], width: int, log_lines: int, app) -> List[Row]:
        if j is None:
            return []
        g_ = self.g
        kv = snap["details"].get(j.id, {})
        bw = max(12, min(30, width - 78))
        rows: List[Row] = []
        if j.pending:
            sub = stamp(j.submit)
            waited = short_duration(clock.now() - sub) if sub else "?"
            rows.append([(f" {j.id} ", "cyan"), (j.name, "bold"), (f"   pending on {j.partition} {g_.dot} submitted {when(j.submit)} {g_.dot} waited {waited} {g_.dot} priority {j.priority} {g_.dot} {j.account or ''} {j.qos or ''}", "")])
            est = when(j.est_start) if j.est_start not in ("N/A", "", "Unknown") else "not projected yet"
            asks = f"{j.nodes} node(s), {j.cpus} cpus" + (f", {j.gpu_text}" if j.gpus else "") + f", mem {j.mem_req}, limit {j.limit}"
            rows.append([(f"   reason {j.reason} {g_.dot} projected start {est} {g_.dot} asks {asks}", "")])
            if j.dependency:
                graph = DepGraph(snap["jobs"], {f.id: f"{f.name} {f.state.lower()}" for f in snap["finished"]})
                blocked = graph.blocked_by(j.id)
                rows.append([(f"   waits for {', '.join(blocked) if blocked else j.dependency}", "yellow")])
                down = graph.downstream(j.id)
                if down:
                    rows.append([(f"   and {len(down)} job{'s' if len(down) != 1 else ''} wait for it: " + " ".join(f"{d}({snap_name(snap, d) or '?'})" for d in down[:6]), "dim")])
            if kv.get("Command"):
                rows.append([(f"   command {cut(kv['Command'], width - 12, g_.ascii)}", "dim")])
            rows += self.tag_rows(snap, j.id)
            return rows
        el, lim = j.elapsed_s, j.limit_s
        tfrac = None if el is None or not lim else el / lim
        rows.append([(f" {j.id} ", "cyan"), (j.name, "bold"),
                     (f"   started {when(j.start)} {g_.dot} submitted {when(j.submit)} {g_.dot} {j.partition} {g_.dot} {j.nodelist} {g_.dot} {j.cpus} cpus" + (f" {g_.dot} {j.gpu_text}" if j.gpus else "")
                      + f" {g_.dot} mem {j.mem_req} {g_.dot} {j.account or ''} {j.qos or ''}", "")])
        lv = snap["live"].get(j.id)
        if not g_.ascii and width >= 104:
            rows += self.resource_cards(snap, j, width)
        else:
            b = bar(g_, tfrac, 10)
            left = "?" if (el is None or lim is None) else hms(max(0, lim - el))
            time_pct = "n/a" if tfrac is None else f"{round(100 * tfrac)}%"
            rows.append([("   time  ", ""), b, (f" {time_pct:>4}  {j.elapsed or '?'} of {j.limit or '?'}, {left} left, ends {when(j.end)}", "")])
            hist = snap["hist_cpu"].get(j.id, [])
            if not lv:
                rows.append([("   cpu   ", ""), bar(g_, None, bw), ("  n/a (sstat has no batch step yet)", "dim")])
            elif lv.rate is None and lv.avg is None:
                rows.append([("   cpu   ", ""), bar(g_, None, bw), ("  n/a (waiting for CPU utilisation samples)", "dim")])
            else:
                shown = lv.rate if lv.rate is not None else lv.avg
                tag = "now" if lv.rate is not None else "avg"
                efficiency = "n/a" if lv.avg is None else f"{100 * lv.avg:.1f}%"
                rows.append([("   cpu   ", ""), bar(g_, shown, bw), (f" {int(100 * shown):>3}% {tag}  eff {efficiency:>6}  ", ""), (spark(g_, hist), "cyan"),
                             (f"  {shown * j.cpus:.1f}/{j.cpus} cores, {hms(lv.cpu_time)} cpu time", "")])
            req = j.mem_bytes
            if lv and lv.rss is not None and req:
                rows.append([("   mem   ", ""), bar(g_, lv.rss / req, bw), (f" {round(100 * lv.rss / req):>3}%  {human(lv.rss)} of {human(req)} requested", "")])
            elif lv and lv.rss is not None:
                rows.append([("   mem   ", ""), bar(g_, None, bw), (f"  {human(lv.rss)} used (request unknown)", "")])
        if j.gpus:
            g = snap["gpu"].get(j.id, [])
            if g is None:
                rows.append([("   gpu   ", ""), bar(g_, None, bw), ("  n/a (nvidia-smi unreachable: srun --overlap and ssh both failed)", "dim")])
            elif not g:
                rows.append([("   gpu   ", ""), bar(g_, None, bw), ("  sampling ..." if app.gpu else "  sampling off", "dim")])
            else:
                for x in g:
                    key = f"{j.id}:{x.node}:{x.index}"
                    mean = snap["gpu_mean"].get(key)
                    tag = f"gpu{x.index}" + (f"@{x.node}" if j.nodes > 1 else "")
                    rows.append([(f"   {tag:<6}", ""), bar(g_, x.util / 100, bw), (f" {int(x.util):>3}%  mem ", ""), bar(g_, x.used / x.total, 8), (f" {x.used / 1024:.1f}/{x.total / 1024:.0f} GB  ", ""),
                                 (spark(g_, snap["hist_gpu"].get(key, [])), "cyan"), (f"  mean {'?' if mean is None else f'{mean:.0f}%'}  {x.name}", "dim")])
        trace = snap.get("trace", {}).get(j.id)
        if trace:
            rows.append(self.trace_row(trace, j, bw))
        for n, info in snap["nodes"].items():
            if n in j.hosts:
                load = f"{info.load:.1f}" if info.load is not None else "unknown"
                memory = f"{info.mem_free / 1024:.0f} of {info.mem_total / 1024:.0f} GB free" if info.mem_free is not None and info.mem_total else "free memory unknown"
                rows.append([(f"   node {n}: load {load} of {info.cpus} cores ({info.alloc} allocated), {memory}, {info.state}", "dim")])
        steps = [st for st in snap.get("steps", {}).get(j.id, []) if st.name not in ("extern",)]
        if len(steps) > 1 or (steps and steps[0].ntasks > 1):
            for st in steps[:4]:
                rows.append(self.step_row(st, j))
        old = (j.elapsed_s or 0) > 60 * self.th["warn_after_minutes"]
        same = any(f.name == j.name for f in snap["finished"])
        if lv and (old or same):
            adv = advisor.advise_running(j, lv, app.store.series_of(j.id), snap["finished"])
            text = adv.summary(g_.dot)
            if text:
                rows.append([("   advice ", "magenta"), (cut(text, width - 12, g_.ascii), "")])
        down = DepGraph(snap["jobs"]).downstream(j.id)
        if down:
            rows.append([(f"   {len(down)} job{'s' if len(down) != 1 else ''} wait for this one: " + " ".join(f"{d}({snap_name(snap, d) or '?'})" for d in down[:6]), "dim")])
        rows += self.tag_rows(snap, j.id)
        if log_lines > 0:
            path = stdout_path(j, kv, self.files)
            lines = tail_lines(path, log_lines, files=self.files)
            rows.append([(f"   log {cut(path or '(stdout path not known yet)', width - 10, g_.ascii)}", "magenta")])
            for l in lines:
                rows.append([("     " + cut(l, width - 6, g_.ascii), "")])
            if path and not lines:
                rows.append([("     (empty)", "dim")])
        return rows

    def tag_rows(self, snap: dict, jid: str) -> List[Row]:
        rec = snap.get("tags", {}).get(jid)
        if not rec:
            return []
        bits = []
        if rec.get("pinned"):
            bits.append("pinned")
        if rec.get("tags"):
            bits.append("tags " + " ".join("#" + t for t in rec["tags"]))
        if rec.get("note"):
            bits.append("note: " + rec["note"])
        return [[("   " + f" {self.g.dot} ".join(bits), "cyan")]] if bits else []

    def trace_row(self, trace: List[dict], j: Job, bw: int) -> Row:
        """One line from the GPU trace the job writes itself: mean utilisation per GPU index over the trace, the last minute."""
        g_ = self.g
        by: Dict[int, List[float]] = {}
        for r in trace:
            by.setdefault(r["index"], []).append(r["util"])
        last_t = trace[-1]["t"]
        last = {r["index"]: r["util"] for r in trace if r["t"] >= last_t - 60}
        means = {i: sum(v) / len(v) for i, v in by.items()}
        span = (trace[-1]["t"] - trace[0]["t"]) / 60
        idle = sum(1 for r in trace if r["util"] < 10)
        parts = "  ".join(f"gpu{i} {means[i]:.0f}% (now {last.get(i, 0):.0f}%)" for i in sorted(means))
        seg: Row = [("   trace ", ""), bar(g_, (sum(means.values()) / len(means)) / 100 if means else None, bw),
                    (f"  {parts}  {g_.dot} {span:.0f} min in the job's own nvidia-smi log, {100 * idle / max(1, len(trace)):.0f}% of samples idle", "dim")]
        return seg

    def step_row(self, st: Step, j: Job) -> Row:
        """One step of a running job: CPU time, peak memory and where, the slowest rank."""
        g_ = self.g
        text = f"   step {st.name or st.id:<8} {st.ntasks} task{'s' if st.ntasks != 1 else ''}"
        if st.cpu_time is not None:
            text += f" {g_.dot} cpu {hms(st.cpu_time)}"
        if st.rss:
            text += f" {g_.dot} peak {human(st.rss)}" + (f" on task {st.rss_task}@{st.rss_node}" if st.ntasks > 1 and st.rss_node else "")
        style = "dim"
        if st.ntasks > 1 and st.min_cpu is not None and st.cpu_time:
            ratio = st.min_cpu / st.cpu_time if st.cpu_time else 1.0
            text += f" {g_.dot} slowest rank {st.min_cpu_task}@{st.min_cpu_node} at {100 * ratio:.0f}% of the mean"
            if ratio < 0.6:
                style = "yellow"
        return [(text, style)]

    def jobs_tab(self, snap: dict, app, actions, width: int, height: Optional[int]) -> Tuple[List[Row], List[Tuple[int, str, str]]]:
        rows_d = self.job_rows(snap, app, actions)
        app.visible_ids = [r["id"] for r in rows_d]
        n = len(rows_d)
        cur = app.clamp_cursor("jobs", n)
        app.selected_id = rows_d[cur]["id"] if n else None
        sel = rows_d[cur]["job"] if n else None
        det = self.selected_panel(snap, sel, width, app.log_lines, app)
        fin = snap["finished"][:5]
        events = [e for e in snap["events"] if not e.get("old")][-4:] or snap["events"][-4:]
        if height is None:
            trows, _ = table(JOB_COLS, rows_d, width, self.g.ascii, droppable=JOB_DROP, cursor=None, marks=(), mark_char=None)
            out = [rule(self.g, width, "jobs")] + trows
            if not rows_d:
                out.append([("   no jobs match the filter; Esc clears it" if app.filter else "   Your queue is clear. New jobs appear here automatically.", "dim")])
            if det:
                out += [rule(self.g, width, "selected")] + det
            out += self.finished_rows(fin, width, "recent")
            out += self.event_rows(events, width)
            return out, []
        budget = height
        table_h = min(n + 1, max(4, budget // 3)) if n else 2
        det_h = len(det) + 1 if det else 0
        fin_h = len(fin) + 2 if fin else 0
        ev_h = len(events) + 1 if events else 0
        while table_h + det_h + fin_h + ev_h > budget and (ev_h or fin_h or det_h > 3 or table_h > 2):
            if ev_h:
                events = events[:-1]; ev_h = len(events) + 1 if events else 0
            elif fin_h:
                fin = fin[:-1]; fin_h = len(fin) + 2 if fin else 0
            elif det_h > 3:
                det = det[:-1]; det_h = len(det) + 1
            else:
                table_h -= 1
        spare = budget - (table_h + det_h + fin_h + ev_h)
        if spare > 0 and n + 1 > table_h:
            table_h = min(n + 1, table_h + spare)
        vis = max(1, table_h - 1)
        top = app.scroll_to("jobs", cur, vis, n)
        shown = rows_d[top:top + vis]
        marks = {i for i, r in enumerate(shown) if r["id"] in app.marks}
        for r in shown:
            r["_mark"] = self.g.pin if r.get("pinned") else ""
        trows, _ = table(JOB_COLS, shown, width, self.g.ascii, droppable=JOB_DROP, cursor=cur - top, marks=marks, mark_char=self.g.mark)
        title = f"jobs {top + 1}-{min(n, top + vis)} of {n}" if n > vis else "jobs"
        out = [rule(self.g, width, title)] + trows
        hits = [(1 + i + 1, "job", r["id"]) for i, r in enumerate(shown)]      # rule + header offset
        if not rows_d:
            out.append([("   no jobs match the filter; Esc clears it" if app.filter else "   Your queue is clear. New jobs appear here automatically.", "dim")])
        if det:
            out += [rule(self.g, width, "selected")] + det
        out += self.finished_rows(fin, width, "recent")
        out += self.event_rows(events, width)
        return out, hits

    # ---- history tab ------------------------------------------------------------------------------
    FIN_COLS = [Column("id", "JOBID", 5, 16), Column("name", "NAME", 8, 30, flex=True), Column("state", "STATE", 5, 14), Column("part", "PART", 4, 9),
                Column("elapsed", "ELAPSED", 7, 12, ">"), Column("cpus", "CPU", 3, 4, ">"), Column("gpus", "GPU", 3, 3, ">"), Column("ce", "CPU EFF", 7, 7, ">"),
                Column("me", "MEM EFF", 7, 7, ">"), Column("rss", "PEAK MEM", 8, 10, ">"), Column("start", "STARTED", 5, 12), Column("end", "ENDED", 5, 12),
                Column("exit", "EXIT", 4, 6), Column("nodes", "NODES", 5, 16, flex=True), Column("tags", "TAGS", 4, 14)]

    def finished_rows(self, fin: Sequence[Finished], width: int, title: str, cursor: Optional[int] = None) -> List[Row]:
        if not fin:
            return []
        data = [self.finished_dict(f) for f in fin]
        rows, _ = table(self.FIN_COLS, data, width, self.g.ascii, indent="   ", droppable=("tags", "nodes", "exit", "start", "gpus", "part", "rss"), cursor=cursor)
        return [rule(self.g, width, title)] + rows

    def finished_dict(self, f: Finished) -> dict:
        ok = f.state == "COMPLETED"
        style = "green" if ok else ("yellow" if f.state.startswith("CANCEL") else "red")
        ce, me = f.cpu_eff, f.mem_eff
        return dict(fin=f, id=f.id, name=f.name, state=f.state, part=f.partition, elapsed=f.elapsed, cpus=f.cpus, gpus=f.gpus or "", ce="n/a" if ce is None else f"{100 * ce:.0f}%",
                    me="n/a" if me is None else f"{100 * me:.0f}%", rss=human(f.rss) if f.rss else "", start=when(f.start), end=when(f.end), exit=f.exit, nodes=f.nodelist,
                    tags=" ".join(self.cfg_tags.get(f.id, {}).get("tags", [])) if hasattr(self, "cfg_tags") else "",
                    _styles={"state": style, "ce": ("red" if ce is not None and ce < self.th["cpu"] else ""), "me": ("yellow" if me is not None and me < self.th["mem"] else "")})

    def history_tab(self, snap: dict, app, width: int, height: Optional[int]) -> Tuple[List[Row], List[Tuple[int, str, str]]]:
        self.cfg_tags = snap.get("tags", {})
        fin = list(snap["finished"])
        key, rev = app.sort.get("history", "end"), app.reverse.get("history", False)
        keyfn = {"end": lambda f: f.end, "name": lambda f: (f.name, f.end), "state": lambda f: (f.state, f.end), "elapsed": lambda f: secs(f.elapsed) or 0,
                 "cpu_eff": lambda f: -1 if f.cpu_eff is None else f.cpu_eff, "mem_eff": lambda f: -1 if f.mem_eff is None else f.mem_eff}[key]
        fin.sort(key=keyfn, reverse=(key == "end") != rev)
        flt = app.filter.lower()
        if flt and flt.startswith("#"):
            fin = [f for f in fin if flt[1:] in [t.lower() for t in self.cfg_tags.get(f.id, {}).get("tags", [])]]
        elif flt:
            fin = [f for f in fin if flt in f.name.lower() or flt in f.id.lower() or flt in f.state.lower() or flt in f.partition.lower()]
        n = len(fin)
        cur = app.clamp_cursor("history", n)
        counts: Dict[str, int] = {}
        for f in fin:
            counts[f.state] = counts.get(f.state, 0) + 1
        core_h = sum(f.core_hours for f in fin)
        gpu_h = sum(f.gpu_hours for f in fin)
        effs = [f.cpu_eff for f in fin if f.cpu_eff is not None]
        summary: Row = [(f" last {self.cfg['history_days']:g} days: {n} jobs  ", "bold")]
        for st, c in sorted(counts.items(), key=lambda kv: -kv[1]):
            summary.append((f"{st.lower()} {c}  ", "green" if st == "COMPLETED" else ("yellow" if st.startswith("CANCEL") else "red")))
        summary.append((f"{self.g.dot} {core_h:.1f} core-hours {self.g.dot} {gpu_h:.1f} gpu-hours" + (f" {self.g.dot} mean cpu eff {100 * sum(effs) / len(effs):.0f}%" if effs else "") + f" {self.g.dot} sorted by {key}{' (reversed)' if rev else ''}", "dim"))
        prefix = [summary]
        if self.visual_room(width, height):
            prefix += self.composition([(state.lower(), count, "green" if state == "COMPLETED" else "yellow" if state.startswith("CANCEL") else "red")
                                        for state, count in sorted(counts.items(), key=lambda pair: -pair[1])], width)
        if height is None:
            rows = self.finished_rows(fin, width, "history")
            return prefix + rows, []
        vis = max(1, height - len(prefix) - 2)
        top = app.scroll_to("history", cur, vis, n)
        shown = fin[top:top + vis]
        data = [self.finished_dict(f) for f in shown]
        trows, _ = table(self.FIN_COLS, data, width, self.g.ascii, droppable=("tags", "nodes", "exit", "start", "gpus", "part", "rss"), cursor=cur - top)
        title = f"history {top + 1}-{min(n, top + vis)} of {n}" if n > vis else "history"
        out = prefix + [rule(self.g, width, title)] + trows
        if not fin:
            out.append([("   nothing matches the filter; Esc clears it" if app.filter else "   No completed runs yet. Finished jobs and efficiency appear here.", "dim")])
        hits = [(len(prefix) + 2 + i, "fin", f.id) for i, f in enumerate(shown)]
        return out, hits

    # ---- cluster tab ------------------------------------------------------------------------------
    def cluster_tab(self, snap: dict, app, width: int, height: Optional[int]) -> Tuple[List[Row], List]:
        parts = list(snap["partitions"])
        want = set(self.cfg["partitions"]) or None
        mine = {j.partition for j in snap["jobs"]}
        if want is None:
            parts = [p for p in parts if p.gpus or p.name in mine]
        else:
            parts = [p for p in parts if p.name in want]
        rows = []
        for p in parts:
            na = p.nodes_aiot.split("/") if p.nodes_aiot else ["", "", "", ""]
            ca = p.cpus_aiot.split("/") if p.cpus_aiot else ["", "", "", ""]
            gp = "  ".join(f"{t} {v['free']}/{v['total'] - v['down']}" + (f" ({v['down']} down)" if v["down"] else "") for t, v in sorted(p.gpus.items()))
            rows.append(dict(name=p.name, avail=p.avail, limit=p.limit, nodes=p.nodes, nidle=na[1] if len(na) > 1 else "", nalloc=na[0], nother=na[2] if len(na) > 2 else "",
                             cidle=ca[1] if len(ca) > 1 else "", calloc=ca[0], gpus=gp, mine=sum(1 for j in snap["jobs"] if j.partition == p.name and not j.pending),
                             minep=sum(1 for j in snap["jobs"] if j.partition == p.name and j.pending),
                             _styles={"avail": "green" if p.avail == "up" else "red"}))
        cols = [Column("name", "PARTITION", 6, 14), Column("avail", "AVAIL", 4, 6), Column("limit", "LIMIT", 5, 12), Column("nodes", "NODES", 5, 6, ">"),
                Column("nidle", "IDLE", 4, 6, ">"), Column("nalloc", "ALLOC", 5, 6, ">"), Column("nother", "OTHER", 5, 6, ">"), Column("cidle", "CPUS IDLE", 9, 10, ">"),
                Column("calloc", "CPUS ALLOC", 10, 11, ">"), Column("mine", "MY RUN", 6, 6, ">"), Column("minep", "MY PEND", 7, 7, ">"), Column("gpus", "GPUS FREE/UP", 12, 60, flex=True)]
        trows, _ = table(cols, rows, width, self.g.ascii, droppable=("nother", "calloc", "cidle", "limit"))
        out = [rule(self.g, width, "partitions")] + trows
        if not rows:
            out.append([("   Waiting for partition data. Open Sources to check sinfo or refresh with r.", "dim")])
        inv = snap["gpu_inventory"]
        if inv:
            out.append(rule(self.g, width, "GPUs cluster-wide (each node once)"))
            for t, v in sorted(inv.items()):
                up = v["total"] - v["down"]
                frac = v["used"] / up if up else 0
                if self.visual_room(width, height, minimum=22):
                    out.append([(f"   {t.upper():<8}", "bold"), (f"{v['total']} installed  ·  {up} available  ·  {v['used']} allocated", "dim")])
                    out += self.composition([("free", v["free"], "green"), ("allocated", v["used"], "cyan"), ("down / drained", v["down"], "red")], width)
                else:
                    out.append([(f"   {t:<6} ", "bold"), bar(self.g, frac, 24), (f"  {v['used']}/{up} in use, {v['free']} free" + (f", {v['down']} down or drained" if v["down"] else ""), "")])
        sh = snap["share"]
        if sh:
            out.append(rule(self.g, width, "fair share"))
            for s in sh[:4]:
                out.append([(f"   {s['account']:<16} fair share {s['fairshare']}  effective usage {s['usage']}", "")])
        acc = snap["account"]
        if acc:
            out.append([(f"   {acc['account']} right now: {acc['running']} running jobs using {acc['cpus']} cpus and {acc['gpus']} gpus, {acc['pending']} pending (everyone in the account)", "dim")])
        out += self.weather_rows(snap, width)
        out += self.budget_rows(snap, width)
        return out, []

    def weather_rows(self, snap: dict, width: int) -> List[Row]:
        """Queue weather: pending work ahead per partition cluster-wide and what sbatch --test-only projects for typical jobs."""
        g = self.g
        ahead, probes = snap.get("pending_ahead", {}), snap.get("weather", [])
        if not ahead and not probes:
            return []
        out: List[Row] = [rule(g, width, "queue weather (pending work ahead of a new job, and when a typical job would start)")]
        parts = [p.name for p in snap["partitions"]] or sorted(ahead)
        shown = [p for p in parts if p in ahead] + [p for p in sorted(ahead) if p not in parts]
        for p in shown[:8]:
            a = ahead[p]
            by = "  ".join(f"{t} {n}" for t, n in sorted(a["by_type"].items()))
            inv = next((x.gpus for x in snap["partitions"] if x.name == p), {})
            free = "  ".join(f"{t} {v['free']} free" for t, v in sorted(inv.items()))
            idle = next((x.nodes_aiot.split("/")[1] for x in snap["partitions"] if x.name == p and x.nodes_aiot.count("/") == 3), "")
            heavy = a["jobs"] >= 20 or (a["gpus"] and not any(v["free"] for v in inv.values()))
            out.append([(f"   {p:<10}", "bold"), (f"{a['jobs']:>4} pending jobs asking {a['cpus']} cpus" + (f", {a['gpus']} gpus ({by})" if a["gpus"] else ""), "yellow" if heavy else ""),
                        (f"   {g.dot} idle nodes {idle}" if idle else "", "dim"), (f"   {g.dot} {free}" if free else "", "dim")])
        now = clock.now()
        for pr in probes:
            what = f"{pr['cpus']} cpus, {pr['mem']}" + (f", {pr['gres']}" if pr["gres"] else "") + f", {pr['limit']}"
            if pr.get("ok") and pr.get("est"):
                t = stamp(pr["est"])
                wait = (t - now) if t else None
                soon = wait is not None and wait < 300
                text = f"would start {'now' if soon else 'in ' + compact(wait) + ' (' + when(pr['est']) + ')' if wait is not None else when(pr['est'])}" + (f" on {pr['nodes']}" if pr.get("nodes") else "")
                style = "green" if soon else ("yellow" if wait is not None and wait > 3600 else "")
            else:
                text, style = f"no projection: {cut(pr.get('text', ''), 70, g.ascii)}", "red"
            out.append([(f"   {pr['partition']:<10}", ""), (f"a job of {what} ", "dim"), (text, style)])
        return out

    def budget_rows(self, snap: dict, width: int) -> List[Row]:
        """The account's allocation: used this month against the limit, the burn rate of the last 7 days, the month-end projection."""
        g = self.g
        b = snap.get("budget", {})
        if not b:
            return []
        out: List[Row] = [rule(g, width, f"allocation of {b['account']} since {b['month']} (sreport; limits from sacctmgr)")]
        now = clock.now()
        day = int(time.strftime("%d", time.localtime(now)))
        import calendar
        days_in_month = calendar.monthrange(int(time.strftime("%Y", time.localtime(now))), int(time.strftime("%m", time.localtime(now))))[1]
        for k, label in (("cpu", "core-hours"), ("gpu", "gpu-hours")):
            used = b.get("used", {}).get(k, 0.0)
            week = b.get("week", {}).get(k, 0.0)
            lim = b.get("limit", {}).get(k)
            rate = week / 7.0
            proj = used + rate * max(0, days_in_month - day)
            seg: Row = [(f"   {label:<11}", "bold")]
            if lim:
                frac = used / lim
                seg += [bar(g, frac, 24), (f"  {used:,.0f} of {lim:,.0f} ({100 * frac:.0f}%)", "")]
                pf = proj / lim
                seg.append((f"  {g.dot} burning {rate:,.0f}/day, month-end projection {proj:,.0f} ({100 * pf:.0f}%)", "red" if pf > 1.0 else ("yellow" if pf > 0.9 else "dim")))
                if rate > 0 and lim > used:
                    seg.append((f"  {g.dot} exhausted in {(lim - used) / rate:.0f} days at this rate", "dim"))
            else:
                seg += [(f"{used:,.0f} used this month", ""), (f"  {g.dot} {rate:,.0f}/day over the last 7 days (no limit set)", "dim")]
            out.append(seg)
        users = b.get("by_user", {})
        if users:
            tops = sorted(users.items(), key=lambda kv: -(kv[1].get("cpu", 0) + 10 * kv[1].get("gpu", 0)))[:6]
            out.append([("   by user   ", "bold"), ("  ".join(f"{u} {v.get('cpu', 0):,.0f} cpu-h / {v.get('gpu', 0):,.0f} gpu-h" for u, v in tops), "dim")])
        return out

    # ---- nodes tab --------------------------------------------------------------------------------
    def nodes_tab(self, snap: dict, app, width: int, height: Optional[int]) -> Tuple[List[Row], List]:
        bar_: Row = [(" ", "")]
        for key, title in NODES_VIEWS:
            bar_.append((f" {title} ", "rev+bold" if key == app.nodes_view else "dim"))
            bar_.append((" ", ""))
        if app.nodes_view == "map":
            rows = self.node_map(snap, app, width, None if height is None else height - 1)
            return [bar_] + rows, []
        rows, hits = self.my_nodes(snap, app, width, height)
        return [bar_] + rows, [(y + 1, k, v) for y, k, v in hits]

    def node_map(self, snap: dict, app, width: int, height: Optional[int]) -> List[Row]:
        """Every node of the cluster as a cell per partition: state glyph, allocated cores, GPUs in use; mine marked."""
        g = self.g
        cells = list(snap.get("nodemap", {}).values())
        if not cells:
            return [rule(g, width, "cluster map"), [("   sinfo -N has not answered yet", "dim")]]
        mine = {h for j in snap["jobs"] if not j.pending for h in j.hosts}
        want = set(self.cfg["partitions"]) or None
        parts: Dict[str, list] = {}
        for c in cells:
            for p in c.partitions:
                if want is None or p in want:
                    parts.setdefault(p, []).append(c)
        order = [p.name for p in snap["partitions"] if p.name in parts] + sorted(p for p in parts if p not in {x.name for x in snap["partitions"]})
        legend: Row = [(" legend  ", "bold"), (g.empty + " idle ", "green"), (g.spark[3] + " mixed ", "yellow"), (g.full + " allocated ", "red"), ("x down/drained ", "magenta"),
                       (f"{g.mark} running one of mine", "cyan"), ("   cell: node  cores used/total  gpus used/total", "dim")]
        out: List[Row] = [legend]
        cell_w = 26
        per_row = max(1, (width - 3) // cell_w)
        for p in order:
            if height is not None and len(out) >= height:
                break
            nodes = sorted(parts[p], key=lambda c: c.name)
            n_idle = sum(1 for c in nodes if c.state.startswith("idle"))
            n_down = sum(1 for c in nodes if c.down)
            n_mine = sum(1 for c in nodes if c.name in mine)
            gp = sum(c.gpus for c in nodes)
            gu = sum(c.gpus_used for c in nodes)
            cores = sum(c.cpus for c in nodes)
            alloc = sum(c.cpus_alloc for c in nodes)
            title = f"{p}: {len(nodes)} node{'s' if len(nodes) != 1 else ''}, {n_idle} idle, {n_down} down/drained, {alloc}/{cores} cores allocated" + (f", {gu}/{gp} gpus in use" if gp else "") + (f", {n_mine} running mine" if n_mine else "")
            out.append(rule(g, width, title))
            for i in range(0, len(nodes), per_row):
                if height is not None and len(out) >= height:
                    break
                row: Row = [("  ", "")]
                capacity: Row = [("  ", "")]
                for c in nodes[i:i + per_row]:
                    if c.down:
                        glyph, style = "x", "magenta"
                    elif c.state.startswith("idle"):
                        glyph, style = g.empty, "green"
                    elif c.state.startswith("alloc") or c.state.startswith("comp"):
                        glyph, style = g.full, "red"
                    else:
                        glyph, style = g.spark[3], "yellow"
                    mark = g.mark if c.name in mine else " "
                    gpu = f" {c.gpus_used}/{c.gpus}g" if c.gpus else ""
                    text = f"{mark}{glyph} {cut(c.name, 9, g.ascii):<9}{c.cpus_alloc:>3}/{c.cpus:<3}{gpu}"
                    row.append((pad(text, cell_w), ("cyan" if c.name in mine else style)))
                    if not g.ascii:
                        frac = c.cpus_alloc / c.cpus if c.cpus else None
                        capacity += [("  ", "")] + gradient_bar(g, frac, 12, "#34d399", "#22d3ee")
                        capacity.append((f" {100 * frac:>3.0f}%  " if frac is not None else "   ?   ", "dim"))
                        capacity += gradient_bar(g, c.gpus_used / c.gpus if c.gpus else None, 4, "#a78bfa", "#ec4899") + [(" ", "")]
                out.append(row)
                if not g.ascii and (height is None or len(out) < height):
                    out.append(capacity)
        if height is not None:
            out = out[:height]
        return out

    def my_nodes(self, snap: dict, app, width: int, height: Optional[int]) -> Tuple[List[Row], List]:
        nodes = list(snap["nodes"].values())
        key, rev = app.sort.get("nodes", "name"), app.reverse.get("nodes", False)
        nodes.sort(key=(lambda n: n.name) if key == "name" else (lambda n: (n.load is None, -(n.load or 0))), reverse=rev)
        by_host: Dict[str, List[Job]] = {}
        for j in snap["jobs"]:
            for h in j.hosts:
                by_host.setdefault(h, []).append(j)
        rows = []
        for nd in nodes:
            jobs = by_host.get(nd.name, [])
            gsamp = []
            for j in jobs:
                for s in snap["gpu"].get(j.id) or []:
                    gsamp.append(s)
            gutil = f"{sum(s.util for s in gsamp) / len(gsamp):.0f}%" if gsamp else ""
            rows.append(dict(name=nd.name, state=nd.state, load=f"{nd.load:.1f}" if nd.load is not None else "n/a", cpus=f"{nd.alloc}/{nd.cpus}", loadpct=f"{100 * nd.load / nd.cpus:.0f}%" if nd.load is not None and nd.cpus else "n/a",
                             mem=f"{(nd.mem_total - nd.mem_free) / 1024:.0f}/{nd.mem_total / 1024:.0f} GB" if nd.mem_free is not None and nd.mem_total and nd.mem_free <= nd.mem_total else "n/a", gres=nd.gres.split("(")[0] if nd.gres and nd.gres != "(null)" else "",
                             gused=nd.gres_used.split("(")[0] if nd.gres_used and nd.gres_used != "(null)" else "", gutil=gutil,
                             jobs=" ".join(f"{j.id}({j.name})" for j in jobs), _styles={"state": "red" if any(k in nd.state.lower() for k in ("drain", "down", "fail")) else ""}))
        cols = [Column("name", "NODE", 6, 16), Column("state", "STATE", 5, 14), Column("cpus", "ALLOC/CPUS", 10, 10, ">"), Column("load", "LOAD", 4, 7, ">"), Column("loadpct", "LOAD%", 5, 5, ">"),
                Column("mem", "MEM USED", 8, 14, ">"), Column("gres", "GRES", 4, 16), Column("gused", "GRES USED", 9, 16), Column("gutil", "GPU%", 4, 4, ">"), Column("jobs", "MY JOBS", 7, 60, flex=True)]
        trows, _ = table(cols, rows, width, self.g.ascii, droppable=("gused", "gres", "loadpct"))
        out = []
        if nodes and self.visual_room(width, height, minimum=22):
            out += self.node_resource_rows(nodes, width)
        out += [rule(self.g, width, "nodes running your jobs")] + trows
        if not rows:
            out.append([("   no running jobs (or scontrol has not answered yet)", "dim")])
        for nd in nodes:
            jobs = by_host.get(nd.name, [])
            for j in jobs:
                for s in snap["gpu"].get(j.id) or []:
                    if s.node == nd.name or s.node.startswith("task"):
                        key = f"{j.id}:{s.node}:{s.index}"
                        mean = snap["gpu_mean"].get(key)
                        out.append([(f"   {nd.name} gpu{s.index} ", ""), bar(self.g, s.util / 100, 20), (f" {int(s.util):>3}%  mem {s.used / 1024:.1f}/{s.total / 1024:.0f} GB  ", ""),
                                    (spark(self.g, snap["hist_gpu"].get(key, []), 20), "cyan"), (f"  mean {'?' if mean is None else f'{mean:.0f}%'}  job {j.id}", "dim")])
        return out, []

    # ---- group tab --------------------------------------------------------------------------------
    GROUP_COLS = [Column("user", "USER", 4, 12), Column("id", "JOBID", 5, 16), Column("name", "NAME", 8, 28, flex=True), Column("part", "PART", 4, 9), Column("st", "ST", 2, 3),
                  Column("where", "NODES", 5, 18, flex=True), Column("cpus", "CPU", 3, 4, ">"), Column("gpu", "GPU", 3, 8), Column("time", "ELAPSED/LIMIT", 8, 20),
                  Column("prio", "PRIO", 4, 7, ">"), Column("info", "INFO", 10, 40, flex=True)]

    def group_tab(self, snap: dict, app, width: int, height: Optional[int]) -> Tuple[List[Row], List]:
        g = self.g
        jobs = list(snap.get("group", []))
        acc = snap.get("account", {})
        out: List[Row] = []
        if not jobs:
            out.append(rule(g, width, "group"))
            out.append([("   squeue -A has not answered yet (or the account is unknown: --account, or [account] in the config)" if not acc else "   nobody in the account has jobs", "dim")])
            return out, []
        # per-user summary
        by_user: Dict[str, dict] = {}
        for j in jobs:
            d = by_user.setdefault(j.user or "?", dict(running=0, pending=0, cpus=0, gpus=0, nodes=0))
            if j.pending:
                d["pending"] += 1
            else:
                d["running"] += 1
                d["cpus"] += j.cpus
                d["gpus"] += j.gpus
                d["nodes"] += j.nodes
        tot_cpu = sum(d["cpus"] for d in by_user.values()) or 1
        out.append(rule(g, width, f"{acc.get('account', 'the account')}: {len(by_user)} users, {sum(d['running'] for d in by_user.values())} running, {sum(d['pending'] for d in by_user.values())} pending"))
        ordered_users = sorted(by_user.items(), key=lambda kv: (-kv[1]["cpus"], kv[0]))
        if self.visual_room(width, height):
            mix = [(u, d["cpus"], "cyan" if u == app.user else "magenta" if i % 2 else "blue") for i, (u, d) in enumerate(ordered_users[:6])]
            if len(ordered_users) > 6:
                mix.append(("other users", sum(d["cpus"] for _, d in ordered_users[6:]), "dim"))
            out += self.composition(mix, width)
        user_limit = len(ordered_users) if height is None else max(1, min(6, (height - len(out) - 5) // 2))
        for u, d in ordered_users[:user_limit]:
            style = "cyan" if u == app.user else ""
            meter = [bar(g, d["cpus"] / tot_cpu, 16)] if g.ascii else gradient_bar(g, d["cpus"] / tot_cpu, 16)
            out.append([(f"   {u:<12}", "bold+" + style if style else "bold")] + meter +
                       [(f"  {d['running']:>3} running on {d['cpus']:>5} cpus" + (f", {d['gpus']} gpus" if d["gpus"] else "") + f", {d['nodes']} nodes   {d['pending']} pending", style)])
        if user_limit < len(ordered_users) and (height is None or height - len(out) >= 5):
            out.append([(f"   {len(ordered_users) - user_limit} more users in the account; the job table includes everyone", "dim")])
        # the table
        rows = []
        for j in jobs:
            st = "PD" if j.pending else {"RUNNING": "R", "COMPLETING": "CG", "CONFIGURING": "CF", "SUSPENDED": "S"}.get(j.state, j.state[:2])
            sub = stamp(j.submit)
            info = (j.reason + (f" {g.dot} waited {compact(clock.now() - sub)}" if sub else "")) if j.pending else f"started {when(j.start) if j.start else ''}".strip()
            rows.append(dict(job=j, user=j.user, id=j.id, name=j.name, part=j.partition, st=st, where=j.nodelist if not j.pending else f"{j.nodes} node{'s' if j.nodes != 1 else ''}",
                             cpus=j.cpus, gpu=j.gpu_text, time=f"{j.elapsed}/{j.limit}" if not j.pending else f"-/{j.limit}", prio=j.priority, info=info,
                             _style="cyan" if j.user == app.user else ("dim" if j.pending else "")))
        key, rev = app.sort.get("group", "user"), app.reverse.get("group", False)
        keyfn = {"user": lambda r: (r["user"], r["job"].pending, r["id"]), "state": lambda r: (r["job"].pending, r["user"], r["id"]), "name": lambda r: (r["name"], r["id"]),
                 "id": lambda r: r["id"], "time": lambda r: -(r["job"].elapsed_s or -1), "priority": lambda r: -r["job"].priority}[key]
        rows.sort(key=keyfn, reverse=rev)
        flt = app.filter.lower()
        if flt:
            rows = [r for r in rows if flt in r["user"].lower() or flt in r["name"].lower() or flt in r["id"].lower() or flt in r["part"].lower()]
        n = len(rows)
        app.group_ids = [r["id"] for r in rows]
        cur = app.clamp_cursor("group", n)
        if n:
            app.selected_id = app.group_ids[cur]
        if height is None:
            trows, _ = table(self.GROUP_COLS, rows, width, g.ascii, droppable=("prio", "part", "gpu", "where", "st"))
            return out + [rule(g, width, "jobs")] + trows, []
        vis = max(1, height - len(out) - 2)
        top = app.scroll_to("group", cur, vis, n)
        shown = rows[top:top + vis]
        trows, _ = table(self.GROUP_COLS, shown, width, g.ascii, droppable=("prio", "part", "gpu", "where", "st"), cursor=cur - top)
        title = f"jobs {top + 1}-{min(n, top + vis)} of {n}" if n > vis else "jobs"
        base = len(out) + 1
        out += [rule(g, width, title + f", sorted by {key}{' (reversed)' if rev else ''}")] + trows
        hits = [(base + 1 + i, "group", r["id"]) for i, r in enumerate(shown)]
        return out, hits

    # ---- deps tab ---------------------------------------------------------------------------------
    def deps_tab(self, snap: dict, app, width: int, height: Optional[int]) -> Tuple[List[Row], List]:
        """Dependency chains as trees; the cursor selects a job, and the actions apply to it and everything downstream."""
        g = self.g
        names = {f.id: f"{f.name} {f.state.lower()}" for f in snap["finished"]}
        graph = DepGraph(snap["jobs"], names)
        jobs = graph.jobs
        trees = graph.trees()
        out: List[Row] = [rule(g, width, f"dependency chains: {len(graph.edges)} edges among {len(graph.related())} jobs (c cancels a job and everything downstream, h releases a held chain)")]
        if self.visual_room(width, height) and trees:
            related = [jobs[jid] for jid in graph.related() if jid in jobs]
            held = sum(j.held for j in related)
            out += self.composition([("running", sum(not j.pending for j in related), "green"),
                                     ("waiting", sum(j.pending for j in related) - held, "yellow"),
                                     ("held", held, "magenta")], width)
        prefix_length = len(out)
        app.dep_ids = []
        if not trees:
            out.append([("   no job depends on another (the Dependency field of squeue is empty for all of yours)", "dim")])
        hits = []
        cur = app.clamp_cursor("deps", sum(len(t) for t in trees))
        k = 0
        for tree in trees:
            for depth, kind, jid in tree:
                j = jobs.get(jid)
                if j is None:
                    desc, style = names.get(jid, "no longer in the queue"), "dim"
                elif j.pending:
                    desc = f"pending ({j.reason})" + (f" {g.dot} est {when(j.est_start)}" if j.est_start not in ("N/A", "", "Unknown") else "")
                    style = "yellow" if j.held or j.reason == "Dependency" else ""
                else:
                    desc, style = f"{j.state.lower()} {j.elapsed} of {j.limit} on {j.nodelist}", "green" if j.state == "RUNNING" else ""
                name = j.name if j else ""
                branch = ("" if depth == 0 else "   " * (depth - 1) + ("  " + (g.box[2] if not g.ascii else "+") + (g.box[4] if not g.ascii else "-") + " "))
                kind_t = (kind + " " + (g.arrow + " ") if kind else "")
                row: Row = [("   " + branch, "dim"), (kind_t, "magenta"), (f"{jid} ", "cyan"), (pad(cut(name, 20, g.ascii), 20), "bold"), ("  " + desc, style)]
                if jid in app.marks:
                    row.insert(0, (g.mark, "magenta"))
                if k == cur and height is not None:
                    row = [(t, "rev") for t, _ in row]
                out.append(row)
                hits.append((len(out) - 1, "dep", jid))
                app.dep_ids.append(jid)
                k += 1
            out.append([("", "")])
        if app.dep_ids and cur < len(app.dep_ids):
            sel = app.dep_ids[cur]
            app.selected_id = sel
            down, up = graph.downstream(sel), graph.upstream(sel)
            out.append([(f"   selected {sel}: {len(up)} upstream, {len(down)} downstream" + (f" ({', '.join(down[:8])})" if down else ""), "dim")])
            j = jobs.get(sel)
            if j and j.pending:
                out.append([("   waits for " + ", ".join(graph.blocked_by(sel)), "yellow")])
        others = [j for j in snap["jobs"] if j.id not in graph.related()]
        if others:
            out.append(rule(g, width, f"{len(others)} independent jobs"))
            out.append([("   " + cut("  ".join(f"{j.id}({j.name})" for j in others), width - 4, g.ascii), "dim")])
        if height is not None:
            # Keep the selected dependency visible while retaining its position in the
            # full graph for keyboard actions and chain confirmations.
            visible = max(1, height - prefix_length)
            selected_row = hits[cur][0] - prefix_length if hits else 0
            top = app.scroll_to("deps", selected_row, visible, max(0, len(out) - prefix_length))
            out = out[:prefix_length] + out[prefix_length + top:prefix_length + top + visible]
            hits = [(y - top, kind, key) for y, kind, key in hits if prefix_length + top <= y < prefix_length + top + visible]
        return out, hits

    # ---- log tab ----------------------------------------------------------------------------------
    def log_candidates(self, app, j: Job, kv: dict) -> List[str]:
        """The other files of the job's log directory that carry its id: array tasks, step outputs, the GPU trace."""
        import time as _t
        cache = app.logs.candidates.get(j.id)
        if cache and _t.time() - cache[0] < 30:
            return cache[1]
        base = stdout_path(j, kv, self.files) or stdout_path(j, kv, self.files, "StdErr")
        out: List[str] = []
        if base:
            d = os.path.dirname(base)
            root = j.id.split("_")[0]
            try:
                names = self.files.listdir(d)
            except OSError:
                names = []
            out = sorted(os.path.join(d, n) for n in names if root in n and os.path.join(d, n) not in (stdout_path(j, kv, self.files), stdout_path(j, kv, self.files, "StdErr")))
        app.logs.candidates[j.id] = (_t.time(), out)
        return out

    def log_path(self, app, j: Job, kv: dict) -> Tuple[str, str]:
        """(the file the Log tab shows, a label): stdout, stderr, or one of the other files."""
        cands = self.log_candidates(app, j, kv)
        if app.logs.file_index > 0 and cands:
            i = (app.logs.file_index - 1) % len(cands)
            return cands[i], f"file {i + 2}/{len(cands) + 1}"
        app.logs.file_index = 0
        if app.logs.which == "err":
            err = stdout_path(j, kv, self.files, "StdErr")
            same = err and err == stdout_path(j, kv, self.files)
            return err, "stderr (the same file as stdout)" if same else "stderr"
        return stdout_path(j, kv, self.files), "stdout"

    def log_tab(self, snap: dict, app, width: int, height: Optional[int]) -> Tuple[List[Row], List]:
        jid = app.log_job or app.selected_id
        j = next((x for x in snap["jobs"] if x.id == jid), None)
        if j is None:
            return [rule(self.g, width, "log"), [("   select a job on the Jobs tab first", "dim")]], []
        kv = snap["details"].get(j.id, {})
        path, label = self.log_path(app, j, kv)
        g = self.g
        page = max(1, (height - 2) if height else 40)       # the rule and the status line, then the page
        app.logs.page = page
        buf = app.logs.buffer(path) if path else None
        cands = app.logs.candidates.get(j.id, (0, []))[1]
        head = f"{j.id} {j.name} {g.dot} {label}" + (f" {g.dot} o: {len(cands)} other file{'s' if len(cands) != 1 else ''}" if cands else "") + f" {g.dot} {path or 'path not known yet'}"
        out = [rule(g, width, cut(head, width - 8, g.ascii))]
        if buf is None:
            return out + [[("   the stdout path comes from scontrol show job; it appears within a few seconds", "dim")]], []
        if buf.error:
            return out + [[(f"   {buf.error}", "red")]], []
        lines, start = buf.window(app.logs.top, page)
        total = buf.total
        search = app.logs.search
        rx = None
        if search:
            import re
            try:
                rx = re.compile(search, re.IGNORECASE)
            except re.error:
                rx = re.compile(re.escape(search), re.IGNORECASE)
        marks = set(app.logs.bookmarks.get(path, []))
        pos = f"lines {start + 1}-{start + len(lines)} of {total}" if total else "empty file"
        pct = f" ({100 * (start + len(lines)) // total}%)" if total else ""
        status: Row = [(f" {pos}{pct} {g.dot} {buf.size / 1024 ** 2:.1f} MB", "dim"),
                       (f" {g.dot} following", "green") if app.logs.following else (f" {g.dot} paused (End or f follows)", "yellow")]
        if app.logs.wrap:
            status.append((f" {g.dot} wrapped", "dim"))
        if buf.truncated:
            status.append((f" {g.dot} the first {buf.skipped_bytes / 1024 ** 2:.0f} MB are not loaded (log_max_mb)", "yellow"))
        if search:
            status.append((f" {g.dot} search '{search}': {buf.count(search)} lines (N / P next / previous)", "magenta"))
        if marks:
            status.append((f" {g.dot} {len(marks)} bookmark{'s' if len(marks) != 1 else ''} (' jumps)", "cyan"))
        if not g.ascii and width >= 100 and total:
            status = [(" ", "")] + gradient_bar(g, (start + len(lines)) / total, 12) + [(" ", "")] + status
        out.append(status)
        body: List[Row] = []
        for i, l in enumerate(lines):
            idx = start + i
            if rx is not None and rx.search(l):
                style = "sel" if idx == app.logs.match else "yellow"
            elif LOG_ERROR.search(l):
                style = "red"
            elif LOG_WARNING.search(l):
                style = "yellow"
            elif LOG_SUCCESS.search(l):
                style = "green"
            else:
                style = ""
            mark = (g.mark if idx in marks else " ")
            numbers = not g.ascii and width >= 64
            number_width = max(5, len(str(total))) if numbers else 0
            gutter = [(mark, "cyan"), (f"{idx + 1:>{number_width}} │ ", "dim")] if numbers else [(mark, "cyan")]
            content_width = max(1, width - (number_width + 5 if numbers else 2))
            if app.logs.wrap and vlen(l) > content_width:
                chunks, cur = [], l
                while cur:
                    chunk = L.truncate(cur, content_width)
                    # A wide glyph cannot fit a one-column viewport. Consume it with an
                    # explicit placeholder, rather than looping forever on an empty chunk.
                    consumed = len(chunk) if chunk else 1
                    chunks.append(chunk or "?")
                    cur = cur[consumed:]
                for n, ch in enumerate(chunks):
                    continuation = [(" " * (number_width + 1) + " │ ", "dim")] if numbers else [(" ", "cyan")]
                    body.append((gutter if n == 0 else continuation) + [(ch, style)])
            else:
                body.append(gutter + [(cut(l, content_width, g.ascii), style)])
        if app.logs.wrap and len(body) > page:
            body = body[-page:] if app.logs.following else body[:page]
        out += body
        if not lines:
            out.append([("   No output yet. This view updates as the job writes to its log.", "dim")])
        return out, []

    # ---- sources tab ------------------------------------------------------------------------------
    def sources_tab(self, snap: dict, app, width: int, height: Optional[int]) -> Tuple[List[Row], List]:
        hs = sorted(snap["health"].values(), key=lambda h: h.name)
        n = len(hs)
        cur = app.clamp_cursor("sources", n)
        now = clock.now()
        rows = []
        for h in hs:
            state = "off" if not h.enabled else ("error" if h.error else ("ok" if h.last_ok else "pending"))
            rows.append(dict(name=h.name, state=state, every=f"{self.cfg['intervals'].get(h.name, 0):g}s", last=short_duration(now - h.last_ok) + " ago" if h.last_ok else "never",
                             latency=f"{h.latency_ms:.0f} ms" if h.latency_ms else "", calls=h.calls, errors=h.errors, backoff=f"{h.backoff:.0f}s" if h.backoff else "",
                             error=h.error, _styles={"state": {"ok": "green", "error": "red", "off": "dim", "pending": "yellow"}[state]}))
        cols = [Column("name", "SOURCE", 6, 12), Column("state", "STATE", 5, 7), Column("every", "EVERY", 5, 6, ">"), Column("last", "LAST OK", 7, 12, ">"),
                Column("latency", "LATENCY", 7, 8, ">"), Column("calls", "CALLS", 5, 6, ">"), Column("errors", "ERRORS", 6, 6, ">"), Column("backoff", "BACKOFF", 7, 7, ">"),
                Column("error", "LAST ERROR", 10, 80, flex=True)]
        prefix = []
        if self.visual_room(width, height):
            enabled = [h for h in hs if h.enabled]
            prefix += self.composition([("healthy", sum(bool(h.last_ok) and not h.error for h in enabled), "green"),
                                        ("error", sum(bool(h.error) for h in enabled), "red"),
                                        ("waiting", sum(not h.last_ok and not h.error for h in enabled), "yellow"),
                                        ("off", len(hs) - len(enabled), "dim")], width)
        vis = len(rows) if height is None else max(1, height - len(prefix) - 2)
        top = app.scroll_to("sources", cur, vis, n) if height is not None else 0
        shown = rows[top:top + vis]
        trows, _ = table(cols, shown, width, self.g.ascii, cursor=cur - top if height else None,
                         droppable=("backoff", "calls", "errors", "every", "error"))
        title = f"sources {top + 1}-{min(n, top + vis)} of {n}" if n > vis else "sources"
        out = prefix + [rule(self.g, width, title + f" ({app.keys_help('source_toggle')} enables / disables the selected one)")] + trows
        if not hs:
            out.append([("   Waiting for the first sample. Source health appears here automatically.", "dim")])
        out.append([("", "")])
        out.append([("   jobs: squeue (your jobs)   starts: squeue --start   live: sstat (CPU time, peak memory)   gpu: nvidia-smi through srun --overlap, ssh fallback", "dim")])
        out.append([("   nodes: scontrol show node   partitions: sinfo   finished: sacct   share: sshare   account: squeue -A   details: scontrol show job (the selected job)", "dim")])
        ev = snap["events"][-8:]
        if ev:
            out += self.event_rows(ev, width, limit=8)
        hits = [(len(prefix) + 2 + i, "source", r["name"]) for i, r in enumerate(shown)]
        return out, hits

    # ---- analytics tab ----------------------------------------------------------------------------
    def analytics_jobs(self, snap: dict, app) -> List[str]:
        """Jobs the series view can show: running first, then every job with a recorded series."""
        ids = [j.id for j in snap["jobs"] if not j.pending]
        for i in app.store.series_jobs():
            if i not in ids:
                ids.append(i)
        return ids

    def analytics_tab(self, snap: dict, app, width: int, height: Optional[int]) -> Tuple[List[Row], List]:
        g = self.g
        view = app.analytics_view
        days = app.analytics_days_value()
        names = dict(ANALYTICS_VIEWS)
        bar_: Row = [(" ", "")]
        for key, title in ANALYTICS_VIEWS:
            bar_.append((f" {title} ", "rev+bold" if key == view else "dim"))
            bar_.append((" ", ""))
        bar_.append((f"   window {days:g} day{'s' if days != 1 else ''}", "dim"))
        out: List[Row] = [bar_]
        avail = None if height is None else height - 1
        if view == "job":
            body = self.analytics_job(snap, app, width, avail)
        elif view == "history":
            body = self.analytics_history(snap, app, width, avail, days)
        elif view == "advisor":
            body = self.analytics_advisor(snap, app, width, avail, days)
        elif view == "compare":
            body = self.analytics_compare(snap, app, width, avail)
        else:
            body = self.analytics_timeline(snap, app, width, avail, days)
        return out + body, []

    def analytics_advisor(self, snap: dict, app, width: int, avail: Optional[int], days: float) -> List[Row]:
        """What each job name should ask for, from its completed runs in the window; the running jobs so far."""
        g = self.g
        now = clock.now()
        t_lo = now - days * 86400
        fin = [f for f in snap["finished"] if (stamp(f.end) or now) >= t_lo]
        advices = advisor.advise_names(fin)
        out: List[Row] = [rule(g, width, f"advisor: what the jobs of the last {days:g} day{'s' if days != 1 else ''} should have asked for ({len(advices)} job names)")]
        wasted = sum(a.wasted_core_hours for a in advices)
        out.append([(f"   {wasted:.1f} core-hours spent on idle cores over the window (1 - efficiency, times core-hours); suggestions keep {int(100 * (advisor.MEM_HEADROOM - 1))}% memory headroom and {int(100 * (advisor.TIME_HEADROOM - 1))}% time headroom over the worst run", "dim")])
        rows = []
        for a in advices:
            rows.append(dict(name=a.name, runs=a.id, mem=f"{human(a.mem_peak) if a.mem_peak else '?'} / {human(a.mem_req) if a.mem_req else '?'}", mem_s=a.mem_suggest or (g.dot if a.mem_req else ""),
                             eff=f"{100 * a.cpu_eff:.0f}%" if a.cpu_eff is not None else "", cpus=f"{a.cpus}", cpus_s=str(a.cpus_suggest) if a.cpus_suggest and a.cpus_suggest != a.cpus else g.dot,
                             time=f"{hms(a.elapsed) if a.elapsed else '?'} / {hms(a.limit) if a.limit else '?'}", time_s=a.time_suggest or g.dot, waste=f"{a.wasted_core_hours:.1f}",
                             notes=", ".join(a.notes), flags=a.flags(),
                             _styles={"mem_s": "yellow" if a.mem_suggest else "", "cpus_s": "yellow" if (a.cpus_suggest and a.cpus_suggest != a.cpus) else "", "time_s": "yellow" if a.time_suggest else "",
                                      "notes": "red" if a.notes else ""}))
        cols = [Column("name", "JOB NAME", 8, 24, flex=True), Column("runs", "RUNS", 4, 7), Column("mem", "PEAK / REQ MEM", 14, 20), Column("mem_s", "MEM", 3, 6, ">"), Column("eff", "EFF", 3, 4, ">"),
                Column("cpus", "CPUS", 4, 4, ">"), Column("cpus_s", "CPUS", 4, 4, ">"), Column("time", "LONGEST / LIMIT", 15, 20), Column("time_s", "TIME", 4, 10), Column("waste", "IDLE C-H", 8, 8, ">"),
                Column("notes", "NOTES", 5, 30, flex=True)]
        if rows:
            trows, _ = table(cols, rows, width, g.ascii, droppable=("notes", "waste", "eff"))
            out += trows
            out.append([("   copy a line with v then y; the flags of the first row: " + (rows[0]["flags"] or "nothing to change"), "dim")])
        else:
            out.append([("   nothing finished in the window", "dim")])
        running = [j for j in snap["jobs"] if not j.pending]
        if running:
            out.append(rule(g, width, "running jobs so far"))
            for j in running[:8]:
                lv = snap["live"].get(j.id)
                adv = advisor.advise_running(j, lv, app.store.series_of(j.id), snap["finished"])
                text = adv.summary(g.dot) or "nothing to change yet"
                out.append([(f"   {j.id} ", "cyan"), (pad(cut(j.name, 20, g.ascii), 20), "bold"), (" " + cut(text, width - 36, g.ascii), "")])
        if avail is not None:
            out = out[:avail]
        return out

    def analytics_compare(self, snap: dict, app, width: int, avail: Optional[int]) -> List[Row]:
        """The marked (or :compare) jobs side by side: a table, then each metric aligned on time since the job started."""
        g = self.g
        ids = list(app.compare_ids) or sorted(app.marks)
        out: List[Row] = [rule(g, width, f"compare {len(ids)} jobs (mark jobs with Space, or :compare <ids>)")]
        if len(ids) < 1:
            return out + [[("   mark two or more jobs on the Jobs tab (Space), or :compare 123 456", "dim")]]
        jobs = {j.id: j for j in snap["jobs"]}
        fins = {f.id: f for f in snap["finished"]}
        rows = []
        series = {}
        for i in ids[:6]:
            s = app.store.series_of(i)
            series[i] = s
            live = [x for x in s if x.get("k") == "live"]
            gpu = [x for x in s if x.get("k") == "gpu"]
            cpu = [x.get("cpu") if x.get("cpu") is not None else x.get("eff") for x in live]
            cpu = [c for c in cpu if c is not None]
            rss = [x.get("rss") for x in live if x.get("rss") is not None]
            gu = [sum(v[0] for v in x["gpu"].values()) / len(x["gpu"]) for x in gpu if x.get("gpu")]
            j, f = jobs.get(i), fins.get(i)
            name = j.name if j else (f.name if f else "?")
            state = j.state if j else (f.state if f else "?")
            cpus = j.cpus if j else (f.cpus if f else 0)
            req = j.mem_bytes if j else (f.req_mem if f else 0)
            el = j.elapsed_s if j else (secs(f.elapsed) if f else None)
            rows.append(dict(id=i, name=name, state=state, elapsed=hms(el) if el is not None else "?", cpus=cpus,
                             cpu_mean=f"{100 * sum(cpu) / len(cpu):.0f}%" if cpu else "", cpu_max=f"{100 * max(cpu):.0f}%" if cpu else "",
                             mem=human(max(rss)) if rss else (human(f.rss) if f and f.rss else ""), mem_pct=f"{100 * max(rss) / req:.0f}%" if (rss and req) else (f"{100 * f.mem_eff:.0f}%" if f and f.mem_eff is not None else ""),
                             gpu=f"{sum(gu) / len(gu):.0f}%" if gu else "", samples=len(s), coreh=f"{(el or 0) * cpus / 3600:.1f}",
                             _styles={"state": "green" if state in ("COMPLETED", "RUNNING") else "red"}))
        cols = [Column("id", "JOBID", 5, 16), Column("name", "NAME", 6, 24, flex=True), Column("state", "STATE", 5, 13), Column("elapsed", "ELAPSED", 7, 12), Column("cpus", "CPUS", 4, 4, ">"),
                Column("cpu_mean", "CPU MEAN", 8, 8, ">"), Column("cpu_max", "CPU MAX", 7, 7, ">"), Column("mem", "PEAK MEM", 8, 9, ">"), Column("mem_pct", "MEM%", 4, 5, ">"), Column("gpu", "GPU MEAN", 8, 8, ">"),
                Column("coreh", "CORE-H", 6, 7, ">"), Column("samples", "SAMPLES", 7, 7, ">")]
        trows, _ = table(cols, rows, width, g.ascii, droppable=("samples", "coreh", "cpu_max"))
        out += trows
        metrics = [("cpu per core", lambda x: (100 * x["cpu"] if x.get("cpu") is not None else (100 * x["eff"] if x.get("eff") is not None else None)) if x.get("k") == "live" else None, 100.0, "%", "live"),
                   ("memory (GB)", lambda x: (x["rss"] / 1024 ** 3) if (x.get("k") == "live" and x.get("rss") is not None) else None, None, "G", "live"),
                   ("gpu utilisation", lambda x: (sum(v[0] for v in x["gpu"].values()) / len(x["gpu"])) if (x.get("k") == "gpu" and x.get("gpu")) else None, 100.0, "%", "gpu")]
        with_data = [i for i in ids[:6] if series.get(i)]
        if not with_data:
            return out + [[("   no recorded series for these jobs (series accumulate while the dashboard runs)", "dim")]]
        span = max((series[i][-1]["t"] - series[i][0]["t"]) for i in with_data) or 1.0
        n_charts = sum(1 for _, fn, _, _, _ in metrics if any(fn(x) is not None for i in with_data for x in series[i]))
        h = 3 if avail is None else max(2, min(6, (avail - len(out) - 3 * n_charts * len(with_data)) // max(1, n_charts * len(with_data))))
        for title, fn, hi, unit, kind in metrics:
            if not any(fn(x) is not None for i in with_data for x in series[i]):
                continue
            out.append(rule(g, width, f"{title}, aligned on each job's first sample ({compact(span)} across)"))
            hi_all = hi
            if hi is None:
                vals = [fn(x) for i in with_data for x in series[i] if fn(x) is not None]
                hi_all = max(vals) * 1.05 if vals else 1.0
            for i in with_data:
                s = series[i]
                t0 = s[0]["t"]
                samples = [x for x in s if x.get("k") == kind]
                values = [fn(x) for x in samples]
                label = f"{i} {cut(rows[[r['id'] for r in rows].index(i)]['name'], 14, g.ascii)}"
                out += charts.braille_chart(g, values, width, h, hi=hi_all, unit=unit, title=label, times=(0, span),
                                             sample_times=[x["t"] - t0 for x in samples], sample_interval=self.cfg["intervals"][kind], elapsed=True)
        if avail is not None:
            out = out[:avail]
        return out

    def analytics_job(self, snap: dict, app, width: int, avail: Optional[int]) -> List[Row]:
        g = self.g
        ids = self.analytics_jobs(snap, app)
        if not ids:
            return [rule(g, width, "job series"), [("   no running job and no recorded series yet (series accumulate while the dashboard runs)", "dim")]]
        if app.analytics_job not in ids:
            app.analytics_job = app.selected_id if app.selected_id in ids else ids[0]
        jid = app.analytics_job
        pos = ids.index(jid)
        job = next((j for j in snap["jobs"] if j.id == jid), None)
        fin = next((f for f in snap["finished"] if f.id == jid), None)
        name = job.name if job else (fin.name if fin else "")
        state = job.state.lower() if job else (fin.state.lower() if fin else "no longer listed")
        series = app.store.series_of(jid)
        live = [s for s in series if s.get("k") == "live"]
        gpus = [s for s in series if s.get("k") == "gpu"]
        head = [rule(g, width, f"job series {pos + 1}/{len(ids)}"),
                [(f" {jid} ", "cyan"), (name, "bold"), (f"   {state}", ""), (f"   {len(live)} cpu samples, {len(gpus)} gpu samples" + (f" over {compact(series[-1]['t'] - series[0]['t'])}" if len(series) > 1 else ""), "dim")]]
        if job:
            head[1].append((f"   {job.partition} {g.dot} {job.nodelist or 'pending'} {g.dot} {job.cpus} cpus" + (f" {g.dot} {job.gpu_text}" if job.gpus else "") + f" {g.dot} {job.elapsed} of {job.limit}", "dim"))
        if not series and not snap.get("trace", {}).get(jid):
            return head + [[("   no samples recorded for this job yet", "dim")]]
        charts_ = []
        if live:
            cpu = [(s.get("cpu") if s.get("cpu") is not None else s.get("eff")) for s in live]
            cpu_times = (live[0]["t"], live[-1]["t"])
            cpu_stamps = [s["t"] for s in live]
            cpu_title = "cpu per core (rate, efficiency where no rate)" if g.ascii else "CPU per core · rate / efficiency"
            charts_.append((cpu_title, [None if v is None else 100 * v for v in cpu], 100.0, "%", cpu_times, cpu_stamps, self.cfg["intervals"]["live"]))
            req = job.mem_bytes if job else (fin.req_mem if fin else 0)
            if req:
                charts_.append(("memory of the request", [None if s.get("rss") is None else 100 * s["rss"] / req for s in live], 100.0, "%", cpu_times, cpu_stamps, self.cfg["intervals"]["live"]))
            else:
                charts_.append(("resident memory (GB)", [None if s.get("rss") is None else s["rss"] / 1024 ** 3 for s in live], None, "G", cpu_times, cpu_stamps, self.cfg["intervals"]["live"]))
        keys = []
        for s in gpus:
            for k in s.get("gpu", {}):
                if k not in keys:
                    keys.append(k)
        for k in keys[:4]:
            charts_.append((f"gpu {k} utilisation", [s.get("gpu", {}).get(k, [None])[0] for s in gpus], 100.0, "%", (gpus[0]["t"], gpus[-1]["t"]), [s["t"] for s in gpus], self.cfg["intervals"]["gpu"]))
        trace = snap.get("trace", {}).get(jid, [])
        if trace:
            idx = sorted({r["index"] for r in trace})
            for i in idx[:4]:
                pts = [r for r in trace if r["index"] == i]
                trace_title = f"gpu {i} utilisation from the job's own nvidia-smi log (1/min, {len(pts)} samples)" if g.ascii else f"gpu {i} · job trace · {len(pts)} samples"
                charts_.append((trace_title, [r["util"] for r in pts], 100.0, "%", (pts[0]["t"], pts[-1]["t"]), [r["t"] for r in pts], 60.0))
        n = len(charts_)
        if not g.ascii and width >= 120 and (avail is None or avail >= 28):
            telemetry = [(title, values) for title, values, hi, unit, _, _, _ in charts_ if unit == "%" and len(values) >= 2][:4]
            if telemetry:
                head += charts.heatmap(g, [values for _, values in telemetry], width,
                                      labels=[title.split(" · ")[0] for title, _ in telemetry], hi=100, unit="%",
                                      title="telemetry heatmap · each row's observations, oldest to newest")
        columns = 2 if not g.ascii and width >= 140 and n >= 2 and (avail is None or avail >= 20) else 1
        plot_rows = max(1, (n + columns - 1) // columns)
        filled = not g.ascii and (avail is None or avail - len(head) >= plot_rows * 10)
        overhead = 7 if filled else 3
        h = 8 if avail is None else max(2, min(12, (avail - len(head)) // plot_rows - overhead))
        cell_width = (width - 2 * (columns - 1)) // columns
        out = list(head)
        for offset in range(0, n, columns):
            if avail is not None and len(out) >= avail:
                break
            panels = []
            for title, values, hi, unit, times, sample_times, sample_interval in charts_[offset:offset + columns]:
                # Each resource uses its own sampled span; a GPU trace cannot move a CPU time axis.
                title = title.replace(" · ", " - ") if g.ascii else title
                panel = charts.braille_chart(g, values, cell_width, h, hi=hi, unit=unit, title=title, times=times,
                                             sample_times=sample_times, sample_interval=sample_interval)
                if filled:
                    panel += charts.vbar_chart(g, values, cell_width, 2, hi=hi, unit=unit, times=times,
                                              sample_times=sample_times, sample_interval=sample_interval)
                panels.append(panel)
            out += self.beside(panels, [cell_width] * len(panels)) if columns > 1 else panels[0]
        return out if avail is None else out[:avail]

    def analytics_history(self, snap: dict, app, width: int, avail: Optional[int], days: float) -> List[Row]:
        g = self.g
        now = clock.now()
        t_lo = now - days * 86400
        fin = [f for f in snap["finished"] if (stamp(f.end) or now) >= t_lo]
        out: List[Row] = [rule(g, width, f"history, last {days:g} day{'s' if days != 1 else ''}: {len(fin)} finished jobs")]
        if not fin:
            return out + [[("   nothing finished in the window", "dim")]]
        by_day: Dict[str, Dict[str, float]] = {}
        for f in fin:
            day = (f.end or f.start)[:10] or "?"
            d = by_day.setdefault(day, dict(completed=0, failed=0, other=0, core_h=0.0, gpu_h=0.0))
            key = "completed" if f.state == "COMPLETED" else ("other" if f.state.startswith("CANCEL") else "failed")
            d[key] += 1
            d["core_h"] += f.core_hours
            d["gpu_h"] += f.gpu_hours
        days_sorted = sorted(by_day)
        out.append([("   jobs per day", "bold"), ("   completed ", "dim"), (g.full * 2, "green"), ("  failed / timeout / oom ", "dim"), (g.full * 2, "red"), ("  cancelled ", "dim"), (g.full * 2, "yellow")])
        peak = max(sum(v for k, v in d.items() if k in ("completed", "failed", "other")) for d in by_day.values()) or 1
        bar_w = max(10, width - 36)
        for day in days_sorted:
            d = by_day[day]
            segs: Row = [(f"   {day[5:]}  ", "")]
            total = 0
            for key, style in (("completed", "green"), ("failed", "red"), ("other", "yellow")):
                n = int(round(d[key] / peak * bar_w))
                segs.append((g.full * n, style))
                total += d[key]
            segs.append((f" {int(total)}  ({d['core_h']:.1f} core-h, {d['gpu_h']:.1f} gpu-h)", "dim"))
            out.append(segs)
        out.append(rule(g, width, "core-hours per partition"))
        parts: Dict[str, float] = {}
        for f in fin:
            parts[f.partition or "?"] = parts.get(f.partition or "?", 0.0) + f.core_hours
        out += charts.hbar_rows(g, [(p, v, "cyan") for p, v in sorted(parts.items(), key=lambda kv: -kv[1])[:6]], width, unit="h")
        waits = []
        for f in fin:
            a, b = stamp(f.submit), stamp(f.start)
            if a and b and b >= a:
                waits.append((b - a) / 60)
        if waits:
            out.append(rule(g, width, f"queue wait (minutes), {len(waits)} jobs, median {sorted(waits)[len(waits) // 2]:.0f}"))
            out += charts.histogram(g, waits, [0, 1, 5, 15, 60, 240, 1440], width, fmt=lambda x: f"{x:g}")
        effs = [100 * f.cpu_eff for f in fin if f.cpu_eff is not None]
        if effs:
            out.append(rule(g, width, f"cpu efficiency (%), mean {sum(effs) / len(effs):.0f}"))
            out += charts.histogram(g, effs, [0, 10, 25, 50, 75, 90], width, fmt=lambda x: f"{x:g}")
        if avail is not None:
            out = out[:avail]
        return out

    def analytics_timeline(self, snap: dict, app, width: int, avail: Optional[int], days: float) -> List[Row]:
        g = self.g
        now = clock.now()
        t_lo = now - days * 86400
        items = []
        for f in snap["finished"]:
            end = stamp(f.end)
            if end is not None and end < t_lo:
                continue
            items.append(dict(name=f.name, id=f.id, state=f.state, submit=stamp(f.submit), start=stamp(f.start), end=end))
        for j in snap["jobs"]:
            items.append(dict(name=j.name, id=j.id, state=j.state, submit=stamp(j.submit), start=stamp(j.start) if not j.pending else None, end=None))
        items.sort(key=lambda d: (d["start"] if d["start"] is not None else (d["submit"] or now)))
        out: List[Row] = [rule(g, width, f"timeline, last {days:g} day{'s' if days != 1 else ''}: {len(items)} jobs ({g.dot} queued, {g.full} running)")]
        if not items:
            return out + [[("   nothing in the window", "dim")]]
        earliest = min((d["submit"] or d["start"] or now) for d in items)
        t0 = max(t_lo, earliest - 60)
        t1 = now + max(60.0, (now - t0) * 0.02)
        rows = charts.gantt(g, items, t0, t1, width)
        if avail is not None:
            rows = rows[:avail - 1]
        return out + rows

    # ---- shared -----------------------------------------------------------------------------------
    def event_rows(self, events: Sequence[dict], width: int, limit: int = 4) -> List[Row]:
        ev = list(events)[-limit:]
        if not ev:
            return []
        out = [rule(self.g, width, "events")]
        for e in ev:
            col = {"started": "green", "queued": "blue", "finished": "dim", "left": "dim", "action": ("red" if not e.get("ok", True) else "magenta"), "held": "yellow", "released": "green",
                   "alert": "red+bold", "alert_error": "red", "plugin": "red", "tag": "cyan"}.get(e.get("kind", ""), "dim")
            t = time.strftime("%H:%M:%S", time.localtime(e.get("t", 0)))
            day = time.strftime("%m-%d", time.localtime(e.get("t", 0)))
            if day != time.strftime("%m-%d", time.localtime(clock.now())):
                t = f"{day} {t}"
            out.append([("   " + cut(f"{t}  {e.get('text', '')}", width - 4, self.g.ascii), col)])
        return out

    def compose(self, snap: dict, app, width: int, height: Optional[int], actions=None) -> Tuple[List[Row], List[Tuple[int, str, str]]]:
        width = max(0, width)
        if height is not None and height <= 0:
            app.tab_hits, app.last_rows = [], []
            return [], []
        head = self.header(snap, app, width)
        body_h = None if height is None else max(0, height - len(head) - 1)
        fn = {"jobs": lambda: self.jobs_tab(snap, app, actions, width, body_h), "history": lambda: self.history_tab(snap, app, width, body_h),
              "cluster": lambda: self.cluster_tab(snap, app, width, body_h), "nodes": lambda: self.nodes_tab(snap, app, width, body_h),
              "log": lambda: self.log_tab(snap, app, width, body_h), "sources": lambda: self.sources_tab(snap, app, width, body_h),
              "analytics": lambda: self.analytics_tab(snap, app, width, body_h), "group": lambda: self.group_tab(snap, app, width, body_h),
              "deps": lambda: self.deps_tab(snap, app, width, body_h),
              "research": lambda: self.research_tab(snap, app, width, body_h)}.get(app.tab)
        if fn is None:
            body, hits = self.plugin_tab(snap, app, width, body_h), []
        else:
            body, hits = fn()
        hits = [(y + len(head), kind, key) for y, kind, key in hits]
        if height is None:
            return [L.clip_row(r, width) for r in head + body], hits
        rows = [L.clip_row(r, width) for r in head + body]   # every row fits the width, whatever the panel put in it
        while len(rows) < height - 1:
            rows.append([("", "")])
        rows = rows[:height - 1]
        app.last_rows = rows                               # what a copy or an export of the screen reproduces
        if app.sel_anchor is not None:
            a, b = sorted((app.sel_anchor, min(app.sel_end, len(rows) - 1)))
            for y in range(max(0, a), b + 1):
                rows[y] = [(t, "sel") for t, _ in rows[y]]
        hits = [(y, kind, key) for y, kind, key in hits if 0 <= y < max(0, height - 1)]
        app.tab_hits = [hit for hit in app.tab_hits if hit[0] < height - 1 and hit[1] < hit[2]]
        return rows + [L.clip_row(self.footer(app, width), width)], hits

    def step_lines(self, steps: Sequence[Step], width: int) -> List[Row]:
        """A small table of a job's steps (sstat for a running job, sacct -j for a finished one)."""
        rows = []
        for st in steps:
            rows.append(dict(step=st.name or st.id, state=st.state, tasks=st.ntasks or "", elapsed=st.elapsed, cpu=hms(st.cpu_time) if st.cpu_time is not None else "",
                             rss=human(st.rss) if st.rss else "", where=(f"task {st.rss_task}@{st.rss_node}" if st.rss_node and (st.ntasks or 0) > 1 else st.rss_node or st.nodelist),
                             slow=(f"task {st.min_cpu_task}@{st.min_cpu_node} {hms(st.min_cpu)}" if st.min_cpu is not None and (st.ntasks or 0) > 1 else ""), exit=st.exit,
                             _styles={"slow": "yellow" if (st.min_cpu is not None and st.cpu_time and st.min_cpu / st.cpu_time < 0.6) else ""}))
        cols = [Column("step", "STEP", 4, 10), Column("state", "STATE", 5, 10), Column("tasks", "TASKS", 5, 5, ">"), Column("elapsed", "ELAPSED", 7, 10), Column("cpu", "CPU TIME", 8, 11),
                Column("rss", "PEAK MEM", 8, 9, ">"), Column("where", "PEAK ON", 7, 18), Column("slow", "SLOWEST RANK", 12, 30), Column("exit", "EXIT", 4, 5)]
        trows, _ = table(cols, rows, width - 8, self.g.ascii, indent="   ", droppable=("exit", "state", "elapsed"))
        return [[(" steps", "bold")]] + trows

    def plugin_tab(self, snap: dict, app, width: int, height: Optional[int]) -> List[Row]:
        render = self.extra_tabs.get(app.tab)
        if render is None:
            return [rule(self.g, width, app.tab), [("   no such tab", "dim")]]
        try:
            rows = render(snap, app, width, height)
            return [list(r) for r in rows]
        except Exception as e:                            # a plugin's tab never takes the screen down
            return [rule(self.g, width, app.tab), [(f"   plugin tab failed: {type(e).__name__}: {e}", "red")]]

    # ---- overlays ---------------------------------------------------------------------------------
    def research_tab(self, snap, app, width, height):
        from .research_views import render
        return render(self, snap, app, width, height)

    def overlay(self, snap: dict, app, width: int, height: int):
        g = self.g
        if app.mode == "confirm" and app.confirm.get("action") == "submit":
            from .research import clean
            plan = app.confirm["plan"]
            lines = [[(" Submit this reviewed batch script?", "bold")],
                     [("   workdir: " + clean(plan["workdir"], g.ascii), "dim")]]
            text = clean(plan["command"], g.ascii, limit=131072)
            w = max(1, width - 12)
            for i in range(0, min(len(text), w * 12), w):
                lines.append([("   " + text[i:i + w], "cyan")])
            if len(text) > w * 12:
                lines.append([("   command continues; review exact argv with tower run prepare", "yellow")])
            for issue in plan.get("issues", [])[:6]:
                lines.append([("   " + clean(issue.get("message", ""), g.ascii), "yellow")])
            lines.append([("   y submits once; any other key keeps the prepared plan", "dim")])
            return box(g, lines, width, height, "submit")
        if app.mode == "confirm" and app.confirm.get("action") == "resubmit":
            c = app.confirm["clone"]
            lines = [[(f" Resubmit {c.id} {c.name}?", "bold")], [("", "")], [(f"   from the {c.source}, in {c.workdir or 'the current directory'}:", "dim")]]
            text = c.command()
            w = max(40, width - 12)
            while text:
                lines.append([("   " + text[:w], "cyan")])
                text = text[w:]
            lines.append([("", "")])
            fl = c.flags()
            res = "  ".join(f"{k} {fl[k]}" for k in ("partition", "cpus", "mem", "time", "gres", "nodes", "dependency") if k in fl)
            if res:
                lines.append([("   " + res, "")])
            lines.append([("   " + c.probe, "yellow" if "would start" in c.probe else "red")])
            for n in c.notes:
                lines.append([("   " + n, "yellow")])
            lines += [[("", "")], [("   y submits, any other key keeps it (:resubmit <id> --mem 12G --time 03:00:00 -c 4 --advised changes the flags)", "dim")]]
            return box(g, lines, width, height, "resubmit")
        if app.mode == "confirm":
            jobs = app.confirm["jobs"]
            verb = app.confirm["action"]
            lines: List[Row] = [[(f" {verb.capitalize()} {len(jobs)} job{'s' if len(jobs) != 1 else ''}?", "bold")], [("", "")]]
            for j in jobs[:12]:
                lines.append([(f"   {j.id:<12} {cut(j.name, 24, g.ascii):<24} {'pending' if j.pending else 'running'} on {j.partition}", "")])
            if len(jobs) > 12:
                lines.append([(f"   ... and {len(jobs) - 12} more", "dim")])
            lines += [[("", "")], [("   y confirms, any other key keeps them", "dim")]]
            return box(g, lines, width, height, "confirm")
        if app.mode == "help":
            k = app.keys_help
            keys = [(f"{k('up')} {k('down')} {k('page_up')} {k('page_down')} {k('home')} {k('end')}", "move; on the Log tab: scroll"),
                    (f"{k('next_tab')} {k('prev_tab')} 1-9, 0", "switch tabs; 0 opens Research (Left/Right views, PgUp/PgDn scroll)"),
                    (f"{k('mark')} {k('mark_all')} {k('unmark_all')}", "mark a job, all visible jobs, none: actions apply to the marked jobs, else the selected one"),
                    (k("pin"), "pin / unpin the marked or selected jobs (pinned jobs stay on top; :tag, :note and filter #tag go with it)"),
                    (k("resubmit"), "clone and resubmit the selected job: the palette opens with resubmit <id>, add --mem --time -c --gres -p or --advised; sbatch --test-only previews"),
                    (k("details"), "the job's scontrol show job record and its steps (Esc closes); History: the series"),
                    (k("steps"), "details with the steps: sstat per step of a running job (slowest rank, peak memory), sacct -j of a finished one"),
                    (k("cancel"), "cancel (asks first)"), (k("hold"), "hold a pending job, release a held one (asks first)"),
                    (k("requeue"), "requeue a running job (asks first)"), (k("top"), "scontrol top: put a pending job first among your own"),
                    (k("log"), "the Log tab for the selected job"), (k("less"), "its stdout in less (Shift-F follows, q returns)"),
                    (f"{k('follow')} {k('filter')} {k('find_next')} {k('find_prev')}", "Log tab: pause / follow; search (a regular expression, highlighted); next / previous match"),
                    (f"{k('wrap')} {k('stderr')} {k('log_file')} {k('bookmark')} {k('bookmark_next')}", "Log tab: wrap long lines; stdout / stderr; cycle the job's other files (array tasks, steps, the GPU trace); bookmark the current line; jump to the next bookmark"),
                    (f"{k('replay_pause')} {k('replay_back')} {k('replay_fwd')} {k('replay_slower')} {k('replay_faster')}", "replay (--replay FILE): pause / play; 60 s back / forward; half / double the speed (:replay seek 10:30, :replay seek 50%)"),
                    (f"{k('log_lines')} {k('log_lines_less')}", "more / fewer log lines under the selected job"),
                    (f"{k('sort')} {k('reverse')}", "cycle the sort of the tab; reverse it"), (k("filter"), "filter by name, id, partition or info (Enter applies, Esc clears)"),
                    (k("gpu_toggle"), "GPU sampling on / off"), (k("bell_toggle"), "bell on start on / off"), (k("source_toggle"), "Sources tab: enable / disable the selected source"),
                    (k("refresh"), "sample every source now"),
                    (f"{k('visual')} {k('visual_all')} {k('yank')}", "select screen lines from the cursor row (arrows extend; right-click or shift-click extends to a row), all lines; copy them"),
                    (f"{k('export_text')} {k('export_csv')} {k('export_json')}", "export the tab as text; its table as CSV; the marked or selected jobs with their series as JSON (:export report: the whole dashboard as a terminal report)"),
                    (k("palette"), "command palette: cancel <ids>, hold, release, requeue, top, filter, sort, days, tab, export, profile, eval, advise, compare, tag, pin, note, chain ..."),
                    (f"{k('view_prev')} {k('view_next')} {k('days_more')} {k('days_less')}", "Analytics: previous / next view (job series, history, timeline, advisor, compare); a longer / shorter window.  Nodes: my nodes / the cluster map"),
                    (f"Deps tab: {k('cancel')} {k('hold')}", "cancel a job and everything that waits for it; hold / release the chain (asks first)"),
                    (k("theme"), "cycle the theme (default, mono, high contrast, cb: colour-blind safe, reader: plain text)"),
                    (k("help"), "this help"), (k("quit"), "quit (Esc closes an overlay or clears the filter)")]
            lines = [[(" keys", "bold")]] + [[(f"   {a:<26}", "cyan"), (b, "")] for a, b in keys]
            lines += [[("", "")], [(" figures", "bold")],
                      [("   CPU% is the rate between two accounting samples (30 s apart); EFF the CPU time over elapsed x cores so far; MEM% the peak", "")],
                      [("   resident set against the request; GPU% the mean utilisation at the last sample.  FLAGS: !cpu !mem !gpu when a job older than", "")],
                      [(f"   {self.th['warn_after_minutes']} min is below {100 * self.th['cpu']:.0f}% / {100 * self.th['mem']:.0f}% / {100 * self.th['gpu']:.0f}%; ending: under 10 min left; held, dep.  History: what seff reports, from sacct.", "")],
                      [("", "")], [(f" config {app.config_path or '(defaults; tower --write-config creates one)'}", "dim")]]
            return box(g, lines, width, height, "help")
        if app.mode == "details":
            jid = app.detail_id
            j = next((x for x in snap["jobs"] if x.id == jid), None)
            fin = next((x for x in snap["finished"] if x.id == jid), None) if j is None else None
            kv = snap["details"].get(jid, {})
            lines = [[(f" {jid} {j.name if j else (fin.name if fin else '')}", "bold")]]
            if fin is not None:
                d = self.finished_dict(fin)
                lines.append([(f"   {fin.state} {g.dot} {fin.partition} {g.dot} {fin.elapsed} on {fin.nodes} node(s), {fin.cpus} cpus" + (f", {fin.gpus} gpus" if fin.gpus else "")
                               + f" {g.dot} cpu eff {d['ce']} {g.dot} mem eff {d['me']} (peak {d['rss'] or '?'}) {g.dot} exit {fin.exit} {g.dot} {when(fin.start)} to {when(fin.end)}", "")])
                if fin.workdir:
                    lines.append([(f"   workdir {fin.workdir}", "dim")])
                steps = snap.get("fin_steps", {}).get(jid)
                if steps is None:
                    lines.append([("   fetching sacct -j ...", "dim")])
                else:
                    lines += self.step_lines(steps, width)
                app.scroll = min(app.scroll, max(0, len(lines) - 2))
                return box(g, lines[:1] + lines[1 + app.scroll:], width, height, "details (Esc closes, up/down scroll)")
            if not kv:
                lines.append([("   fetching scontrol show job ...", "dim")])
            steps = snap.get("steps", {}).get(jid, [])
            if steps:
                lines += self.step_lines(steps, width)
            first = ("JobState", "Reason", "Dependency", "Priority", "RunTime", "TimeLimit", "SubmitTime", "StartTime", "EndTime", "Partition", "NodeList", "NumNodes", "NumCPUs", "TRES",
                     "Account", "QOS", "StdOut", "StdErr", "WorkDir", "Command")
            keys = sorted(kv, key=lambda k: (k not in first, first.index(k) if k in first else 0, k))
            for k in keys:
                lines.append([(f"   {k:<22}", "cyan"), (cut(kv[k], width - 32, g.ascii), "")])
            app.scroll = min(app.scroll, max(0, len(lines) - 2))
            return box(g, lines[:1] + lines[1 + app.scroll:], width, height, "details (Esc closes, up/down scroll)")
        return None


def step_lines_of(views, steps, width):
    return views.step_lines(steps, width)


def g_speed(c) -> str:
    return f"x{c.speed:g}" if c.speed != 1 else "x1"


def snap_name(snap: dict, jid: str) -> str:
    for j in snap["jobs"]:
        if j.id == jid:
            return j.name
    for f in snap["finished"]:
        if f.id == jid:
            return f"{f.name} {f.state.lower()}"
    return ""
