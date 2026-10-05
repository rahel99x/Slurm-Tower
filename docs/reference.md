# Slurm Tower: complete reference

[Quick start](../README.md) · [Runbook](runbook.md)

This reference describes the terminal dashboard and its underlying metrics.
Unicode block visuals are the normal terminal presentation, with portable ASCII
and accessible themes available.
ASCII reports present the complete snapshot as portable plain text.
Run Tower directly on your CARC login node; the runbook provides a low-impact profile.

```bash
tower                        # interactive (curses); q quits, ? lists the keys
tower --fake                 # a simulated cluster: try it anywhere, no Slurm needed
tower --unicode              # explicitly prefer block and braille visuals
tower --ascii --no-color     # portable fallback for a limited terminal
tower --watch --bell         # the animated non-interactive screen (Ctrl-C exits)
tower --once --tab history   # one frame of text, e.g. to paste into a chat
tower --json                 # the whole snapshot as JSON, for scripts
tower --write-config         # ~/.config/tower/config.toml with the commented defaults
tower --profile carc         # a [profiles.carc] section of the config: a cluster (host, account, ...)
tower --host login.example.edu   # from a laptop: every Slurm command over ssh, logs read remotely
tower --record today.jsonl.gz    # keep every command and answer; --replay today.jsonl.gz --speed 10 plays it back
tower run cancel 123 --yes   # one palette command without the screen (exit 0 ok, 1 failed, 3 needs --yes)
tower --eval '[j.id for j in running if j.cpu < 0.3]'     # an expression over the snapshot
tower --wait-for 'n_pending == 0' --timeout 3600          # block until it holds (exit 0) or time out (exit 2)
tower --report report.txt    # the whole dashboard as a plain ASCII text report
```

## Install and configure

Start with the [quick start](../README.md#start-on-your-carc-login-node) or the
[adaptive runbook](runbook.md). The commands below use `tower` after installing
the Bash alias or Python package; `./scripts/tower` from the checkout accepts
the same arguments.

## Terminal visuals and accessibility

The dashboard uses solid Unicode blocks for resource bars, distributions, and
timelines. Fractional blocks preserve values at one eighth of a character's width.
Filled area charts use gradient blocks; braille telemetry curves use two by four
dots per character for finer detail. Measured resource heatmaps use opaque cells,
an explicit scale, and numeric readings. Composition strips carry a legend with
the underlying counts or allocation values.
`--unicode` explicitly selects the Unicode preference; `--ascii` selects portable
characters. By default Tower checks the output encoding and terminal type and
falls back to ASCII when needed. `--unicode` overrides the default fallback for
`TERM=dumb`, but cannot override an output encoding that lacks the glyphs.
Existing configurations with `ascii = true`
retain that preference unless overridden on the command line.

Color adapts to terminal support. The interactive curses renderer uses native
truecolor when ncurses and the terminal description expose direct colors, with
256-color and basic fallbacks. ANSI `--once` and `--watch` output uses truecolor gradients
when `COLORTERM` is `truecolor` or `24bit`, or `$TERM` names a direct-color terminal;
otherwise it selects 256 or basic colors. Labels, axis values, and state names convey
the metrics without relying on color alone. `--no-color` and a nonempty
`NO_COLOR` environment variable suppress colors. `T` or `:theme NAME` selects
`default`, `mono`, `high`, `cb`, or `reader`: `mono` retains the graphics without
colors; `cb` uses the color-blind palette; `reader` forces plain ASCII text.

Charts use collected measurements. Unavailable metrics and gaps remain unknown,
and time-series detail grows as samples arrive. ASCII `--report` exports remain
portable plain text regardless of the live dashboard's glyph preference.

Roomier terminals reveal resource cards, node heatmaps, and additional charts;
compact terminals retain the essential tables and labels. These visuals reuse
the existing snapshot and sample history without increasing Slurm polling.

## Tabs

The **Research** tab (`0`) includes twelve workspaces: experiment telemetry, job arrays,
failure evidence, output contracts, run passports, batch submission preparation,
resource predictions, queue-start forecasts, scheduler blockers, submission
tradeoffs, controlled scaling and workflow critical paths.
Use Left/Right for subviews and PgUp/PgDn to scroll. Jobs and History carry the
selected job into Research. See [Research workflows](RESEARCH.md) for schemas,
instrumentation, commands, examples and inspection limits.
See [Wave two planning](WAVE_TWO.md) for evidence requirements, prediction and
calibration limits, reviewed choices, and complete scaling/workflow examples.

```bash
tower --fake --tab research --research-view predict
tower run blockers 123
tower run scaling plan examples/planning/scaling.json --workdir "$PWD"
tower run scaling analyze measurements.json --mode strong --baseline 1
tower run workflow analyze examples/planning/workflow.json
```

`--research-view` accepts `experiment`, `arrays`, `evidence`, `artifacts`,
`passport`, `submit`, `predict`, `forecast`, `blockers`, `tradeoffs`, `scaling`
and `workflow`. `--planning-file PATH` attaches explicit local observations or
a recipe. `predict`, `forecast` and `blockers` use the selected snapshot job, or
read an explicit bundle with `--file PATH`; the latter runs without contacting
Slurm. `tradeoffs`, `scaling` and `workflow` use explicit local files.
Planning preparation is separate from confirmed submission. Prediction ranges
require matching evidence, queue forecasts require recorded calibration, and
scaling spread describes measured repeats rather than future-run confidence.

| tab | what it shows |
|---|---|
| **Jobs** | your running jobs (by start) then pending ones (by priority): partition, state, nodes, CPUs, GPUs, elapsed against the limit, time left or time waited, CPU rate, CPU efficiency so far, memory against the request, GPU utilisation, flags, and the reason / projected start / priority of pending jobs. Below the table: the selected job (bars and sparklines for time, CPU, memory and each GPU with its mean since the dashboard started, the node's load, a tail of its stdout; for a pending job its dependency with the names of the jobs it waits for), the recently finished jobs, the last events. |
| **Cluster** | the partitions (availability, limit, nodes and CPUs allocated / idle / other, your running and pending jobs there, GPUs free per type with drained ones subtracted), GPUs cluster-wide with each node counted once, fair share, your account's overall load (everyone's jobs); **queue weather**: the pending jobs, CPUs and GPUs (per type) waiting ahead of a new job in each partition, idle nodes and free GPUs, and what `sbatch --test-only` projects for a few typical jobs (one per GPU type of each GPU partition and one per partition with your jobs, or the `weather_probes` of the config): "a job of 8 cpus, 32G, gpu:a100:1, 01:00:00 would start in 1h09m (07:32) on a01-06"; **allocation**: the account's core-hours and gpu-hours this month against the association's limits (`sreport`, `sacctmgr GrpTRESMins`), the burn rate of the last 7 days, the month-end projection and the days left at that rate, the top users (also `allocation cpu 38% gpu 41%` in the header). |
| **History** | sacct over the last N days (default 2): state, elapsed, CPU and memory efficiency (what `seff` reports), peak memory, exit code, nodes; a summary line with the counts per state, core-hours and gpu-hours; sortable and filterable. |
| **Analytics** | five views (`←`/`→`): **job series**, full-width charts of a job's CPU rate, memory against the request and every GPU's utilisation over time, from samples the dashboard records to `state/series/<job>.jsonl` (so they survive restarts and outlive the job; `↑`/`↓` move between jobs, Enter on a history row opens its series); **history**, jobs per day stacked by outcome with core-hours and gpu-hours, core-hours per partition, the queue-wait and CPU-efficiency distributions; **timeline**, a Gantt chart of every job in the window with its queue wait and run. `=`/`_` widen or narrow the window (1, 2, 7, 14, 30 days; sacct refreshes); **advisor**, what every job name in the window should have asked for (see below); **compare**, the marked jobs (or `:compare 123 456`) side by side: a table (elapsed, cores, CPU mean and max, peak memory and its share of the request, GPU mean, core-hours) and, per metric, one chart per job aligned on its first sample. |
| **Nodes** | two views (`←`/`→`): **my nodes**, the nodes running your jobs: state, allocated CPUs, load, memory in use, GRES and GRES in use, GPU utilisation with a sparkline per GPU; **cluster map**, every node of every partition (or of the configured `partitions`) as a cell: a state glyph (idle, mixed, allocated, down or drained), cores allocated / total, GPUs in use / total, the nodes running your jobs marked, with per-partition totals. |
| **Deps** | the dependency chains among your jobs (the `Dependency` field of squeue: `afterok`, `afterany`, `afternotok`, `after`, `aftercorr`, `singleton`), as trees from each root with every job's state; prerequisites that already finished are named from the history. The cursor selects a job; `c` cancels it **and everything that waits for it** (the confirmation lists the chain), `h` holds or releases the chain, `Space` marks, `Enter` opens its details. The selected panel on the Jobs tab says what a pending job still waits for and how many jobs wait for it. |
| **Group** | everyone in your account: a bar per user (running jobs, CPUs, GPUs, nodes, pending) and the table of all their jobs (sortable by user, state, name, id, time, priority; filterable; `C` exports it; `i` opens a job's details). |
| **Log** | logs stay attached to the exact job selected from active Jobs, Recents, or History, including failed and other terminal states. `O` opens a grouped file list combining actual scheduler stdout/stderr, bounded job-ID-matching files in both output directories, and explicit `tower.logs/v1` index entries from other locations. Select with arrows/PgUp/PgDn/Home/End and Enter; Esc returns to the list, then closes it. The displayed tail is bounded by `log_max_mb` and follows appended bytes. Arrows move a logical line cursor, page keys move across pages, Home goes to the first retained line, and End or `f` follows unless extending a selection. `v` starts a line selection; `y` copies its original text. `V` then `y`, `Y`, or `:copy all` copies the entire selected file through a worker, independent of the tail limit. `/` searches, `N`/`P` move through matches, `L` opens `less`, `w` wraps, `e` switches stdout/stderr, and `o` cycles files. `m` bookmarks a line; `'` jumps to the next bookmark. Bookmarks and wrapping persist in `ui.json`. Missing historical paths stay missing instead of falling back to a running job. |
| **Sources** | every Slurm command the dashboard runs: cadence, last success, latency, calls, errors, backoff, the last error; `x` disables or enables one (say `sinfo` on a slow controller). |

## Observed job completion

When a job disappears from a successful live-queue observation, its last real
record remains selectable in Jobs' Recents as **awaiting accounting**. Queue
absence alone does not establish `COMPLETED`, failure, cancellation, or another
terminal state. Tower requests a bounded, expedited accounting refresh while
respecting source timeouts and backoff. A matching terminal accounting record
confirms the attempt and adds it to History; cached details and log paths remain
associated with that exact job. Delayed accounting remains visible as pending
evidence instead of a fabricated terminal record.
If the same job ID is requeued, Tower clears the old attempt's cached details
and requests fresh metadata subject to source backoff; old log paths do not
silently become evidence for the new attempt.

In the interactive terminal, departure produces a 1.6-second block-particle
motion toward Recents. Confirmed History arrivals trigger exactly two
0.35-second pulses, followed by a static `+N` unread badge. Entering History
acknowledges the badge. Existing history loaded at startup and unchanged polling
results do not replay a completion animation. Set `animations = false` in TOML,
`"animations": false` in JSON, or use the `reader` theme to retain static notices
without motion or pulses. One-frame reports are static as well.

## Keys (remappable in the config)

| keys | action |
|---|---|
| `↑` `↓` `j` `k` `PgUp` `PgDn` `Home` `End` `g` `G` | move; in Logs, move the logical line cursor before selection and extend it after `v` |
| `Tab` `S-Tab` `]` `[` `1`..`9` | switch tabs (7 Analytics, 8 Group, 9 Deps) |
| `Space` `a` `u` | mark the selected job, all visible jobs, none: actions apply to the marked jobs, else the selected one |
| `p` | pin or unpin the marked or selected jobs: pinned jobs stay at the top of the Jobs table with a `⚲` mark; `:tag [ids] <tags>`, `:untag`, `:note [id] <text>` attach tags (a TAGS column, also on the History tab) and a note (shown in INFO and under the job); `/#tag` filters by tag; `j.tags` in expressions. All of it persists in `state/tags.json` across restarts. |
| `A` | clone and resubmit the selected job (also `:resubmit [id] ...`, `tower run resubmit 123 --mem 12G --yes`): the palette opens with `resubmit <id> `, where `--mem 12G`, `--time 03:00:00`, `-c 4`, `--gres gpu:a100:2`, `-p gpu`, `--dependency=`, `--script PATH` override the original flags and `--advised` applies the advisor's suggestions. The clone is the job's own submit line (sacct's `SubmitLine`, Slurm 23.02+, so `#SBATCH` lines in the script still apply and the overrides win over them) or, without one, an `sbatch` command rebuilt from `scontrol show job` and the record (name, partition, account, QOS, nodes, CPUs, memory, limit, GRES, an output pattern with `%x-%j` in place of the old name and id, the script). The confirmation box shows the exact command, the working directory it runs in, the resources, what `sbatch --test-only` projects for it and any caveat (an array task without `--array`, a kept dependency); `y` submits. The new job is tagged `from-<old id>` and the audit event carries the command. |
| `Enter` `d` `i` | the job's `scontrol show job` record with its **steps** (sstat per step: tasks, CPU time, peak memory and the task and node holding it, the slowest rank and how far behind the mean it is); `i` on the History or Group tab opens the same for that job (sacct -j for a finished one: steps, states, exit codes, peak memory). The selected panel shows the steps of a multi-task job, and the job's own GPU trace when `logs/gpu-util-<id>.csv` exists in its WorkDir (one nvidia-smi line per GPU per minute, see "The GPU trace" below): mean and current utilisation per GPU and the share of idle samples; the Analytics job view charts it. |
| `c` | cancel (a confirmation box lists the jobs; `y` confirms) |
| `h` | hold a pending job, release a held one (confirmation) |
| `R` | requeue a running job (confirmation) |
| `t` | `scontrol top`: put a pending job first among your own (confirmation) |
| `l` `L` `f` `+` `-` | the Log tab for the exact selected Jobs/Recents/History job; the current log in `less`; follow on/off; more / fewer log lines under the selected job |
| `O` `Enter` `Esc` | Logs: open the grouped file list; open its selected file; return from the file to its list, then close the list |
| `s` `S` | cycle the sort of the tab (jobs: state, name, id, time, priority; history: end, name, state, elapsed, cpu eff, mem eff); reverse |
| `/` `Esc` | filter by name, id, partition or info; clear the filter (or the marks) |
| `n` `b` `r` `x` | GPU sampling on/off; bell on start on/off; sample every source now; Sources tab: enable / disable the selected source |
| `v` `V` `y` | Logs: start a logical line selection at the cursor, mark the whole file, copy the original selection or whole file. Other tabs: select screen lines, select the screen, copy its text. Arrows/page keys extend a selection; right-click or shift-click extends to a row. |
| `Y` | Logs: copy the entire exact selected file, independent of displayed lines, search, scrolling, or wrapping |
| `E` `C` `J` | export the tab as text; its table as CSV; the marked or selected jobs with their recorded series as JSON |
| `:` | the command palette (Tab completes): `cancel 123 456`, `hold marked`, `filter rb2`, `sort name`, `days 7`, `tab history`, `view timeline`, `export csv`, `copy 5 12`, `gpu off`, `source sinfo off`, `theme mono`, `log 123`, `profile carc`, `eval n_pending`, and every plugin command |
| `T` | cycle the theme: default, mono, high contrast, cb (colour-blind safe: blue / orange / magenta for green / red / yellow), reader (no colour, no glyphs: plain text for screen readers and dumb terminals) |
| `?` `q` | help; quit (Esc closes an overlay, cancels a selection, clears the filter or the marks) |

The mouse works too: a click selects a row or switches tabs, a double-click opens the details (Jobs) or the series
(History), or opens the selected file in the Logs browser. The wheel scrolls,
and a right-click or shift-click extends a line selection from the last click.

The palette follows the same targets: `:find PATTERN` from Jobs or History opens
that selected job's logs. In the file browser, `:filter TEXT` filters file labels,
groups, and paths; inside a file, it sets the content search. These filters stay
separate from the job-table filter. Empty tables or file lists have no action target.

## Copying and exporting

In a log file, arrows move the logical line cursor before `v` starts selection.
The cursor has a right-edge `›` caret (`>` in ASCII); selected lines have an
orange right-edge `◆` (`*` in ASCII), including wrapped continuations. With a
selection active, arrows, PgUp/PgDn, Home, and End extend the range across pages;
Esc cancels it. `y` copies source text without row numbers, status lines, search
highlights, or wrapping. Tabs and CRLF line endings are preserved for valid
UTF-8 text. The display's bounded retained history still applies to line ranges.
Other tabs keep screen-row selection and screen-wide `V` behavior.

Ranges larger than 256 KiB or 4,096 lines run on the shared worker, as do ranges
containing invalid UTF-8. These copies pin the selected source bytes and publish
a private unique `state/exports/log-selected-<uuid>.log` file before attempting
clipboard delivery. Invalid UTF-8 skips text clipboard transport rather than
substituting replacement characters. Small valid UTF-8 ranges keep the immediate
private atomic `clipboard.txt` fallback. With `--no-state`, exports use
`./tower-exports/` instead.
An unfinished selected last line keeps its original bytes without an invented
final newline.

Rotation, truncation, or eviction of selected lines from the retained tail
invalidates their selection. Pressing `y` then reports that you need to reselect;
it does not turn an expired range into a whole-file copy. Stale mouse clicks are
also rejected instead of selecting whatever now occupies the old screen row.

In Logs, `V` marks the **whole file** and `y` then requests a full-file copy.
`Y`, `:copy all`, or `y` with no line selection requests the same operation.
Open an entry with Enter before copying from the file browser. The worker reads
the exact selected file from its selected local or SSH backend in 1 MiB chunks,
with bounded memory, independently of tail-buffer limits, filtering, cursor
position, wrapping, or line count. It saves exact source bytes to a unique
private file with mode `0600` at `state/exports/log-full-<uuid>.log`; the default
state base is `~/.local/state/tower`, honoring `XDG_STATE_HOME`. With `--no-state`,
the file goes under the launch directory's `tower-exports/` instead.

A growing log is copied through its initial byte count; later appends are
excluded and the status reports that snapshot. The writer is not locked, so
this is not an atomic application checkpoint. Detected replacement, rotation,
truncation, in-place mutation, or a short read fails without publishing a
partial export or requesting clipboard delivery; retry the current file.

Tower attempts an OSC 52 request when the **complete** UTF-8 text fits its
100,000-byte base64 limit, and a local clipboard tool when available. It never
sends only a prefix. Terminal clipboard permission and acceptance cannot be
confirmed; the status says when a request was sent. Oversize or non-UTF-8 files
keep their complete raw export, with the skipped transport explained. A local
tool can accept larger text files when a usable display is available.

Small valid UTF-8 selections and ordinary screen-text copies publish private, atomically replaced
`state/clipboard.txt` (or `tower-exports/clipboard.txt` with `--no-state`) as a
fallback. The clipboard tools are pbcopy, wl-copy, xclip, xsel, or clip.exe.
Exports of views use `text-<tab>-<stamp>.txt`, `csv-<tab>-<stamp>.csv`,
`json-<tab>-<stamp>.json`, or `report-<stamp>.txt` under `state/exports/`.
JSON carries the job record, live statistics, GPU samples, controller details,
and recorded series. From the command line, `tower --csv --tab history`,
`tower --json`, and `tower --report [PATH]` print the corresponding reports.

`:export report` (and `--report`) writes **the complete dashboard as an ASCII text
report**: summary, jobs, partitions, history, analytics, nodes, dependencies,
group usage, logs, and source health. Tables, resource bars, trend charts, and
timelines use terminal-renderable characters. Read it with `less report.txt` or
attach it as plain text. JSON and CSV exports remain available for scripts.

## Remote mode and profiles

`--host login.example` (or `host = ...` in the config) runs every Slurm command on that machine over ssh with a
ControlMaster connection (`~/.ssh/tower-*`), so a command costs one round trip after the first; stdout and the GPU
traces are read there too (`stat` and offset reads, so following a log costs one stat every 1.5 s), and `L`
opens `less` over `ssh -t`.  Actions go the same way.  `ssh_user` and `ssh_opts` (`["-J", "bastion"]`) complete it.

A profile is a named set of configuration keys, one per cluster or per way of looking at one:

```toml
[profiles.mycluster]
host = "login.example.edu"
ssh_user = "me"
account = "lab_01"
partitions = ["gpu", "main"]
[profiles.local]
history_days = 7
```

`tower --profile mycluster` merges it over the top level; `:profile local` inside the dashboard restarts on that
profile (the header shows `user@host [profile]`).

## Recording and replay

`--record FILE` (or `record = ...` in the config) appends every command, its answer or error, and every action to
a JSONL file (gzipped when the name ends in `.gz`).  `--replay FILE` runs the whole dashboard against it: the
clock is the recording's (`--speed 10` plays ten recorded seconds per second, `--paused` starts still), every
tab, chart and log position works, actions are refused, and nothing is written to the state directory.  The
header shows `REPLAY <time> x<speed>` and a scrub bar under it with the position in the recording, its span, the
speed and the state.  `|` pauses and plays, `<` and `>` move 60 s, `{` and `}` halve and double the speed;
`:replay seek 10:30`, `:replay seek 50%`, `:replay seek +600`, `:replay speed 20`, `:replay pause`.  A recording
made with `--fake --record` is a self-contained fixture: the tests replay one.

## Scripted mode and expressions

`tower run <palette command>` runs one command without a screen: `tower run cancel 123 --yes`, `tower run export
csv --tab history`, `tower run hold marked` (marks come from the saved state).  An action that would ask for
confirmation needs `--yes` (exit 3 otherwise); a failed or unknown command exits 1.

`--eval EXPR` prints the value of an expression over the snapshot; `--wait-for EXPR [--timeout S] [--poll S]`
polls until it is true (exit 0) or the timeout passes (exit 2), for scripts that wait on the queue:

```bash
tower --wait-for 'not any(j.name.startswith("train") for j in jobs)' --timeout 7200 && ./collect_results.sh
tower --eval 'sum(j.gpus for j in running)'
tower --eval '[j.id for j in running if j.cpu is not None and j.cpu < 0.2 and j.elapsed > 600]'
```

The language is Python syntax restricted to literals, names, attribute and item access, arithmetic, comparisons,
`and or not`, conditionals, comprehensions and the functions `len min max sum any all abs round int float str
sorted bool list set` plus the string methods `startswith endswith lower upper split strip replace count find`
and `dict.get`; nothing else parses.  A missing field reads as None, and a comparison with None is False rather
than an error.  Names: `jobs running pending` (lists of jobs), `finished` (the history), `n_running n_pending
n_jobs n_finished cpus_running gpus_running gpus_free`, `free_gpus` (per type), `partitions nodes account events
source_errors now user`, `by_id` and `by_name`.  A job has `id name state partition pending running held dep
reason priority nodes cpus gpus gpu_type nodelist hosts elapsed limit left waited age` (seconds), `cpu eff mem`
(fractions), `rss mem_req` (bytes), `gpu gpu_mean` (percent), `account qos submit start est_start` (epoch
seconds), `command marked tags`.  A finished job has `id name state partition elapsed cpus gpus nodes cpu_eff
mem_eff rss mem_req exit start end submit nodelist core_hours gpu_hours ok`.  `:eval EXPR` in the palette shows
the same inside the dashboard; the alert rules use the same language.

## Plugins

Python files in `~/.config/tower/plugins/` (or listed under `plugins` in the config; `--no-plugins` skips them)
define `setup(api)` and register palette commands, flags in the FLAGS column, extra tabs, event hooks and
sampled sources, each with the same health and backoff as the built-in sources:

```python
def setup(api):
    api.command("hello", lambda app, args: f"hello {' '.join(args) or app.user}", "hello [name]")
    api.flag(lambda job, snap, app: "big" if job.cpus >= 32 else None, style="magenta")
    api.tab("hello", "Hello", lambda snap, app, width, height: [[("   hi there", "bold")]])
    api.on_event(lambda ev: print(ev["kind"], ev["text"]))
    api.source("ticker", 60.0, lambda slurm, store: store.event("tick", "tick"))
```

A plugin that fails to load or whose tab raises is reported (an event, a line on the tab) and never stops the
dashboard.

## The advisor

The **advisor** view of the Analytics tab (and `:advise [id | name]`, `tower run advise rb3-identity`) turns what
jobs used into what they should ask for: peak memory × 1.25 rounded to a round `--mem` (doubled after an
out-of-memory), `--cpus-per-task` from the CPU efficiency when it is under 50% (cores = CPU time / (elapsed × 0.7)),
`--time` from the longest run × 1.3 rounded up to 15 minutes (doubled after a timeout) when the limit is more than
40% slack or too short.  Per job name over the window: the runs, peak against request, efficiency, longest run
against limit, the suggested flags, the core-hours spent on idle cores (1 - efficiency × core-hours), and what
failed.  For a running job the same so far, with the finished runs of the same name widening the memory and time
figures: the selected panel shows one `advice` line once the job is older than `warn_after_minutes` or has
history, and "already N past the longest completed run" when it is running long.

## Alert rules

```toml
[[alerts]]
name = "idle gpu"
when = "running and gpus and gpu is not None and gpu < 15 and elapsed > 900"   # over each job (scope = "job")
every = 1800                    # seconds before the same job fires the rule again (0: once per job)
actions = ["bell", "event"]     # bell | event | notify (the [notify] command, TOWER_EVENT=alert) | command
command = ""                    # with "command": a shell command with TOWER_ALERT TOWER_JOBID TOWER_JOBNAME TOWER_TEXT
[[alerts]]
name = "queue empty"
scope = "cluster"               # over the whole snapshot: n_pending, free_gpus, source_errors ...
when = "n_pending == 0 and n_running == 0"
every = 0
```

Rules use the expression language above; the sampler evaluates them after every jobs, live and GPU round.  A
firing rings (the curses screen beeps, `--watch` writes a bell), logs an `alert` event (red in the events list),
runs the notify command or the rule's own command, and the header shows the active alerts (`⚠ 2 alerts: idle gpu
12480001, queue empty`) until their conditions turn false.  A rule that does not parse or fails to evaluate is an
`alert_error` event, once.  `--alert EXPR` (repeatable) adds a rule for one run: `tower --watch --alert 'running
and cpu is not None and cpu < 0.1'`.

## Figures and flags

CPU% is the rate between two accounting samples (Slurm samples every 30 s, so it moves in steps); EFF the CPU time
over elapsed × cores so far; MEM% the peak resident set against the request; GPU% the mean utilisation of the job's
GPUs at the last sample.  FLAGS: `!cpu` `!mem` `!gpu` when a job older than `thresholds.warn_after_minutes` is below
the configured fractions, `ending` under ten minutes before the limit, `held`, `dep`.  Finished jobs: CPU EFF and
MEM EFF are what `seff` reports, computed from sacct.

## Sources and cadences

| source | command | every |
|---|---|---|
| jobs | `squeue -u $USER` | 2 s |
| starts | `squeue --start` (pending jobs) | 10 s, and after every queue change |
| live | `sstat` (CPU time, peak memory of the batch step) | 10 s |
| gpu | `nvidia-smi` through `srun --jobid ID --overlap --immediate=5`, ssh to the node as the fallback | 5 s |
| nodes | `scontrol show node` | 15 s |
| partitions | `sinfo` (partitions, GPU inventory per node) | 60 s |
| finished | `sacct -S now-Nhours` | 60 s |
| share | `sshare -U` | 120 s |
| account | `squeue -A account` (everyone's jobs in the account: the Group tab and the header's load) | 30 s |
| details | `scontrol show job` of the selected job | 20 s |
| weather | `squeue -t PD` cluster-wide (pending work per partition) and `sbatch --test-only` per probe | 120 s |
| budget | `sreport cluster AccountUtilizationByUser` since the first of the month and over the last 7 days, `sacctmgr show assoc` for the limits | 600 s |
| trace | the GPU trace CSV of each running GPU job and of the job the analytics view shows, through the file reader (local or ssh) | 60 s |
| fin_details | `sacct -j` of the finished job whose details are open | on demand |

Every source runs in a small thread pool on its own cadence, never overlapping itself, with a timeout per command;
a failing source backs off (doubling up to five minutes) without touching the others, and its error shows in the
header and on the Sources tab.  Nothing in the screen thread ever waits on Slurm.  A job that leaves the queue shows
within one `jobs` round.

## Configuration

`~/.config/tower/config.toml` (or `.json`; `--config PATH`; `$TOWER_CONFIG`).  `tower --write-config` writes the
commented defaults without replacing an existing config (JSON on Python 3.10, TOML on 3.11+).  Sections: top level (`user`, `account`, `ascii`, `color`, `history_days`, `log_lines`,
`gpu_sampling`, `bell`, `partitions`, `gpu_types`, `weather`, `weather_probes`, `budget`, `animations`), `[research]`, `[logs]`, `[intervals]`, `[timeouts]`, `[thresholds]`, `[[alerts]]`, `[notify]`
(`command` runs through the shell on the configured `events` with `TOWER_EVENT`, `TOWER_JOBID`, `TOWER_JOBNAME`
and `TOWER_TEXT` in the environment: a Slack webhook, an e-mail, anything), `[keys]` (action = list of key names).

Set `logs.manifest_file` to an exact log-index filename, such as `logs.json`.
Relative filenames use the explicitly selected research workdir (`--workdir`),
otherwise the selected job's actual WorkDir; `{job_id}` follows that exact job.
The index's relative file entries use its own directory and may explicitly name
sibling locations. Exact absolute entries may name other directories; they retain
their source-machine meaning after copying a run. See the
[project log-index standard](PROJECT_STANDARD.md#log-locations-logsjson) and
[schema](schemas/logs.v1.schema.json). Tower caches bounded catalog work on its
shared background worker and does not recursively scan directories.

State lives in `~/.local/state/tower/`: `ui.json` (tab, sort, log lines, toggles) and `events.jsonl`, the append-only
log of every transition and every action (an audit trail: what was cancelled, held or requeued, when, and whether
Slurm accepted it).  `--no-state` reads and writes neither.

## The twenty features at a glance

| | feature | where |
|---|---|---|
| 1 | resource advisor: suggested `--mem` / `--cpus-per-task` / `--time`, idle core-hours, time against the longest run | Analytics › advisor, the selected panel, `:advise` |
| 2 | clone and resubmit with overrides, the advisor's flags and an `sbatch --test-only` preview | `A`, `:resubmit`, `tower run resubmit` |
| 3 | dependency chains as trees, chain cancel / hold / release | Deps tab, `:chain` |
| 4 | alert rules (per job or over the snapshot) with rate limits: bell, event, notify, command | `[[alerts]]`, `--alert` |
| 5 | queue weather: pending work ahead per partition, `sbatch --test-only` projections | Cluster tab |
| 6 | allocation budget: used this month, limits, burn rate, month-end projection, by user | Cluster tab, header |
| 7 | cluster map: every node as a cell with state, cores and GPUs | Nodes › cluster map |
| 8 | the account's jobs: per-user bars and the full table | Group tab |
| 9 | session recording and replay with a scrub bar | `--record`, `--replay` |
| 10 | a complete ASCII text report | `--report`, `:export report` |
| 11 | remote mode over ssh with remote file reads | `--host`, `host =` |
| 12 | per-cluster profiles with hot switching | `--profile`, `:profile` |
| 13 | job comparison: a table and aligned charts of the marked jobs | Analytics › compare |
| 14 | pins, tags and notes that persist; `#tag` filters | `p`, `:tag`, `:note` |
| 15 | steps per job: tasks, CPU time, peak memory and where, the slowest rank; sacct steps of finished jobs | the panel, `i` |
| 16 | the job's own GPU trace CSV in the panel and the charts | `logs/gpu-util-<id>.csv` |
| 17 | log extras: grouped multi-location files, wrap, stderr, bookmarks | Log tab `O` `w` `e` `o` `m` `'` |
| 18 | scripted mode: one command, an expression, a wait | `tower run`, `--eval`, `--wait-for` |
| 19 | plugins: commands, flags, tabs, hooks, sources | `~/.config/tower/plugins/` |
| 20 | accessibility: a colour-blind palette and a plain-text reader theme; recordings as test fixtures | `T`, `theme cb`, `theme reader` |

## The GPU trace

The panel, the charts and the advisor read a CSV the job writes itself, `<WorkDir>/logs/gpu-util-<jobid>.csv`, with
one line per GPU per minute: `timestamp, index, utilization.gpu, memory.used`.  Add this to a GPU job script, before
the work starts:

```bash
mkdir -p logs
nvidia-smi --query-gpu=timestamp,index,utilization.gpu,memory.used --format=csv,noheader,nounits -l 60 \
    > logs/gpu-util-${SLURM_JOB_ID}.csv 2>/dev/null &
trap 'kill $! 2>/dev/null' EXIT
```

Without the file the dashboard still samples `nvidia-smi` live inside the allocation (`gpu_sampling`); the trace
adds the history from before the dashboard started and survives the job.

## Architecture

```
tower/
  layout.py      pure layout: columns fitted to a width (shrink flexible ones, drop the least useful, then a floor),
                 ellipsis clipping by display width, bars, sparklines, rules, boxes, painters to text / ANSI
  model.py       typed records (Job, Live, GpuSample, Node, Partition, Finished, Health) and the Store: histories,
                 transitions, events, per-source health, persistence
  slurm.py       the command layer: one function per Slurm call, parsers on the recorded formats, and FakeBackend,
                 a simulated cluster answering the same commands as text
  sampler.py     the scheduler: cadences, a thread pool, per-source timeouts, backoff, health, kick
  transitions.py short monotonic queue-departure motion, confirmed History pulses, and an unread count
  actions.py     cancel / hold / release / requeue / top with an audit event each; the notification hook
  views.py       the tabs and overlays as rows of (text, style) segments
  controller.py  the application state and every key, mouse click and confirmation; no curses, so tests drive it;
                 the line selection, the command palette, exports and the clipboard
  charts.py      vertical bar charts with axes (eight sub-levels per row), horizontal bars, histograms, Gantt rows
  logs.py        bounded incremental log buffers, logical keyboard cursors, raw line ranges, and selection
  log_catalog.py bounded grouped file discovery and explicit tower.logs/v1 manifests on the selected backend
  log_copy.py    background exact-byte full-file snapshots and selected ranges, private exports, clipboard handoff
  research.py    the shared bounded worker for research inspections, log catalogs, and full-log copies
  clipboard.py   complete OSC 52 requests, streamed local clipboard tools, and private atomic text fallbacks
  export.py      text / CSV / JSON exports
  screen.py      the curses loop (colours, mouse, resize, less), the ANSI watch loop, one-frame text and JSON
  cli.py         the command line: profiles, remote mode, recording and replay, scripted mode, plugins
  doctor.py      read-only environment checks for demo, local Slurm, and remote SSH capabilities
  clock.py       the dashboard's clock (the wall clock, or the recording's time under --replay)
  expr.py        the expression language (alert rules, --eval, --wait-for) and the namespaces over the snapshot
  record.py      RecordingBackend, ReplayBackend and the replay clock (pause, seek, speed)
  remote.py      SshBackend (ControlMaster) and the file readers: LocalFiles, RemoteFiles (stat and offset reads over ssh)
  plugins.py     the plugin API and loader
  advisor.py     the resource advisor: suggested --mem / --cpus-per-task / --time from finished and running jobs
  alerts.py      the alert rules engine (per job or over the snapshot, rate limits, bell / event / notify / command)
  deps.py        dependency parsing, the chain graph (trees, upstream, downstream) behind the Deps tab and chain actions
  resubmit.py    clone and resubmit: sbatch flag parsing, overrides, the clone from a submit line or a record, the preview
  report.py      the ASCII report: complete terminal snapshots of every tab
```

`tests/test_tower.py` runs the parsers on recorded output, the layout, the configuration, the store's transitions,
the controller against the simulated cluster (marks, confirmations, every action, filter, sort, tabs, overlays,
mouse), the one-frame and JSON outputs, the watch mode, the curses screen through a pseudo-terminal, the
expression language (and what it refuses), a recording replayed through the whole dashboard, the ssh transport
and remote file reads through a local shell, profiles, plugins (commands, flags, tabs, hooks, sources, a broken
one), scripted mode and the themes; the advisor on finished and running jobs, alert rules (firing, rate limits, scopes,
errors, the header and events, `--alert`), the dependency graph and chain cancel through the Deps tab, tags, pins,
notes and the compare view; sbatch flag parsing and overrides, clones from a submit line and from a record, and a
resubmission through the screen and the scripted mode (the fake cluster lists the new job); the ASCII report from the
screen and the command line, the replay controls, scrub bar and seeks, and the log extras (wrap, stderr, the job's
other files, bookmarks that persist).
