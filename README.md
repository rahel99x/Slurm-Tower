# Slurm Tower

**Inspect Slurm jobs, measurements, logs, and results in one terminal.**

Slurm Tower is a terminal application for CARC and other Slurm clusters.
It uses solid block graphs, resource maps, and labeled tables.
It runs through an ordinary SSH session.
It also provides an ASCII display mode and plain-text reports.

| Requirement | Specification |
| --- | --- |
| Interface | Terminal only; curses for the interactive display |
| Python | Python 3.10 or later, with curses and venv support |
| Operating system | Linux, macOS, or Windows through WSL |
| Runtime packages | Python standard library only |
| Live data | Slurm commands available to your cluster account |
| Demonstration | Simulated scheduler; no cluster account required |
| Release | Tower 4.1 |
| License | [MIT](LICENSE) |

[Installation and operation](docs/runbook.md) ·
[Fedora desktop setup](docs/DESKTOP.md) ·
[Controls](docs/CONTROLS.md) ·
[All 50 improvements](docs/QUALITY_OF_LIFE.md) ·
[Complete reference](docs/reference.md) ·
[Project reporting standard](docs/PROJECT_STANDARD.md)

## 1. Install on CARC

**Prerequisites:** Connect to your CARC login node.
Use the SSH hostname and account supplied by your institution.
Select a site Python module if `python3` is older than version 3.10.

1. Get the source.

   ```bash
   git clone https://github.com/rahel99x/Slurm-Tower.git
   cd Slurm-Tower
   ```

2. Set up the local launcher.

   ```bash
   python3 scripts/setup.py --mode local
   ```

3. Start Tower with the CARC profile.

   ```bash
   ./scripts/tower --config docs/config.example.json --profile carc
   ```

**Expected result:** Tower opens the Jobs page.
The CARC profile uses slower sampling intervals.
It disables live GPU sampling, queue forecast probes, and allocation queries.
Adapt those settings to your site's operating rules.

Setup creates `.venv` and checks the application with simulated data.
It writes a demonstration report to `.tower/demo.txt`.
Normal setup requires no package downloads or administrator access.
It preserves existing configuration, state, and reports.
See the [runbook](docs/runbook.md) for Python environments and SSH transport.

### Install the `tower` command

Run these commands from the checkout:

```bash
python3 scripts/install_shell.py --apply
source ~/.bashrc
type tower
tower
```

The helper backs up `.bashrc` before it changes the file.
It replaces the old `tower`, `dash`, and `dash2` definitions with one managed alias.
The alias selects this checkout's launcher, the CARC profile, and Unicode graphics.
The launcher uses this checkout's `.venv` when it exists.
An active virtual environment for another project does not change that interpreter.

Use `python3 scripts/install_shell.py` to preview the alias without changing `.bashrc`.
Rerun the helper if you move the checkout.
See [shell setup](docs/runbook.md#use-one-tower-shell-command) for account overrides and backups.

### Update an existing installation

Run these commands from the checkout:

```bash
git pull --ff-only
python3 scripts/setup.py --mode local
tower
```

Resolve local Git changes if the first command fails.
Keep the existing configuration and state directories.
See [update and removal](docs/runbook.md#7-update-or-remove) for the complete procedure.

### Run Tower on a Fedora desktop

Use the desktop profile when Slurm is already installed directly on Fedora.
Run these commands from your existing checkout as your normal desktop user:

```bash
git pull --ff-only
python3 scripts/setup.py --mode local --profile desktop
python3 scripts/install_shell.py --profile desktop --apply
source ~/.bashrc
tower --version
tower --doctor
tower --once --tab sources
tower
```

The desktop profile uses local Slurm commands and normal user detection.
It samples Jobs every two seconds and accounting every ten seconds.
Cluster shows reported local partitions, including idle CPU-only partitions.
GPU sampling, forecast probes, and allocation-budget queries remain disabled.
The desktop alias ignores `CARC_ACCOUNT`.
Use `SLURM_TOWER_ACCOUNT` when you need an explicit desktop account override.
Desktop preferences, bookmarks, tags, and recorded resource samples use separate state from CARC.

An empty queue is normal when you have no jobs.
History requires working Slurm accounting.
Sources reports unavailable accounting; Tower keeps missing results unknown.
See the [Fedora desktop guide](docs/DESKTOP.md) for preflight checks, first installation, and troubleshooting.

## 2. Try Tower without a cluster

```bash
python3 scripts/setup.py --mode demo
./scripts/tower --fake
```

**Expected result:** Tower displays simulated jobs and resource measurements.
Leave it open briefly to collect graph samples.
Press `Tab` to change pages.
Press `?` to open help.
Press `q` to exit.

You can also run `python3 -m tower --fake` directly from the checkout.

## 3. Select a display mode

```bash
tower --unicode
tower --ascii --no-color
tower --fake --unicode --once --tab analytics
```

Unicode graphics are the default on compatible terminals.
Use a UTF-8 locale and a monospace font with block and braille characters.
Tower selects an ASCII fallback when the output encoding cannot display those characters.

Use `--ascii` for portable character graphics.
Use `--no-color` or `NO_COLOR=1` to disable color.
Metric labels and state names remain visible without color.

Press `T` to change the theme.
Use `:theme dark`, `:theme light`, or `:theme terminal` to select a background style.
The `mono`, `high`, `cb`, and `reader` themes provide additional display options.
The `reader` theme uses plain ASCII text and static notices.
Set `animations` to `false` to disable completion animations.

## 4. Learn the controls

A leading `:` opens the command palette.
Type the command without that leading character inside the palette.
Uppercase and lowercase keys have different functions.

| Control | Function |
| --- | --- |
| `Tab` / `Shift-Tab` | Open the next or previous page |
| `1`–`9`, `0` | Open a page directly; see the page table below |
| Up / Down | Move the cursor |
| Page Up / Page Down | Move through the visible table or document |
| Home / End | Move to the start or end of the current list |
| `/` | Filter the current list or search the current log |
| `Enter` | Open the selected item |
| `I` | Open the selected job's inspector |
| `l` | Open logs for the selected job |
| `Ctrl-W` / F6 | Change panel focus |
| `Ctrl-B` / Alt-Left | Return to the previous location |
| Alt-Right | Restore the next location after Back |
| `Ctrl-G` | Search jobs, runs, logs, views, workspaces, and commands |
| `Ctrl-P` | Open the Research workspace picker |
| `Ctrl-A` | Open Activity and background task results |
| `:` | Open the editable command palette |
| `?` | Open searchable help |
| `Esc` | Close the current overlay or clear the current selection |
| `q` | Exit Tower |

Click a page label to open that page.
Click a row to select it.
Use the mouse wheel to scroll.
Click a column heading to cycle **ascending → descending → off**.
The first active column has the highest sort priority.
Later columns resolve ties.
`^1` and `v2` show the direction and priority.

JOBID uses numeric order, including array task IDs.
For example, `9` precedes `10`, and `123_2` precedes `123_10`.
Unknown measurements remain last in either direction.
Removing one sort rule preserves the other rules.

```text
:sortby jobs name asc
:sortby jobs cpus desc
:sortby jobs cpus off
:sortby jobs clear
```

See [Controls](docs/CONTROLS.md) for every key, mouse action, command family, and CLI option.
See the [50-improvement guide](docs/QUALITY_OF_LIFE.md) for the new workflows.

### Tower 4.0 operating tools

| Task | Entry controls | Procedure |
| --- | --- | --- |
| Arrange and inspect tables | `:sorteditor`, `:headers`, `:columns`, `:filters`, `:marked`, `:freeze` | [Tables](docs/guides/tables.md) |
| Search complete log sources | `:logsearch`, `:logresults`, `:logolder`, `:loggoto`, `:logmarks` | [Log search](docs/guides/log-search.md) |
| Compare and organize log content | `:logdiff`, `:logalign`, `:logjson`, `:logfold`, `:logunread` | [Log display](docs/guides/log-view.md) |
| Find destinations and change preferences | `:jump`, `:forward`, `:location`, `:settings`, `:keybindings`, `:peek` | [Navigation](docs/guides/navigation.md) |
| Inspect measured intervals and graph scales | `:chart`, `:metricdisplay` | [Charts](docs/guides/charts.md) |
| Review completions and application results | `:inbox`, `:activity`, `:exports`, `:alerts`, `:terminaldoctor` | [Operations](docs/guides/operations.md) |
| Read declared result files | `:outputs`, `:artifact` | [Artifacts](docs/guides/artifacts.md) |

## 5. Select a page

| Key | Page | Purpose |
| --- | --- | --- |
| `1` | Jobs | Inspect active jobs, pending reasons, and recent completions |
| `2` | Cluster | Inspect partition capacity, queue estimates, and account allocation |
| `3` | History | Inspect completed jobs, failures, and resource efficiency |
| `4` | Nodes | Inspect allocated nodes and the cluster resource map |
| `5` | Logs | Read the selected job's exact log sources |
| `6` | Sources | Inspect sampler freshness, latency, errors, and backoff |
| `7` | Analytics | Inspect resource series, outcomes, timelines, advice, and comparisons |
| `8` | Group | Inspect the account's jobs and resource use by user |
| `9` | Dependencies | Inspect prerequisites and dependent jobs |
| `0` | Research | Inspect project measurements, outputs, provenance, and execution plans |

Use Left and Right to change subviews in Analytics, Nodes, and Research.
Research has twelve workspaces:
Experiment, Arrays, Evidence, Artifacts, Passport, Submit, Predict, Forecast,
Blockers, Tradeoffs, Scaling, and Workflow.

The [complete reference](docs/reference.md#tabs) defines each page and metric.
The [Research guide](docs/RESEARCH.md) explains application reports and submission preparation.
The [planning guide](docs/WAVE_TWO.md) explains predictions, uncertainty, scaling, and workflows.

## 6. Work with jobs and logs

### Inspect a completed or failed job

1. Open Jobs or History.
2. Select the job in the active table, Recents, or History.
3. Press `I` to inspect its identity, resources, steps, files, and evidence.
4. Press `l` to open its logs.
5. Press `O` to open its grouped log-file list.
6. Select a file with the arrow keys.
7. Press `Enter` to open the file.
8. Press `Esc` to return to the file list.

**Expected result:** The inspector and logs remain attached to the selected job ID.
A missing historical path remains unavailable.
Use a run's `logs.json` index to retain project-owned log locations.

When a job leaves the active queue, Recents shows it as awaiting accounting.
Tower requests a bounded accounting refresh.
History receives the terminal state when Slurm confirms it.
Completion notices do not require an application restart.

### Select and copy log text

1. Move the line cursor with Up or Down.
2. Press `v` to start a selection.
3. Extend the selection with arrows or page keys.
4. Press `y` to copy the original text.

Selected lines show an orange marker on the right.
The ASCII display uses `*` for that marker.

Press `Y`, or run `:copy all`, to copy the entire selected log file.
This operation runs in a background worker.
The displayed page, wrapping, and retained tail do not limit the full-file copy.
Tower also writes a private complete export when the clipboard cannot accept the content.
Open Activity to inspect the result or cancel an active copy.

See [log search](docs/guides/log-search.md) and [log display](docs/guides/log-view.md) for paging, search, bookmarks, structured logs, comparisons, and unread lines.

## 7. Add your project

Use the [project reporting standard](docs/PROJECT_STANDARD.md) for portable integration.
Copy the [project template](examples/project-template/README.md) when you start an integration.
The reporter uses the Python standard library.

```text
my-project/
  .tower/                   configuration, contracts, and recipes
  jobs/                     batch scripts
  runs/
    <run_id>/
      run.json              execution identity and declared paths
      logs.json             grouped index of exact log files
      metrics.jsonl         application measurements and progress
      summary.json          final measurements and results
      logs/                 project-owned log files
      outputs/              declared result files
      passports/            immutable provenance records
  reports/                  selected planning observations
```

1. Create a separate run directory for each execution attempt.
2. Record the actual Slurm job ID when it is known.
3. Write measurements to `metrics.jsonl`.
4. Register all required log locations in `logs.json`.
5. Declare result files in an output contract.
6. Run `:project /absolute/project/path` in Tower.
7. Select the execution attempt.
8. Run `:outputs` to inspect its declared results.

**Expected result:** Tower binds that attempt's measurements, logs, outputs, and verified provenance.
Project discovery is bounded and explicit.
It does not recursively scan your source tree.
Local project runs can be inspected without a Slurm job.

Use the [JSON Schema guide](docs/schemas/README.md) to check interchange files.
Keep generated run directories and private reports out of Git.

## 8. Prepare and review execution

```bash
tower run prepare examples/research/sample.sbatch --workdir "$PWD"
tower --fake --tab research --research-view submit
tower run scaling plan examples/planning/scaling.json --workdir "$PWD"
```

Preparation validates a script without submitting it.
Resource plans report their evidence and uncertainty.
Missing measurements remain unknown.

Use `:preflight SCRIPT --workdir DIR` to edit and check a submission.
Use `:orchestrate workflow FILE --workdir DIR` for a batch workflow review.
Use `:orchestrate scaling FILE --workdir DIR` for a scaling experiment review.

Inspect the exact command, working directory, resource request, and complete target list.
Confirm the review to submit or change jobs.
Tower records actual scheduler IDs and partial or unknown outcomes.
Batch execution requires local cluster operation and writable persistent state.
See [execution and recovery](docs/WORKBENCH.md#execute-a-reviewed-workflow-or-scaling-experiment) before submitting a batch.

## 9. Export and automate

| Method | Command | Result |
| --- | --- | --- |
| Inspect prerequisites | `tower --doctor` | Local environment checks |
| Inspect a simulated environment | `tower --doctor --fake` | Checks without Slurm |
| Export one page | `tower --once --tab history` | One terminal frame |
| Export a snapshot | `tower --json` | Machine-readable JSON |
| Export a table | `tower --csv --tab history` | CSV table |
| Export the complete dashboard | `tower --report report.txt` | Portable ASCII report |
| Record a session | `tower --record session.jsonl.gz` | Scheduler observations for replay |
| Replay a session | `tower --replay session.jsonl.gz` | Recorded scheduler data |
| Evaluate an expression | `tower --eval 'n_running'` | Expression result |
| Wait for a condition | `tower --wait-for 'n_pending == 0' --timeout 3600` | Status when the condition holds or times out |
| Run a palette command | `tower run COMMAND ARGUMENTS` | One command without the interactive screen |

Use `E`, `C`, or `J` inside Tower to export text, CSV, or job JSON.
Use `:export report` for a complete interactive report export.
Recordings, exports, and logs can contain private job names and paths.
Review a file before you share it.
Use `--fake` when you need public examples.

Scripted job changes require `--yes`.
The [scripted-mode reference](docs/reference.md#scripted-mode-and-expressions) defines expressions and exit codes.
The [operations guide](docs/guides/operations.md) covers export history, completion review, diagnostics, and alert controls.

## 10. Configure Tower

Run `tower --write-config` to create a commented default configuration.
The command preserves an existing file.

Tower searches for configuration in this order:

1. The path supplied with `--config`.
2. The path in `TOWER_CONFIG`.
3. `~/.config/tower/config.toml` or `config.json`.

Python 3.11 and later read TOML.
Use JSON with Python 3.10.
Start with [config.example.json](docs/config.example.json) for cluster profiles.

The normal UI state base is `~/.local/state/tower/`.
The desktop profile selects a separate connection directory with `state_namespace = "desktop"`.
Use `--no-state` to disable normal state reads and writes.
The [configuration reference](docs/reference.md#configuration) describes every section.
The [navigation guide](docs/guides/navigation.md) describes interactive settings and key bindings.

Live GPU sampling creates short `srun` steps inside an existing allocation.
It can fall back to SSH on a compute node.
Enable this feature only where cluster policy permits it.
Use `--no-gpu` to disable it for one launch.

## 11. Find a guide

These guides use controlled technical English guided by ASD-STE100 principles.
See [Documentation style](docs/DOCUMENTATION_STYLE.md) for terminology and procedure conventions.

| Task | Guide |
| --- | --- |
| Install, update, or diagnose a CARC launch | [Adaptive runbook](docs/runbook.md) |
| Use an existing Slurm installation on Fedora | [Desktop setup](docs/DESKTOP.md) |
| Find a key, command, CLI option, or mouse action | [Controls](docs/CONTROLS.md) |
| Find any of the 50 quality-of-life changes | [Improvement index](docs/QUALITY_OF_LIFE.md) |
| Sort, filter, mark, and inspect table records | [Table guide](docs/guides/tables.md) |
| Read older log content or search complete files | [Log search guide](docs/guides/log-search.md) |
| Bookmark, compare, and organize log content | [Log display guide](docs/guides/log-view.md) |
| Change navigation, settings, and command input | [Navigation guide](docs/guides/navigation.md) |
| Inspect graph windows, ranges, events, and units | [Chart guide](docs/guides/charts.md) |
| Page through declared output files | [Artifact guide](docs/guides/artifacts.md) |
| Review completions, exports, diagnostics, and alerts | [Operations guide](docs/guides/operations.md) |
| Use the original terminal workbench | [Workbench guide](docs/WORKBENCH.md) |
| Instrument projects and define reports | [Project reporting standard](docs/PROJECT_STANDARD.md) |
| Prepare research and output contracts | [Research workflows](docs/RESEARCH.md) |
| Analyse predictions, scaling, and dependencies | [Planning workflows](docs/WAVE_TWO.md) |
| Adapt the source or add tests | [Contribution guide](CONTRIBUTING.md) |
| Apply the documentation conventions | [Documentation style](docs/DOCUMENTATION_STYLE.md) |

## 12. Develop and adapt

```bash
python3 scripts/setup.py --mode demo --dev --test
.venv/bin/python -m build
```

Development tools are optional dependencies.
Normal operation requires no third-party Python packages.
Tests use simulated Slurm output and temporary files.
They check parsing, job identity, actions, reports, remote transport, and terminal interaction.
GitHub Actions tests supported Python versions and builds installable packages.

To install the Python entry point, create a virtual environment.
Activate that environment.
Run `python -m pip install .` from the checkout.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before you change the source.
Read [SECURITY.md](SECURITY.md) to report a security issue.
You can fork, adapt, redistribute, and use Tower commercially under the [MIT license](LICENSE).
