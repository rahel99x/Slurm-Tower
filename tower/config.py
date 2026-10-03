"""Configuration: defaults, a TOML (or JSON) file, environment overrides, and the key map.

Search order for the file: --config, $TOWER_CONFIG, ~/.config/tower/config.toml (or config.json).  ``tower --write-config``
writes the commented defaults there."""
from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict, Optional

DEFAULTS: Dict[str, Any] = {
    "user": "",                          # empty: $USER
    "account": "",                       # empty: the first account of sshare -U
    "ascii": True,                       # portable ASCII bars, rules and sparklines for CARC and SSH terminals
    "color": True,
    "history_days": 2,                   # sacct window of the history tab
    "log_lines": 8,                      # stdout tail under the selected job
    "log_max_mb": 32,                    # the Log tab keeps the last this many MB of a file in memory (read once, then only what is appended)
    "gpu_sampling": True,                # nvidia-smi inside the job's allocation
    "bell": False,                       # terminal bell when one of your jobs starts
    "intervals": {                       # seconds between samples of each source
        "jobs": 2.0, "starts": 10.0, "live": 10.0, "gpu": 5.0, "nodes": 15.0, "partitions": 60.0, "finished": 60.0,
        "share": 120.0, "account": 30.0, "details": 20.0, "weather": 120.0, "budget": 600.0, "trace": 60.0, "fin_details": 5.0,
    },
    "timeouts": {"command": 8.0, "gpu": 12.0, "action": 15.0},
    "thresholds": {                      # a running job older than warn_after_minutes below these fractions gets a flag
        "cpu": 0.3, "mem": 0.2, "gpu": 0.2, "warn_after_minutes": 10,
    },
    "notify": {
        "command": "",                   # run on every transition with TOWER_EVENT, TOWER_JOBID, TOWER_JOBNAME, TOWER_STATE in the environment
        "events": ["started", "finished", "failed", "alert"],
    },
    "alerts": [],                        # [[alerts]] name = ..., when = "<expression over a job>", every = 1800, actions = ["bell", "event", "notify", "command"], scope = "job" | "cluster"
    "partitions": [],                    # cluster tab: partitions to show (empty: those with GPUs or with your jobs)
    "weather": True,                     # queue weather: pending work ahead per partition and sbatch --test-only probes
    "weather_probes": [],                # the probes: [{partition="gpu", gres="gpu:a100:1", cpus=8, mem="32G", limit="01:00:00"}, ...]; empty: one per GPU type and per partition with your jobs
    "budget": True,                      # the account's allocation from sreport and sacctmgr (used this month, last 7 days, limits)
    "series_keep": 4000,                 # samples kept per job for the analytics tab (also appended to state/series/<job>.jsonl)
    "analytics_days": [1, 2, 7, 14, 30], # the history windows the analytics tab cycles through
    "theme": "default",                  # default | mono | high | cb (colour-blind safe) | reader (plain text, no glyphs)
    "host": "",                          # remote mode: run every Slurm command on this login node over ssh (ControlMaster reused)
    "ssh_user": "",                      # the login on that host (empty: the same as here)
    "ssh_opts": [],                      # extra ssh options, e.g. ["-J", "bastion"]
    "profiles": {},                      # named sets of these keys: [profiles.mycluster] host = "...", account = "..."; tower --profile mycluster
    "plugins": [],                       # extra plugin files or directories besides ~/.config/tower/plugins/
    "record": "",                        # record every command and answer to this file (also --record PATH)
    "clipboard": {"osc52": True, "tools": True},   # where y sends the selection besides the clipboard file
    "gpu_types": ["a100", "a40", "a30", "v100", "l40s", "p100"],
    "keys": {                            # action: keys (names as screen.py reports them)
        "quit": ["q"], "help": ["?"], "refresh": ["r"],
        "up": ["up", "k"], "down": ["down", "j"], "page_up": ["pgup"], "page_down": ["pgdn"], "home": ["home", "g"], "end": ["end", "G"],
        "next_tab": ["tab", "]"], "prev_tab": ["btab", "["], "tab_jobs": ["1"], "tab_cluster": ["2"], "tab_history": ["3"], "tab_nodes": ["4"],
        "tab_log": ["5"], "tab_sources": ["6"], "tab_group": ["8"], "tab_deps": ["9"], "steps": ["i"], "pin": ["p"], "resubmit": ["A"],
        "wrap": ["w"], "stderr": ["e"], "log_file": ["o"], "bookmark": ["m"], "bookmark_next": ["'"],
        "replay_pause": ["|"], "replay_back": ["<"], "replay_fwd": [">"], "replay_slower": ["{"], "replay_faster": ["}"],
        "mark": ["space"], "mark_all": ["a"], "unmark_all": ["u"],
        "details": ["enter", "d"], "cancel": ["c"], "hold": ["h"], "requeue": ["R"], "top": ["t"],
        "log": ["l"], "less": ["L"], "follow": ["f"], "sort": ["s"], "reverse": ["S"], "filter": ["/"], "clear": ["esc"],
        "gpu_toggle": ["n"], "bell_toggle": ["b"], "log_lines": ["+"], "log_lines_less": ["-"], "source_toggle": ["x"],
        "tab_analytics": ["7"], "view_prev": ["left", ","], "view_next": ["right", "."], "days_more": ["="], "days_less": ["_"],
        "visual": ["v"], "visual_all": ["V"], "yank": ["y"], "export_text": ["E"], "export_csv": ["C"], "export_json": ["J"],
        "palette": [":"], "theme": ["T"], "find_next": ["N"], "find_prev": ["P"],
    },
}

TEMPLATE = '''# tower configuration (TOML).  Every key is optional; these are the defaults.
# user = ""                     # empty: $USER
# account = ""                  # empty: the first account of sshare -U
ascii = true                    # portable ASCII bars, rules and sparklines for CARC and SSH terminals
color = true
history_days = 2                # sacct window of the history tab
log_lines = 8                   # stdout tail under the selected job
log_max_mb = 32                 # the Log tab keeps the last this many MB of a file (read once, then only what is appended)
gpu_sampling = true             # nvidia-smi inside the job's allocation (each sample is a small job step)
bell = false                    # terminal bell when one of your jobs starts

# partitions = ["gpu", "main"]  # cluster tab: partitions to show (empty: those with GPUs or with your jobs)
weather = true                  # queue weather on the Cluster tab: pending work ahead per partition, sbatch --test-only probes
# weather_probes = [{partition = "gpu", gres = "gpu:a100:1", cpus = 8, mem = "32G", limit = "01:00:00"}]   # empty: one per GPU type and per partition with your jobs
budget = true                   # the account's allocation (sreport this month and the last 7 days, sacctmgr limits)
gpu_types = ["a100", "a40", "a30", "v100", "l40s", "p100"]

series_keep = 4000              # samples kept per job for the analytics tab (also appended to state/series/<job>.jsonl)
analytics_days = [1, 2, 7, 14, 30]
theme = "default"               # default | mono | high | cb (colour-blind safe) | reader (plain text, no glyphs)

# host = "login.example.edu"    # remote mode: every Slurm command runs there over ssh (a ControlMaster connection is reused)
# ssh_user = "me"
# ssh_opts = ["-J", "bastion"]
# plugins = ["~/my-tower-plugins"]      # besides ~/.config/tower/plugins/*.py; each file defines setup(api)
# record = ""                           # record every command and answer to this file (tower --replay FILE plays it back)

[intervals]                     # seconds between samples of each source
jobs = 2.0
starts = 10.0
live = 10.0
gpu = 5.0
nodes = 15.0
partitions = 60.0
finished = 60.0
share = 120.0
account = 30.0
details = 20.0
weather = 120.0
budget = 600.0
trace = 60.0

[timeouts]
command = 8.0
gpu = 12.0
action = 15.0

[thresholds]                    # a running job older than warn_after_minutes below these fractions gets a flag
cpu = 0.3
mem = 0.2
gpu = 0.2
warn_after_minutes = 10

[notify]
command = ""                    # e.g. "curl -s -X POST -d \\"{\\\\\\"text\\\\\\": \\\\\\"$TOWER_EVENT $TOWER_JOBID $TOWER_JOBNAME\\\\\\"}\\" https://hooks.slack.com/..."
events = ["started", "finished", "failed", "alert"]

# [[alerts]]                    # alert rules: an expression over each job (scope = "job") or the snapshot (scope = "cluster")
# name = "idle gpu"
# when = "running and gpus and gpu is not None and gpu < 15 and elapsed > 900"
# every = 1800                  # seconds before the same job fires the rule again (0: once per job)
# actions = ["bell", "event"]   # bell | event | notify (the [notify] command, TOWER_EVENT=alert) | command (below)
# command = ""
# [[alerts]]
# name = "ending soon"
# when = "running and left is not None and left < 1800"
# [[alerts]]
# name = "queue empty"
# scope = "cluster"
# when = "n_pending == 0 and n_running == 0"
# every = 0

# [profiles.mycluster]          # tower --profile mycluster (or :profile mycluster inside): any key above, per cluster
# host = "login.example.edu"
# ssh_user = "me"
# account = "lab_01"
# partitions = ["gpu", "main"]

[clipboard]
osc52 = true                    # y also sends the selection to the terminal's clipboard (works over ssh in most terminals)
tools = true                    # and to pbcopy / wl-copy / xclip / xsel / clip.exe when one can reach a display

[keys]                          # action = [keys]; key names: a-z A-Z 0-9 up down left right pgup pgdn home end tab btab enter esc space and punctuation
quit = ["q"]
help = ["?"]
cancel = ["c"]
hold = ["h"]
visual = ["v"]                  # start a line selection at the cursor row; V selects the whole screen; y copies; Esc cancels
yank = ["y"]
export_text = ["E"]
export_csv = ["C"]
export_json = ["J"]
palette = [":"]
'''


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def default_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "tower", "config.toml")


def state_dir() -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "tower")


def load_file(path: str) -> Dict[str, Any]:
    with open(path, "rb") as f:
        data = f.read()
    if path.endswith(".json"):
        return json.loads(data.decode("utf-8"))
    try:
        import tomllib
    except ImportError:                                   # Python < 3.11: JSON only
        raise RuntimeError(f"{path}: TOML needs Python 3.11+; use a .json file")
    return tomllib.loads(data.decode("utf-8"))


class Config:
    def __init__(self, data: Optional[Dict[str, Any]] = None):
        if data is not None and not isinstance(data, dict):
            raise ValueError("configuration must be a TOML table or JSON object")
        self.data = _merge(DEFAULTS, data or {})
        self.path = ""
        self.profile_name = ""

    def profiles(self) -> list:
        return sorted(k for k in (self.data.get("profiles") or {}) if isinstance(self.data["profiles"][k], dict))

    def profile(self, name: str) -> "Config":
        """A copy with the named profile's keys merged over the top level."""
        if name not in self.profiles():
            raise KeyError(f"no profile '{name}' (known: {', '.join(self.profiles()) or 'none'})")
        out = Config(_merge(self.data, self.data["profiles"][name]))
        out.path, out.profile_name = self.path, name
        return out

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        cand = [p for p in (path, os.environ.get("TOWER_CONFIG"), default_path(), default_path()[:-5] + ".json") if p]
        for p in cand:
            if os.path.exists(p):
                cfg = cls(load_file(p))
                cfg.path = p
                return cfg
            if path and p == path:
                raise FileNotFoundError(path)
        return cls()

    def __getitem__(self, key: str):
        return self.data[key]

    def get(self, key: str, default=None):
        cur: Any = self.data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, key: str, value) -> None:
        cur = self.data
        parts = key.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value

    def keymap(self) -> Dict[str, str]:
        """key name -> action."""
        out = {}
        for action, keys in self.data["keys"].items():
            for k in keys:
                out[k] = action
        return out

    @staticmethod
    def write_default(path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "x", encoding="utf-8") as f:
            f.write(json.dumps(DEFAULTS, indent=2) + "\n" if path.endswith(".json") else TEMPLATE)
        return path
