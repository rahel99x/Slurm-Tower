"""Short, monotonic terminal feedback for observed queue/accounting transitions."""
from __future__ import annotations

from collections import OrderedDict
import time


class CompletionFeedback:
    MOVE_SECONDS = 1.6
    FLASH_SECONDS = 1.4

    def __init__(self, snapshot=None):
        snapshot = snapshot or {}
        self.sequence = max((item.get("seq", 0) for item in snapshot.get("job_transitions", [])), default=0)
        self.revision = snapshot.get("history_revision", 0)
        self.moves = OrderedDict()
        self.sources = OrderedDict()
        self.flash_started = None
        self.new_history = 0

    def update(self, snapshot, now=None):
        now = time.monotonic() if now is None else now
        for item in snapshot.get("job_transitions", []):
            seq = item.get("seq", 0)
            if seq <= self.sequence:
                continue
            self.sequence = seq
            jid = item.get("job")
            if not jid:
                continue
            if item.get("kind") == "departed":
                # Delayed frames never replay an old animation after an overlay/pager.
                observed = item.get("mono", now)
                if 0 <= now - observed < self.MOVE_SECONDS:
                    self.moves[jid] = dict(item, started=observed, source=self.sources.get(jid))
                    while len(self.moves) > 8:
                        self.moves.popitem(last=False)
            elif item.get("kind") == "returned":
                self.moves.pop(jid, None)
        revision = snapshot.get("history_revision", self.revision)
        if revision > self.revision:
            self.new_history += revision - self.revision
            self.flash_started = now
        self.revision = revision
        self.moves = OrderedDict((jid, item) for jid, item in self.moves.items()
                                 if 0 <= now - item["started"] < self.MOVE_SECONDS)

    def remember(self, hits):
        for y, kind, jid in hits:
            if kind == "job":
                self.sources[jid] = y
                self.sources.move_to_end(jid)
        while len(self.sources) > 256:
            self.sources.popitem(last=False)

    def moving(self, now=None):
        now = time.monotonic() if now is None else now
        return [dict(item, progress=max(0.0, min(1.0, (now - item["started"]) / self.MOVE_SECONDS)))
                for item in self.moves.values() if 0 <= now - item["started"] < self.MOVE_SECONDS]

    def flash_on(self, now=None):
        if self.flash_started is None:
            return False
        age = (time.monotonic() if now is None else now) - self.flash_started
        return 0 <= age < .35 or .7 <= age < 1.05

    @property
    def active(self):
        now = time.monotonic()
        return bool(self.moving(now)) or (self.flash_started is not None and 0 <= now - self.flash_started < self.FLASH_SECONDS)

    def acknowledge(self):
        self.new_history = 0
