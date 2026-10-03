"""Alert rules: expressions over each job (or over the whole snapshot) that ring, notify, log an event or run a
command when they hold, with a rate limit per job and rule.

    [[alerts]]
    name = "idle gpu"
    when = "running and gpus and gpu is not None and gpu < 15 and elapsed > 900"
    every = 1800                      # seconds before the same job fires this rule again (0: once per job)
    actions = ["bell", "event"]       # bell | event | notify (the [notify] command with TOWER_EVENT=alert) | command
    command = ""                      # with "command": a shell command, TOWER_ALERT TOWER_JOBID TOWER_JOBNAME TOWER_TEXT in the environment
    scope = "job"                     # job: per job; cluster: once over the snapshot (n_pending, free_gpus ...)
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Callable, Dict, List, Optional

from .expr import Expr, ExprError, cluster_ns, job_ns


class Rule:
    def __init__(self, spec: dict):
        self.name = str(spec.get("name") or spec.get("when", "")[:30])
        self.when = str(spec.get("when", ""))
        self.every = float(spec.get("every", 1800))
        self.actions = list(spec.get("actions", ["bell", "event"]))
        self.command = str(spec.get("command", ""))
        self.scope = str(spec.get("scope", "job"))
        self.error = ""
        try:
            self.expr: Optional[Expr] = Expr(self.when)
        except ExprError as e:
            self.expr, self.error = None, str(e)
        self.fired: Dict[str, float] = {}             # job id (or "*" for cluster scope) -> last time it fired
        self.active: set = set()                      # keys currently true

    def due(self, key: str, now: float) -> bool:
        last = self.fired.get(key)
        if last is None:
            return True
        if self.every <= 0:
            return False
        return now - last >= self.every


class AlertEngine:
    """``check(snap)`` evaluates every rule; ``bell`` is a counter the screen watches."""

    def __init__(self, rules: List[dict], store, user: str = "", notify: Optional[Callable[[dict], None]] = None, bell: Optional[Callable[[], None]] = None):
        self.rules = [Rule(r) for r in rules if isinstance(r, dict) and r.get("when")]
        self.store, self.user, self.notify, self.bell_fn = store, user, notify, bell
        self.bell = 0
        self.errors: Dict[str, str] = {r.name: r.error for r in self.rules if r.error}
        self.recent: List[dict] = []                   # the last alerts, newest last
        self.lock = threading.Lock()
        for name, err in self.errors.items():
            store.event("alert_error", f"alert rule '{name}': {err}", name=name)

    def add(self, when: str, name: str = "", actions=("bell", "event"), every: float = 1800, scope: str = "job") -> Rule:
        r = Rule(dict(name=name or when, when=when, actions=list(actions), every=every, scope=scope))
        self.rules.append(r)
        if r.error:
            self.errors[r.name] = r.error
        return r

    def check(self, snap: dict, marks=(), tags=None) -> List[dict]:
        """Evaluate the rules over the snapshot; returns the alerts fired now."""
        if not self.rules:
            return []
        now = time.time()
        fired: List[dict] = []
        cns = None
        for rule in self.rules:
            if rule.expr is None:
                continue
            try:
                if rule.scope == "cluster":
                    cns = cns if cns is not None else cluster_ns(snap, self.user, marks, tags)
                    hits = [("*", "", bool(rule.expr(cns)))]
                else:
                    hits = []
                    for j in snap.get("jobs", []):
                        ns = job_ns(j, snap, marks, tags)
                        hits.append((j.id, j.name, bool(rule.expr(ns))))
            except ExprError as e:
                if rule.name not in self.errors:
                    self.errors[rule.name] = str(e)
                    self.store.event("alert_error", f"alert rule '{rule.name}': {e}", name=rule.name)
                continue
            for key, name, hit in hits:
                if not hit:
                    rule.active.discard(key)
                    continue
                first = key not in rule.active
                rule.active.add(key)
                if not (first and rule.every <= 0 and key not in rule.fired) and not rule.due(key, now):
                    continue
                if rule.every <= 0 and key in rule.fired:
                    continue
                rule.fired[key] = now
                text = f"{rule.name}: {key + ' ' + name if key != '*' else rule.when}".strip()
                ev = self.store.event("alert", text, job_id=key if key != "*" else "", name=name, rule=rule.name)
                fired.append(ev)
                self.fire(rule, ev)
        if fired:
            with self.lock:
                self.recent = (self.recent + fired)[-50:]
        return fired

    def fire(self, rule: Rule, ev: dict):
        if "bell" in rule.actions:
            self.bell += 1
            if self.bell_fn:
                try:
                    self.bell_fn()
                except Exception:
                    pass
        if "notify" in rule.actions and self.notify:
            try:
                self.notify(dict(ev, kind="alert"))
            except Exception:
                pass
        if "command" in rule.actions and rule.command:
            env = dict(os.environ, TOWER_EVENT="alert", TOWER_ALERT=rule.name, TOWER_JOBID=str(ev.get("job", "")), TOWER_JOBNAME=str(ev.get("name", "")), TOWER_TEXT=ev["text"])

            def go():
                try:
                    subprocess.run(rule.command, shell=True, env=env, timeout=30, capture_output=True)
                except (OSError, subprocess.TimeoutExpired):
                    pass

            threading.Thread(target=go, daemon=True).start()

    def active_count(self) -> int:
        return sum(len(r.active) for r in self.rules)

    def active_text(self) -> List[str]:
        out = []
        for r in self.rules:
            for key in sorted(r.active):
                out.append(f"{r.name}" + (f" {key}" if key != "*" else ""))
        return out
