"""Dependency chains among jobs: the ``Dependency`` field of squeue parsed into edges, laid out as trees, with the
downstream closure for chain actions (cancel or release a job and everything that waits for it)."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .model import Job

KINDS = ("afterok", "afternotok", "afterany", "after", "aftercorr", "afterburstbuffer", "singleton")


def parse_dependency(text: str) -> List[Tuple[str, str]]:
    """'afterok:123:456(unfulfilled),afterany:789?singleton' -> [(kind, id), ...]; singleton -> ('singleton', '')."""
    out: List[Tuple[str, str]] = []
    if not text or text in ("(null)", "None"):
        return out
    for clause in re.split(r"[,?]", text):
        clause = re.sub(r"\(.*?\)", "", clause).strip()
        if not clause:
            continue
        if clause == "singleton":
            out.append(("singleton", ""))
            continue
        if ":" not in clause:
            continue
        kind, rest = clause.split(":", 1)
        for jid in rest.split(":"):
            jid = jid.split("+")[0].strip()              # after:123+5 (minutes)
            if jid:
                out.append((kind, jid))
    return out


class DepGraph:
    def __init__(self, jobs: Sequence[Job], finished_names: Optional[Dict[str, str]] = None):
        self.jobs: Dict[str, Job] = {j.id: j for j in jobs}
        self.names = dict(finished_names or {})           # ids no longer queued -> "name state"
        self.edges: List[Tuple[str, str, str]] = []        # (prerequisite, kind, dependent)
        self.singletons: Set[str] = set()
        for j in jobs:
            for kind, pre in parse_dependency(j.dependency):
                if kind == "singleton":
                    self.singletons.add(j.id)
                else:
                    self.edges.append((pre, kind, j.id))
        self.down: Dict[str, List[Tuple[str, str]]] = {}
        self.up: Dict[str, List[Tuple[str, str]]] = {}
        for pre, kind, dep in self.edges:
            self.down.setdefault(pre, []).append((kind, dep))
            self.up.setdefault(dep, []).append((kind, pre))
        for j in jobs:                                      # singleton: the same name and user, earlier id first
            if j.id in self.singletons:
                for k in jobs:
                    if k.id != j.id and k.name == j.name and k.id < j.id and k.id not in {p for _, p in self.up.get(j.id, [])}:
                        self.edges.append((k.id, "singleton", j.id))
                        self.down.setdefault(k.id, []).append(("singleton", j.id))
                        self.up.setdefault(j.id, []).append(("singleton", k.id))

    def related(self) -> Set[str]:
        s = set()
        for pre, _, dep in self.edges:
            s.add(pre)
            s.add(dep)
        return s

    def roots(self) -> List[str]:
        """Prerequisites that have no prerequisite themselves (queued or not), in queue order."""
        rel = self.related()
        order = list(self.jobs) + [i for i in rel if i not in self.jobs]
        return [i for i in order if i in rel and not self.up.get(i)]

    def downstream(self, jid: str) -> List[str]:
        """Every job that (transitively) waits for ``jid``, nearest first, without ``jid``."""
        out, seen, stack = [], {jid}, [jid]
        while stack:
            cur = stack.pop(0)
            for _, dep in self.down.get(cur, []):
                if dep not in seen:
                    seen.add(dep)
                    out.append(dep)
                    stack.append(dep)
        return out

    def upstream(self, jid: str) -> List[str]:
        out, seen, stack = [], {jid}, [jid]
        while stack:
            cur = stack.pop(0)
            for _, pre in self.up.get(cur, []):
                if pre not in seen:
                    seen.add(pre)
                    out.append(pre)
                    stack.append(pre)
        return out

    def trees(self) -> List[List[Tuple[int, str, str]]]:
        """One list per root of (depth, kind, id) rows, depth-first; a job reachable from two roots appears under
        the first (marked by kind ending in '*' when repeated)."""
        out = []
        placed: Set[str] = set()
        for root in self.roots():
            rows: List[Tuple[int, str, str]] = []

            def rec(jid, depth, kind):
                repeat = jid in placed
                rows.append((depth, kind + ("*" if repeat else ""), jid))
                if repeat:
                    return
                placed.add(jid)
                for k, dep in sorted(self.down.get(jid, []), key=lambda kd: kd[1]):
                    rec(dep, depth + 1, k)

            rec(root, 0, "")
            out.append(rows)
        return out

    def blocked_by(self, jid: str) -> List[str]:
        """What a pending job still waits for, in words."""
        out = []
        for kind, pre in self.up.get(jid, []):
            j = self.jobs.get(pre)
            if j is None:
                out.append(f"{kind} {pre} ({self.names.get(pre, 'gone')})")
            else:
                out.append(f"{kind} {pre} {j.name} ({j.state.lower()})")
        return out
