# The Slurm Tower runbook

Run Tower in a terminal on your CARC login node. Setup is noninteractive and
repeatable. It never submits or changes jobs, installs system packages, replaces
your configuration, or asks for a password.

To instrument another application, follow the
[project reporting standard](PROJECT_STANDARD.md) and copy its
[project template](../examples/project-template/README.md). It defines the run
directories, metrics, final reports, contracts, and analysis exports Tower reads.

## 1. Connect to CARC and check the tools

Use your institution's documented SSH hostname and username. Complete the normal
key, passphrase, MFA, and host-key verification flow, then run these commands on
the login node:

```bash
python3 --version
command -v squeue
command -v scontrol
```

Use Python 3.10 or newer. If Python or Slurm is unavailable, check your site's
module documentation. Where a module system is provided, `module avail` lists
available modules; load the actual Python/Slurm modules your site specifies.
Module names and available versions vary, so no specific module name is assumed.

The application uses standard-library Python and POSIX curses on Linux, macOS,
or WSL. There are no runtime packages, databases, servers, or build tools to install.
Do not install system software or start a Slurm controller to use Tower.

## 2. Get the source and set up locally

```bash
git clone https://github.com/rahel99x/Slurm-Tower.git
cd Slurm-Tower
python3 scripts/setup.py --mode local
./scripts/tower --config docs/config.example.json --profile carc
```

If the login node cannot access GitHub, download the repository on a permitted
machine and transfer the source directory using your site's file-transfer procedure.
Then run setup from that directory. The default setup is offline and needs no
administrator access.

The `carc` example profile polls jobs every 10 seconds, disables in-allocation GPU
sampling, disables forecast probes, and disables allocation-budget queries. Start
there, then adjust the profile to your site's usage guidelines. It does not assume
an account name, partition, scheduler version, or institution-specific hostname.

Every mode validates simulated JSON output, all ten terminal tabs, all twelve
Research workspaces in Unicode and ASCII, and a plain-text report.
Local mode checks command availability; it does not query or
change your jobs. A successful diagnostic confirms tools, not the health of the
Slurm controller or your site's authorization rules. Verify real data in step 4.

Setup creates `.venv` without downloading pip or packages. Existing valid virtual
environments are reused; unrelated directories are rejected. Keep the checkout:
the `./scripts/tower` launcher runs its source with `.venv/bin/python` when present,
otherwise `python3`. To run without setup, use `python3 -m tower` from the checkout.

### Use one `tower` shell command

After setting up the application, install the optional Bash alias from the new
Slurm-Tower checkout on CARC. If this is an older clone, run `git pull --ff-only`
first to obtain `scripts/install_shell.py`; preserve any conflicting local edits.

```bash
python3 scripts/install_shell.py --apply
source ~/.bashrc
type tower
tower
```

The helper backs up `.bashrc` before updating it atomically and prints the backup
location. Its managed block clears the old `tower`, `dash`, and `dash2` aliases or
functions, then defines one `tower` alias for this checkout's `scripts/tower` with
the low-impact `carc` profile and Unicode visuals. It preserves the rest of your
shell configuration.
Rerunning the helper updates the same managed block.

The launcher uses the Slurm-Tower checkout's own `.venv`, independently of an
active virtual environment for another project. Run normal setup first so that `.venv` exists;
without it, the source launcher falls back to `python3` on `PATH`. Keep this
checkout at its current location, or rerun the helper after moving it.

The alias passes your arguments through and uses `CARC_ACCOUNT` when that shell
variable is set. When it is empty, Tower retains its normal account detection.
You can override the account for one invocation with `tower --account ACCOUNT`.

```bash
tower --doctor
tower --once --tab sources
tower --fake
tower --ascii --no-color     # portable fallback for a limited terminal
```

To inspect the alias block without changing a file, run the helper with no flags.
To create a complete updated-file preview, choose an output path:

```bash
python3 scripts/install_shell.py
python3 scripts/install_shell.py --output /tmp/tower-bashrc-preview
```

Use `--bashrc /path/to/bashrc` to select a different Bash configuration file for
preview or installation. The helper modifies shell startup configuration only
when you explicitly pass `--apply`. Source the file you updated, or open a new
Bash session, to load the alias.

### Preview and choose terminal visuals

Tower renders every chart inside the terminal; no browser, graphical display, or
image viewer is needed. A UTF-8 terminal and a font with block and braille glyphs
provide the fullest visuals. Unicode is the default, with an automatic ASCII
fallback for unsupported output encodings and dumb terminals. `--unicode` selects
the Unicode preference explicitly, even when `$TERM` is `dumb`, while an unsupported
output encoding still requires ASCII. `--ascii` selects portable characters. An
explicit `tower --ascii` also overrides the alias's Unicode preference.

Try the full dashboard without contacting the cluster:

```bash
./scripts/tower --fake --unicode
# Or print one simulated Analytics frame in the current terminal:
./scripts/tower --fake --unicode --once --tab analytics
```

Let the demo run briefly to build sample history, then use `Tab` for the ten pages
and the left/right arrows for each page's alternate views. `T` cycles themes.
The `mono` theme keeps the glyphs without colors; `reader` uses plain ASCII text.
`--no-color` or a nonempty `NO_COLOR` environment variable disables color.
The interactive curses display uses native truecolor when ncurses and the terminal
description expose direct colors; otherwise it uses 256 or basic colors.
ANSI output from `--once` or `--watch` also supports truecolor
when the terminal advertises it through `COLORTERM=truecolor`, `COLORTERM=24bit`,
or a direct-color `$TERM`. Missing data remains visibly unknown rather than
appearing as zero usage. Plain-text reports always use ASCII, independently of
the live dashboard's visual preference.

## 3. Adapt setup to your environment

| Your environment | Setup | Launch |
| --- | --- | --- |
| CARC or another Slurm login node | `python3 scripts/setup.py --mode local` | `./scripts/tower --config docs/config.example.json --profile carc` |
| Try the simulated cluster | `python3 scripts/setup.py --mode demo` | `./scripts/tower --fake` |
| Let setup detect it | `python3 scripts/setup.py` | Use the command it prints |
| Optional SSH transport from another machine | `python3 scripts/setup.py --mode remote --host your-ssh-alias` | `./scripts/tower --host your-ssh-alias` |

Automatic mode uses remote when given `--host`, local when `squeue` is on `PATH`,
and demo otherwise. If a Slurm command is present but the installation is incomplete,
setup reports the missing capability; it does not disguise a broken cluster as a demo.

```bash
# Choose a separate virtual environment; use the launch command setup prints.
python3 scripts/setup.py --mode demo --venv /path/to/tower-venv

# Read a complete ASCII snapshot in the terminal.
less .tower/demo.txt

# Save a fresh demo report without replacing an existing file.
python3 scripts/setup.py --mode demo --report /tmp/tower-preview.txt

# Optional contributor tools and full regression suite; requires a package index.
python3 scripts/setup.py --mode demo --dev --test
```

`--dev` bootstraps pip inside the venv if needed, then installs the editable project,
pytest, and packaging tools using the configured pip index with normal verification.
Development tools are unnecessary for everyday monitoring. Setup exits `0` when
requested checks pass and `1` with a specific failure otherwise (`2` indicates
invalid command-line syntax). Demo validation still completes if local or remote
prerequisites are missing. Successful local and remote setup prints a launch command
using the included low-impact `carc` profile; demo setup prints `--fake`.

### Optional SSH transport

The primary workflow runs Tower directly on the login node. If you choose to run
its terminal interface on a different machine, `--host` sends Slurm commands and
log reads over your existing SSH connection:

```bash
ssh your-ssh-alias 'command -v squeue; command -v sacct'
./scripts/tower --doctor --host your-ssh-alias
./scripts/tower --host your-ssh-alias --no-gpu
```

Doctor uses a bounded, read-only SSH check in batch mode. Establish normal SSH
access first; do not disable host-key checking. Put a bastion, nondefault port, or
login username in your normal `~/.ssh/config`, then pass that SSH alias to Tower.
Remote log reads use Linux coreutils (`stat`, `dd`, `base64`, and `ls`).

Slurm must be on the remote noninteractive `PATH`, not only in an interactive
shell. Follow the site's module-loading instructions if those differ. No SSH
keys or tokens belong in the repository; Tower uses your existing credentials.

## 4. Verify real data with low-impact settings

```bash
./scripts/tower --doctor
./scripts/tower --config docs/config.example.json --profile carc --once
./scripts/tower --config docs/config.example.json --profile carc --once --tab sources
```

Jobs and Cluster should match your usual `squeue` and `sinfo` views. Sources shows
each command's status, latency, retries, and last error. Missing optional accounting,
allocation, or GPU features can leave those sections empty while the queue works.

The `carc` profile disables live GPU collection. If site policy allows it, enable
`gpu_sampling` in your personal profile. It runs short `srun` steps in an existing
allocation and may fall back to SSH to the assigned node. `--no-gpu` disables it
for one run. Forecasts use `sbatch --test-only` probes: these do not submit jobs but
do contact the scheduler, and are also disabled in the `carc` profile.

The dashboard reads job and log data. Job mutations are separate actions with
confirmations. `tower run ... --yes` is explicit unattended authorization for
that action; do not add it to a generic health check.

### Inspect experiments and plan the next run

Press `0` for Research and use Left/Right to move among its twelve workspaces.
The first six cover metric streams, arrays, failure evidence, output contracts,
passports and submission preparation. The next six show resource predictions,
queue-start forecast calibration, scheduler blockers, resource tradeoffs,
controlled scaling and workflow critical paths.

```bash
./scripts/tower --fake --tab research --research-view predict
./scripts/tower --fake --tab research --research-view scaling
./scripts/tower run scaling plan examples/planning/scaling.json --workdir "$PWD"
./scripts/tower run workflow analyze examples/planning/workflow.json
```

Preparing a scaling or workflow plan inspects explicit local inputs and prints
reviewable commands. It does not submit jobs or run scheduler probes. Evidence
gaps remain visible; resource predictions use matching completed runs, calibrated
queue windows require recorded start outcomes, and failed/censored scaling runs
cannot support relative performance claims. Use the [wave two guide](WAVE_TWO.md)
for the complete recipes, commands and assumptions, and the
[research guide](RESEARCH.md) for metric instrumentation and output validation.

To measure the bounded CPU example locally without Slurm, choose three new paths:

```bash
.venv/bin/python examples/planning/scaling_workload.py local --workers 1 --problem-size 10000 --output one.json
.venv/bin/python examples/planning/scaling_workload.py local --workers 2 --problem-size 10000 --output two.json
.venv/bin/python examples/planning/scaling_workload.py combine one.json two.json --output measurements.json
./scripts/tower run scaling analyze measurements.json --mode strong --baseline 1
```

The example writes actual measured elapsed times, including process startup;
it is a small synthetic demonstration. With one repeat per worker, observed
spread is unavailable. Use at least three separately measured repeats per worker
for empirical spread. `combine` reads 1..1000 explicitly named individual record
files, at most 64 KiB each and 8 MiB in aggregate; it performs no directory walk
and preserves existing output files. All analysis remains terminal only.

## 5. Configure your cluster

All defaults work without a config file. Copy [config.example.json](config.example.json)
to a new personal file, preserve the `carc` profile, and add your account, partitions,
thresholds, or polling preferences. Use `--config /path/to/my-tower.json --profile carc`
to select it. Do not overwrite an existing personal configuration to follow this guide.

JSON works on every supported Python. Python 3.11+ also accepts TOML. The optional
`tower --write-config` command creates a default config only when none exists.
Tower normally reads `~/.config/tower/config.toml` or `config.json`, honoring
`XDG_CONFIG_HOME` and `TOWER_CONFIG`. State is under `~/.local/state/tower`, honoring
`XDG_STATE_HOME`. Use `--no-state` to skip state and `--no-plugins` to skip plugins.

Notification hooks and plugins execute code: load trusted files only. Demo mode
simulates Slurm, but normal config/plugin loading still applies. Setup's smoke test
uses an empty config and disables plugins and state explicitly.

Slurm accounting itself may update only every 30 seconds. Faster polling does not
guarantee fresher CPU metrics. Tune intervals to your site's guidance and use Sources
to identify slow or unavailable commands.

### Reports and automation

```bash
./scripts/tower --config /path/to/my-tower.json --profile carc --report report.txt
less report.txt
./scripts/tower --json > snapshot.json
./scripts/tower --csv --tab history > history.csv
./scripts/tower --doctor --json
```

Reports are plain ASCII snapshots for terminals, text editors, and attachments.
Exports and recordings may expose names, account usage, log output, and file paths;
review them before sharing and use `--fake` for public examples. The regular
`--report PATH` command replaces its destination. Choose a unique filename to
retain older reports. Setup's `--report` never replaces a file.

For scheduled collection, use absolute paths to the venv's Python, the checkout's
`tower` directory, and your config. The interactive UI needs a terminal; use
`--once`, `--json`, or `--report` in automation. No background service is required.

### Active and historical job logs

Select an active Jobs row, a **Recents** row, or any History job and press `l`.
Logs remains attached to that exact job, including failed jobs. Press `O` for
the grouped file list; arrows/PgUp/PgDn/Home/End select an entry and Enter opens
it. Esc returns to the list, then closes the list. Lowercase `o` cycles files;
`e` switches scheduler stdout/stderr.

For multiple application/worker logs or files in other locations, follow the
[per-run log-index standard](PROJECT_STANDARD.md#log-locations-logsjson).
The copyable reporter creates `logs.json`; its `register_log` helper adds exact
relative or absolute files with stable groups and labels. Configure
`"logs": {"manifest_file": "logs.json"}` and select the concrete run directory
with `--workdir /absolute/project/runs/attempt-id`. Without a workdir override,
a relative index filename uses the selected job's actual scheduler WorkDir.
Relative entry paths resolve from the index directory, including explicit
sibling paths. Absolute entries retain their source-machine meaning when moved.
Tower lists actual stdout/stderr and bounded matching names from both output
directories alongside the index; it performs no recursive filesystem scan.

Some Slurm accounting installations do not retain historical stdout/stderr or
WorkDir. Tower keeps controller paths it actually observed, reports absent
evidence, and never substitutes a running job. Preserve failed-run files and
indexes, and bind their run directory explicitly when scheduler metadata is gone.

## 6. Troubleshoot the specific failure

| Symptom | Next step |
| --- | --- |
| Python is too old | Select a Python 3.10+ module/interpreter provided by the site. |
| `.venv` is not a virtual environment | Keep its contents; choose a new `--venv PATH`. |
| `No module named venv` | Select a site Python with venv support, or run `python3 -m tower --fake` directly. |
| `No module named curses` | Use a Python build with curses support, or WSL on Windows. |
| Slurm command missing | Load the site's Slurm module and rerun `--doctor` on the login node. |
| SSH check fails | Verify normal SSH, keys/MFA, host keys, network access, and remote noninteractive `PATH`. |
| TOML fails on Python 3.10 | Use JSON config or Python 3.11+. |
| Blank history or budget | Check Sources; `sacct`, `sreport`, or `sacctmgr` may be unavailable or restricted. |
| Historical logs have no path | Select the job's actual run directory with `--workdir`; configure its `logs.manifest_file` index. Accounting may not retain old paths. |
| Missing GPU metrics | Start with `--no-gpu`; enable sampling only for allocated GPUs where site policy permits. |
| Terminal looks broken | Check `$TERM`, widen the terminal, and try `--ascii --no-color`. |
| Blocks or braille look misaligned | Use a UTF-8 locale and a monospace terminal font with those glyphs, or use `--ascii`. |
| Setup's report looks unchanged | Existing reports are preserved; choose a new `--report` path. |
| Contributor tools cannot download | Runtime setup is offline; omit `--dev`, use a permitted package mirror, or provide development wheels. |

Network access is needed only for cloning, optional package installation, and SSH
to a real cluster. Standard pip downloads use `pypi.org` and
`files.pythonhosted.org` unless a different index is configured. Tower requires no
analytics or telemetry endpoint.

## 7. Update or remove

Pull reviewed updates with `git pull --ff-only` when your checkout has no conflicting
local edits, then rerun the same setup command. If you installed the Bash alias,
refresh its managed block and reload it as well:

```bash
git pull --ff-only
python3 scripts/setup.py --mode local
python3 scripts/install_shell.py --apply
source ~/.bashrc
tower
```

This refresh enables the current Unicode preference even if your old alias passed
`--ascii`. The source launcher sees application changes immediately. For a packaged
install, reinstall with that venv's
`python -m pip install .`. Preserve personal changes and review incoming code before
running it.

To remove Tower, remove only the checkout and virtual environment you created.
Personal configuration and state are separate; keep them for future use or remove
them intentionally. Core setup never edits shell startup files or creates services.
The optional
`scripts/install_shell.py --apply` command changes only the selected Bash startup
file after creating a backup.
