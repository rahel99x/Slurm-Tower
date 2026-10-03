"""The data model: typed records for jobs, live statistics, GPUs, nodes, partitions and finished jobs; the
thread-safe store with histories, transitions, events, per-source health and persistence."""
from __future__ import annotations

import collections
import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Deque, Dict, List, Optional, Sequence

from . import clock


# ------------------------------------------------------------------------------------------------ parsing helpers
def secs(s: Optional[str]) -> Optional[float]:
    """[DD-]HH:MM:SS[.f] | MM:SS | 'UNLIMITED' -> seconds (None if unknown)."""
    if not s or s in ("UNLIMITED", "N/A", "INVALID", "Unknown", "-", "NOT_SET", "PARTITION_TIME_LIMIT"):
        return None
    d = 0
    try:
        if "-" in s:
            d, s = s.split("-", 1)
            d = int(d)
        parts = [float(p) for p in s.split(":")]
    except ValueError:
        return None
    if len(parts) == 3:
        return int(d) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return int(d) * 86400 + parts[0] * 60 + parts[1]
    return parts[0]


def hms(seconds: Optional[float]) -> str:
    if seconds is None:
        return "?"
    seconds = int(seconds)
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    return (f"{d}-" if d else "") + f"{h:02d}:{m:02d}:{s:02d}"


def short_duration(seconds: Optional[float]) -> str:
    """1d 02h | 3h 04m | 12m | 45s."""
    if seconds is None:
        return "?"
    seconds = int(max(0, seconds))
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    if d:
        return f"{d}d {h:02d}h"
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def compact(seconds: Optional[float]) -> str:
    """12m | 3h04m | 1d03h | 45s: one or two units."""
    if seconds is None:
        return "?"
    seconds = int(max(0, seconds))
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    if d:
        return f"{d}d{h:02d}h"
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m"
    return f"{s}s"


def nbytes(s: Optional[str]) -> float:
    """12345K, 1.5G, 800M, 32G, 64Gn, 4000Mc -> bytes."""
    if not s:
        return 0.0
    unit = "".join(c for c in s.upper() if c.isalpha())[:1]
    try:
        v = float("".join(c for c in s if c.isdigit() or c == "."))
    except ValueError:
        return 0.0
    return v * {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}.get(unit, 1)


def human(b: float) -> str:
    for unit, div in (("TB", 1024 ** 4), ("GB", 1024 ** 3), ("MB", 1024 ** 2)):
        if b >= div:
            return f"{b / div:.1f} {unit}"
    return f"{b / 1024:.0f} KB"


def fnum(s) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def fint(s) -> int:
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 0


def stamp(s: Optional[str]) -> Optional[float]:
    """Slurm time 'YYYY-MM-DDTHH:MM:SS' -> epoch seconds."""
    try:
        return time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return None


def when(s: Optional[str]) -> str:
    """'YYYY-MM-DDTHH:MM:SS' -> 'HH:MM' today, else 'MM-DD HH:MM'."""
    if not s or s in ("N/A", "Unknown", "NONE"):
        return "n/a"
    try:
        day, clock_ = s.split("T")
        return clock_[:5] if day == clock.today() else f"{day[5:]} {clock_[:5]}"
    except ValueError:
        return s


def gres_gpus(s: Optional[str]):
    """'gres/gpu:a100:2' | 'gpu:2' | 'gpu:a100:2(S:0-1)' | 'gres:gpu:1' | 'N/A' -> (type, count)."""
    if not s or "gpu" not in s:
        return ("", 0)
    body = s.split("gpu", 1)[1].lstrip(":").split("(")[0]
    bits = [b for b in body.split(":") if b]
    if not bits:
        return ("", 0)
    if bits[-1].isdigit():
        return (bits[0] if len(bits) > 1 else "", int(bits[-1]))
    return (bits[0], 1)


def gpus_in_tres(tres: str) -> int:
    """'cpu=8,mem=32G,node=1,billing=8,gres/gpu=1,gres/gpu:a100=1' -> 1."""
    for part in (tres or "").split(","):
        if part.startswith("gres/gpu=") :
            return fint(part.split("=", 1)[1])
    return 0


def mem_request_bytes(mem_req: str, cpus: int, nodes: int) -> float:
    req = nbytes(mem_req)
    if req and mem_req.endswith("c"):
        req *= max(cpus, 1)
    elif req and mem_req.endswith("n"):
        req *= max(nodes, 1)
    return req


# ------------------------------------------------------------------------------------------------ records
@dataclass
class Job:
    id: str
    name: str
    partition: str
    state: str                       # RUNNING PENDING COMPLETING CONFIGURING SUSPENDED ...
    elapsed: str = "0:00"
    limit: str = ""
    nodes: int = 1
    cpus: int = 0
    gpu_type: str = ""
    gpus: int = 0                    # over all nodes
    nodelist: str = ""
    mem_req: str = ""
    start: str = ""
    submit: str = ""
    reason: str = ""
    priority: int = 0
    dependency: str = ""
    account: str = ""
    qos: str = ""
    end: str = ""                    # expected end
    command: str = ""
    est_start: str = ""              # squeue --start
    hosts: List[str] = field(default_factory=list)
    user: str = ""                   # set for the account-wide listing

    @property
    def pending(self) -> bool:
        return self.state == "PENDING"

    @property
    def held(self) -> bool:
        return self.reason in ("JobHeldUser", "JobHeldAdmin")

    @property
    def elapsed_s(self) -> Optional[float]:
        return secs(self.elapsed)

    @property
    def limit_s(self) -> Optional[float]:
        return secs(self.limit)

    @property
    def mem_bytes(self) -> float:
        return mem_request_bytes(self.mem_req, self.cpus, self.nodes)

    @property
    def gpu_text(self) -> str:
        return f"{self.gpus}x{self.gpu_type or 'gpu'}" if self.gpus else ""


@dataclass
class Live:
    cpu_time: Optional[float] = None     # seconds of CPU consumed (sstat AveCPU of the batch step)
    rss: Optional[float] = None          # peak resident set, bytes
    avg: Optional[float] = None          # CPU efficiency so far: cpu_time / (elapsed * cpus)
    rate: Optional[float] = None         # CPU rate between the last two samples, per core
    t: float = 0.0


@dataclass
class GpuSample:
    node: str
    index: int
    util: float                          # percent
    used: float                          # MiB
    total: float                         # MiB
    name: str = ""


@dataclass
class Node:
    name: str
    state: str = ""
    cpus: int = 0
    alloc: int = 0
    load: float = 0.0
    mem_total: float = 0.0               # MiB
    mem_free: float = 0.0
    gres: str = ""
    gres_used: str = ""
    partitions: str = ""


@dataclass
class Partition:
    name: str
    avail: str = ""
    limit: str = ""
    nodes: int = 0
    nodes_aiot: str = ""                 # allocated/idle/other/total
    cpus_aiot: str = ""
    gpus: Dict[str, Dict[str, int]] = field(default_factory=dict)   # type -> total/used/down/free


@dataclass
class Finished:
    id: str
    name: str = ""
    state: str = ""
    elapsed: str = ""
    cpus: int = 0
    nodes: int = 1
    gpus: int = 0
    cpu_time: Optional[float] = None
    req_mem: float = 0.0
    rss: float = 0.0
    start: str = ""
    end: str = ""
    partition: str = ""
    exit: str = ""
    nodelist: str = ""
    submit: str = ""
    workdir: str = ""
    limit: str = ""

    @property
    def cpu_eff(self) -> Optional[float]:
        el = secs(self.elapsed) or 0
        return (self.cpu_time / (el * self.cpus)) if (self.cpu_time is not None and el and self.cpus) else None

    @property
    def mem_eff(self) -> Optional[float]:
        return (self.rss / self.req_mem) if self.req_mem else None

    @property
    def core_hours(self) -> float:
        return (secs(self.elapsed) or 0) * self.cpus / 3600

    @property
    def gpu_hours(self) -> float:
        return (secs(self.elapsed) or 0) * self.gpus / 3600


@dataclass
class Step:
    """One step of a running job (sstat) or of a finished one (sacct -j)."""
    id: str                          # 12345.batch, 12345.0 ...
    name: str = ""
    cpu_time: Optional[float] = None
    rss: float = 0.0                 # peak over tasks, bytes
    rss_task: str = ""               # the task and node holding the peak
    rss_node: str = ""
    ntasks: int = 0
    min_cpu: Optional[float] = None  # the least CPU time of any task: the slowest rank
    min_cpu_task: str = ""
    min_cpu_node: str = ""
    ave_rss: float = 0.0
    state: str = ""
    elapsed: str = ""
    exit: str = ""
    nodelist: str = ""


@dataclass
class NodeCell:
    """One node of the cluster-wide map (sinfo -N)."""
    name: str
    partitions: List[str] = field(default_factory=list)
    state: str = ""
    cpus_alloc: int = 0
    cpus_idle: int = 0
    cpus_other: int = 0
    cpus: int = 0
    mem: float = 0.0                 # MiB
    mem_alloc: float = 0.0
    gpu_type: str = ""
    gpus: int = 0
    gpus_used: int = 0

    @property
    def down(self) -> bool:
        return any(k in self.state for k in ("down", "drain", "drng", "fail", "maint", "inval")) or self.state.endswith("*")


@dataclass
class Health:
    name: str
    enabled: bool = True
    calls: int = 0
    errors: int = 0
    last_ok: float = 0.0
    last_try: float = 0.0
    latency_ms: float = 0.0
    error: str = ""
    backoff: float = 0.0
    inflight: bool = False


def to_plain(obj):
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return {str(k): to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, collections.deque)):
        return [to_plain(v) for v in obj]
    return obj


# ------------------------------------------------------------------------------------------------ the store
class Store:
    """Everything the screen reads; updated by the sampler under a lock.  ``snapshot()`` is a shallow copy."""

    def __init__(self, state_dir: Optional[str] = None, persist: bool = True, max_events: int = 200, series_keep: int = 4000):
        self.lock = threading.RLock()
        self.jobs: List[Job] = []
        self.live: Dict[str, Live] = {}
        self.gpu: Dict[str, Optional[List[GpuSample]]] = {}
        self.nodes: Dict[str, Node] = {}
        self.partitions: List[Partition] = []
        self.gpu_inventory: Dict[str, Dict[str, int]] = {}
        self.finished: List[Finished] = []
        self.share: List[dict] = []
        self.account: dict = {}
        self.group: List[Job] = []                         # everyone's jobs in the account
        self.weather: List[dict] = []                      # queue weather probes (partition, gres, pending ahead, projected start)
        self.pending_ahead: Dict[str, dict] = {}           # partition -> pending jobs / cpus / gpus cluster-wide
        self.budget: dict = {}                             # the account's allocation: used, limit, burn rate
        self.nodemap: Dict[str, NodeCell] = {}             # every node of the cluster
        self.steps: Dict[str, List[Step]] = {}             # per running job, from sstat
        self.fin_steps: Dict[str, List[Step]] = {}         # per finished job, from sacct -j (on demand)
        self.trace: Dict[str, List[dict]] = {}             # per job, the GPU trace CSV written inside the job (t, index, util, mem)
        self.details: Dict[str, dict] = {}
        self.health: Dict[str, Health] = {}
        self.events: Deque[dict] = collections.deque(maxlen=max_events)
        self.hist_cpu: Dict[str, Deque[float]] = collections.defaultdict(lambda: collections.deque(maxlen=600))
        self.hist_gpu: Dict[str, Deque[float]] = collections.defaultdict(lambda: collections.deque(maxlen=600))
        self.series: Dict[str, Deque[dict]] = collections.defaultdict(lambda: collections.deque(maxlen=series_keep))
        self.series_keep = series_keep
        self._series_loaded: set = set()
        self.gpu_mean: Dict[str, List[float]] = collections.defaultdict(lambda: [0.0, 0])
        self.prev_cpu: Dict[str, tuple] = {}
        self.seen: Dict[str, str] = {}                     # id -> last state seen (for transitions)
        self.names: Dict[str, str] = {}
        self.t_jobs = 0.0
        self.error = ""
        self.tags: Dict[str, dict] = {}                   # job id -> {"tags": [...], "pinned": bool, "note": ""}
        self.alerts = None                                 # the AlertEngine (set by the cli)
        self.state_dir = state_dir
        self.persist = persist and bool(state_dir)
        if self.persist:
            os.makedirs(state_dir, exist_ok=True)
            self._load_events()
            self._load_tags()

    # ---- tags, pins, notes ---------------------------------------------------------------------------
    def _load_tags(self):
        try:
            with open(os.path.join(self.state_dir, "tags.json")) as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.tags = {k: v for k, v in data.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            pass

    def _save_tags(self):
        if not self.persist:
            return
        try:
            with open(os.path.join(self.state_dir, "tags.json"), "w") as f:
                json.dump(self.tags, f)
        except OSError:
            pass

    def tag(self, jid: str, *tags: str, remove: bool = False) -> List[str]:
        with self.lock:
            rec = self.tags.setdefault(jid, dict(tags=[], pinned=False, note=""))
            for t in tags:
                t = t.lstrip("#").strip()
                if not t:
                    continue
                if remove:
                    rec["tags"] = [x for x in rec["tags"] if x != t]
                elif t not in rec["tags"]:
                    rec["tags"].append(t)
            if not rec["tags"] and not rec["pinned"] and not rec["note"]:
                del self.tags[jid]
                rec = dict(tags=[])
        self._save_tags()
        return list(rec["tags"])

    def pin(self, jid: str, value: Optional[bool] = None) -> bool:
        with self.lock:
            rec = self.tags.setdefault(jid, dict(tags=[], pinned=False, note=""))
            rec["pinned"] = (not rec["pinned"]) if value is None else bool(value)
            out = rec["pinned"]
            if not rec["tags"] and not rec["pinned"] and not rec["note"]:
                del self.tags[jid]
        self._save_tags()
        return out

    def note(self, jid: str, text: str) -> str:
        with self.lock:
            rec = self.tags.setdefault(jid, dict(tags=[], pinned=False, note=""))
            rec["note"] = text.strip()
            if not rec["tags"] and not rec["pinned"] and not rec["note"]:
                del self.tags[jid]
        self._save_tags()
        return text.strip()

    def tags_of(self, jid: str) -> List[str]:
        return list(self.tags.get(jid, {}).get("tags", []))

    def pinned(self, jid: str) -> bool:
        return bool(self.tags.get(jid, {}).get("pinned"))

    def tag_map(self) -> Dict[str, List[str]]:
        return {k: list(v.get("tags", [])) for k, v in self.tags.items()}

    # ---- events ------------------------------------------------------------------------------------
    def event(self, kind: str, text: str, job: Optional[Job] = None, **extra) -> dict:
        ev = dict(t=clock.now(), kind=kind, text=text, job=(job.id if job else extra.pop("job_id", "")),
                  name=(job.name if job else extra.pop("name", "")), **extra)
        with self.lock:
            self.events.append(ev)
        if self.persist:
            try:
                with open(os.path.join(self.state_dir, "events.jsonl"), "a") as f:
                    f.write(json.dumps(ev) + "\n")
            except OSError:
                pass
        return ev

    def _load_events(self):
        path = os.path.join(self.state_dir, "events.jsonl")
        try:
            with open(path) as f:
                lines = collections.deque(f, maxlen=self.events.maxlen)
        except OSError:
            return
        for line in lines:
            try:
                ev = json.loads(line)
                if not isinstance(ev, dict):
                    continue
                ev["old"] = True
                self.events.append(ev)
            except ValueError:
                pass

    # ---- transitions -------------------------------------------------------------------------------
    def apply_jobs(self, jobs: Sequence[Job]) -> List[dict]:
        """Store a fresh squeue listing; returns the transition events (queued, started, finished, held, released)."""
        out = []
        with self.lock:
            now = {j.id: j for j in jobs}
            first = not self.seen and not self.names
            for j in jobs:
                prev = self.seen.get(j.id)
                if prev is None and not first:
                    out.append(self.event("queued" if j.pending else "started", f"{'queued' if j.pending else 'started'} {j.id} {j.name}", j))
                elif prev == "PENDING" and not j.pending:
                    out.append(self.event("started", f"started {j.id} {j.name}", j))
                elif prev is not None and prev != j.state and not j.pending and j.state in ("COMPLETING", "SUSPENDED"):
                    out.append(self.event("state", f"{j.state.lower()} {j.id} {j.name}", j))
                if prev is not None:
                    was_held = self.seen.get(j.id + ":held") == "1"
                    if j.held and not was_held:
                        out.append(self.event("held", f"held {j.id} {j.name}", j))
                    elif was_held and not j.held:
                        out.append(self.event("released", f"released {j.id} {j.name}", j))
                self.seen[j.id + ":held"] = "1" if j.held else "0"
            for jid, st in list(self.seen.items()):
                if ":" in jid:
                    continue
                if jid not in now:
                    kind = "finished" if st != "PENDING" else "left"
                    out.append(self.event(kind, f"{'finished' if kind == 'finished' else 'left queue'} {jid} {self.names.get(jid, '')}", job_id=jid, name=self.names.get(jid, "")))
                    del self.seen[jid]
                    self.seen.pop(jid + ":held", None)
                    self.live.pop(jid, None)
                    self.gpu.pop(jid, None)
                    self.prev_cpu.pop(jid, None)
            for j in jobs:
                self.seen[j.id] = j.state
                self.names[j.id] = j.name
            # keep the projected starts already known
            old = {j.id: j.est_start for j in self.jobs}
            for j in jobs:
                if not j.est_start:
                    j.est_start = old.get(j.id, "")
            self.jobs = list(jobs)
            self.t_jobs = clock.now()
        return out

    def apply_starts(self, starts: Dict[str, str]):
        with self.lock:
            for j in self.jobs:
                if j.id in starts:
                    j.est_start = starts[j.id]

    # ---- per-job time series -----------------------------------------------------------------------
    def _series_path(self, jid: str) -> Optional[str]:
        if not self.persist:
            return None
        safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in jid)
        return os.path.join(self.state_dir, "series", f"{safe}.jsonl")

    def record(self, jid: str, sample: dict):
        """Append one sample {t, ...} to the job's series in memory and on disk."""
        with self.lock:
            self.series[jid].append(sample)
        path = self._series_path(jid)
        if path:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "a") as f:
                    f.write(json.dumps(sample) + "\n")
            except OSError:
                pass

    def series_of(self, jid: str) -> List[dict]:
        """The job's samples, oldest first: what this session recorded plus what earlier sessions left on disk."""
        with self.lock:
            if jid not in self._series_loaded:
                self._series_loaded.add(jid)
                path = self._series_path(jid)
                if path and os.path.exists(path):
                    try:
                        old = collections.deque(maxlen=self.series_keep)
                        with open(path) as f:
                            for line in f:
                                try:
                                    sample = json.loads(line)
                                except ValueError:
                                    continue  # Preserve valid history after a truncated final write.
                                if isinstance(sample, dict):
                                    old.append(sample)
                    except OSError:
                        old = []
                    mem = list(self.series[jid])
                    seen = {(s.get("t"), s.get("k")) for s in mem}
                    merged = [s for s in old if (s.get("t"), s.get("k")) not in seen] + mem
                    merged.sort(key=lambda s: s.get("t", 0))
                    self.series[jid] = collections.deque(merged[-self.series_keep:], maxlen=self.series_keep)
            return list(self.series[jid])

    def series_jobs(self) -> List[str]:
        """Job ids with a series on disk or in memory."""
        ids = set(self.series)
        if self.persist:
            d = os.path.join(self.state_dir, "series")
            try:
                ids.update(f[:-6] for f in os.listdir(d) if f.endswith(".jsonl"))
            except OSError:
                pass
        return sorted(ids)

    def apply_live(self, jid: str, lv: Live):
        with self.lock:
            self.live[jid] = lv
            value = lv.rate if lv.rate is not None else lv.avg
            if value is not None:
                self.hist_cpu[jid].append(value)
        if lv.cpu_time is not None:
            self.record(jid, dict(t=round(lv.t, 1), k="live", cpu=lv.rate, eff=lv.avg, rss=lv.rss, cpu_time=lv.cpu_time))

    def apply_gpu(self, jid: str, samples: Optional[List[GpuSample]]):
        with self.lock:
            self.gpu[jid] = samples
            for s in samples or []:
                key = f"{jid}:{s.node}:{s.index}"
                self.hist_gpu[key].append(s.util / 100.0)
                m = self.gpu_mean[key]
                m[0] += s.util
                m[1] += 1
        if samples:
            self.record(jid, dict(t=round(clock.now(), 1), k="gpu", gpu={f"{s.node}:{s.index}": [s.util, s.used, s.total] for s in samples}))

    def gpu_mean_of(self, key: str) -> Optional[float]:
        m = self.gpu_mean.get(key)
        return (m[0] / m[1]) if m and m[1] else None

    def job(self, jid: str) -> Optional[Job]:
        with self.lock:
            for j in self.jobs:
                if j.id == jid:
                    return j
        return None

    def snapshot(self) -> dict:
        with self.lock:
            return dict(jobs=list(self.jobs), live=dict(self.live), gpu=dict(self.gpu), nodes=dict(self.nodes), partitions=list(self.partitions),
                        gpu_inventory=dict(self.gpu_inventory), finished=list(self.finished), share=list(self.share), account=dict(self.account),
                        details=dict(self.details), health={k: Health(**asdict(v)) for k, v in self.health.items()}, events=list(self.events),
                        group=list(self.group), weather=list(self.weather), pending_ahead=dict(self.pending_ahead), budget=dict(self.budget),
                        nodemap=dict(self.nodemap), steps=dict(self.steps), fin_steps=dict(self.fin_steps), trace=dict(self.trace),
                        tags={k: dict(v) for k, v in self.tags.items()},
                        hist_cpu={k: list(v) for k, v in self.hist_cpu.items()}, hist_gpu={k: list(v) for k, v in self.hist_gpu.items()},
                        gpu_mean={k: (v[0] / v[1] if v[1] else None) for k, v in self.gpu_mean.items()}, t_jobs=self.t_jobs, error=self.error)

    # ---- ui state persistence ----------------------------------------------------------------------
    def load_ui(self) -> dict:
        if not self.persist:
            return {}
        try:
            with open(os.path.join(self.state_dir, "ui.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save_ui(self, data: dict):
        if not self.persist:
            return
        try:
            with open(os.path.join(self.state_dir, "ui.json"), "w") as f:
                json.dump(data, f)
        except OSError:
            pass
