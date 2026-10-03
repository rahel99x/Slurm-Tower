#!/usr/bin/env python3
"""Repeatable, offline-first development setup. Requires Python 3.10+."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]


class SetupError(Exception):
    pass


def run(command, *, capture=False, timeout=120):
    try:
        result = subprocess.run(
            [str(part) for part in command], cwd=ROOT, text=True,
            capture_output=capture, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupError(f"Could not run {shlex.join(map(str, command))}: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip() if capture else ""
        raise SetupError(f"Command exited {result.returncode}: {shlex.join(map(str, command))}" + (f"\n{detail}" if detail else ""))
    return result.stdout if capture else None


def select_mode(mode, host):
    if mode == "remote" and not host:
        raise SetupError("Remote mode needs --host LOGIN, for example --host me@login.example.edu.")
    if host and mode in ("demo", "local"):
        raise SetupError("--host can only be used with --mode remote or --mode auto.")
    if host and (host.startswith("-") or any(c.isspace() for c in host)):
        raise SetupError("Use an SSH hostname or user@hostname for --host; put SSH options in ~/.ssh/config.")
    if mode != "auto":
        return mode
    return "remote" if host else "local" if shutil.which("squeue") else "demo"


def prepare_venv(path):
    path = path.expanduser().resolve()
    if path == ROOT or path in ROOT.parents:
        raise SetupError("Choose a dedicated virtual-environment directory, not the checkout or one of its parents.")
    if path.exists() and (not path.is_dir() or (any(path.iterdir()) and not (path / "pyvenv.cfg").is_file())):
        raise SetupError(f"Refusing to replace a non-venv path: {path}. Choose a new --venv directory.")
    if not (path / "pyvenv.cfg").is_file():
        print(f"Creating isolated Python environment: {path}", flush=True)
        try:
            # No downloads, ensurepip dependency, or system package changes.
            venv.EnvBuilder(with_pip=False).create(path)
        except (OSError, RuntimeError) as exc:
            raise SetupError(f"Cannot create a venv: {exc}. Install your OS's Python venv package, or run python3 -m tower directly.") from exc
    else:
        print(f"Reusing Python environment: {path}", flush=True)
    python = path / "bin" / "python"
    result = run([python, "-c", "import sys; print(sys.prefix); sys.exit(0 if sys.version_info >= (3, 10) else 'Python 3.10+ required')"], capture=True)
    if Path(result.strip()).resolve() != path:
        raise SetupError(f"{python} is not an isolated interpreter for {path}.")
    return python


def install_dev(python):
    print("Installing optional development tools from the configured pip index...", flush=True)
    probe = subprocess.run([str(python), "-m", "pip", "--version"], capture_output=True, check=False)
    if probe.returncode:
        run([python, "-m", "ensurepip", "--upgrade"])
    run([python, "-m", "pip", "install", "--disable-pip-version-check", "-e", f"{ROOT}[dev]"], timeout=600)


def publish_report(source, destination):
    """Never replace a pre-existing file, including a user-selected report."""
    destination = destination.expanduser().absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("x", encoding="utf-8") as target:
            target.write(source.read_text(encoding="utf-8"))
    except FileExistsError:
        print(f"Existing report preserved: {destination}", flush=True)
        return False
    print(f"Demo report: {destination}", flush=True)
    return True


def validate(python, mode, host, report):
    with tempfile.TemporaryDirectory(prefix="tower-setup-") as temporary:
        scratch = Path(temporary)
        config = scratch / "config.json"
        config.write_text("{}\n", encoding="utf-8")
        command = [python, ROOT / "tower", "--config", config, "--no-state", "--no-plugins"]
        print("Validating simulated jobs, all terminal views, and the ASCII report...", flush=True)
        snapshot = json.loads(run([*command, "--fake", "--json"], capture=True))
        if not isinstance(snapshot, dict) or not snapshot.get("jobs"):
            raise SetupError("The simulated cluster did not produce any jobs.")
        for tab in ("jobs", "cluster", "history", "analytics", "nodes", "group", "deps", "log", "sources"):
            frame = run([*command, "--fake", "--once", "--tab", tab, "--ascii", "--no-color", "--width", "120"], capture=True)
            if not frame.strip() or not frame.isascii():
                raise SetupError(f"The {tab} terminal view did not produce plain ASCII output.")
        preview = scratch / "demo.txt"
        run([*command, "--fake", "--report", preview], capture=True)
        page = preview.read_text(encoding="utf-8")
        if not page.strip() or not page.isascii() or "JOBS" not in page.upper():
            raise SetupError("The report smoke test did not produce a complete ASCII snapshot.")
        publish_report(preview, report)
        print(f"Checking {mode} capabilities...", flush=True)
        flags = ["--fake"] if mode == "demo" else ["--host", host] if mode == "remote" else []
        run([*command, "--doctor", *flags], timeout=45)


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--mode", choices=("auto", "demo", "local", "remote"), default="auto", help="auto chooses remote with --host, local with squeue, otherwise demo")
    ap.add_argument("--host", default="", help="SSH hostname or user@hostname for remote mode; uses existing SSH authentication")
    ap.add_argument("--venv", type=Path, default=ROOT / ".venv", help="isolated Python environment to create or reuse")
    ap.add_argument("--report", type=Path, default=ROOT / ".tower" / "demo.txt", help="save a demo ASCII report; existing files are preserved")
    ap.add_argument("--dev", action="store_true", help="also install editable package, pytest and build tools (requires pip index access)")
    ap.add_argument("--test", action="store_true", help="also run the complete test suite; use --dev to install test dependencies")
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if sys.version_info < (3, 10):
            raise SetupError("Python 3.10 or newer is required. Select a newer python3 and rerun setup.")
        if os.name != "posix":
            raise SetupError("Use Linux, macOS, or Windows Subsystem for Linux (WSL); the terminal dashboard uses POSIX curses.")
        mode = select_mode(args.mode, args.host)
        python = prepare_venv(args.venv)
        if args.dev:
            install_dev(python)
        validate(python, mode, args.host, args.report)
        if args.test:
            print("Running tests...", flush=True)
            try:
                run([python, "-m", "pytest", "-q"], timeout=600)
            except SetupError as exc:
                raise SetupError(f"{exc}\nIf pytest is unavailable, rerun setup with --dev --test.") from exc
        command = [str(python), str(ROOT / "tower")]
        launch_flags = ["--fake"] if mode == "demo" else ["--config", str(ROOT / "docs" / "config.example.json"), "--profile", "carc"]
        if mode == "remote":
            launch_flags += ["--host", args.host]
        command += launch_flags
        print(f"\nReady ({mode}). Launch in a terminal:\n  {shlex.join(command)}")
        if args.venv.expanduser().resolve() == ROOT / ".venv":
            print(f"Or, from this checkout:\n  {shlex.join(['./scripts/tower', *launch_flags])}")
        print("Press ? for help; q to quit. Read docs/runbook.md for cluster configuration and troubleshooting.")
        return 0
    except (SetupError, ValueError, OSError) as exc:
        print(f"\nSetup needs attention: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
