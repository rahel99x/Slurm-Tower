"""Read-only prerequisite checks; never sample, submit, or change a cluster."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys

from .remote import SshBackend
from .slurm import CommandError

REQUIRED = ("squeue", "scontrol", "sinfo", "sacct", "sstat")
OPTIONAL = {
    "sshare": "fair-share information",
    "sreport": "allocation usage",
    "sacctmgr": "allocation limits",
    "sbatch": "queue forecasts and resubmission",
    "scancel": "job cancellation",
}


def diagnose(cfg, *, fake=False, host="", ssh_user=""):
    """Return capability evidence, including missing optional tools separately."""
    host = "" if fake else (host or cfg["host"])
    mode = "demo" if fake else "remote" if host else "local"
    checks = []

    def add(name, ok, detail, required=True):
        checks.append(dict(name=name, status="ok" if ok else "error" if required else "warning",
                           required=required, detail=detail))

    add("Python", sys.version_info >= (3, 10), sys.version.split()[0])
    add("Interactive terminal", importlib.util.find_spec("curses") is not None,
        "curses supports the interactive screen; text, JSON and ASCII reports also work without it", False)
    if fake:
        add("Simulated cluster", True, "No Slurm installation or cluster credentials required")
    else:
        found = set()
        connected = True
        if host:
            connected = bool(shutil.which("ssh"))
            add("SSH client", connected, "OpenSSH must be available locally")
            if connected:
                # Tool names are constants; no host, username, or config enters the shell program.
                probe = ('for tool in ' + " ".join((*REQUIRED, *OPTIONAL)) + '; do '
                         'if command -v "$tool" >/dev/null 2>&1; then printf "%s\\n" "$tool"; fi; done')
                try:
                    backend = SshBackend(host, user=ssh_user or cfg["ssh_user"], opts=cfg["ssh_opts"], control=False)
                    output, _ = backend.run(["sh", "-c", probe], timeout=8)
                    found = set(output.splitlines())
                    add("SSH connection", True, "Read-only command probe completed with host-key verification")
                except (CommandError, ValueError) as exc:
                    connected = False
                    add("SSH connection", False, str(exc))
        else:
            found = {tool for tool in (*REQUIRED, *OPTIONAL) if shutil.which(tool)}
        if connected:
            for tool in REQUIRED:
                add(tool, tool in found, "available" if tool in found else "Load your site's Slurm module or use --host LOGIN")
            for tool, purpose in OPTIONAL.items():
                add(tool, tool in found, purpose, False)

    ready = all(c["status"] != "error" for c in checks)
    return dict(mode=mode, ready=ready, checks=checks,
                next_step=("tower --fake" if fake else "tower --host LOGIN" if host else "tower") if ready
                else "Use tower --fake to explore; load Slurm locally or configure SSH access to a login node.",
                scope="Prerequisites only; cluster permissions, accounting data and live job behavior require a live smoke check.")


def render(result, *, as_json=False):
    if as_json:
        return json.dumps(result, indent=2)
    lines = [f"Slurm Tower / {result['mode']} environment", ""]
    for check in result["checks"]:
        label = {"ok": "OK", "warning": "OPTIONAL", "error": "MISSING"}[check["status"]]
        lines.append(f"  {label:8} {check['name']}: {check['detail']}")
    lines.extend(["", "Prerequisites ready." if result["ready"] else "Some required capabilities are missing.",
                  result["scope"], f"Next: {result['next_step']}"])
    return "\n".join(lines)
