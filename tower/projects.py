"""Explicit, bounded project inventories and declared artifact previews.

Only ``ROOT/runs/<attempt>/run.json`` is discovered. Reads stay anchored to the
chosen root, reject symlinks and special files, and verify stable observations.
Nothing in this module runs project code or recursively scans a project.
"""
from __future__ import annotations

import csv
import codecs
import io
import json
import math
import os
import re
import stat
from contextlib import contextmanager

from .artifacts import _contract, _json, _open_local, _signature, validate_contract
from .remote import LocalFiles

MAX_RUNS = 256
MAX_DIRECTORY_ENTRIES = 4096
MAX_INVENTORY_BYTES = 65536
MAX_INVENTORY_TOTAL = 8 * 1024 * 1024
MAX_PREVIEW_BYTES = 65536
MAX_PREVIEW_LINES = 256
MAX_TREE_NODES = 2048
_IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_STATES = set("CREATED SUBMITTED PENDING RUNNING COMPLETING COMPLETED FAILED CANCELLED TIMEOUT OUT_OF_MEMORY NODE_FAIL PREEMPTED BOOT_FAIL DEADLINE REQUEUED REQUEUE_FED REQUEUE_HOLD RESIZING REVOKED SIGNALING SPECIAL_EXIT STAGE_OUT STOPPED SUSPENDED UNKNOWN INTERRUPTED".split())
_FIELDS = set("schema project_id run_id experiment_id attempt name state job_id start end submit paths provenance parameters results metadata description resources input_size".split())
_PATHS = set("metrics summary outputs logs passports stdout stderr log_index planning predict forecast blockers tradeoffs scaling workflow submit".split())
PLANNING_PATHS = ("predict", "forecast", "blockers", "tradeoffs", "scaling", "workflow")


def _local(files):
    if files is not None and type(files) is not LocalFiles:
        raise ValueError("Project discovery requires Tower running locally on CARC; this file backend cannot prove confined directory reads")


def _text(value, name, maximum=128, *, empty=False):
    if not isinstance(value, str) or not (0 if empty else 1) <= len(value) <= maximum or any(not ch.isprintable() for ch in value):
        raise ValueError(f"{name} must be printable text of at most {maximum} characters")
    return value


def relative_path(value):
    _text(value, "path", 4096)
    if value.startswith("/") or any(ch in value for ch in "\\*?[]") or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("path must be an exact relative POSIX path without traversal or globs")
    return value


def validate_inventory(value):
    """Validate the native tower.run/v1 vocabulary without optional libraries."""
    required = {"schema", "run_id", "experiment_id", "attempt", "state"}
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - _FIELDS:
        raise ValueError("run inventory has missing or unsupported fields")
    if value["schema"] != "tower.run/v1":
        raise ValueError("run inventory schema must be tower.run/v1")
    for key in ("run_id", "project_id"):
        if key in value and not _IDENT.fullmatch(_text(value[key], key)):
            raise ValueError(f"{key} must be a safe ASCII identifier")
    for key in ("experiment_id", "name", "job_id"):
        if key in value and not (key == "job_id" and value[key] is None):
            _text(value[key], key)
    if type(value["attempt"]) is not int or not 1 <= value["attempt"] <= 2147483647:
        raise ValueError("attempt must be a positive bounded integer")
    if not isinstance(value["state"], str) or value["state"] not in _STATES:
        raise ValueError("unsupported run state")
    for key in ("start", "end", "submit", "input_size"):
        number = value.get(key)
        maximum = 1e100 if key == "input_size" else 253402300799
        if number is not None and (isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not 0 <= number <= maximum):
            raise ValueError(f"{key} must be a bounded nonnegative number or null")
    for key in ("description",):
        if key in value:
            _text(value[key], key, 4096, empty=True)
    paths = value.get("paths", {})
    if not isinstance(paths, dict) or paths.keys() - _PATHS:
        raise ValueError("unsupported run paths")
    for path in paths.values():
        relative_path(path)
    for key in ("results", "metadata"):
        if key in value and not isinstance(value[key], dict):
            raise ValueError(f"{key} must be a JSON object")
    if "parameters" in value:
        from .predict import _parameters
        _parameters(value["parameters"])
    provenance = value.get("provenance", {})
    if not isinstance(provenance, dict) or provenance.keys() - {"script", "script_sha256", "git_commit", "description"}:
        raise ValueError("unsupported provenance fields")
    if "script" in provenance:
        relative_path(provenance["script"])
    if "script_sha256" in provenance and (not isinstance(provenance["script_sha256"], str) or not re.fullmatch(r"[0-9a-fA-F]{64}", provenance["script_sha256"])):
        raise ValueError("invalid script SHA-256")
    if provenance.get("git_commit") is not None and (not isinstance(provenance["git_commit"], str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", provenance["git_commit"])):
        raise ValueError("invalid Git commit")
    if "description" in provenance:
        _text(provenance["description"], "provenance.description", 4096, empty=True)
    resources = value.get("resources", {})
    if not isinstance(resources, dict) or resources.keys() - set("partition cpus nodes gpus gpu_type account qos mem_bytes time_seconds".split()):
        raise ValueError("unsupported resource fields")
    for key, number in resources.items():
        if number is None:
            continue
        if key in ("partition", "account", "qos", "gpu_type"):
            _text(number, "resources." + key, empty=key == "gpu_type")
        elif key in ("cpus", "nodes", "gpus"):
            if type(number) is not int or not (0 if key == "gpus" else 1) <= number <= 10**9:
                raise ValueError(f"resources.{key} must be a bounded allocation count")
        elif key == "mem_bytes":
            if type(number) is not int or not 1 <= number <= 9223372036854775807:
                raise ValueError("resources.mem_bytes must be positive integral bytes")
        elif isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not 0 < number <= 3162240000:
            raise ValueError("resources.time_seconds must be a bounded positive duration")
    return value


def _root(path):
    if not isinstance(path, str) or not path or "\x00" in path:
        raise ValueError("project root must be an explicit filesystem path")
    root = os.path.abspath(os.path.expanduser(path))
    # Pin every parent, including the supplied root's ancestors. A valid
    # inventory cannot turn a replaced project directory into an external read.
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in root.split("/"):
            if not component:
                continue
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return root, fd
    except BaseException:
        os.close(fd)
        raise


def _directory(root_fd, path):
    relative_path(path)
    fd = os.dup(root_fd)
    try:
        for component in path.split("/"):
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read(root_fd, path, limit, *, truncate=False):
    relative_path(path)
    fd, parent, name = _open_local(root_fd, path)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("file changed to a nonregular file")
        if before.st_size > limit and not truncate:
            raise ValueError(f"{path} exceeds the {limit}-byte limit")
        expected = min(before.st_size, limit)
        pieces, remaining = [], expected
        while remaining:
            piece = os.read(fd, min(remaining, 65536))
            if not piece:
                break
            pieces.append(piece)
            remaining -= len(piece)
        named = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if remaining or _signature(before) != _signature(os.fstat(fd)) or _signature(before) != _signature(named):
            raise ValueError(f"{path} changed during inspection; refresh to retry")
        # Reopening through the root also detects a replaced parent directory.
        verify, verify_parent, _ = _open_local(root_fd, path)
        try:
            if _signature(before) != _signature(os.fstat(verify)):
                raise ValueError(f"{path} changed during inspection; refresh to retry")
        finally:
            os.close(verify)
            os.close(verify_parent)
        return b"".join(pieces), before.st_size
    finally:
        os.close(fd)
        os.close(parent)


def _inventory(root_fd, directory, budget=None):
    data, size = _read(root_fd, "runs/" + directory + "/run.json", MAX_INVENTORY_BYTES)
    if budget is not None:
        budget[0] += len(data)
    value = validate_inventory(_json(data))
    if value["run_id"] != directory:
        raise ValueError("run_id must match its attempt directory")
    return {"directory": directory, "inventory": value, "bytes": size, **{key: value.get(key) for key in ("run_id", "experiment_id", "attempt", "state", "job_id", "name", "start", "end")}}


def discover_project(path, *, files=None):
    """Inspect at most 256 direct attempts, never project descendants."""
    _local(files)
    root, root_fd = _root(path)
    result = {"status": "ready", "root": root, "runs": [], "warnings": [], "limited": False, "bytes_read": 0, "entries_seen": 0}
    try:
        try:
            runs_fd = _directory(root_fd, "runs")
        except FileNotFoundError:
            result["summary"] = "No runs directory; create runs/<run_id>/run.json using the reporting standard"
            return result
        try:
            names = []
            with os.scandir(runs_fd) as entries:
                for entry in entries:
                    result["entries_seen"] += 1
                    if result["entries_seen"] > MAX_DIRECTORY_ENTRIES:
                        result["limited"] = True
                        break
                    if not _IDENT.fullmatch(entry.name):
                        continue
                    if entry.is_symlink():
                        if len(result["warnings"]) < 32:
                            result["warnings"].append(f"{entry.name}: symlink attempt refused")
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        names.append(entry.name)
                        if len(names) > MAX_RUNS:
                            result["limited"] = True
                            break
            budget = [0]
            for directory in sorted(names[:MAX_RUNS]):
                if budget[0] + MAX_INVENTORY_BYTES > MAX_INVENTORY_TOTAL:
                    result["limited"] = True
                    break
                try:
                    run = _inventory(root_fd, directory, budget)
                    result["runs"].append(run)
                except (OSError, ValueError, RecursionError) as exc:
                    if len(result["warnings"]) < 32:
                        result["warnings"].append(f"{directory}: {exc}")
                finally:
                    result["bytes_read"] = budget[0]
        finally:
            os.close(runs_fd)
    finally:
        os.close(root_fd)
    result["runs"].sort(key=lambda run: (run.get("start") or 0, run["run_id"]), reverse=True)
    result["summary"] = f"{len(result['runs'])} valid attempt inventories" + ("; bounded discovery limit reached" if result["limited"] else "")
    return result


def job_project_roots(workdir, registered=""):
    """Choose at most two lexical roots; never search arbitrary ancestors.

    A job normally runs at ROOT, or beneath ROOT/runs/RUN_ID. Other layouts
    require an explicit :project ROOT registration.
    """
    roots = []
    if isinstance(registered, str) and registered:
        roots.append(os.path.abspath(os.path.expanduser(registered)))
    if isinstance(workdir, str) and workdir.startswith("/") and len(workdir) <= 4096 and all(c.isprintable() for c in workdir):
        path = os.path.normpath(workdir)
        parts = path.split("/")
        indexes = [index for index in range(1, len(parts) - 1) if parts[index] == "runs" and _IDENT.fullmatch(parts[index + 1])]
        root = "/".join(parts[:indexes[-1]]) or "/" if indexes else path
        if root not in roots:
            roots.append(root)
    return roots[:2]


def discover_job(roots, job_id, *, files=None):
    """Bind a single exact scheduler identity, refusing partial/ambiguous scans."""
    _local(files)
    _text(job_id, "job_id")
    if not isinstance(roots, (list, tuple)) or len(roots) > 2:
        raise ValueError("automatic discovery permits at most two explicit roots")
    projects_found, matches, warnings = [], [], []
    incomplete = False
    seen = set()
    for root in roots:
        try:
            found = discover_project(root, files=files)
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as exc:
            warnings.append(f"Project unavailable: {root}: {exc}")
            incomplete = True
            continue
        if found["root"] in seen:
            continue
        seen.add(found["root"])
        projects_found.append(found)
        incomplete = incomplete or found["limited"] or bool(found["warnings"])
        warnings.extend(found["warnings"][:32])
        matches.extend((found["root"], run["run_id"]) for run in found["runs"] if run.get("job_id") == job_id)
    result = {"status": "missing", "selected": None, "projects": projects_found, "warnings": warnings[:64],
              "summary": f"No run inventory declares exact job_id {job_id}"}
    if incomplete:
        result.update(status="incomplete", summary="Project discovery is incomplete; choose a run explicitly with :runs")
    elif len(matches) > 1:
        result.update(status="ambiguous", summary=f"{len(matches)} inventories declare job_id {job_id}; choose the actual attempt with :runs")
    elif len(matches) == 1:
        selected = select_run(*matches[0], files=files)
        if selected["binding"].get("job_id") != job_id:
            result.update(status="changed", summary="Run identity changed during discovery; waiting for the next refresh")
        else:
            result.update(status="ready", selected=selected, summary=f"Linked job {job_id} to run {matches[0][1]}")
    return result


@contextmanager
def bound_run_root(binding):
    """Pin and revalidate one exact run before a report read, including parents."""
    if not isinstance(binding, dict):
        raise ValueError("an exact run binding is required")
    root, project_fd = _root(binding.get("project_root"))
    run_fd = None
    try:
        run_id = binding.get("run_id")
        if not isinstance(run_id, str) or not _IDENT.fullmatch(run_id):
            raise ValueError("invalid bound run ID")
        expected = os.path.join(root, "runs", run_id)
        if binding.get("run_root") != expected:
            raise ValueError("bound run root is outside its project")
        current = _inventory(project_fd, run_id)["inventory"]
        if current.get("job_id") != binding.get("job_id"):
            raise ValueError("run job identity changed; waiting for automatic rebinding")
        run_fd = _directory(project_fd, "runs/" + run_id)
        yield project_fd, run_fd, current
    finally:
        if run_fd is not None:
            os.close(run_fd)
        os.close(project_fd)


def bound_relative(binding, path, current, *, key=None):
    """Check a current declaration before reading a cached absolute source."""
    if not isinstance(path, str) or not os.path.isabs(path):
        raise ValueError("bound report path must be absolute")
    relative = os.path.relpath(path, binding["run_root"]).replace(os.sep, "/")
    relative_path(relative)
    if key is not None and current.get("paths", {}).get(key) != relative:
        raise ValueError("run report declaration changed; waiting for automatic rebinding")
    return relative


def read_bound_json(binding, path, *, key=None, max_bytes=1048576):
    """Read stable JSON through an exact run descriptor, never its replaced path."""
    with bound_run_root(binding) as (_, run_fd, current):
        relative = bound_relative(binding, path, current, key=key)
        data, _ = _read(run_fd, relative, max_bytes)
        value = _json(data)
        from .planning_io import _bounded
        _bounded(value, 32)
        if not isinstance(value, (dict, list)):
            raise ValueError("run report JSON must be an object or array")
        return value


def read_bound_passport(binding, path):
    with bound_run_root(binding) as (_, run_fd, current):
        relative = bound_relative(binding, path, current)
        directory = current.get("paths", {}).get("passports", "")
        if not binding.get("passport_explicit") and (not directory or not relative.startswith(directory + "/")):
            raise ValueError("passport is outside the current declared passport directory")
        data, _ = _read(run_fd, relative, 1048576)
        value = _json(data)
        from .provenance import validate
        validate(value)
        if binding.get("job_id") is not None and value.get("job_id") not in (None, binding["job_id"]):
            raise ValueError("passport job identity does not match the selected run")
        return value


def read_bound_artifacts(binding, *, files=None):
    _local(files)
    with bound_run_root(binding) as (project_fd, run_fd, _):
        data, _ = _read(project_fd, ".tower/contracts/outputs.v1.json", 262144)
        return validate_contract(_json(data), binding["run_root"], files=files, root_fd=run_fd)


def read_bound_tail(binding, entry, max_bytes):
    """Read one currently declared log through pinned, no-symlink parents."""
    if type(max_bytes) is not int or not 0 <= max_bytes <= 1048576:
        raise ValueError("project evidence log read is bounded to one MiB")
    with bound_run_root(binding) as (_, run_fd, current):
        path = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(path, str) or not os.path.isabs(path):
            raise ValueError("project log path must be absolute")
        allowed = {os.path.join(binding["run_root"], current["paths"][key])
                   for key in ("stdout", "stderr") if current.get("paths", {}).get(key)}
        manifest = current.get("paths", {}).get("log_index")
        if manifest:
            data, _ = _read(run_fd, manifest, 262144)
            document = _json(data)
            if document.get("run_id", binding["run_id"]) != binding["run_id"]:
                raise ValueError("log manifest identity does not match selected run")
            from .log_catalog import _manifest_entries
            allowed.update(item["path"] for item in _manifest_entries(document, binding.get("job_id"), os.path.join(binding["run_root"], manifest)))
        if path not in allowed:
            raise ValueError("project log is no longer declared by this exact run")
        relative = os.path.relpath(path, binding["run_root"]).replace(os.sep, "/")
        external_root = None
        try:
            if relative == ".." or relative.startswith("../"):
                external_root = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                root_fd, relative = external_root, path.lstrip("/")
            else:
                root_fd = run_fd
            relative_path(relative)
            fd, parent, name = _open_local(root_fd, relative)
            try:
                before = os.fstat(fd)
                length = min(before.st_size, max_bytes)
                data = os.pread(fd, length, max(0, before.st_size - length))
                named = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if len(data) != length or _signature(before) != _signature(os.fstat(fd)) or _signature(before) != _signature(named):
                    raise ValueError("project log changed during evidence read")
                identity = {"size": before.st_size, "ident": (before.st_dev, before.st_ino), "updated": (before.st_mtime_ns, before.st_ctime_ns)}
                return data, before.st_size, identity
            finally:
                os.close(fd)
                os.close(parent)
        finally:
            if external_root is not None:
                os.close(external_root)


def _declared_path(root_fd, root, value, *, directory=False):
    relative_path(value)
    try:
        if directory:
            fd = _directory(root_fd, value)
            os.close(fd)
        else:
            fd, parent, _ = _open_local(root_fd, value)
            os.close(fd)
            os.close(parent)
    except FileNotFoundError:
        return os.path.join(root, value), "not created yet"
    return os.path.join(root, value), "ready"


def select_run(path, run_id, *, files=None):
    """Revalidate one explicit attempt and return its exact binding and sources."""
    _local(files)
    if not isinstance(run_id, str) or not _IDENT.fullmatch(run_id):
        raise ValueError("run ID must be a safe ASCII identifier")
    root, root_fd = _root(path)
    run_fd = None
    try:
        run = _inventory(root_fd, run_id)
        inventory = run["inventory"]
        run_root = os.path.join(root, "runs", run_id)
        run_fd = _directory(root_fd, "runs/" + run_id)
        binding = {"project_root": root, "run_root": run_root, **{key: inventory.get(key) for key in ("run_id", "experiment_id", "attempt", "state", "job_id")},
                   "metrics_file": "", "log_manifest": "", "stdout": "", "stderr": "", "contract": "", "passport": "",
                   "planning_file": "", "planning_files": {}, "submit_file": ""}
        result = {"status": "ready", "run": run, "binding": binding, "logs": [], "warnings": []}
        paths = inventory.get("paths", {})
        for key, target in (("metrics", "metrics_file"), ("log_index", "log_manifest"), ("stdout", "stdout"), ("stderr", "stderr"),
                            ("planning", "planning_file"), ("submit", "submit_file")):
            if key not in paths:
                continue
            try:
                absolute, state = _declared_path(run_fd, run_root, paths[key])
                binding[target] = absolute
                if state != "ready":
                    result["warnings"].append(f"{key}: {state}")
            except (OSError, ValueError) as exc:
                result["warnings"].append(f"{key}: binding refused ({exc})")
        for key in PLANNING_PATHS:
            if key not in paths:
                continue
            try:
                absolute, state = _declared_path(run_fd, run_root, paths[key])
                binding["planning_files"][key] = absolute
                if state != "ready":
                    result["warnings"].append(f"{key}: {state}")
            except (OSError, ValueError) as exc:
                result["warnings"].append(f"{key}: binding refused ({exc})")
        for key, role in (("stdout", "stdout"), ("stderr", "stderr")):
            if binding[key]:
                result["logs"].append({"id": "project." + key, "path": binding[key], "label": key, "group": "Run streams", "role": role, "source": "project", "run_id": run_id, "job_id": binding["job_id"]})
        if binding["log_manifest"]:
            try:
                data, _ = _read(run_fd, paths["log_index"], 262144)
                manifest = _json(data)
                if manifest.get("run_id", run_id) != run_id:
                    raise ValueError("log manifest run_id does not match selected run")
                from .log_catalog import _manifest_entries
                for entry in _manifest_entries(manifest, binding["job_id"], binding["log_manifest"]):
                    relative = os.path.relpath(entry["path"], run_root).replace(os.sep, "/")
                    external = relative == ".." or relative.startswith("../")
                    try:
                        if external:
                            # Native log indexes deliberately permit exact sibling
                            # and absolute locations. They stay explicit, with
                            # visible provenance; no directory scan is implied.
                            external_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
                            try:
                                _declared_path(external_fd, "/", entry["path"].lstrip("/"))
                            finally:
                                os.close(external_fd)
                            result["warnings"].append(f"External log declaration: {entry['label']} {entry['path']}")
                        else:
                            relative_path(relative)
                            _declared_path(run_fd, run_root, relative)
                    except (OSError, ValueError) as exc:
                        result["warnings"].append(f"Log {entry['label']}: unsafe declaration refused ({exc})")
                        continue
                    if entry["path"] not in {item["path"] for item in result["logs"]}:
                        result["logs"].append({**entry, "source": "project", "role": "application", "run_id": run_id, "job_id": binding["job_id"], "external": external})
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                result["warnings"].append(f"log_index: {exc}")
                binding["log_manifest"] = ""
        try:
            data, _ = _read(root_fd, ".tower/contracts/outputs.v1.json", 262144)
            _contract(_json(data))
            binding["contract"] = os.path.join(root, ".tower/contracts/outputs.v1.json")
        except FileNotFoundError:
            result["warnings"].append("No standard output contract; attach one explicitly with :artifacts CONTRACT RUN_ROOT")
        except (OSError, ValueError) as exc:
            result["warnings"].append(f"Output contract refused: {exc}")
        passport_dir = paths.get("passports")
        if passport_dir:
            passport_fd = None
            try:
                passport_fd = _directory(run_fd, passport_dir)
                names = []
                with os.scandir(passport_fd) as entries:
                    for index, entry in enumerate(entries):
                        if index >= 64:
                            raise ValueError("passport directory has more than 64 entries; choose a passport explicitly")
                        if entry.name.endswith(".json") and entry.is_file(follow_symlinks=False):
                            names.append(entry.name)
                if len(names) == 1:
                    passport_path = passport_dir + "/" + names[0]
                    passport = read_passport(run_root, passport_path, job_id=binding["job_id"])
                    binding["passport"] = os.path.join(run_root, passport_path)
                    result["passport_record"] = passport
                elif len(names) > 1:
                    result["warnings"].append("Multiple passports; choose the actual record with :run passport RELATIVE_PATH")
            except FileNotFoundError:
                pass
            except (OSError, ValueError) as exc:
                result["warnings"].append(f"Passport binding refused: {exc}")
            finally:
                if passport_fd is not None:
                    os.close(passport_fd)
        return result
    finally:
        if run_fd is not None:
            os.close(run_fd)
        os.close(root_fd)


def read_passport(root, path, *, job_id=None, files=None):
    _local(files)
    _, fd = _root(root)
    try:
        data, _ = _read(fd, path, 1024 * 1024)
        passport = _json(data)
        from .provenance import validate
        validate(passport)
        if job_id is not None and passport.get("job_id") not in (None, job_id):
            raise ValueError("passport job identity does not match the selected run")
        return passport
    finally:
        os.close(fd)


def _output_status(output):
    checks = output.get("checks", [])
    if output.get("missing") or any(check.get("name") == "presence" and check.get("status") == "fail" for check in checks):
        return "missing"
    state = output.get("status", "not_checked")
    return "incomplete" if state == "not_checked" else state


def artifact_tree(contract_path, root, *, files=None):
    """Validate declared outputs and publish a bounded navigable virtual tree."""
    _local(files)
    from .artifacts import load_contract
    contract = load_contract(contract_path)
    checked = validate_contract(contract, root, files=files)
    specifications = {item["path"]: item for item in contract["outputs"]}
    nodes = {}
    limited = False
    for output in checked["outputs"]:
        parts = output["path"].split("/")
        prefix = ""
        for index, part in enumerate(parts):
            prefix = prefix + "/" + part if prefix else part
            if prefix not in nodes and len(nodes) >= MAX_TREE_NODES:
                limited = True
                break
            leaf = index == len(parts) - 1
            node = nodes.setdefault(prefix, {"path": prefix, "name": part, "depth": index, "directory": not leaf, "status": "directory"})
            if leaf:
                node.update(directory=False, status=_output_status(output), output=output, specification=specifications[prefix], size=output.get("size"))
    ordered = sorted(nodes.values(), key=lambda node: tuple(node["path"].split("/")))
    return {"status": checked["status"], "summary": checked["summary"], "root": os.path.abspath(os.path.expanduser(root)), "contract": os.path.abspath(os.path.expanduser(contract_path)),
            "nodes": ordered, "validation": checked, "limited": limited, "declared": len(contract["outputs"])}


def preview_artifact(root, specification, *, files=None):
    """Read a stable 64 KiB prefix of one exact declared regular output."""
    _local(files)
    _contract({"version": 1, "outputs": [specification]})
    root, fd = _root(root)
    path = specification["path"]
    try:
        data, size = _read(fd, path, MAX_PREVIEW_BYTES, truncate=True)
    finally:
        os.close(fd)
    result = {"status": "ready", "root": root, "path": path, "bytes_read": len(data), "size": size, "truncated": size > len(data), "lines": [], "format": specification.get("format", "text")}
    try:
        if b"\x00" in data:
            raise UnicodeError("NUL bytes indicate binary content")
        text = codecs.getincrementaldecoder("utf-8-sig")().decode(data, final=not result["truncated"])
    except UnicodeError:
        result.update(status="unsupported", summary="Binary or invalid UTF-8 output; no text preview", format="binary")
        return result
    if result["format"] == "json" and not result["truncated"]:
        try:
            text = json.dumps(_json(data), ensure_ascii=False, indent=2, allow_nan=False)
        except (ValueError, RecursionError) as exc:
            result.update(status="invalid", summary=f"Invalid JSON: {exc}")
    elif result["format"] == "csv":
        try:
            rows = []
            for index, values in enumerate(csv.reader(io.StringIO(text, newline=""), strict=True)):
                if index >= MAX_PREVIEW_LINES:
                    result["truncated"] = True
                    break
                rows.append(" | ".join(values))
            text = "\n".join(rows)
        except csv.Error as exc:
            result.update(status="partial" if result["truncated"] else "invalid", summary=f"CSV prefix could not parse: {exc}")
    # A huge single line or JSON indentation cannot grow the published snapshot.
    if len(text) > MAX_PREVIEW_BYTES:
        result["truncated"] = True
    text = text[:MAX_PREVIEW_BYTES]
    lines = text.splitlines()
    if len(lines) > MAX_PREVIEW_LINES:
        result["truncated"] = True
    result["lines"] = lines[:MAX_PREVIEW_LINES]
    result.setdefault("summary", f"{len(data)} of {size} source bytes; prefix preview" if result["truncated"] else f"{size} source bytes")
    return result
