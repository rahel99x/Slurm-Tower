"""The Slurm command layer: one place that runs squeue / sstat / sacct / scontrol / sinfo / sshare / scancel and
parses their output into records, plus a simulated backend (``--fake``) that answers the same commands from a
small cluster that evolves in time, so the parsers, the screen and the tests all exercise one code path."""
from __future__ import annotations

import os
import re
import subprocess
import time
from typing import Dict, List, Optional, Sequence, Tuple

from .model import Finished, GpuSample, Job, Live, Node, NodeCell, Partition, Step, fint, fnum, gres_gpus, gpus_in_tres, hms, nbytes, secs, stamp

JOB_FMT = "%i|%j|%P|%T|%M|%l|%D|%C|%b|%N|%m|%S|%V|%r|%Q|%E|%a|%q|%e|%o"
START_FMT = "%i|%S"
GROUP_FMT = "%i|%u|%j|%P|%T|%M|%l|%D|%C|%b|%r|%Q|%N|%V|%S"
PEND_FMT = "%P|%C|%b|%D"
SACCT_FIELDS = "JobID,JobName,State,Elapsed,AllocCPUS,TotalCPU,ReqMem,MaxRSS,Start,End,Partition,NNodes,ExitCode,AllocTRES,NodeList,Submit,WorkDir,Timelimit"
SSTAT_FIELDS = "JobID,AveCPU,MaxRSS,MaxRSSTask,MaxRSSNode,AveRSS,NTasks,MinCPU,MinCPUTask,MinCPUNode"
SACCT_STEP_FIELDS = "JobID,JobName,State,Elapsed,TotalCPU,MaxRSS,MaxRSSNode,MaxRSSTask,NTasks,ExitCode,NodeList"
SACCT_SUBMIT_FIELDS = "JobID,SubmitLine,WorkDir,JobName,Partition,Account,QOS,ReqCPUS,ReqMem,Timelimit,NNodes,ReqTRES"
SINFO_NODE_FMT = "NodeList:24,Partition:20,Gres:60,GresUsed:60,StateCompact:14,CPUsState:16,Memory:12,AllocMem:12"
NVSMI = ["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used,memory.total,name", "--format=csv,noheader,nounits"]


class CommandError(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------------ backends
class Backend:
    """Runs a command; returns (stdout, latency seconds).  Raises CommandError on failure or timeout."""

    def run(self, cmd: Sequence[str], timeout: float = 8.0) -> Tuple[str, float]:
        t0 = time.perf_counter()
        try:
            r = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            raise CommandError(f"{cmd[0]}: not found")
        except subprocess.TimeoutExpired:
            raise CommandError(f"{cmd[0]}: timed out after {timeout:g}s")
        except OSError as e:
            raise CommandError(f"{cmd[0]}: {e}")
        dt = time.perf_counter() - t0
        if r.returncode != 0:
            raise CommandError(f"{cmd[0]} exit {r.returncode}: {(r.stderr or r.stdout).strip()[:200]}")
        return r.stdout, dt

    def call(self, cmd: Sequence[str], timeout: float = 15.0) -> Tuple[bool, str]:
        """An action: (ok, combined output)."""
        try:
            r = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
            return r.returncode == 0, (r.stdout + r.stderr).strip()
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, str(e)


class FakeBackend(Backend):
    """A small cluster that evolves with the wall clock: jobs start, finish, get cancelled or held, GPU load
    breathes.  Answers the exact commands the real layer issues, as text, so every parser runs."""

    def __init__(self, user: str = "alex", t0: Optional[float] = None, speed: float = 1.0):
        self.user, self.t0, self.speed = user, (time.time() if t0 is None else t0), speed
        self.cancelled: Dict[str, float] = {}
        self.held: set = set()
        self.calls: List[List[str]] = []
        self.day = time.strftime("%Y-%m-%d")
        T = lambda off: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.t0 + off))
        # id, name, partition, submit offset, start offset (None: pending), duration, cpus, gpus type, count, nodes, mem, limit, reason, dep
        self.spec = [
            dict(id="12477369", name="rb-setup", part="gpu", submit=-3600, start=-1041, dur=5400, cpus=8, gt="a100", gn=1, nodes=1, mem="32G", limit="01:30:00", node="a01-05", prio=12000),
            dict(id="12480001", name="rb1-allrank", part="main", submit=-7200, start=-3730, dur=43200, cpus=32, gt="", gn=0, nodes=1, mem="64G", limit="12:00:00", node="e05-12", prio=11000),
            dict(id="12480004", name="rb7-scale", part="gpu", submit=-600, start=-120, dur=20, cpus=16, gt="a100", gn=2, nodes=2, mem="64G", limit="12:00:00", node="a02-[01-02]", prio=10500),
            dict(id="12480002_[0-7]", name="rb1-panel", part="main", submit=-725, start=None, dur=3600, cpus=32, gt="", gn=0, nodes=1, mem="64G", limit="12:00:00", reason="Priority", prio=10234, est=3600, dep="afterany:12480003"),
            dict(id="12480003", name="rb2-controls", part="gpu", submit=-120, start=None, dur=3600, cpus=8, gt="a100", gn=1, nodes=1, mem="32G", limit="23:00:00", reason="Dependency", prio=10100, dep="afterok:12480001"),
            dict(id="12480005", name="rb5-selector", part="gpu", submit=-100, start=25, dur=3600, cpus=8, gt="a100", gn=1, nodes=1, mem="64G", limit="23:00:00", reason="Resources", prio=10050, node="a01-06"),
        ]
        self.others = [                                   # the rest of the account: id, user, name, partition, state, elapsed, limit, nodes, cpus, gres, reason, prio, node
            ("12470001", "bob", "md-run", "gpu", "RUNNING", 7200, "1-00:00:00", 1, 16, "gres/gpu:a100:2", "None", 9000, "a02-01"),
            ("12470002", "bob", "md-run", "gpu", "RUNNING", 3600, "1-00:00:00", 1, 16, "gres/gpu:a100:2", "None", 9000, "a02-02"),
            ("12470003", "carol", "dft", "main", "RUNNING", 86400, "2-00:00:00", 4, 64, "N/A", "None", 8000, "e05-[01-04]"),
            ("12470004", "carol", "dft-next", "main", "PENDING", 0, "2-00:00:00", 4, 64, "N/A", "Priority", 7000, ""),
            ("12470005", "bob", "md-post", "gpu", "PENDING", 0, "04:00:00", 1, 8, "gres/gpu:a40:1", "Resources", 6500, ""),
        ]
        self.done = [
            dict(id="12476001", name="rb-gpucheck", state="COMPLETED", elapsed="00:03:12", cpus=4, cpu="00:01:30", mem="16G", rss="1.1G", start=T(-5400), end=T(-5208), part="gpu", nodes=1, exit="0:0", tres="cpu=4,mem=16G,node=1,gres/gpu=1", nl="a01-05"),
            dict(id="12475990", name="rb-setup", state="TIMEOUT", elapsed="01:30:00", cpus=8, cpu="00:12:00", mem="32G", rss="2.3G", start=T(-14400), end=T(-9000), part="gpu", nodes=1, exit="0:0", tres="cpu=8,mem=32G,node=1,gres/gpu=1", nl="a01-05"),
            dict(id="12475980", name="rb3-identity", state="OUT_OF_MEMORY", elapsed="00:41:03", cpus=8, cpu="03:10:00", mem="32G", rss="31.9G", start=T(-18000), end=T(-15537), part="main", nodes=1, exit="0:125", tres="cpu=8,mem=32G,node=1", nl="e06-01"),
        ]

    # ---- simulated state ---------------------------------------------------------------------------
    def now(self) -> float:
        return (time.time() - self.t0) * self.speed

    def _ts(self, offset: float) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.t0 + offset))

    @staticmethod
    def _before(ts: str, seconds: float) -> str:
        t = stamp(ts)
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t - seconds)) if t else "Unknown"

    def _rows(self):
        t = self.now()
        rows = []
        for s in self.spec:
            if s["id"] in self.cancelled:
                continue
            start = s["start"]
            if start is None or t < start:
                state = "PENDING"
                elapsed = 0.0
            elif t < start + s["dur"]:
                state = "RUNNING"
                elapsed = t - start
            else:
                continue                                    # finished
            rows.append((s, state, elapsed))
        return rows

    def _finished_rows(self):
        t = self.now()
        out = list(self.done)
        for s in self.spec:
            start = s["start"]
            if s["id"] in self.cancelled:
                c = self.cancelled[s["id"]]
                el = max(0.0, c - start) if start is not None and c > start else 0.0
                out.append(dict(id=s["id"], name=s["name"], state="CANCELLED by 1000", elapsed=hms(el), cpus=s["cpus"], cpu=hms(el * 0.3), mem=s["mem"], rss="1.0G",
                                start=self._ts(start) if start is not None else "None", end=self._ts(c), part=s["part"], nodes=s["nodes"], exit="0:0",
                                tres=f"cpu={s['cpus']},mem={s['mem']},node={s['nodes']}" + (f",gres/gpu={s['gn'] * s['nodes']}" if s["gn"] else ""), nl=s.get("node", "None"),
                                submit=self._ts(s["submit"]), limit=s["limit"]))
            elif start is not None and t >= start + s["dur"]:
                out.append(dict(id=s["id"], name=s["name"], state="COMPLETED", elapsed=hms(s["dur"]), cpus=s["cpus"], cpu=hms(s["dur"] * 0.6), mem=s["mem"], rss="4.2G",
                                start=self._ts(start), end=self._ts(start + s["dur"]), part=s["part"], nodes=s["nodes"], exit="0:0",
                                tres=f"cpu={s['cpus']},mem={s['mem']},node={s['nodes']}" + (f",gres/gpu={s['gn'] * s['nodes']}" if s["gn"] else ""), nl=s.get("node", ""),
                                submit=self._ts(s["submit"]), limit=s["limit"]))
        return out

    # ---- the commands ------------------------------------------------------------------------------
    def run(self, cmd: Sequence[str], timeout: float = 8.0) -> Tuple[str, float]:
        cmd = list(cmd)
        self.calls.append(cmd)
        name = os.path.basename(cmd[0])
        t = self.now()
        if name == "squeue":
            if "--start" in cmd:
                lines = [f"{s['id']}|{self._ts(s['start']) if s.get('start') is not None else (self._ts(s['est']) if s.get('est') else 'N/A')}"
                         for s, state, _ in self._rows() if state == "PENDING"]
                return "\n".join(lines) + ("\n" if lines else ""), 0.01
            fmt = cmd[cmd.index("-o") + 1] if "-o" in cmd else ""
            if fmt == GROUP_FMT:                            # everyone in the account
                lines = []
                for s, state, elapsed in self._rows():
                    gres = f"gres/gpu:{s['gt']}:{s['gn']}" if s["gn"] else "N/A"
                    reason = ("JobHeldUser" if s["id"] in self.held else s.get("reason", "None")) if state == "PENDING" else "None"
                    lines.append("|".join([s["id"], self.user, s["name"], s["part"], state, hms(elapsed) if state == "RUNNING" else "0:00", s["limit"], str(s["nodes"]), str(s["cpus"]),
                                           gres, reason, str(s["prio"]), s.get("node", "") if state == "RUNNING" else "", self._ts(s["submit"]),
                                           self._ts(s["start"]) if state == "RUNNING" else "N/A"]))
                for (i, u, n, p, st, el, lim, nn, c, g, r, pr, nd) in self.others:
                    lines.append("|".join([i, u, n, p, st, hms(el + t) if st == "RUNNING" else "0:00", lim, str(nn), str(c), g, r, str(pr), nd, self._ts(-el - 600),
                                           self._ts(-el) if st == "RUNNING" else "N/A"]))
                return "\n".join(lines) + "\n", 0.03
            if fmt == PEND_FMT:                             # cluster-wide pending
                lines = [f"{s['part']}|{s['cpus']}|{('gres/gpu:' + s['gt'] + ':' + str(s['gn'])) if s['gn'] else 'N/A'}|{s['nodes']}" for s, state, _ in self._rows() if state == "PENDING"]
                lines += [f"{p}|{c}|{g}|{nn}" for (i, u, n, p, st, el, lim, nn, c, g, r, pr, nd) in self.others if st == "PENDING"]
                lines += ["gpu|8|gres/gpu:a100:1|1"] * 6 + ["main|32|N/A|1"] * 20 + ["gpu|16|gres/gpu:a40:2|1"] * 2
                return "\n".join(lines) + "\n", 0.05
            if "-A" in cmd:
                want = cmd[cmd.index("-t") + 1] if "-t" in cmd else "R"
                lines = [f"{s['cpus']}|{('gres/gpu:' + s['gt'] + ':' + str(s['gn'])) if s['gn'] else 'N/A'}|{s['nodes']}"
                         for s, state, _ in self._rows() if (state == "RUNNING") == (want == "R")]
                return "\n".join(lines) + ("\n" if lines else ""), 0.01
            lines = []
            for s, state, elapsed in self._rows():
                pending = state == "PENDING"
                held = s["id"] in self.held
                reason = ("JobHeldUser" if held else s.get("reason", "None")) if pending else "None"
                gres = f"gres/gpu:{s['gt']}:{s['gn']}" if s["gn"] else "N/A"
                lines.append("|".join([s["id"], s["name"], s["part"], state, hms(elapsed) if not pending else "0:00", s["limit"], str(s["nodes"]), str(s["cpus"]), gres,
                                       s.get("node", "") if not pending else "", s["mem"], self._ts(s["start"]) if s.get("start") is not None and not pending else "N/A",
                                       self._ts(s["submit"]), reason, str(s["prio"]), s.get("dep", "(null)") or "(null)", "lab_01", "normal",
                                       self._ts(s["start"] + secs(s["limit"])) if s.get("start") is not None and not pending else "N/A",
                                       f"/home/{self.user}/jobs/{s['name'].split('_')[0]}.sbatch"]))
            return "\n".join(lines) + ("\n" if lines else ""), 0.02
        if name == "sstat":
            jid = cmd[cmd.index("-j") + 1]
            for s, state, elapsed in self._rows():
                if s["id"] == jid and state == "RUNNING":
                    frac = 0.3 if s["gn"] else 0.85
                    cpu = elapsed * s["cpus"] * frac
                    rss = nbytes(s["mem"]) * (0.1 + 0.3 * min(1.0, elapsed / 3600)) / 1024
                    node = s.get("node", "n").split("[")[0].rstrip("-") + ("-01" if "[" in s.get("node", "") else "")
                    lines = [f"{jid}.extern|00:00:00|1200K|0|{node}|1200K|{s['nodes']}|00:00:00|0|{node}",
                             f"{jid}.batch|{hms(cpu)}|{rss:.0f}K|0|{node}|{rss * 0.8:.0f}K|1|{hms(cpu)}|0|{node}"]
                    if s["nodes"] > 1:                      # a multi-node step with a slow rank
                        lines.append(f"{jid}.0|{hms(cpu * 0.9)}|{rss * 0.7:.0f}K|3|{node[:-2]}02|{rss * 0.5:.0f}K|{s['nodes'] * 2}|{hms(cpu * 0.4)}|3|{node[:-2]}02")
                    return "\n".join(lines) + "\n", 0.05
            raise CommandError("sstat: no steps running")
        if name == "srun":
            jid = cmd[cmd.index("--jobid") + 1]
            for s, state, elapsed in self._rows():
                if s["id"] == jid and state == "RUNNING" and s["gn"]:
                    if elapsed < 10:
                        raise CommandError("srun: job step creation temporarily disabled")
                    lines = []
                    for task in range(s["nodes"]):
                        for i in range(s["gn"]):
                            util = 50 + 45 * abs(((t / 7 + i + task) % 2) - 1)
                            lines.append(f"{task}: {i}, {util:.0f}, {12390 + 900 * i}, 40960, NVIDIA A100-SXM4-40GB")
                    return "\n".join(lines) + "\n", 0.3
            raise CommandError("srun: no allocation")
        if name == "scontrol":
            if "hostnames" in cmd:
                nl = cmd[-1]
                m = re.match(r"^(.*)\[(\d+)-(\d+)\]$", nl)
                if m:
                    a, b = int(m.group(2)), int(m.group(3))
                    width = len(m.group(2))
                    return "\n".join(f"{m.group(1)}{i:0{width}d}" for i in range(a, b + 1)) + "\n", 0.01
                return nl + "\n", 0.01
            if "node" in cmd:
                n = cmd[cmd.index("node") + 1]
                load = 7.9 if n.startswith("e") else 12.4
                gres = "gpu:a100:2(S:0-1)" if n.startswith("a") else "(null)"
                used = "gpu:a100:1(IDX:0)" if n.startswith("a") else "gpu:0"
                return (f"NodeName={n} Arch=x86_64 CoresPerSocket=32 CPUAlloc=8 CPUTot=64 CPULoad={load} AvailableFeatures=xeon Gres={gres} "
                        f"NodeAddr={n} RealMemory=257000 AllocMem=32768 FreeMem=210000 State=MIXED Partitions={'gpu' if n.startswith('a') else 'main'} "
                        f"GresUsed={used}\n"), 0.02
            if "job" in cmd:
                jid = cmd[-1]
                for s, state, elapsed in self._rows():
                    if s["id"] == jid:
                        out = os.path.join(os.getcwd(), "logs", f"{s['name'].split('_')[0]}-{jid}.out")
                        return (f"JobId={jid} JobName={s['name']} UserId={self.user}(1000) GroupId={self.user}(1000) Priority={s['prio']} Account=lab_01 QOS=normal "
                                f"JobState={state} Reason={'None' if state == 'RUNNING' else s.get('reason', 'None')} Dependency={s.get('dep', '(null)') or '(null)'} "
                                f"RunTime={hms(elapsed)} TimeLimit={s['limit']} SubmitTime={self._ts(s['submit'])} StartTime={self._ts(s['start']) if s.get('start') is not None else 'Unknown'} "
                                f"Partition={s['part']} NodeList={s.get('node', '(null)') if state == 'RUNNING' else '(null)'} NumNodes={s['nodes']} NumCPUs={s['cpus']} "
                                f"TRES=cpu={s['cpus']},mem={s['mem']},node={s['nodes']}" + (f",gres/gpu={s['gn'] * s['nodes']}" if s["gn"] else "") +
                                f" Command=/home/{self.user}/jobs/{s['name'].split('_')[0]}.sbatch WorkDir={os.getcwd()} "
                                f"StdErr={out} StdOut={out}\n"), 0.03
                raise CommandError(f"scontrol: Invalid job id specified {jid}")
        if name == "sacct":
            wd = os.getcwd()
            if "-j" in cmd and "SubmitLine" in " ".join(cmd):   # the submit line of one job
                jid = cmd[cmd.index("-j") + 1]
                for s in self.spec:
                    if s["id"] == jid:
                        gres = f",gres/gpu={s['gn']},gres/gpu:{s['gt']}={s['gn']}" if s["gn"] else ""
                        line = f"sbatch jobs/{s['name'].split('_')[0].replace('-', '_')}.sbatch" if s.get("submit_line") is None else s["submit_line"]
                        return f"{jid}|{line}|{wd}|{s['name']}|{s['part']}|lab_01|normal|{s['cpus']}|{s['mem']}|{s['limit']}|{s['nodes']}|cpu={s['cpus']},mem={s['mem']},node={s['nodes']}{gres}\n{jid}.batch|||||||||||\n", 0.1
                for f in self._finished_rows():
                    if f["id"] == jid:
                        line = f"sbatch jobs/{f['name'].split('_')[0].replace('-', '_')}.sbatch"
                        return f"{jid}|{line}|{wd}|{f['name']}|{f['part']}|lab_01|normal|{f['cpus']}|{f['mem']}|{f.get('limit', '02:00:00')}|{f['nodes']}|{f['tres']}\n", 0.1
                return "", 0.1
            if "-j" in cmd:                                 # the steps of one finished job
                jid = cmd[cmd.index("-j") + 1]
                for f in self._finished_rows():
                    if f["id"] == jid:
                        st = f["state"].split()[0]
                        return (f"{jid}|{f['name']}|{st}|{f['elapsed']}|{f['cpu']}||||{f['nodes']}|{f['exit']}|{f['nl']}\n"
                                f"{jid}.batch|batch|{st}|{f['elapsed']}|{f['cpu']}|{f['rss']}|{f['nl'].split('[')[0]}|0|1|{f['exit']}|{f['nl']}\n"
                                f"{jid}.extern|extern|COMPLETED|{f['elapsed']}|00:00:00|1200K|{f['nl'].split('[')[0]}|0|{f['nodes']}|0:0|{f['nl']}\n"), 0.1
                return "", 0.1
            lines = []
            for f in self._finished_rows():
                sub = f.get("submit") or self._before(f["start"], 600)
                lim = f.get("limit", {"TIMEOUT": f["elapsed"]}.get(f["state"], "02:00:00"))
                lines.append("|".join([f["id"], f["name"], f["state"], f["elapsed"], str(f["cpus"]), f["cpu"], f["mem"], "", f["start"], f["end"], f["part"], str(f["nodes"]), f["exit"], f["tres"], f["nl"], sub, wd, lim]))
                lines.append("|".join([f["id"] + ".batch", "batch", f["state"].split()[0], f["elapsed"], str(f["cpus"]), f["cpu"], "", f["rss"], f["start"], f["end"], f["part"], str(f["nodes"]), f["exit"], f["tres"], f["nl"], sub, wd, lim]))
            for s, state, elapsed in self._rows():
                if state == "RUNNING":
                    lines.append("|".join([s["id"], s["name"], "RUNNING", hms(elapsed), str(s["cpus"]), "00:00:00", s["mem"], "", self._ts(s["start"]), "Unknown", s["part"], str(s["nodes"]), "0:0", "", s.get("node", ""), self._ts(s["submit"]), wd, s["limit"]]))
            return "\n".join(lines) + "\n", 0.2
        if name == "sinfo":
            if "-N" in cmd:
                return ("a01-05 gpu gpu:a100:2(S:0-1) gpu:a100:2(IDX:0-1) mix 24/40/0/64 257000 65536\n"
                        "a01-06 gpu gpu:a100:2(S:0-1) gpu:a100:0(IDX:N/A) idle 0/64/0/64 257000 0\n"
                        "a02-01 gpu gpu:a100:2(S:0-1) gpu:a100:2(IDX:0-1) alloc 64/0/0/64 257000 257000\n"
                        "a02-02 gpu gpu:a100:2(S:0-1) gpu:a100:2(IDX:0-1) alloc 64/0/0/64 257000 257000\n"
                        "b01-01 gpu gpu:a40:4(S:0-1) gpu:a40:3(IDX:0-2) mix 48/16/0/64 515000 300000\n"
                        "b01-02 gpu gpu:a40:4(S:0-1) gpu:a40:0(IDX:N/A) drain 0/0/64/64 515000 0\n"
                        "c01-01 gpu gpu:a30:4(S:0-1) gpu:a30:1(IDX:0) mix 8/56/0/64 257000 32000\n"
                        "e05-12 main (null) (null) mix 32/32/0/64 257000 65536\n"
                        "e05-12 debug (null) (null) mix 32/32/0/64 257000 65536\n"
                        "e05-01 main (null) (null) alloc 64/0/0/64 257000 257000\n"
                        "e05-02 main (null) (null) alloc 64/0/0/64 257000 257000\n"
                        "e05-03 main (null) (null) alloc 64/0/0/64 257000 257000\n"
                        "e05-04 main (null) (null) alloc 64/0/0/64 257000 257000\n"
                        "e06-01 main (null) (null) idle 0/64/0/64 257000 0\n"
                        "e06-02 main (null) (null) down* 0/0/64/64 257000 0\n"
                        "l01-01 largemem (null) (null) idle 0/64/0/64 1030000 0\n"), 0.1
            return ("gpu|up|2-00:00:00|7|4/1/2/7|300/148/64/512\n"
                    "main|up|2-00:00:00|400|312/70/18/400|18000/6000|1600/25600\n"
                    "debug|up|01:00:00|4|1/3/0/4|64/192/0/256\n"
                    "largemem|up|7-00:00:00|8|2/6/0/8|256/768/0/1024\n"), 0.05
        if name == "sshare":
            return "lab_01|0.123456|0.421000\nother_12|0.001000|0.900000\n", 0.05
        if name == "sreport":
            week = any("start=now-7days" in c for c in cmd)
            if week:
                return "lab_01||cpu|2100\nlab_01||gres/gpu|260\nlab_01|alex|cpu|900\nlab_01|alex|gres/gpu|120\nlab_01|bob|cpu|1200\nlab_01|bob|gres/gpu|140\n", 0.3
            return "lab_01||cpu|38400\nlab_01||gres/gpu|4100\nlab_01|alex|cpu|12400\nlab_01|alex|gres/gpu|1700\nlab_01|bob|cpu|20000\nlab_01|bob|gres/gpu|2400\nlab_01|carol|cpu|6000\nlab_01|carol|gres/gpu|0\n", 0.3
        if name == "sacctmgr":
            return "lab_01||cpu=6000000,gres/gpu=600000|\n", 0.1
        raise CommandError(f"fake backend: unknown command {name}")

    def call(self, cmd: Sequence[str], timeout: float = 15.0) -> Tuple[bool, str]:
        cmd = list(cmd)
        self.calls.append(cmd)
        if cmd[:2] == ["sh", "-c"] and "sbatch" in cmd[2]:    # cd <workdir> && sbatch ...
            import shlex as _shlex
            words = _shlex.split(cmd[2])
            cmd = words[words.index("sbatch"):]
        name = os.path.basename(cmd[0])
        ids = [c for c in cmd[1:] if c[:1].isdigit()]
        known = {s["id"] for s in self.spec}
        if name == "sbatch" and "--test-only" not in cmd:
            from .resubmit import flags_of
            fl = flags_of(cmd[1:])
            new_id = str(12480100 + sum(1 for s in self.spec if s["id"].startswith("124801")))
            gres = fl.get("gres", "")
            gt, gn = ("", 0)
            if gres.startswith("gpu"):
                bits = gres.split(":")
                gt, gn = (bits[1] if len(bits) > 2 else ""), int(bits[-1]) if bits[-1].isdigit() else 1
            self.spec.append(dict(id=new_id, name=fl.get("name", os.path.basename(cmd[-1]).split(".")[0]), part=fl.get("partition", "main"), submit=self.now(), start=None, dur=3600,
                                  cpus=int(fl.get("cpus", "1")), gt=gt, gn=gn, nodes=int(fl.get("nodes", "1")), mem=fl.get("mem", "4G"), limit=fl.get("time", "01:00:00"),
                                  reason="Priority", prio=9000, est=1800, submit_line=" ".join(cmd), dep=fl.get("dependency", "")))
            return True, f"Submitted batch job {new_id}"
        if name == "scancel":
            for i in ids:
                if i not in known:
                    return False, f"scancel: error: Invalid job id {i}"
                self.cancelled[i] = self.now()
            return True, ""
        if name == "sbatch" and "--test-only" in cmd:
            part = cmd[cmd.index("-p") + 1] if "-p" in cmd else "main"
            gres = next((c.split("=", 1)[1] for c in cmd if c.startswith("--gres=")), "")
            wait = {"gpu": 2100, "main": 300, "debug": 30, "largemem": 60}.get(part, 600) * (2 if "a100" in gres else 1)
            return True, f"sbatch: Job 99999999 to start at {self._ts(self.now() + wait)} using {cmd[cmd.index('-c') + 1] if '-c' in cmd else 1} processors on nodes a01-06 in partition {part}"
        if name == "scontrol":
            verb = cmd[1]
            for i in ids:
                if i not in known:
                    return False, f"scontrol: error: Invalid job id specified {i}"
                if verb == "hold":
                    self.held.add(i)
                elif verb == "release":
                    self.held.discard(i)
                elif verb in ("requeue", "top"):
                    pass
                else:
                    return False, f"scontrol: unknown verb {verb}"
            return True, ""
        return False, f"fake backend: unknown action {name}"


# ------------------------------------------------------------------------------------------------ parsers
def parse_jobs(text: str) -> List[Job]:
    out = []
    for line in text.splitlines():
        f = line.split("|")
        if len(f) < 15:
            continue
        gtype, gcount = gres_gpus(f[8])
        nodes = fint(f[6]) or 1
        out.append(Job(id=f[0], name=f[1], partition=f[2], state=f[3], elapsed=f[4], limit=f[5], nodes=nodes, cpus=fint(f[7]), gpu_type=gtype,
                       gpus=gcount * nodes, nodelist="" if f[9].startswith("(") else f[9], mem_req=f[10], start=f[11], submit=f[12], reason=f[13],
                       priority=fint(f[14]), dependency=("" if len(f) < 16 or f[15] in ("(null)", "") else f[15]), account=f[16] if len(f) > 16 else "",
                       qos=f[17] if len(f) > 17 else "", end=f[18] if len(f) > 18 else "", command=f[19] if len(f) > 19 else ""))
    return out


def parse_group(text: str) -> List[Job]:
    """squeue -A <account> with GROUP_FMT: everyone's jobs, with the user."""
    out = []
    for line in text.splitlines():
        f = line.split("|")
        if len(f) < 12:
            continue
        gtype, gcount = gres_gpus(f[9])
        nodes = fint(f[7]) or 1
        out.append(Job(id=f[0], user=f[1], name=f[2], partition=f[3], state=f[4], elapsed=f[5], limit=f[6], nodes=nodes, cpus=fint(f[8]), gpu_type=gtype,
                       gpus=gcount * nodes, reason=f[10], priority=fint(f[11]), nodelist=f[12] if len(f) > 12 and not f[12].startswith("(") else "",
                       submit=f[13] if len(f) > 13 else "", start=f[14] if len(f) > 14 and f[14] != "N/A" else ""))
    return out


def parse_pending_ahead(text: str) -> Dict[str, dict]:
    """squeue -t PD cluster-wide with PEND_FMT -> partition -> jobs / cpus / gpus (per type) waiting."""
    out: Dict[str, dict] = {}
    for line in text.splitlines():
        f = line.split("|")
        if len(f) < 4:
            continue
        for part in f[0].split(","):
            d = out.setdefault(part, dict(jobs=0, cpus=0, gpus=0, by_type={}))
            d["jobs"] += 1
            d["cpus"] += fint(f[1])
            t, c = gres_gpus(f[2])
            n = c * (fint(f[3]) or 1)
            d["gpus"] += n
            if n:
                d["by_type"][t or "gpu"] = d["by_type"].get(t or "gpu", 0) + n
    return out


def parse_test_only(text: str) -> Tuple[Optional[str], str]:
    """'sbatch: Job 123 to start at 2026-10-01T07:00:00 using 8 processors on nodes a01-05 in partition gpu' -> (time, nodes)."""
    m = re.search(r"to start at (\S+)(?: using \d+ processors on nodes (\S+))?", text)
    if not m:
        return None, text.strip()[:120]
    return m.group(1), m.group(2) or ""


def parse_sreport(text: str) -> Dict[str, Dict[str, float]]:
    """sreport AccountUtilizationByUser -t hours format=Account,Login,TRESName,Used -> login ('' = the account) -> tres -> hours."""
    out: Dict[str, Dict[str, float]] = {}
    for line in text.splitlines():
        f = line.split("|")
        if len(f) < 4:
            continue
        tres = "gpu" if "gpu" in f[2] else f[2].strip()
        out.setdefault(f[1].strip(), {})[tres] = fnum(f[3])
    return out


def parse_tres_mins(text: str) -> Dict[str, float]:
    """sacctmgr show assoc format=Account,User,GrpTRESMins -> tres -> hours (the account-level association)."""
    out: Dict[str, float] = {}
    for line in text.splitlines():
        f = line.split("|")
        if len(f) < 3 or f[1].strip():
            continue
        for part in f[2].split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                out["gpu" if "gpu" in k else k.strip()] = fnum(v) / 60.0
    return out


def parse_steps(text: str, jid: str = "") -> List[Step]:
    """sstat with SSTAT_FIELDS -> one Step per line."""
    out = []
    for line in text.splitlines():
        f = line.split("|")
        if len(f) < 3:
            continue
        st = Step(id=f[0], name=f[0].split(".", 1)[1] if "." in f[0] else "", cpu_time=secs(f[1]), rss=nbytes(f[2]))
        if len(f) >= 10:
            st.rss_task, st.rss_node, st.ave_rss, st.ntasks = f[3], f[4], nbytes(f[5]), fint(f[6])
            st.min_cpu, st.min_cpu_task, st.min_cpu_node = secs(f[7]), f[8], f[9]
        out.append(st)
    return out


def parse_sacct_steps(text: str) -> List[Step]:
    """sacct -j <id> with SACCT_STEP_FIELDS -> the job line then its steps."""
    out = []
    for line in text.splitlines():
        f = line.split("|")
        if len(f) < 11:
            continue
        out.append(Step(id=f[0], name=f[1], state=f[2].split()[0] if f[2] else "", elapsed=f[3], cpu_time=secs(f[4]), rss=nbytes(f[5]), rss_node=f[6], rss_task=f[7],
                        ntasks=fint(f[8]), exit=f[9], nodelist=f[10]))
    return out


def parse_node_map(text: str) -> Dict[str, NodeCell]:
    """sinfo -N -O SINFO_NODE_FMT -> every node once, with its partitions, CPU state, memory and GPUs."""
    out: Dict[str, NodeCell] = {}
    for line in text.splitlines():
        f = line.split()
        if len(f) < 5:
            continue
        n = out.setdefault(f[0], NodeCell(name=f[0]))
        if f[1] not in n.partitions:
            n.partitions.append(f[1])
        n.state = f[4]
        t, c = gres_gpus("gres/" + f[2]) if f[2].startswith("gpu") else ("", 0)
        if c:
            n.gpu_type, n.gpus = t, c
            tu, cu = gres_gpus("gres/" + f[3]) if f[3].startswith("gpu") else ("", 0)
            n.gpus_used = cu if f[3].startswith("gpu") and not f[3].split("(")[0].endswith(":0") else 0
            if f[3].startswith("gpu") and f[3].split("(")[0].endswith(":0"):
                n.gpus_used = 0
        if len(f) >= 6 and f[5].count("/") == 3:
            a, i, o, tot = (fint(x) for x in f[5].split("/"))
            n.cpus_alloc, n.cpus_idle, n.cpus_other, n.cpus = a, i, o, tot
        if len(f) >= 7:
            n.mem = fnum(f[6])
        if len(f) >= 8:
            n.mem_alloc = fnum(f[7])
    return out


def parse_gpu_trace(data: bytes, max_rows: int = 20000) -> List[dict]:
    """The nvidia-smi CSV written inside a job (timestamp, index, utilization.gpu, memory.used; one line per GPU per
    minute) -> [{t, index, util, mem}] oldest first."""
    out = []
    text = data.decode("utf-8", "replace")
    for line in text.splitlines()[-max_rows:]:
        f = [x.strip() for x in line.split(",")]
        if len(f) < 3 or not f[1].isdigit():
            continue
        try:
            t = time.mktime(time.strptime(f[0].split(".")[0], "%Y/%m/%d %H:%M:%S"))
        except ValueError:
            continue
        out.append(dict(t=t, index=int(f[1]), util=fnum(f[2]), mem=fnum(f[3]) if len(f) > 3 else 0.0))
    return out


def parse_starts(text: str) -> Dict[str, str]:
    out = {}
    for line in text.splitlines():
        f = line.split("|")
        if len(f) >= 2 and f[0]:
            out[f[0]] = f[1]
    return out


def parse_sstat(text: str) -> Tuple[Optional[float], Optional[float]]:
    """(cpu seconds of the batch step, peak rss bytes)."""
    cpu, rss, seen = None, 0.0, False
    for line in text.splitlines():
        f = line.split("|")
        if len(f) < 3:
            continue
        seen = True
        if f[0].endswith(".batch") or (cpu is None and not f[0].endswith(".extern")):
            cpu = secs(f[1])
        rss = max(rss, nbytes(f[2]))
    return cpu, (rss if seen else None)


def parse_nvsmi(text: str, labelled: bool, node: str = "") -> List[GpuSample]:
    out = []
    for line in text.splitlines():
        tag, rest = ("0", line)
        if labelled and ":" in line.split(",")[0]:
            tag, rest = line.split(":", 1)
        f = [x.strip() for x in rest.split(",")]
        if len(f) >= 4 and f[0].isdigit():
            out.append(GpuSample(node=node or f"task{tag.strip()}", index=int(f[0]), util=fnum(f[1]), used=fnum(f[2]), total=fnum(f[3]) or 1.0, name=f[4] if len(f) > 4 else ""))
    return out


def parse_kv(text: str) -> Dict[str, str]:
    kv = {}
    for tok in text.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            kv[k] = v
    return kv


def parse_node(text: str) -> Optional[Node]:
    kv = parse_kv(text)
    if "NodeName" not in kv:
        return None
    return Node(name=kv["NodeName"], state=kv.get("State", ""), cpus=fint(kv.get("CPUTot")), alloc=fint(kv.get("CPUAlloc")), load=fnum(kv.get("CPULoad")),
                mem_total=fnum(kv.get("RealMemory")), mem_free=fnum(kv.get("FreeMem")), gres=kv.get("Gres", ""), gres_used=kv.get("GresUsed", ""),
                partitions=kv.get("Partitions", ""))


def parse_sacct(text: str) -> List[Finished]:
    jobs: Dict[str, Finished] = {}
    for line in text.splitlines():
        f = line.split("|")
        if len(f) < 13:
            continue
        base = f[0].split(".")[0]
        j = jobs.setdefault(base, Finished(id=base))
        if "." not in f[0]:
            j.name, j.state, j.elapsed, j.cpus = f[1], f[2].split()[0] if f[2] else "", f[3], fint(f[4])
            j.cpu_time, j.start, j.end, j.partition, j.nodes, j.exit = secs(f[5]), f[8], f[9], f[10], fint(f[11]) or 1, f[12]
            j.gpus = gpus_in_tres(f[13]) if len(f) > 13 else 0
            j.nodelist = f[14] if len(f) > 14 else ""
            j.submit = f[15] if len(f) > 15 else ""
            j.workdir = f[16] if len(f) > 16 else ""
            j.limit = f[17] if len(f) > 17 else ""
            req = nbytes(f[6])
            if f[6].endswith("c"):
                req *= j.cpus or 1
            elif f[6].endswith("n"):
                req *= j.nodes
            j.req_mem = req
        else:
            if j.cpu_time is None and f[5]:
                j.cpu_time = secs(f[5])
        j.rss = max(j.rss, nbytes(f[7]))
    done = [j for j in jobs.values() if j.state and j.state not in ("RUNNING", "PENDING", "COMPLETING", "CONFIGURING", "SUSPENDED")]
    done.sort(key=lambda j: j.end, reverse=True)
    return done


def parse_gpu_inventory(text: str, gpu_types: Sequence[str] = ()) -> Tuple[Dict[str, Dict[str, int]], Dict[str, Dict[str, Dict[str, int]]]]:
    """sinfo -N -O NodeList,Partition,Gres,GresUsed,StateCompact -> (cluster totals per type, per partition per type),
    each node counted once for the cluster totals."""
    tot: Dict[str, Dict[str, int]] = {}
    per: Dict[str, Dict[str, Dict[str, int]]] = {}
    seen = set()
    for line in text.splitlines():
        f = line.split()
        if len(f) < 5:
            continue
        node, part, gres, used, state = f[0], f[1], f[2], f[3], f[4]
        down = any(k in state for k in ("down", "drain", "drng", "fail", "maint", "inval")) or state.endswith("*")
        counts: Dict[str, List[int]] = {}
        for piece in gres.split(","):
            t, c = gres_gpus("gres/" + piece) if piece.startswith("gpu") else ("", 0)
            if c and t:
                counts.setdefault(t, [0, 0])[0] += c
        for piece in used.split(","):
            t, c = gres_gpus("gres/" + piece) if piece.startswith("gpu") else ("", 0)
            if c and t in counts:
                counts[t][1] += c
        for t, (c, u) in counts.items():
            for target in ([per.setdefault(part, {})] + ([tot] if node not in seen else [])):
                d = target.setdefault(t, dict(total=0, used=0, down=0, free=0))
                d["total"] += c
                d["used"] += u
                if down:
                    d["down"] += c
                d["free"] = max(0, d["total"] - d["used"] - d["down"])
        seen.add(node)
    return tot, per


def parse_partitions(text: str) -> List[Partition]:
    out = []
    for line in text.splitlines():
        f = line.split("|")
        if len(f) < 6:
            continue
        out.append(Partition(name=f[0].rstrip("*"), avail=f[1], limit=f[2], nodes=fint(f[3]), nodes_aiot=f[4], cpus_aiot=f[5]))
    return out


def parse_share(text: str) -> List[dict]:
    rows = []
    for line in text.splitlines():
        f = line.split("|")
        if len(f) >= 3 and f[0].strip():
            rows.append(dict(account=f[0].strip(), usage=f[1].strip(), fairshare=f[2].strip()))
    return rows


# ------------------------------------------------------------------------------------------------ the layer
class Slurm:
    def __init__(self, backend: Backend, user: str, timeout: float = 8.0, gpu_timeout: float = 12.0, action_timeout: float = 15.0):
        self.b, self.user = backend, user
        self.timeout, self.gpu_timeout, self.action_timeout = timeout, gpu_timeout, action_timeout
        self._hosts: Dict[str, List[str]] = {}

    def jobs(self) -> List[Job]:
        out, _ = self.b.run(["squeue", "-u", self.user, "-h", "-o", JOB_FMT], self.timeout)
        jobs = parse_jobs(out)
        for j in jobs:
            j.hosts = self.hostnames(j.nodelist) if j.nodelist else []
        return jobs

    def starts(self) -> Dict[str, str]:
        out, _ = self.b.run(["squeue", "-u", self.user, "-h", "-t", "PD", "--start", "-o", START_FMT], self.timeout)
        return parse_starts(out)

    def hostnames(self, nodelist: str) -> List[str]:
        if nodelist not in self._hosts:
            try:
                out, _ = self.b.run(["scontrol", "show", "hostnames", nodelist], self.timeout)
                self._hosts[nodelist] = out.split()
            except CommandError:
                return [nodelist]
        return self._hosts[nodelist]

    def live(self, job: Job, prev: Optional[tuple], now: float) -> Tuple[Live, Optional[tuple], List[Step]]:
        """sstat of one running job -> (Live, the (t, cpu) pair to remember for the next rate, the steps)."""
        out, _ = self.b.run(["sstat", "-j", job.id, "-a", "-n", "-P", "-o", SSTAT_FIELDS], self.timeout)
        cpu, rss = parse_sstat(out)
        steps = parse_steps(out, job.id)
        el = job.elapsed_s or 0
        avg = (cpu / (el * job.cpus)) if (cpu is not None and el and job.cpus) else None
        rate, keep = None, prev
        if cpu is not None:
            if prev and now - prev[0] >= 5 and cpu >= prev[1]:
                rate = (cpu - prev[1]) / (now - prev[0]) / max(job.cpus, 1)
            if prev is None or cpu != prev[1] or now - prev[0] > 120:
                keep = (now, cpu)
        return Live(cpu_time=cpu, rss=rss, avg=avg, rate=rate, t=now), keep, steps

    def gpu(self, job: Job) -> List[GpuSample]:
        try:
            out, _ = self.b.run(["srun", "--jobid", job.id, "--overlap", "--immediate=5", "--quiet", "-N", str(job.nodes), "--ntasks-per-node=1", "--label"] + NVSMI, self.gpu_timeout)
            rows = parse_nvsmi(out, labelled=True)
            if rows:
                return rows
        except CommandError:
            pass
        rows = []
        for node in job.hosts:
            try:
                out, _ = self.b.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", "-o", "StrictHostKeyChecking=yes", "--", node] + NVSMI, self.gpu_timeout)
                rows += parse_nvsmi(out, labelled=False, node=node)
            except CommandError:
                continue
        if not rows:
            raise CommandError("nvidia-smi unreachable (srun --overlap and ssh both failed)")
        return rows

    def node(self, name: str) -> Optional[Node]:
        out, _ = self.b.run(["scontrol", "show", "node", name, "-o"], self.timeout)
        return parse_node(out)

    def details(self, jid: str) -> Dict[str, str]:
        out, _ = self.b.run(["scontrol", "show", "job", "-o", jid], self.timeout)
        return parse_kv(out)

    def finished(self, days: float) -> List[Finished]:
        out, _ = self.b.run(["sacct", "-u", self.user, "-n", "-P", "-S", f"now-{int(days * 24)}hours", "-o", SACCT_FIELDS], max(self.timeout, 20.0))
        return parse_sacct(out)

    def partitions(self, gpu_types: Sequence[str]) -> Tuple[List[Partition], Dict[str, Dict[str, int]], Dict[str, NodeCell]]:
        out, _ = self.b.run(["sinfo", "-h", "-o", "%P|%a|%l|%D|%F|%C"], self.timeout)
        parts = parse_partitions(out)
        out, _ = self.b.run(["sinfo", "-h", "-N", "-O", SINFO_NODE_FMT], max(self.timeout, 12.0))
        tot, per = parse_gpu_inventory(out, gpu_types)
        for p in parts:
            p.gpus = per.get(p.name, {})
        return parts, tot, parse_node_map(out)

    def group(self, account: str) -> List[Job]:
        """Everyone's jobs in the account."""
        out, _ = self.b.run(["squeue", "-h", "-A", account, "-o", GROUP_FMT], self.timeout)
        return parse_group(out)

    def pending_ahead(self) -> Dict[str, dict]:
        out, _ = self.b.run(["squeue", "-h", "-t", "PD", "-o", PEND_FMT], max(self.timeout, 12.0))
        return parse_pending_ahead(out)

    def probe(self, partition: str, gres: str = "", cpus: int = 8, mem: str = "32G", limit: str = "01:00:00", account: str = "") -> dict:
        """sbatch --test-only: when would such a job start?  -> dict(partition, gres, cpus, mem, limit, est, nodes, text)."""
        cmd = ["sbatch", "--test-only", "-p", partition, "-c", str(cpus), "--mem", mem, "-t", limit, "-J", "tower-probe", "--wrap", "true"]
        if gres:
            cmd.insert(4, f"--gres={gres}")
        if account:
            cmd += ["-A", account]
        ok, text = self.b.call(cmd, self.timeout)
        est, nodes = parse_test_only(text) if ok else (None, text)
        return dict(partition=partition, gres=gres, cpus=cpus, mem=mem, limit=limit, est=est, nodes=nodes, text=text.strip()[:160], ok=ok)

    def budget(self, account: str) -> dict:
        """sreport since the first of the month and over the last 7 days, sacctmgr for the association's limits -> hours."""
        month = time.strftime("%Y-%m-01")
        fmt = "format=Account,Login,TRESName,Used"
        out, _ = self.b.run(["sreport", "-n", "-P", "-t", "hours", "-T", "cpu,gres/gpu", "cluster", "AccountUtilizationByUser", f"account={account}", f"start={month}", "end=now", fmt], max(self.timeout, 20.0))
        used = parse_sreport(out)
        out, _ = self.b.run(["sreport", "-n", "-P", "-t", "hours", "-T", "cpu,gres/gpu", "cluster", "AccountUtilizationByUser", f"account={account}", "start=now-7days", "end=now", fmt], max(self.timeout, 20.0))
        week = parse_sreport(out)
        limit: Dict[str, float] = {}
        try:
            out, _ = self.b.run(["sacctmgr", "-n", "-P", "show", "assoc", f"where", f"account={account}", "format=Account,User,GrpTRESMins"], self.timeout)
            limit = parse_tres_mins(out)
        except CommandError:
            pass
        return dict(account=account, month=month, used=used.get("", {}), by_user={k: v for k, v in used.items() if k}, week=week.get("", {}),
                    week_by_user={k: v for k, v in week.items() if k}, limit=limit, t=time.time())

    def submit_info(self, jid: str) -> Dict[str, str]:
        """sacct's submit line and record of one job (any state)."""
        from .resubmit import parse_submit_info
        out, _ = self.b.run(["sacct", "-j", jid, "-n", "-P", "-o", SACCT_SUBMIT_FIELDS], self.timeout)
        return parse_submit_info(out)

    def preview_submit(self, argv: Sequence[str], workdir: str = "") -> Tuple[bool, str]:
        """Ask Slurm to validate the exact submission without creating a job."""
        import shlex
        full = ["sbatch", "--test-only"] + list(argv)
        cmd = ["sh", "-c", f"cd {shlex.quote(workdir)} && {shlex.join(full)}"] if workdir else full
        return self.b.call(cmd, self.action_timeout)

    def submit(self, argv: Sequence[str], workdir: str = "") -> Tuple[bool, str, Optional[str]]:
        """sbatch in the job's working directory -> (ok, output, the new job id)."""
        from .resubmit import parse_submitted
        import shlex
        full = ["sbatch"] + list(argv)
        cmd = ["sh", "-c", f"cd {shlex.quote(workdir)} && {shlex.join(full)}"] if workdir else full
        ok, out = self.b.call(cmd, self.action_timeout)
        return ok, out, (parse_submitted(out) if ok else None)

    def fin_steps(self, jid: str) -> List[Step]:
        out, _ = self.b.run(["sacct", "-j", jid, "-n", "-P", "-o", SACCT_STEP_FIELDS], self.timeout)
        return parse_sacct_steps(out)

    @staticmethod
    def gpu_trace(path: str, files, max_bytes: int = 1 << 20) -> List[dict]:
        data, size = files.tail(path, max_bytes)
        if size > max_bytes:
            nl = data.find(b"\n")
            data = data[nl + 1:] if nl >= 0 else b""
        return parse_gpu_trace(data)

    def share(self) -> List[dict]:
        out, _ = self.b.run(["sshare", "-U", "-n", "-P", "-o", "Account,EffectvUsage,FairShare"], self.timeout)
        return parse_share(out)

    def account_load(self, account: str) -> dict:
        """Running cpus / gpus and pending jobs of the whole account (everyone's jobs)."""
        out, _ = self.b.run(["squeue", "-h", "-A", account, "-t", "R", "-o", "%C|%b|%D"], self.timeout)
        cpus = gpus = jobs = 0
        for line in out.splitlines():
            f = line.split("|")
            if len(f) < 3:
                continue
            jobs += 1
            cpus += fint(f[0])
            gpus += gres_gpus(f[1])[1] * (fint(f[2]) or 1)
        out, _ = self.b.run(["squeue", "-h", "-A", account, "-t", "PD", "-o", "%C|%b|%D"], self.timeout)
        pending = len([l for l in out.splitlines() if l.strip()])
        return dict(account=account, running=jobs, cpus=cpus, gpus=gpus, pending=pending)

    # ---- actions ------------------------------------------------------------------------------------
    def cancel(self, ids: Sequence[str]) -> Tuple[bool, str]:
        return self.b.call(["scancel"] + list(ids), self.action_timeout)

    def hold(self, ids: Sequence[str]) -> Tuple[bool, str]:
        return self.b.call(["scontrol", "hold"] + list(ids), self.action_timeout)

    def release(self, ids: Sequence[str]) -> Tuple[bool, str]:
        return self.b.call(["scontrol", "release"] + list(ids), self.action_timeout)

    def requeue(self, ids: Sequence[str]) -> Tuple[bool, str]:
        return self.b.call(["scontrol", "requeue"] + list(ids), self.action_timeout)

    def top(self, ids: Sequence[str]) -> Tuple[bool, str]:
        return self.b.call(["scontrol", "top"] + list(ids), self.action_timeout)
