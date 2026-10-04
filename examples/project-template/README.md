# Portable Tower project template

Copy this directory into a new project. The application writes portable JSON;
it does not need Tower installed. Tower reads explicitly selected files using
its existing terminal views and commands. The complete convention and schemas
are in [the project integration guide](https://github.com/rahel99x/Slurm-Tower/blob/main/docs/PROJECT_STANDARD.md).
The included MIT `LICENSE` permits reuse and adaptation; retain its notice when
copying the reporting code.

## Try the real, small example

From your copied **project root**:

```bash
python3 experiment.py --run-id demo-001 --steps 20 --terms-per-step 1000
python3 reporting.py export runs/demo-001 --reference runs/demo-001
tower --fake --config .tower/config.json --workdir "$PWD/runs/demo-001" \
  --tab research --research-view experiment
```

`--fake` supplies explicitly simulated scheduler data for this local walkthrough;
the selected application metrics and outputs are real. On CARC, omit `--fake`
and add `--profile carc` to use the supplied profile with slower polling.

The example computes a real approximation of pi, reports actual error and
progress, and records measured wall time and coordinator CPU time. A local run
has no scheduler allocation, so CPU/node/GPU requests and memory usage remain
absent. Its single run cannot support a calibrated resource prediction.

Inspect outputs and planning independently:

```bash
tower run validate .tower/contracts/outputs.v1.json runs/demo-001
tower run predict --file reports/planning.json
tower run workflow analyze .tower/definitions/workflow.json
```

`predict` explains missing evidence rather than estimating from one local run.
The workflow has one actual step and an unknown duration; replace its definition
with your real dependencies and measured timing estimates when available.

## Standard layout

```text
your-project/
  .tower/
    config.json                    Tower binding; committed
    contracts/outputs.v1.json       Exact expected outputs; committed
    definitions/workflow.json      Optional project-owned planning recipe
  experiment.py                    Replace with your scientific application
  reporting.py                     Optional copyable stdlib instrumentation
  jobs/run.sbatch                   Example CPU batch entry point
  runs/<unique-attempt-id>/
    run.json                       Project-owned manifest and explicit paths
    logs.json                      Grouped index of exact per-run log locations
    metrics.jsonl                  Append-only native Tower metric rows
    summary.json                   One terminal summary per attempt
    outputs/results.json           Scientific outputs declared by the contract
    logs/stdout.log                 Application stdout
    logs/stderr.log                 Application stderr
    passports/                     Optional explicit Tower provenance captures
  reports/planning.json             Explicit aggregate of selected summaries
  logs/<slurm-job-id>.out           Scheduler launch stdout, created by Slurm
  logs/<slurm-job-id>.err           Scheduler launch stderr, created by Slurm
```

Runtime files are ignored by Git. Each retry gets a new run ID, even if Slurm
reuses the same scheduler ID. Keep `name` stable for the scientific workload and
`parameters` stable for comparable work. The example fingerprints the actual
Python scientific entry point rather than only its batch wrapper. For a larger
project, also put deterministic code-tree, dataset, environment, and scientific
configuration digests in `parameters`; exclude timestamps, run paths, and retry
identifiers. Do not pool runs after changing work or inputs.

`run.json` and `summary.json` are reporting conventions. Tower does not discover
run directories or load their manifests automatically. The config binds native
metrics, output checks, and an explicit planning aggregate.
The config also binds the native `logs.json` index, so application logs can be
opened independently of the scheduler's launch stdout/stderr.

## Paths and terminal views

Always launch these examples from the project root. In this config:

- `metrics_file = metrics.jsonl` is relative to the selected `--workdir`.
- `logs.manifest_file = logs.json` is relative to the selected `--workdir`;
  without that override it uses the selected scheduler job's actual WorkDir.
- A relative entry in `logs.json` is relative to the index's directory.
- The contract and `planning_file` paths are relative to the process working
  directory, so they stay at the project root.
- Contract output paths are relative to the selected `--workdir`.
- Each manifest `paths` entry is relative to its own run directory. Its
  `provenance.script` is relative to the project root.

For artifact checks use the same config and run directory with
`--research-view artifacts`. For aggregate resource analysis use
`--research-view predict`. Inside Tower, `:metrics /absolute/project/runs/demo-001/metrics.jsonl`
attaches an explicit stream; use an absolute path when a run workdir is already
selected. `:artifacts .tower/contracts/outputs.v1.json
runs/demo-001` attaches the matching output root.

## Organize logs across locations

`begin_run` writes `logs.json` with application stdout/stderr and the actual
`job_id` when provided. Add explicit other files with the same run coordinator:

```python
from reporting import register_log

register_log(run, "training.rank-0", "logs/rank-0.log",
             label="Rank 0", group="Training", description="Coordinator training output")
register_log(run, "scheduler.stderr", "/scratch/my-project/batch/12345.err",
             label="Batch stderr", group="Scheduler")
```

Replace the external path with the real location for that run. IDs and resolved
paths must be unique; at most 256 entries and 256 KiB are allowed. Registration replaces the
index atomically without opening the logs. A listed file may not exist yet;
existing paths must use regular files and real directory ancestors. An explicit
`../` path may reach a sibling location; these read-only log attachments are
separate from confined artifact-contract paths. No glob, symlink, or recursive
discovery is allowed. Absolute paths retain their
source-machine meaning when copying a run; update them explicitly or move the
file into the bundle and use a relative entry.

In Jobs, select an active job or a row in **Recents**, then press `l`. In History,
select any job state and press `l`; its identity stays bound in Logs. Press `O`
to open the grouped file list, move with arrows or PgUp/PgDn/Home/End, and press
Enter to open a file. Esc returns to the list, then back to the file view;
choose another entry without changing jobs. `o` retains quick cycling and `e`
switches stdout/stderr. Scheduler paths and bounded job-ID-matching files in
their directories join the explicit index; Tower does not scan the filesystem.

For old jobs whose accounting service did not retain stdout/stderr or WorkDir,
Tower reports missing evidence instead of using a currently running job. Select
the run directory explicitly with `--workdir` to attach its `logs.json`.

## Instrument another application

```python
import time
from reporting import begin_run, write_metric, finish_run

run = begin_run(".", "trial-001", name="stable-workload", script="my_program.py",
                parameters={"dataset_sha256": "actual-data-digest", "algorithm": "v1"})
started = time.perf_counter()
try:
    # Your real work belongs here. Only report values you actually measured.
    write_metric(run, {"loss": 0.12}, step=1, phase="training",
                 progress={"completed": 1, "total": 10, "unit": "epochs"})
except Exception:
    finish_run(run, state="FAILED", runtime_seconds=time.perf_counter() - started,
               exit_code=1)
    raise
else:
    finish_run(run, state="COMPLETED", runtime_seconds=time.perf_counter() - started,
               results={"score": 0.9}, exit_code=0)
```

The numeric values above illustrate the API; replace them with measurements.
`begin_run` refuses an existing run directory. One coordinator appends metrics
for a run; distributed workers must send their observations to that coordinator
or write separately selected streams. `finish_run` publishes a fresh summary
atomically and refuses to overwrite one. JSON numbers must be finite.

Request/allocation fields may be passed to `begin_run(..., resources={...})`
only when known: `cpus`, `nodes`, and `gpus` are **job totals**; `mem_bytes` is
requested total memory; `time_seconds` is requested walltime. Measurements go in
`finish_run`: `runtime_seconds`, `cpu_seconds`, and `memory_bytes`. Observed
memory requires `memory_scope` of `job_peak`, `per_node_peak`, or `max_task_rss`.
Slurm `MaxRSS` is a per-task peak and must not become total job memory. Use
optional `metadata` to document measurement sources and scope.

Explicit controlled scaling observations may pass
`scaling={"workers": 2, "problem_size": 1000, "repeat": 1}` to `finish_run`.
Those values must describe actual controlled work. The pi example is a single
process and emits no scaling metadata or unsupported scaling recipe. Worker
count alone never establishes allocated CPU count.

## Explicit aggregate collection

```bash
python3 reporting.py export runs/trial-001 runs/trial-002 \
  --reference runs/trial-002
```

Select at most 256 exact attempt paths. The helper does not scan directories,
follow symlinks, launch jobs, or invent queue observations. It preserves failed,
timeout, OOM, and other terminal outcomes in `history`. An explicit reference run
sets the prediction `query`; unavailable allocation fields remain unavailable.
Only summaries with explicit scaling controls also enter `scaling`.

The default report is an authoritative snapshot of the selected attempts. A
later export replaces a prior native planning bundle atomically; it refuses to
replace other content. Keep the final document below Tower's default 1 MiB JSON
limit; oversize selections fail without silently discarding evidence. Split
large projects into explicit comparable experiment reports with `--output`.

## Run on CARC

Review partition/account/QoS, Python module or environment activation, and
resource requests for your CARC allocation. From the project root:

```bash
mkdir -p logs
tower run prepare jobs/run.sbatch --workdir "$PWD"
```

Review the preflight before choosing Tower's explicit confirmation-based submit
flow, or submitting the script through your usual `sbatch` process. `logs/` must
exist **before submission** because Slurm opens stdout/stderr before the script
runs. The batch job then creates its unique run and application logs. This
example records Slurm allocation counts only when its environment explicitly
provides them; it never uses host CPU count or worker count as an allocation.

A killed process may be unable to publish `summary.json` and may leave a RUNNING
manifest. Do not call that completed. Your scheduler reconciliation step must
record the authoritative outcome separately; do not infer OOM, timeout, or
cancellation from an arbitrary exception. Keep incomplete attempt evidence and
retain terminal failure summaries when you can finalize them accurately.
An observed keyboard interrupt is recorded as `INTERRUPTED`; other unknown
terminal causes may be recorded as `UNKNOWN` with their known evidence retained.
