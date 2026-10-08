"""Conservative launch groups and shared, identity-safe table projections.

Groups are presentation objects, never scheduler allocations.  Every Child
retains its original record and ID; a Header cannot be passed to a job action.
Inference reads supplied snapshots only and never queries Slurm or the disk.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import blake2s
import re
from types import MappingProxyType
from typing import Any, Mapping

from .model import stamp

BURST_SECONDS = 10
MAX_ID_GAP = 1
MAX_COLLAPSED = 256
_ARRAY = re.compile(r"^([0-9]{1,19})_([0-9]{1,19}|\[[0-9,:%-]+\])(?:\+[0-9]{1,19})?$")
_HET = re.compile(r"^([0-9]{1,19})\+[0-9]{1,19}$")
_MARKER = re.compile(r"^(?:launch:|group:)([A-Za-z0-9][A-Za-z0-9_.-]{0,127})$")
_EXPLICIT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_FAMILY = re.compile(r"^(.*?)[_.-]([0-9]+)$")
_EMPTY = frozenset(("", "Unknown", "N/A", "NONE", "(null)", "-"))
_MISSING = object()
_EMPTY_VALUES = (_MISSING,) * 10
_EMPTY_MAP = {}
_RECORD_FIELDS = ("id", "name", "submit", "cluster", "user", "account", "workdir", "command",
                  "TowerLaunchId", "LaunchId", "LaunchGroup", "JobGroup")


def _value(record, key, default=""):
    if isinstance(record, dict):
        return record.get(key, default)
    value = getattr(record, key, _MISSING)
    if value is not _MISSING:
        return value
    get = getattr(record, "get", None)
    return get(key, default) if callable(get) else default


def _text(value):
    return value if isinstance(value, str) and value not in _EMPTY and len(value) <= 4096 else ""


def _digest(parts):
    # Length prefixes avoid collisions between field separators in paths/names.
    digest = blake2s(digest_size=10)
    for part in parts:
        raw = str(part).encode("utf-8", "surrogatepass")
        digest.update(str(len(raw)).encode("ascii") + b":" + raw)
    return digest.hexdigest()


@dataclass(frozen=True)
class Group:
    id: str
    label: str
    kind: str
    reason: str
    confidence: str
    members: tuple[str, ...]
    cohort: tuple = ()
    first_submit: float | None = None


@dataclass(frozen=True)
class Index:
    groups: Mapping[str, Group]
    by_job: Mapping[str, str]

    def for_job(self, job_id):
        return self.groups.get(self.by_job.get(job_id))


@dataclass(frozen=True)
class Header:
    group: Group
    records: tuple[Any, ...]
    collapsed: bool

    @property
    def visible_count(self):
        return len(self.records)

    @property
    def total_count(self):
        return len(self.group.members)


@dataclass(frozen=True)
class Child:
    record: Any
    group_id: str | None = None


@dataclass(frozen=True)
class GroupMeta:
    group: Group
    representative_id: str
    header: bool
    collapsed: bool
    records: tuple[Any, ...]

    @property
    def visible_count(self):
        return len(self.records)

    @property
    def total_count(self):
        return len(self.group.members)


@dataclass(frozen=True)
class _Evidence:
    id: str
    name: str
    submit: str
    cluster: str
    user: str
    account: str
    workdir: str
    command: str
    explicit: str
    structural: tuple[str, str] | None


def _records(snap):
    """Queue records win over departed/accounting records of the same ID."""
    records = {}
    for record in snap.get("group", ()):
        jid = _text(_value(record, "id"))
        if jid:
            records[jid] = record
    for record in snap.get("finished", ()):
        jid = _text(_value(record, "id"))
        if jid:
            records[jid] = record
    for jid, record in snap.get("departed_jobs", {}).items():
        if isinstance(jid, str):
            records[jid] = record
    for record in snap.get("jobs", ()):
        jid = _text(_value(record, "id"))
        if jid:
            records[jid] = record
    return records


def _evidence(record, snap, previous=None, inherit=()):
    jid = _text(_value(record, "id"))
    details = snap.get("details", _EMPTY_MAP).get(jid, _EMPTY_MAP)
    details = details if isinstance(details, Mapping) else {}

    def field(name, scheduler):
        if scheduler in details:
            return _text(details[scheduler])
        if isinstance(record, Mapping) and name in record or hasattr(record, name):
            return _text(_value(record, name))
        # Finished records omit owner, account, and command. Carry only fields
        # omitted by a record-type transition, not deleted metadata or blanks.
        return getattr(previous, name, "") if previous and name in inherit else ""

    structural = None
    if match := _ARRAY.fullmatch(jid):
        if match[2].startswith("["):
            from .arrays import parse_range
            try:
                parse_range(match[2])
            except ValueError:
                pass
            else:
                structural = ("array", match[1])
        else:
            structural = ("array", match[1])
    elif match := _HET.fullmatch(jid):
        structural = ("heterogeneous", match[1])
    if structural:
        return _Evidence(jid, "", "", field("cluster", "Cluster"), "", "", "", "", "", structural)

    user = field("user", "UserId")
    if re.fullmatch(r"[^()]+\([0-9]+\)", user):
        user = user.rsplit("(", 1)[0]
    explicit = ""
    for key in ("TowerLaunchId", "LaunchId", "LaunchGroup", "JobGroup"):
        candidate = _text(details.get(key)) or _text(_value(record, key))
        if candidate and _EXPLICIT.fullmatch(candidate):
            explicit = candidate
            break
    if not explicit:
        tags = snap.get("tags", {}).get(jid, {})
        tags = tags.get("tags", ()) if isinstance(tags, Mapping) else ()
        tags = tags if isinstance(tags, (list, tuple, set, frozenset)) else ()
        markers = sorted({match[1] for tag in tags if isinstance(tag, str)
                          and (match := _MARKER.fullmatch(tag))})
        # Conflicting markers provide no reliable shared launch identity.
        explicit = markers[0] if len(markers) == 1 else ""
    return _Evidence(jid, _text(_value(record, "name")), field("submit", "SubmitTime"),
                     field("cluster", "Cluster"), user, field("account", "Account"),
                     field("workdir", "WorkDir"), field("command", "Command"),
                     explicit, structural)


def _input(record, jid, snap):
    """Cheap exact field comparison before parsing or constructing evidence."""
    source = record if isinstance(record, dict) or callable(getattr(record, "get", None)) else getattr(record, "__dict__", None)
    if source is None:
        fields = tuple(getattr(record, key, _MISSING) for key in _RECORD_FIELDS)
    else:
        get = source.get
        fields = (get("id", _MISSING), get("name", _MISSING), get("submit", _MISSING),
                  get("cluster", _MISSING), get("user", _MISSING), get("account", _MISSING),
                  get("workdir", _MISSING), get("command", _MISSING),
                  get("TowerLaunchId", _MISSING), get("LaunchId", _MISSING),
                  get("LaunchGroup", _MISSING), get("JobGroup", _MISSING))
    details = snap.get("details", _EMPTY_MAP).get(jid, _EMPTY_MAP)
    if not details or not (isinstance(details, dict) or isinstance(details, Mapping)):
        values = _EMPTY_VALUES
    else:
        get = details.get
        values = (get("WorkDir", _MISSING), get("UserId", _MISSING), get("Account", _MISSING),
                  get("Command", _MISSING), get("SubmitTime", _MISSING), get("Cluster", _MISSING),
                  get("TowerLaunchId", _MISSING), get("LaunchId", _MISSING),
                  get("LaunchGroup", _MISSING), get("JobGroup", _MISSING))
    tags = snap.get("tags", _EMPTY_MAP).get(jid, _EMPTY_MAP)
    tags = tags.get("tags", ()) if isinstance(tags, dict) or isinstance(tags, Mapping) else ()
    tags = tuple(tags) if isinstance(tags, (list, tuple, set, frozenset)) else ()
    return fields, values, tags, type(record)


class Registry:
    """One snapshot-sensitive inference cache and collapse registry per app."""

    def __init__(self, collapsed=()):
        self.collapsed = set(value for value in collapsed if valid_group_id(value))
        self.index = Index(MappingProxyType({}), MappingProxyType({}))
        self._fingerprint = None
        self._evidence = {}
        self._inputs = {}
        self.inference_count = 0

    def ensure(self, snap):
        records = _records(snap)
        evidence, inputs = {}, {}
        changed = len(records) != len(self._inputs)
        for jid, record in records.items():
            value = inputs[jid] = _input(record, jid, snap)
            if jid in self._evidence and self._inputs.get(jid) == value:
                evidence[jid] = self._evidence[jid]
            else:
                changed = True
                previous = self._evidence.get(jid)
                fields, values, tags, record_type = value
                old_input = self._inputs.get(jid)
                inherited = ()
                if old_input is not None and old_input[3] is not record_type:
                    inherited = tuple(name for name, old, new in zip(_RECORD_FIELDS, old_input[0], fields)
                                      if old is not _MISSING and new is _MISSING)
                # Ordinary accounting records have no owner/account/command
                # provenance. Reject that common case before parsing fields
                # or constructing evidence, while still noticing new details,
                # markers and retained live provenance on the next check.
                impossible = (previous is None and values is _EMPTY_VALUES and not tags
                              and jid.isascii() and jid.isdigit()
                              and not any(isinstance(item, str) and item for item in fields[8:])
                              and not all(isinstance(fields[index], str) and fields[index]
                                          for index in (4, 5, 6, 7)))
                evidence[jid] = None if impossible else _evidence(record, snap, previous, inherited)
        # Equality checks exact relevant content, including in-place detail,
        # command, submit, and tag corrections; Store revision alone is unsafe.
        if not changed and self._fingerprint is not None:
            return self.index
        self._inputs = inputs
        if evidence == self._evidence and self._fingerprint is not None:
            return self.index
        previous = self._evidence
        self._evidence = evidence
        self._fingerprint = True
        self.inference_count += 1
        self.index = self._infer(evidence, previous)
        return self.index

    def _infer(self, evidence, previous):
        assigned, candidates = set(), []
        structural, explicit = defaultdict(list), defaultdict(list)
        for item in evidence.values():
            if item is None:
                continue
            if item.structural:
                structural[(item.cluster, *item.structural)].append(item)
            elif item.explicit:
                explicit[(item.cluster, item.user, item.account, item.workdir, item.explicit)].append(item)

        for (cluster, kind, parent), items in structural.items():
            if len(items) < 2:
                continue
            suffix = ":" + _digest((cluster,)) if cluster else ""
            gid = f"{kind}:{parent}{suffix}"
            reason = "Slurm array task IDs share allocation " if kind == "array" else "Slurm heterogeneous component IDs share allocation "
            candidates.append(Group(gid, f"{'Array' if kind == 'array' else 'Heterogeneous'} {parent}",
                                    kind, reason + parent, "certain", tuple(sorted(item.id for item in items))))
            assigned.update(item.id for item in items)

        for cohort, items in explicit.items():
            if len(items) < 2:
                continue
            marker = cohort[-1]
            candidates.append(Group("launch:" + _digest(cohort), f"Launch {marker}", "explicit",
                                    f"Matching explicit launch marker {marker}", "explicit",
                                    tuple(sorted(item.id for item in items)), cohort))
            assigned.update(item.id for item in items)

        bursts = defaultdict(list)
        for item in evidence.values():
            if item is None:
                continue
            if item.id in assigned or item.structural or item.explicit or len(item.id) > 19 or not item.id.isascii() or not item.id.isdigit():
                continue
            if not all((item.user, item.account, item.workdir, item.command, item.name)):
                continue
            when = stamp(item.submit)
            if when is None:
                continue
            family = _FAMILY.fullmatch(item.name)
            name = family[1] if family and family[1] else item.name
            cohort = (item.cluster, item.user, item.account, item.workdir, item.command, name)
            bursts[cohort].append((when, int(item.id), item))

        for cohort, items in bursts.items():
            items.sort(key=lambda value: (value[0], value[1]))
            run = []
            for when, number, item in items:
                if run and (when - run[0][0] > BURST_SECONDS or not 0 < number - run[-1][1] <= MAX_ID_GAP):
                    self._burst_group(cohort, run, candidates, previous)
                    run = []
                run.append((when, number, item))
            self._burst_group(cohort, run, candidates, previous)

        groups = {group.id: group for group in candidates}
        by_job = {jid: group.id for group in candidates for jid in group.members}
        return Index(MappingProxyType(groups), MappingProxyType(by_job))

    def _burst_group(self, cohort, run, candidates, previous):
        if len(run) < 2 or len({entry[2].name for entry in run}) > 1 and len(run) < 3:
            return
        members = tuple(entry[2].id for entry in run)
        start = run[0][0]
        # Retain collapse identity when a member completes or older metadata
        # arrives, but never attach a reused ID from a later launch attempt.
        old = {self.index.by_job[jid] for jid in members if jid in self.index.by_job}
        compatible = [self.index.groups[gid] for gid in old
                      if self.index.groups[gid].kind == "burst" and self.index.groups[gid].cohort == cohort
                      and abs(start - self.index.groups[gid].first_submit) <= BURST_SECONDS
                      and any(previous.get(jid) is not None and previous[jid].submit == self._evidence[jid].submit
                              for jid in members if jid in self.index.groups[gid].members)]
        gid = min((group.id for group in compatible), default="burst:" + _digest((*cohort, members[0], start)))
        candidates.append(Group(gid, f"Launch {cohort[-1]}", "burst",
                                "Submit times span at most 10 seconds; owner, account, work directory, command and name match; job IDs are adjacent",
                                "likely", members, cohort, start))

    def is_collapsed(self, group):
        # Old releases persisted numeric array parents. Preserve that setting.
        parent = group.label.split()[-1]
        return group.id in self.collapsed or group.kind == "array" and group.id == "array:" + parent and parent in self.collapsed

    def fold(self, group_id, collapsed=None):
        if not valid_group_id(group_id):
            return False
        group = self.index.groups.get(group_id)
        if group is None:
            return False
        value = not self.is_collapsed(group) if collapsed is None else bool(collapsed)
        self.collapsed.discard(group.id)
        parent = group.label.split()[-1]
        if group.kind == "array":
            self.collapsed.discard(parent)
        stored = parent if group.kind == "array" and group.id == "array:" + parent else group.id
        if value:
            # Keep the legacy unscoped array parent setting compatible with
            # existing sort reanchoring and saved preferences.
            self.collapsed.add(stored)
        if len(self.collapsed) > MAX_COLLAPSED:
            self.collapsed = (set(sorted(self.collapsed - {stored})[-(MAX_COLLAPSED - 1):]) | {stored}
                              if value else set(sorted(self.collapsed)[-MAX_COLLAPSED:]))
        return True

    def project(self, records, *, enabled=True, index=None):
        records = list(records)
        index = self.index if index is None else index
        if not enabled:
            return [Child(record) for record in records]
        visible = defaultdict(list)
        counted = set()
        for record in records:
            jid = _value(record, "id")
            group_id = index.by_job.get(jid)
            if group_id and jid not in counted:
                visible[group_id].append(record)
                counted.add(jid)
        seen, result = set(), []
        for record in records:
            group_id = index.by_job.get(_value(record, "id"))
            if not group_id:
                result.append(Child(record))
                continue
            group = index.groups[group_id]
            if group_id not in seen:
                result.append(Header(group, tuple(visible[group_id]), self.is_collapsed(group)))
                seen.add(group_id)
            if not self.is_collapsed(group):
                result.append(Child(record, group_id))
        return result


def valid_group_id(value):
    return isinstance(value, str) and len(value) <= 128 and bool(re.fullmatch(r"[A-Za-z0-9:_.-]+", value))


def registry(app):
    value = getattr(app, "job_groups", None)
    state = getattr(app, "table_state", {})
    if not isinstance(value, Registry):
        value = app.job_groups = Registry(state.get("collapsed", ()))
    else:
        value.collapsed = {item for item in state.get("collapsed", ()) if valid_group_id(item)}
    return value


def frame_index(app, snap):
    """Reuse an explicitly bounded render pass, never a snapshot-ID cache."""
    current = getattr(app, "job_groups_frame_index", None)
    if isinstance(current, tuple) and len(current) == 2 and current[0] is snap:
        return current[1]
    return registry(app).ensure(snap)


@contextmanager
def frame(app, snap):
    """Share one exact inference check during compose, then always clear it."""
    previous = getattr(app, "job_groups_frame_index", None)
    value = registry(app)
    index = value.ensure(snap) if getattr(app, "table_state", {}).get("groups", False) else value.index
    app.job_groups_frame_index = (snap, index)
    try:
        yield index
    finally:
        app.job_groups_frame_index = previous


def project(app, snap, records, *, enabled=None, index=None):
    value = registry(app)
    if enabled is None:
        enabled = bool(getattr(app, "table_state", {}).get("groups", False))
    index = frame_index(app, snap) if enabled and index is None else index
    return value.project(records, enabled=enabled, index=index)


def fold(app, group_id, collapsed=None):
    value = registry(app)
    changed = value.fold(group_id, collapsed)
    if changed:
        app.table_state["collapsed"] = sorted(value.collapsed)
        if value.is_collapsed(value.index.groups[group_id]):
            _reanchor(app, group_id)
    return changed


def project_records(app, snap, records, tab="history", *, enabled=None, index=None):
    """Keep actual representative rows, with separate presentation metadata.

    An open group leaves the caller's complete sort and pin order unchanged.
    A closed group retains its first visible record, so selection, log lookup,
    and cancellation always refer to one real allocation.  Filtered-out records
    are not reintroduced, and totals distinguish visible from observed jobs.
    """
    records = list(records)
    value = registry(app)
    if enabled is None:
        enabled = bool(getattr(app, "table_state", {}).get("groups", False))
    metadata = getattr(app, "job_group_metadata", None)
    if not isinstance(metadata, dict):
        metadata = app.job_group_metadata = {}
    current = metadata[tab] = {}
    if not enabled:
        return records
    index = frame_index(app, snap) if index is None else index
    visible = defaultdict(list)
    counted = set()
    for record in records:
        jid = _value(record, "id")
        gid = index.by_job.get(jid)
        if gid and jid not in counted:
            visible[gid].append(record)
            counted.add(jid)
    first = {gid: _value(members[0], "id") for gid, members in visible.items()}
    counts = {gid: tuple(members) for gid, members in visible.items()}
    result = []
    for record in records:
        jid = _value(record, "id")
        gid = index.by_job.get(jid)
        if gid is None:
            result.append(record)
            continue
        group = index.groups[gid]
        header = jid == first[gid]
        collapsed = value.is_collapsed(group)
        current[jid] = GroupMeta(group, first[gid], header, collapsed, counts[gid])
        if header or not collapsed:
            result.append(record)
    return result


def metadata_for_record(app, tab, job_id):
    return getattr(app, "job_group_metadata", {}).get(tab, {}).get(job_id)


def project_rows(app, rows, snap=None, tab="jobs", *, index=None):
    rows = list(rows)
    if snap is None:
        # The legacy entry point receives prepared queue rows. Supplying the
        # complete snapshot enables lifecycle and explicit evidence grouping.
        snap = {"jobs": [row["job"] for row in rows]}
    selected = project_records(app, snap, [row["job"] for row in rows], tab, index=index)
    visible = {_value(record, "id") for record in selected}
    result = []
    for row in rows:
        jid = _value(row["job"], "id")
        if jid not in visible:
            continue
        meta = metadata_for_record(app, tab, jid)
        if meta is None:
            result.append(row)
            continue
        item = dict(row, _group=meta)
        if meta.header:
            summary = f"{meta.group.label}: {meta.visible_count}/{meta.total_count} observed jobs"
            item["info"] = str(item.get("info", "")) + " | " + summary + ("; Right expands" if meta.collapsed else "; Left collapses")
        result.append(item)
    return result


def _reanchor(app, group_id):
    selected = getattr(app, "selected_id", None)
    tab = getattr(app, "tab", "")
    contexts = ("jobs", "recent") if tab == "jobs" else (tab, "history:" + tab, "history_dock:" + tab, "history_dock")
    meta = next((metadata_for_record(app, context, selected) for context in contexts
                 if metadata_for_record(app, context, selected) is not None), None)
    if meta is None or meta.group.id != group_id or meta.representative_id == selected:
        return
    app.selected_id = meta.representative_id
    cursor = getattr(app, "cursor", {})
    ids = {"jobs": getattr(app, "last_jobs_ids", ()), "history": getattr(app, "last_history_ids", ()),
           "group": getattr(app, "group_ids", ()), "deps": getattr(app, "dep_ids", ())}.get(tab, ()) or ()
    if tab in cursor and meta.representative_id in ids:
        cursor[tab] = ids.index(meta.representative_id)
