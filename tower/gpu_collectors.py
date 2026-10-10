"""Bounded vendor adapters for allocation-scoped GPU observations.

Vendor CLIs run in a short-lived stdlib Python helper *inside* the allocation.
Neither utility discovery nor hardware reads run in the terminal renderer.
NVIDIA CSV remains accepted through slurm.parse_nvsmi for imported recordings.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re

from .model import GpuSample

PROVIDERS = ("auto", "nvidia", "amd", "intel")
MAX_BYTES = 1 << 20
MAX_DEVICES = 256
MAX_NODES = 256


def provider_name(value):
    if not isinstance(value, str) or value.lower() not in PROVIDERS:
        raise ValueError("GPU provider must be auto, nvidia, amd, or intel")
    return value.lower()


def counter(value, upper=None):
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) and result >= 0 and (upper is None or result <= upper) else None


def clean(value, limit=256):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return ""
    value = str(value)
    if value.lower() in {"n/a", "unknown", "none", "not supported"}:
        return ""
    return "".join(c for c in value[:limit] if c.isprintable())


def index(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 0 <= value <= 65535:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,5}", value):
        return int(value) if int(value) <= 65535 else None
    return None


def decode(raw):
    if not isinstance(raw, str) or len(raw) > MAX_BYTES or len(raw.encode("utf-8")) > MAX_BYTES:
        raise ValueError("GPU reply exceeds the 1 MiB inspection limit")
    try:
        return json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise ValueError("GPU utility returned invalid JSON") from exc


def _items(value, key=None):
    if isinstance(value, dict) and value.get("error"):
        raise ValueError("GPU utility reported: " + clean(value["error"], 300))
    if key and isinstance(value, dict) and key in value:
        value = value[key]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list) or len(value) > MAX_DEVICES:
        raise ValueError("GPU reply has invalid or excessive device records")
    if any(not isinstance(item, dict) for item in value):
        raise ValueError("GPU reply contains a non-object device record")
    return value


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _inventory(raw, vendor):
    rows = _items(decode(raw), "device_list" if vendor == "intel" else "gpu_data")
    result = {}
    for row in rows:
        ident = index(row.get("device_id" if vendor == "intel" else "gpu"))
        if ident is None:
            raise ValueError("GPU inventory lacks a valid device index")
        if ident is not None:
            if ident in result:
                raise ValueError("Duplicate GPU inventory index")
            result[ident] = row
    return result


def _memory(value, *, amd=False):
    unit = value.get("unit", "") if isinstance(value, dict) else ""
    number = counter(value)
    if number is None:
        return None
    # AMD CLI labels MiB values as MB (the upstream code divides by 1024**2).
    units = {"": 1, "MiB": 1, "MB": 1 if amd else 1e6 / 2**20,
             "GiB": 1024, "GB": 1e9 / 2**20, "B": 1 / 2**20,
             "bytes": 1 / 2**20, "KiB": 1 / 1024}
    return number * units[unit] if isinstance(unit, str) and unit in units else None


def parse_amd(metric_json, inventory_json="[]", node=""):
    """AMD SMI metric --usage --mem-usage --json; list --json identity."""
    inventory = _inventory(inventory_json, "amd")
    result = []
    for row in _items(decode(metric_json), "gpu_data"):
        ident = index(row.get("gpu"))
        if ident is None:
            raise ValueError("GPU metric lacks a valid device index")
        static = inventory.get(ident, {})
        usage, memory = _mapping(row.get("usage")), _mapping(row.get("mem_usage"))
        total = _memory(memory.get("total_vram"), amd=True)
        result.append(GpuSample(node, ident, counter(usage.get("gfx_activity"), 100),
            _memory(memory.get("used_vram"), amd=True), total if total else None,
            clean(static.get("market_name") or static.get("name") or "AMD GPU"),
            vendor="amd", uuid=clean(static.get("uuid")), bdf=clean(static.get("bdf")),
            partition=clean(static.get("partition_id"))))
    return _unique(result)


def parse_intel(metric_json, inventory_json='{"device_list":[]}', node=""):
    """XPU-SMI current device counters; tile-only data stays unmeasured.

    Device utilization is NOT an average of tiles; unequal tiles and shared
    memory make such aggregation misleading. No avg/max substitutes for value.
    """
    inventory = _inventory(inventory_json, "intel")
    result = []
    for row in _items(decode(metric_json), "device_list"):
        ident = index(row.get("device_id"))
        if ident is None:
            raise ValueError("GPU metric lacks a valid device index")
        static = inventory.get(ident, {})
        levels = row.get("device_level", [])
        if not isinstance(levels, list) or len(levels) > 512:
            raise ValueError("Intel GPU metrics list exceeds limit")
        metrics = {}
        for item in levels:
            if isinstance(item, dict) and isinstance(item.get("metrics_type"), str):
                key = item["metrics_type"]
                if key in metrics:
                    raise ValueError("Duplicate Intel GPU counter")
                metrics[key] = counter(item.get("value"))
        total = _memory(static.get("memory_physical_size"))
        result.append(GpuSample(node, ident,
            counter(metrics.get("XPUM_STATS_GPU_UTILIZATION"), 100),
            metrics.get("XPUM_STATS_MEMORY_USED"), total if total else None,
            clean(static.get("device_name") or "Intel GPU"), vendor="intel",
            uuid=clean(static.get("uuid")), bdf=clean(static.get("pci_bdf_address"))))
    return _unique(result)


def parse_nvidia(raw, node=""):
    if not isinstance(raw, str) or len(raw) > MAX_BYTES:
        raise ValueError("GPU CSV reply exceeds inspection limit")
    rows = []
    try:
        for fields in csv.reader(io.StringIO(raw), skipinitialspace=True):
            if len(rows) >= MAX_DEVICES:
                raise ValueError("GPU CSV has too many device records")
            if not fields:
                continue
            if len(fields) < 5:
                raise ValueError("NVIDIA GPU row is incomplete")
            fields = [field.strip() for field in fields]
            ident = index(fields[0])
            if ident is None:
                raise ValueError("NVIDIA GPU row lacks a valid device index")
            total = counter(fields[3])
            rows.append(GpuSample(node, ident, counter(fields[1], 100), counter(fields[2]),
                total if total else None, clean(fields[4]), vendor="nvidia",
                uuid=clean(fields[5]) if len(fields) > 5 else "",
                bdf=clean(fields[6]) if len(fields) > 6 else "",
                partition="mig-parent" if len(fields) > 7 and fields[7].lower() == "enabled" else ""))
    except csv.Error as exc:
        raise ValueError("Invalid GPU CSV reply") from exc
    return _unique(rows)


def _unique(rows):
    seen = set()
    for row in rows:
        key = (row.vendor, row.uuid or row.bdf or str(row.index), row.partition)
        if key in seen:
            raise ValueError("Duplicate GPU device identity")
        seen.add(key)
    return rows


def _tokens(raw):
    """Bounded Slurm global IDs, UUIDs or PCI BDFs; never expand huge ranges."""
    if not isinstance(raw, str) or len(raw) > 16384:
        raise ValueError("GPU allocation identity unavailable or oversized")
    result = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        match = re.fullmatch(r"([0-9]+)-([0-9]+)", part)
        if match:
            lo, hi = map(int, match.groups())
            if hi < lo or hi - lo >= MAX_DEVICES:
                raise ValueError("Invalid GPU allocation range")
            result.update(str(i) for i in range(lo, hi + 1))
        elif re.fullmatch(r"[a-zA-Z0-9_.:/-]{1,128}", part):
            result.add(part.lower())
        else:
            raise ValueError("Invalid GPU allocation identifier")
        if len(result) > MAX_DEVICES:
            raise ValueError("Too many GPU allocation identifiers")
    return result


def parse_probe_output(raw, *, job_id="", require_scope=True, expected_nodes=None):
    """Parse interleaved --label lines and return (samples, cache, warnings).

    Only complete helper JSON lines count. Scope is checked independently on
    every node. Unknown/ambiguous ownership is unavailable, never node telemetry.
    """
    if not isinstance(raw, str) or len(raw) > MAX_BYTES or len(raw.encode("utf-8")) > MAX_BYTES:
        raise ValueError("GPU probe reply exceeds the 1 MiB inspection limit")
    samples, cache, warnings, seen_nodes = [], {}, [], set()
    for line in raw.splitlines():
        line = re.sub(r"^\s*\d+:\s?", "", line)
        if not line.startswith('{"tower_gpu":'):
            continue
        payload = decode(line)
        if payload.get("tower_gpu") != 1:
            continue
        node = clean(payload.get("node"))
        if not node or node in seen_nodes or len(seen_nodes) >= MAX_NODES:
            raise ValueError("Invalid or duplicate GPU probe node")
        seen_nodes.add(node)
        if require_scope:
            identities = [payload.get("job_id")]
            if payload.get("array_job_id") and payload.get("array_task_id"):
                identities.append(f"{payload['array_job_id']}_{payload['array_task_id']}")
            if payload.get("het_job_id") and payload.get("het_offset") is not None:
                identities.append(f"{payload['het_job_id']}+{payload['het_offset']}")
            if job_id not in identities:
                raise ValueError("GPU probe allocation identity does not match requested job")
            allowed = _tokens(payload.get("gpus", ""))
            if not allowed:
                warnings.append(f"{node}: Slurm GPU allocation identifiers unavailable; refusing node-wide attribution")
                continue
        else:
            allowed = set()
        devices = payload.get("vendors", {})
        if not isinstance(devices, dict) or len(devices) > 3:
            raise ValueError("Invalid GPU provider envelope")
        node_rows = []
        node_cache = {}
        for vendor, record in devices.items():
            if vendor not in PROVIDERS[1:] or not isinstance(record, dict):
                continue
            if record.get("error"):
                warnings.append(f"{node}/{vendor}: {clean(record['error'], 300)}")
                continue
            metrics, inventory = record.get("metrics", ""), record.get("inventory", "[]")
            parser = {"nvidia": parse_nvidia, "amd": parse_amd, "intel": parse_intel}[vendor]
            parsed = parser(metrics, node=node) if vendor == "nvidia" else parser(metrics, inventory, node)
            node_rows.extend(parsed)
            if vendor != "nvidia":
                node_cache[vendor] = inventory
        hardware = payload.get("hardware_vendors", [])
        if not isinstance(hardware, list) or any(v not in PROVIDERS[1:] for v in hardware):
            raise ValueError("Invalid GPU hardware vendor evidence")
        # Keep failed/empty adapters in the namespace set: a driver failure
        # must not turn an ambiguous global GPU index into a matching device.
        namespaces = set(devices) | set(hardware) | {row.vendor for row in node_rows}
        mixed = len(namespaces) > 1
        if require_scope and mixed and any(token.isdecimal() for token in allowed):
            warnings.append(f"{node}: mixed GPU vendor indices cannot be matched to numeric Slurm IDs; UUID/BDF allocation identity is required")
        visible = payload.get("visible", {})
        if not isinstance(visible, dict):
            raise ValueError("Invalid GPU runtime visibility evidence")
        stable_visibility = {}
        if require_scope:
            for vendor in devices:
                tokens = _tokens(visible.get(vendor, ""))
                stable_visibility[vendor] = {token for token in tokens if not token.isdecimal()}
        numeric = {token for token in allowed if token.isdecimal()}
        # Slurm's global GRES indices need not equal a utility's indices.
        # Numeric scope can identify a complete visible set, not an arbitrary
        # subset. This also preserves the common single-GPU workstation case.
        complete_set = (not mixed and bool(numeric) and len(numeric) == len(allowed)
                        and len(node_rows) == len(numeric)
                        and not any(row.partition == "mig-parent" for row in node_rows))
        if require_scope and node_rows and numeric and not complete_set and not any(stable_visibility.values()):
            warnings.append(f"{node}: numeric Slurm GPU IDs do not prove a complete visible device set; UUID/BDF runtime visibility is required for a subset")
        for row in node_rows:
            if require_scope and row.partition == "mig-parent":
                warnings.append(f"{node}/nvidia: physical MIG parent cannot supply partition-specific job counters")
                continue
            if require_scope:
                candidates = {row.uuid.lower(), row.bdf.lower()} - {""}
                stable = stable_visibility.get(row.vendor, set())
                matched = bool(candidates.intersection(stable or allowed))
                if not matched and (stable or not complete_set):
                    continue
            samples.append(row)
        if node_cache:
            cache[node] = node_cache
        errors = payload.get("errors", [])
        if isinstance(errors, list):
            warnings.extend(f"{node}: {clean(e, 300)}" for e in errors[:5])
    if not seen_nodes:
        raise ValueError("No valid allocation GPU probe reply (python3 must be available on compute nodes)")
    if expected_nodes is not None and len(seen_nodes) < expected_nodes:
        warnings.append(f"GPU probe returned {len(seen_nodes)}/{expected_nodes} node replies; coverage is incomplete")
    if len(samples) > MAX_DEVICES * MAX_NODES:
        raise ValueError("Excessive GPU samples")
    return samples, cache, warnings[:16]


# Standalone program: do not import Tower on compute nodes. Fixed commands only.
# Every child has a deadline and bounded disk output before the parent reads it.
PROBE_SOURCE = r'''
import glob, json, os, shutil, socket, subprocess, sys, tempfile, time
LIMIT = 262144
provider, budget, cached_text = sys.argv[1:4]
deadline = time.monotonic() + max(.2, min(10., float(budget)))
node = os.getenv("SLURMD_NODENAME") or socket.gethostname()
try:
    cached = json.loads(cached_text).get(node, {})
except (ValueError, AttributeError):
    cached = {}

def run(argv):
    remaining = deadline - time.monotonic()
    if remaining <= .05:
        raise RuntimeError("GPU probe time budget exhausted")
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
        def limits():
            import resource
            resource.setrlimit(resource.RLIMIT_FSIZE, (LIMIT, LIMIT))
        try:
            proc = subprocess.run(argv, stdout=output, stderr=error,
                timeout=remaining, preexec_fn=limits)
        except subprocess.TimeoutExpired:
            raise RuntimeError(argv[0] + ": timed out")
        output.seek(0)
        raw = output.read(LIMIT + 1)
        error.seek(0)
        diagnostic = error.read(500).decode("utf-8", "replace").strip()
        if len(raw) >= LIMIT:
            raise RuntimeError(argv[0] + ": output limit exceeded")
        if proc.returncode:
            raise RuntimeError(argv[0] + ": " + (diagnostic or "exit " + str(proc.returncode)))
        return raw.decode("utf-8", "replace")

# Inspect hardware namespaces independently of the selected adapter. A provider
# toggle must not conceal another vendor and make global indices look unique.
hardware_vendors = set()
if glob.glob("/proc/driver/nvidia/gpus/*"):
    hardware_vendors.add("nvidia")
for path in glob.glob("/sys/class/drm/card[0-9]*/device/vendor")[:512]:
    try:
        with open(path) as stream:
            vendor_id = stream.read(32).strip().lower()
        name = {"0x10de": "nvidia", "0x1002": "amd", "0x8086": "intel"}.get(vendor_id)
        if name:
            hardware_vendors.add(name)
    except OSError:
        pass
vendors, errors = {}, []
for vendor, binary in (("nvidia", "nvidia-smi"), ("amd", "amd-smi"), ("intel", "xpu-smi")):
    if provider not in ("auto", vendor):
        continue
    if not shutil.which(binary):
        if provider != "auto":
            errors.append(binary + ": not found")
        continue
    try:
        if vendor == "nvidia":
            vendors[vendor] = {"metrics": run([binary, "--query-gpu=index,utilization.gpu,memory.used,memory.total,name,uuid,pci.bus_id,mig.mode.current", "--format=csv,noheader,nounits"])}
        elif vendor == "amd":
            inventory = cached.get(vendor) or run([binary, "list", "--json"])
            vendors[vendor] = {"inventory": inventory, "metrics": run([binary, "metric", "--usage", "--mem-usage", "--json"])}
        else:
            inventory = cached.get(vendor) or run([binary, "discovery", "-j"])
            data = json.loads(inventory)
            devices = data.get("device_list", [])
            if not isinstance(devices, list) or len(devices) > 256:
                raise RuntimeError("invalid Intel GPU discovery reply")
            metrics = []
            for device in devices:
                if not isinstance(device, dict):
                    continue
                ident = device.get("device_id")
                if type(ident) != int or not 0 <= ident <= 65535:
                    continue
                observation = json.loads(run([binary, "stats", "-d", str(ident), "-j"]))
                if not isinstance(observation, dict) or observation.get("error"):
                    raise RuntimeError("Intel GPU stats: " + str(observation.get("error", "invalid reply") if isinstance(observation, dict) else "invalid reply"))
                metrics.append(observation)
            vendors[vendor] = {"inventory": inventory, "metrics": json.dumps(metrics)}
    except (OSError, ValueError, RuntimeError, AttributeError, RecursionError) as exc:
        vendors[vendor] = {"error": str(exc)[:400]}
if not vendors and not errors:
    errors.append("No supported GPU utility found (nvidia-smi, amd-smi, xpu-smi)")
result = {"tower_gpu": 1, "node": node, "job_id": os.getenv("SLURM_JOB_ID", ""),
    "array_job_id": os.getenv("SLURM_ARRAY_JOB_ID", ""), "array_task_id": os.getenv("SLURM_ARRAY_TASK_ID", ""),
    "het_job_id": os.getenv("SLURM_HET_JOB_ID", ""), "het_offset": os.getenv("SLURM_HET_GROUP", ""),
    "gpus": os.getenv("SLURM_STEP_GPUS") or os.getenv("SLURM_JOB_GPUS", ""),
    "vendors": vendors, "errors": errors, "hardware_vendors": sorted(hardware_vendors),
    "visible": {"nvidia": os.getenv("CUDA_VISIBLE_DEVICES", ""), "amd": os.getenv("ROCR_VISIBLE_DEVICES", "")}}
encoded = json.dumps(result, separators=(",", ":"))
if len(encoded.encode()) > 524288:
    result["vendors"] = {}
    result["errors"] = ["GPU combined output limit exceeded"]
    encoded = json.dumps(result, separators=(",", ":"))
print(encoded)
'''


def probe_command(provider="auto", budget=8., cache=None):
    provider = provider_name(provider)
    cached = json.dumps(cache or {}, separators=(",", ":"))
    if len(cached) > 65536:
        cached = "{}"
    return ["python3", "-I", "-S", "-c", PROBE_SOURCE, provider, str(max(.2, min(10., budget))), cached]
