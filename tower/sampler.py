"""The scheduler: every source runs on its own cadence in a small thread pool, never overlapping itself, with
per-source health (latency, errors, exponential backoff) and a kick that makes the next round immediate."""
from __future__ import annotations

import concurrent.futures
from copy import deepcopy
import threading
import time
from typing import Callable, Dict, List, Optional

from . import clock
from .model import Health, Job, Store
from .slurm import CommandError, Slurm


class Sampler(threading.Thread):
    def __init__(self, slurm: Slurm, store: Store, intervals: Dict[str, float], gpu_types: List[str], history_days: float = 2.0,
                 account: str = "", gpu_sampling: bool = True, workers: int = 4, on_event: Optional[Callable[[dict], None]] = None,
                 weather: bool = True, probes: Optional[List[dict]] = None, budget: bool = True, files=None):
        super().__init__(daemon=True, name="tower-sampler")
        self.slurm, self.store, self.intervals = slurm, store, dict(intervals)
        self.gpu_types, self.history_days, self.account = list(gpu_types), history_days, account
        self.gpu_sampling = gpu_sampling
        self.on_event = on_event
        self.weather, self.probes, self.budget = weather, list(probes or []), budget
        from .remote import LocalFiles
        self.files = files or LocalFiles()
        self.want_fin: Optional[str] = None                # a finished job whose steps the details overlay wants
        self.want_trace: Optional[str] = None              # a job (running or finished) whose GPU trace the analytics view wants
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tower-src")
        # GPU sampling waits for child tasks; sharing the source executor can deadlock
        # with one worker and starve unrelated sources with any pool size.
        self.gpu_workers = min(workers, 4)
        self.gpu_pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.gpu_workers, thread_name_prefix="tower-gpu")
        self._schedule_lock = threading.RLock()
        self.stop = threading.Event()
        self.kick = threading.Event()
        self.want_detail: Optional[str] = None
        self._historical_details: Dict[str, Dict[str, str]] = {}
        self.sources: Dict[str, Callable[[], None]] = {
            "jobs": self.src_jobs, "starts": self.src_starts, "live": self.src_live, "gpu": self.src_gpu, "nodes": self.src_nodes,
            "partitions": self.src_partitions, "finished": self.src_finished, "share": self.src_share, "account": self.src_account, "details": self.src_details,
            "weather": self.src_weather, "budget": self.src_budget, "trace": self.src_trace, "fin_details": self.src_fin_details,
        }
        for name in self.sources:
            self.store.health[name] = Health(name=name)
        self.dependencies = {
            "starts": ("jobs",), "live": ("jobs",), "gpu": ("jobs",),
            "nodes": ("jobs",), "trace": ("jobs",),
            "weather": ("jobs", "partitions", "share"),
        }
        self.last_run: Dict[str, float] = {name: 0.0 for name in self.sources}
        self.hooks: List[Callable[[dict], None]] = []     # plugin event hooks, called after on_event
        self.job_observers = []                         # bounded read-only consumers of existing samples
        self.observer_errors = {}
        self._job_observer_lock = threading.RLock()

    def add_source(self, name: str, interval: float, fn: Callable[[Slurm, Store], None]) -> None:
        """A plugin source: ``fn(slurm, store)`` every ``interval`` seconds, with health and backoff like the others."""
        self.sources[name] = lambda: fn(self.slurm, self.store)
        self.intervals[name] = float(interval)
        self.store.health[name] = Health(name=name)
        self.last_run[name] = 0.0

    def emit(self, events: List[dict]) -> None:
        for ev in events:
            for fn in ([self.on_event] if self.on_event else []) + self.hooks:
                try:
                    fn(ev)
                except Exception:
                    pass

    # ---- scheduling --------------------------------------------------------------------------------
    def health(self, name: str) -> Health:
        return self.store.health[name]

    def due(self, name: str, now: float) -> bool:
        h = self.health(name)
        if not h.enabled or h.inflight:
            return False
        if h.calls == 0:
            for dependency in self.dependencies.get(name, ()):
                prerequisite = self.health(dependency)
                if prerequisite.enabled and (prerequisite.calls == 0 or prerequisite.inflight):
                    return False
        if name == "gpu" and not self.gpu_sampling:
            return False
        if name == "details" and not self.want_detail:
            return False
        if name in ("account", "budget") and not self.account:
            return False
        if name == "weather" and not self.weather:
            return False
        if name == "budget" and not self.budget:
            return False
        if name == "fin_details" and not self.want_fin:
            return False
        return now - self.last_run[name] >= self.intervals.get(name, 30.0) + h.backoff

    def run_source(self, name: str):
        h = self.health(name)
        t0 = time.perf_counter()
        h.last_try = time.time()
        try:
            self.sources[name]()
            with self.store.lock:
                h.calls += 1
                h.latency_ms = 1000 * (time.perf_counter() - t0)
                h.last_ok = time.time()
                h.error = ""
                h.backoff = 0.0
        except CommandError as e:
            with self.store.lock:
                h.calls += 1
                h.errors += 1
                h.error = str(e)
                h.backoff = min(300.0, max(self.intervals.get(name, 30.0), 2 * h.backoff))
        except Exception as e:                            # a bug in a source never stops the others
            with self.store.lock:
                h.calls += 1
                h.errors += 1
                h.error = f"{type(e).__name__}: {e}"
                h.backoff = min(300.0, max(self.intervals.get(name, 30.0), 2 * h.backoff))
        finally:
            with self.store.lock:
                h.inflight = False

    def round(self, now: Optional[float] = None, wait: bool = False):
        """Submit every due source; ``wait`` blocks until they finish (used by --once and the tests)."""
        now = time.time() if now is None else now
        futures, submitted = [], set()
        while True:
            batch = []
            with self._schedule_lock:
                if self.stop.is_set():
                    break
                for name in self.sources:
                    if name not in submitted and self.due(name, now):
                        self.last_run[name] = now
                        self.health(name).inflight = True
                        submitted.add(name)
                        batch.append(self.pool.submit(self.run_source, name))
            futures.extend(batch)
            if not wait or not batch:
                break
            _, pending = concurrent.futures.wait(batch, timeout=60)
            if pending:
                break
            # Initial dependent sources are now eligible. Sample them before --once
            # returns, without repeating sources even when their interval is zero.
        return futures

    def run(self):
        while not self.stop.is_set():
            self.round()
            self.kick.wait(0.5)
            self.kick.clear()

    def refresh_all(self):
        for name in self.last_run:
            self.last_run[name] = 0.0
            self.health(name).backoff = 0.0
        self.kick.set()

    def shutdown(self):
        with self._schedule_lock:
            self.stop.set()
            self.kick.set()
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.gpu_pool.shutdown(wait=False, cancel_futures=True)

    # ---- sources -----------------------------------------------------------------------------------
    def src_jobs(self):
        jobs = self.slurm.jobs()
        events = self.store.apply_jobs(jobs)
        if events:
            self.emit(events)
        if any(ev["kind"] in ("started", "finished", "left") for ev in events):
            self.last_run["starts"] = 0.0                  # projected starts change when the queue moves
        self.check_alerts()
        self.observe_jobs()

    def observe_jobs(self):
        """Observers consume sampled jobs; they never request additional Slurm commands."""
        if not self.job_observers:
            return
        from dataclasses import asdict
        with self._job_observer_lock:
            with self.store.lock:
                jobs = [asdict(j) for j in self.store.jobs[:10000]]
            for index, observer in enumerate(tuple(self.job_observers[:8])):
                try:
                    observer(deepcopy(jobs))
                    self.observer_errors.pop(index, None)
                except Exception as exc:
                    self.observer_errors[index] = str(exc)[:512]

    def check_alerts(self):
        eng = self.store.alerts
        if eng is None or not eng.rules:
            return
        try:
            eng.check(self.store.snapshot(), marks=getattr(self, "marks", ()), tags=self.store.tag_map())
        except Exception:
            pass

    def src_starts(self):
        if any(j.pending for j in self.store.jobs):
            self.store.apply_starts(self.slurm.starts())
            self.observe_jobs()

    def src_live(self):
        now = clock.now()
        with self.store.lock:
            jobs = [j for j in self.store.jobs if not j.pending]
        failures = []
        for job in jobs:
            if self.stop.is_set():
                break
            try:
                lv, keep, steps = self.slurm.live(job, self.store.prev_cpu.get(job.id), now)
            except CommandError as exc:
                failures.append(str(exc))
                continue
            with self.store.lock:
                self.store.prev_cpu[job.id] = keep
                self.store.apply_live(job.id, lv)
                self.store.steps[job.id] = steps
        with self.store.lock:
            alive = {job.id for job in self.store.jobs}
            for jid in set(self.store.steps) - alive:
                del self.store.steps[jid]
        self.check_alerts()
        if failures:
            raise CommandError(f"Live sampling failed for {len(failures)}/{len(jobs)} jobs: {failures[0]}")

    def src_gpu(self):
        jobs = [j for j in self.store.jobs if not j.pending and j.gpus and j.state == "RUNNING"]
        if not jobs:
            return
        pending = {}
        remaining = iter(jobs)
        failures = []
        while not self.stop.is_set():
            # Bound both active commands and queued futures even for a very large account.
            with self._schedule_lock:
                if self.stop.is_set():
                    break
                while len(pending) < self.gpu_workers:
                    job = next(remaining, None)
                    if job is None:
                        break
                    pending[self.gpu_pool.submit(self.slurm.gpu, job)] = job
            if not pending:
                break
            done, _ = concurrent.futures.wait(pending, timeout=0.5, return_when=concurrent.futures.FIRST_COMPLETED)
            for fut in done:
                job = pending.pop(fut)
                try:
                    self.store.apply_gpu(job.id, fut.result())
                except CommandError as exc:
                    self.store.apply_gpu(job.id, None)
                    failures.append(str(exc))
        for fut in pending:
            fut.cancel()
        self.check_alerts()
        if failures:
            raise CommandError(f"GPU sampling failed for {len(failures)}/{len(jobs)} jobs: {failures[0]}")

    def src_nodes(self):
        names = sorted({h for j in self.store.jobs if not j.pending for h in j.hosts})
        nodes = {}
        for n in names:
            node = self.slurm.node(n)
            if node:
                nodes[n] = node
        with self.store.lock:
            self.store.nodes = nodes

    def src_partitions(self):
        parts, tot, nodemap = self.slurm.partitions(self.gpu_types)
        with self.store.lock:
            self.store.partitions, self.store.gpu_inventory, self.store.nodemap = parts, tot, nodemap

    def src_finished(self):
        fin = self.slurm.finished(self.history_days)
        with self.store.lock:
            self.store.finished = fin

    def src_share(self):
        rows = self.slurm.share()
        with self.store.lock:
            self.store.share = rows
        if not self.account and rows:
            self.account = rows[0]["account"]

    def src_account(self):
        """Everyone's jobs in the account (the Group tab) and the account's load (the header)."""
        jobs = self.slurm.group(self.account)
        running = [j for j in jobs if not j.pending]
        info = dict(account=self.account, running=len(running), cpus=sum(j.cpus for j in running), gpus=sum(j.gpus for j in running),
                    pending=sum(1 for j in jobs if j.pending))
        with self.store.lock:
            self.store.group, self.store.account = jobs, info

    def default_probes(self) -> List[dict]:
        """One probe per GPU type of each GPU partition, one per CPU partition that has jobs of mine."""
        mine = {j.partition for j in self.store.jobs}
        out = []
        for p in self.store.partitions:
            if p.gpus:
                for t in sorted(p.gpus):
                    out.append(dict(partition=p.name, gres=f"gpu:{t}:1", cpus=8, mem="32G", limit="01:00:00"))
            elif p.name in mine:
                out.append(dict(partition=p.name, gres="", cpus=16, mem="64G", limit="01:00:00"))
        return out[:8]

    def src_weather(self):
        """Pending work ahead per partition cluster-wide, and sbatch --test-only for a few typical jobs."""
        ahead = self.slurm.pending_ahead()
        probes = self.probes or self.default_probes()
        results = []
        for pr in probes:
            r = self.slurm.probe(pr.get("partition", "main"), pr.get("gres", ""), int(pr.get("cpus", 8)), str(pr.get("mem", "32G")), str(pr.get("limit", "01:00:00")),
                                 account=self.account if pr.get("account", True) else "")
            r["t"] = time.time()
            results.append(r)
        with self.store.lock:
            self.store.pending_ahead, self.store.weather = ahead, results

    def src_budget(self):
        info = self.slurm.budget(self.account)
        with self.store.lock:
            self.store.budget = info

    def trace_path(self, jid: str) -> str:
        """<WorkDir>/logs/gpu-util-<id>.csv from the job's details or its sacct record."""
        import os
        kv = self.store.details.get(jid, {})
        wd = kv.get("WorkDir", "")
        if not wd:
            fin = next((f for f in self.store.finished if f.id == jid), None)
            wd = fin.workdir if fin else ""
        return os.path.join(wd, "logs", f"gpu-util-{jid}.csv") if wd else ""

    def src_trace(self):
        """The nvidia-smi CSV the job writes itself (timestamp, index, utilization.gpu, memory.used; one line per GPU per minute; the README says how a job writes it) for every
        running GPU job and the job the analytics view shows."""
        want = [j.id for j in self.store.jobs if not j.pending and j.gpus]
        if self.want_trace and self.want_trace not in want:
            want.append(self.want_trace)
        traces = {}
        for jid in want:
            path = self.trace_path(jid)
            if not path or not self.files.exists(path):
                continue
            try:
                rows = self.slurm.gpu_trace(path, self.files)
            except OSError:
                continue
            if rows:
                traces[jid] = rows
        with self.store.lock:
            for jid, rows in traces.items():
                self.store.trace[jid] = rows
            for k in [k for k in self.store.trace if k not in want]:
                del self.store.trace[k]

    def src_fin_details(self):
        jid = self.want_fin
        if not jid or jid in self.store.fin_steps:
            return
        steps = self.slurm.fin_steps(jid)
        with self.store.lock:
            self.store.fin_steps[jid] = steps
            if len(self.store.fin_steps) > 50:
                self.store.fin_steps.pop(next(iter(self.store.fin_steps)))

    def src_details(self):
        jid = self.want_detail
        if not jid:
            return
        with self.store.lock:
            finished = next((job for job in self.store.finished if job.id == jid), None)
            previous = dict(self.store.details.get(jid, {}))
        if finished is None:
            kv = self.slurm.details(jid)
        else:
            # Successful completed-job paths are immutable. Missing accounting
            # paths can lag completion, so retry them on the normal cadence or a
            # manual refresh. Keep real paths fetched while the job was alive.
            kv = self._historical_details.get(jid)
            if kv is None:
                seed = dict(previous)
                seed.pop("LogPathError", None)
                seed.update({"JobId": jid, "JobName": finished.name, "JobState": finished.state})
                if finished.workdir and not seed.get("WorkDir"):
                    seed["WorkDir"] = finished.workdir

                def known_path() -> bool:
                    return any(isinstance(seed.get(key), str) and seed[key] and
                               seed[key].lower() not in ("unknown", "n/a", "(null)", "none")
                               for key in ("StdOut", "StdErr"))

                if not known_path():
                    try:
                        control = self.slurm.details(jid)
                    except CommandError:
                        control = {}
                    seed.update(control)
                    if not known_path():
                        seed.update(self.slurm.historical_details(jid))
                kv = seed
                if known_path():
                    self._historical_details[jid] = dict(kv)
                    if len(self._historical_details) > 50:
                        self._historical_details.pop(next(iter(self._historical_details)))
        with self.store.lock:
            # An in-flight fetch for an old cursor must not evict or overwrite
            # the newly selected job's details.
            if jid != self.want_detail:
                return
            self.store.details[jid] = kv
            alive = {j.id for j in self.store.jobs}
            retained = set(self._historical_details)
            for k in [k for k in self.store.details if k not in alive and k not in retained and k != jid]:
                del self.store.details[k]

    def select(self, jid: Optional[str]):
        """The screen's selected job: its details are fetched now and refreshed on the details cadence."""
        if jid != self.want_detail:
            self.want_detail = jid
            self.last_run["details"] = 0.0
            self.kick.set()

    def select_fin(self, jid: Optional[str]):
        """A finished job whose steps the details overlay shows (sacct -j, once)."""
        if jid != self.want_fin:
            self.want_fin = jid
            self.last_run["fin_details"] = 0.0
            self.kick.set()

    def select_trace(self, jid: Optional[str]):
        if jid != self.want_trace:
            self.want_trace = jid
            self.last_run["trace"] = 0.0
            self.kick.set()
