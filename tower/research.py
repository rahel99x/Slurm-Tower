"""Bounded, demand-driven background reads for the research workspace."""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import math
import os
import threading
import time

from . import clock
from .remote import LocalFiles

RESEARCH_VIEWS = [("experiment", "Experiment"), ("arrays", "Arrays"),
                  ("evidence", "Evidence"), ("artifacts", "Artifacts"),
                  ("passport", "Passport"), ("submit", "Submit")]


def clean(value, ascii_=False, limit=4096):
    """External file names and text never introduce terminal controls."""
    text = str(value)[:limit]
    text = "".join(ch if ch.isprintable() else " " for ch in text)
    return text.encode("ascii", "backslashreplace").decode("ascii") if ascii_ else text


class ResearchHub:
    def __init__(self, cfg, files=None, *, demo=False, settings=None, slurm=None):
        self.files = files or LocalFiles()
        self.slurm = slurm
        self.demo = demo
        self.settings = dict(cfg.get("research", {}) or {})
        self.settings.update({k: v for k, v in (settings or {}).items() if v is not None})
        for key in ("metrics_file", "contract", "workdir", "passport"):
            if not isinstance(self.settings.get(key, ""), str):
                raise ValueError(f"research.{key} must be a path string")
        interval = self.settings.get("interval", 5)
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not 1 <= interval <= 86400:
            raise ValueError("research.interval must be finite and between 1 and 86400 seconds")
        self.interval = float(interval)
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tower-research")
        self.future = None
        self.pending = None
        self.closed = False
        self.cache = OrderedDict()
        self.generation = 0
        self.reader = None
        self.plan = None
        self.passport = None
        self.passport_diff = None

    def close(self):
        with self.lock:
            self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)

    def configure(self, **values):
        with self.lock:
            self.settings.update(values)
            self.generation += 1
            self.cache.clear()

    def start_task(self, fn, completion):
        """Explicit UI commands share the single worker, without an unbounded queue."""
        with self.lock:
            if self.closed or self.pending:
                return False
            self.future = self.pool.submit(fn)
            self.pending = (self.future, completion)
            return True

    def poll_task(self):
        """Publish command state on the UI thread, never from a worker."""
        with self.lock:
            pending = self.pending
            if self.closed or not pending or not pending[0].done():
                return
            self.pending = None
        try:
            result = pending[0].result()
        except Exception as exc:
            result = exc
        pending[1](result)

    def context(self, snap, app):
        jid = getattr(app, "research_job_id", None) or app.selected_id
        jobs = snap.get("jobs", []) + snap.get("finished", [])
        job = next((j for j in jobs if j.id == jid), None)
        if job is None and not jid and jobs:
            job = jobs[0]
            jid = job.id
        return {"view": getattr(app, "research_view", "experiment"), "jid": jid,
                "job": job, "snap": snap, "settings": dict(self.settings),
                "generation": self.generation}

    def _key(self, context):
        jid = context["jid"] if context["view"] in ("experiment", "evidence") else None
        return context["generation"], context["view"], jid

    def current(self, context):
        with self.lock:
            entry = self.cache.get(self._key(context))
            return entry[1] if entry else {"status": "loading", "summary": "Waiting for the background reader."}

    def request(self, context, *, wait=False, force=False):
        """At most one worker is active; frames only inspect published snapshots."""
        for _ in range(2 if wait else 1):
            with self.lock:
                if self.closed:
                    return self.current(context)
                if self.pending:
                    return self.current(context)
                entry = self.cache.get(self._key(context))
                if not force and entry and time.monotonic() - entry[0] < self.interval:
                    return entry[1]
                if self.future is None or self.future.done():
                    self.future = self.pool.submit(self._publish, context)
                future = self.future
            if not wait:
                break
            # Remote reads are individually timed out. No such waits occur in a frame.
            future.result(timeout=90)
            force = False
        return self.current(context)

    def _publish(self, context):
        try:
            result = self._read(context)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            result = {"status": "error", "summary": clean(exc)}
        except Exception as exc:
            # A new data adapter cannot take down the curses loop.
            result = {"status": "error", "summary": f"{type(exc).__name__}: {clean(exc)}"}
        with self.lock:
            if not self.closed and context["generation"] == self.generation:
                self.cache[self._key(context)] = (time.monotonic(), result)
                self.cache.move_to_end(self._key(context))
                while len(self.cache) > 16:
                    self.cache.popitem(last=False)
        return result

    def _path(self, value, context):
        if not value:
            return ""
        # Only the documented job ID token is expanded; arbitrary format code is not.
        value = str(value).replace("{job_id}", str(context["jid"] or "unknown"))
        workdir = context["settings"].get("workdir", "")
        if workdir and not os.path.isabs(value):
            value = os.path.join(workdir, value)
        return value if self.files.remote else os.path.expanduser(value)

    def _read(self, context):
        view, settings, snap = context["view"], context["settings"], context["snap"]
        if view == "experiment":
            path = self._path(settings.get("metrics_file"), context)
            if not path:
                return self._demo_metrics() if self.demo else {"status": "empty", "summary": "Attach a metrics stream with :metrics PATH or --metrics-file PATH."}
            if self.reader is None:
                from .metrics import MetricReader
                self.reader = MetricReader(self.files)
            return self.reader.read(path)
        if view == "arrays":
            from .arrays import summarize
            return {"status": "ok", "groups": summarize(snap.get("jobs", []), snap.get("finished", []))}
        if view == "artifacts":
            from .artifacts import load_contract, validate_contract
            path = settings.get("contract", "")
            if not path:
                return {"status": "empty", "summary": "Attach a JSON output contract with :artifacts CONTRACT ROOT."}
            if self.files.remote:
                return {"status": "incomplete", "summary": "Output validation needs a local checkout on the job's cluster. Run Tower on the CARC login node."}
            return validate_contract(load_contract(os.path.expanduser(path)), settings.get("workdir") or os.getcwd(), files=self.files)
        if view == "passport":
            from .provenance import load
            path = settings.get("passport", "")
            if path:
                if self.files.remote:
                    return {"status": "incomplete", "summary": "Passport inspection requires running Tower on the cluster."}
                return {"status": "ok", "passport": load(os.path.expanduser(path)), "differences": self.passport_diff}
            return {"status": "ok", "passport": self.passport, "differences": self.passport_diff} if self.passport or self.passport_diff is not None else {"status": "empty", "summary": "Capture a run with :passport capture SCRIPT --workdir DIR."}
        if view == "submit":
            return {"status": "ok", "plan": self.plan} if self.plan else {"status": "empty", "summary": "Prepare a batch script with :prepare SCRIPT --workdir DIR [resource flags]."}
        if view == "evidence":
            from .investigate import investigate
            job = context["job"]
            if job is None:
                return {"status": "empty", "summary": "Select a job in Jobs or History, then open Evidence."}
            details = snap.get("details", {}).get(job.id, {})
            if not details and self.slurm is not None:
                details = self.slurm.details(job.id)
            logs = {}
            errors = []
            for key, option in (("stdout", "StdOut"), ("stderr", "StdErr")):
                path = details.get(option, "")
                if not path:
                    errors.append(f"{option} path not available")
                    continue
                try:
                    data, size = self._tail(path, 131072)
                    logs[key] = {"text": data.decode("utf-8", "replace"), "path": path, "truncated": size > len(data)}
                except (OSError, ValueError) as exc:
                    errors.append(f"{option}: {clean(exc)}")
            artifact_result = None
            if settings.get("contract"):
                artifact_result = self._read(dict(context, view="artifacts"))
            result = investigate(job, details=details, live=snap.get("live", {}).get(job.id), events=snap.get("events", []),
                                 artifact_results=artifact_result, **logs)
            result.setdefault("limitations", []).extend(errors)
            return result
        return {"status": "error", "summary": "Unknown research view."}

    def _tail(self, path, limit):
        if self.files.remote or type(self.files) is not LocalFiles:
            return self.files.tail(path, limit)
        from .artifacts import read_local_tail
        data, size, stable = read_local_tail(path, max_bytes=limit)
        if not stable:
            raise ValueError("log changed during inspection; retry the view")
        return data, size

    @staticmethod
    def _demo_metrics():
        now = clock.now()
        series = {"loss": [], "accuracy": [], "samples_per_second": []}
        for i in range(120):
            for name, value in (("loss", 2.4 * math.exp(-i / 35) + .03), ("accuracy", .3 + .65 * (1 - math.exp(-i / 40))),
                                ("samples_per_second", 120 + 15 * math.sin(i / 8))):
                series[name].append({"t": now - (119 - i) * 5, "value": value, "step": i})
        return {"status": "ok", "path": "simulated application metrics", "series": series,
                "latest": {k: v[-1]["value"] for k, v in series.items()}, "phase": "training",
                "progress": {"completed": 120, "total": 200, "unit": "steps", "fraction": .6,
                             "eta_seconds": 400, "eta_source": "simulated_progress"}, "errors": [], "records": 120}
