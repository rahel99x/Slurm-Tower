# Slurm Tower

**A calmer view of a busy cluster, entirely in your terminal.**

Slurm Tower brings your jobs, resource usage, logs, and cluster health into one
readable terminal dashboard. Solid block charts, precise trend lines, and resource
heatmaps make trends visible over an ordinary SSH session. Find the jobs that need
attention, understand where resources go, and export a complete plain-text snapshot
when you need to share the picture.

**Terminal only | Unicode block visuals | Python 3.10+ | Zero runtime dependencies | MIT**

[Runbook](docs/runbook.md) | [Complete reference](docs/reference.md) |
[Tests](https://github.com/rahel99x/Slurm-Tower/actions/workflows/tests.yml) |
[Contributing](CONTRIBUTING.md)

## Start on your CARC login node

Connect using the CARC SSH hostname and account provided by your institution.
Run these commands on the login node:

```bash
git clone https://github.com/rahel99x/Slurm-Tower.git
cd Slurm-Tower
python3 scripts/setup.py --mode local
./scripts/tower --config docs/config.example.json --profile carc
```

The included `carc` profile uses slower polling and disables live GPU sampling,
queue forecast probes, and allocation queries. Adapt it to your site's guidance.
The [runbook](docs/runbook.md) covers Python/Slurm modules and optional features.

To launch the new application with one `tower` command, run this from the checkout:

```bash
python3 scripts/install_shell.py --apply
source ~/.bashrc
tower
```

For an older clone, first run `git pull --ff-only`, then rerun the helper to refresh
the alias with Unicode visuals. It backs up `.bashrc`, replaces the active
`tower`/`dash`/`dash2` commands with a single `tower`
alias, and uses this checkout's `.venv` even when another virtual environment is active.
Arguments pass through: `tower --once`, `tower --doctor`, or `tower --fake`.
Use `tower --ascii` when you need the portable fallback.
See the [shell setup options](docs/runbook.md#use-one-tower-shell-command) for a preview.

Setup creates an isolated `.venv`, checks prerequisites, validates every terminal
view against simulated data, and saves `.tower/demo.txt`. It needs no package
downloads or administrator access. Existing environments, configuration, state,
and reports are preserved. Read the demo report with `less .tower/demo.txt`.

No cluster access yet? Try the simulated cluster anywhere on Linux, macOS, or WSL:

```bash
python3 scripts/setup.py --mode demo
./scripts/tower --fake
```

You can skip installation entirely: `python3 -m tower --fake` runs from the clone.
Python 3.11+ reads TOML configuration; Python 3.10 uses JSON.

## Every view answers a question

| View | Get an answer quickly |
| --- | --- |
| **Jobs** | What is running, what is waiting, and which jobs need attention? |
| **Cluster** | Where is capacity available, how long is the queue, and how is the allocation tracking? |
| **History** | Which jobs finished, failed, or used more resources than they needed? |
| **Analytics** | How do CPU, memory, and GPU use change? What should the next run request? |
| **Nodes** | Which nodes are busy, idle, or drained? |
| **Dependencies** | What is blocking a job, and what depends on it? |
| **Group** | How is the account sharing CPUs, GPUs, and nodes? |
| **Logs** | What is the job doing? Search, follow, wrap, and bookmark its output. |
| **Sources** | Is the data fresh? Which command is slow or unavailable? |

Solid fractional bars, gradient area charts, braille precision traces, measured
resource heatmaps, and timelines use terminal-renderable characters. Unicode
visuals are the default on capable terminals; `--unicode`
selects them explicitly and `--ascii` selects the portable character fallback.
Tower falls back automatically on limited output encodings and dumb terminals.
Color adds emphasis, while labels and shapes keep the dashboard useful
without it. Use `--no-color` or `NO_COLOR=1` to suppress colors, and `T` to cycle
accessible themes. The `reader` theme uses plain ASCII text.

Preview the visuals without connecting to Slurm:

```bash
./scripts/tower --fake --unicode       # switch tabs and let live trends accumulate
./scripts/tower --fake --unicode --once --tab analytics
```

## A few useful commands

```bash
./scripts/tower --doctor                       # check local prerequisites
./scripts/tower --doctor --fake                # check demo prerequisites
./scripts/tower --once --tab history           # one readable frame
./scripts/tower --json                         # machine-readable snapshot
./scripts/tower --report report.txt            # full ASCII dashboard report
./scripts/tower --fake --report demo.txt       # shareable simulated report
./scripts/tower --record session.jsonl.gz      # capture a session
./scripts/tower --replay session.jsonl.gz       # explore it later
```

Use `Tab` to switch views, arrows to move, `/` to filter, `Enter` for details,
`?` for help, and `q` to quit. The `:` command palette exposes export, profiles,
and job actions. Actions such as cancel, hold, and resubmit ask for confirmation;
scripted actions require `--yes`.

## Make it yours

Cluster profiles, polling intervals, thresholds, themes, alert rules, key bindings,
and optional plugins are configurable. Start with the [adaptive runbook](docs/runbook.md)
for CARC setup, offline use, automation, optional SSH transport, and troubleshooting.
The [complete reference](docs/reference.md) covers every view, key, and metric.
Example profiles live in [docs/config.example.json](docs/config.example.json).

Live GPU sampling uses short `srun` steps inside an existing allocation and may
fall back to SSH. Enable it only where site policy permits. Reports, exports, and
recordings can contain private job names, paths, account usage, and logs; use
`--fake` for public examples.

## Develop and adapt

```bash
python3 scripts/setup.py --mode demo --dev --test
.venv/bin/python -m build
```

Development tools are the only optional Python dependencies. Tests use simulated
Slurm output and exercise parsing, job actions, remote transport, recording,
reports, and terminal interaction without a live cluster. GitHub Actions runs the
suite across supported Python versions and builds installable distributions.

Prefer an installed `tower` command? Create and activate a virtual environment,
then run `python -m pip install .`. The source launcher works without pip.

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Fork, adapt,
redistribute, and use Slurm Tower commercially under the [MIT license](LICENSE).
