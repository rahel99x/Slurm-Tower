# Tower implementation roadmap

[README](../README.md) · [Phase one guide](guides/phase-one.md) · [Project standard](PROJECT_STANDARD.md)

This roadmap tracks the thirty proposals from the research review. A proposal
is not an available control until its release documentation identifies it as
implemented. Later phases have no promised release date. Each phase requires
review of the current implementation before work starts.

Tower remains a terminal application. Optional adapters must not become
requirements for the core application. Scheduler actions require an exact job
identity and a reviewable scope. Missing evidence must remain unknown.

## Phase one: measurement and submission confidence

Release 4.14.0 implements four focused additions:

| Proposal | Addition | Release scope |
| --- | --- | --- |
| A03 | Shell-body correctness checks | Explicit local syntax and optional ShellCheck analysis; no script execution |
| A13 | AMD and Intel GPU telemetry | Optional command adapters alongside NVIDIA; preserve unsupported counters as unknown |
| A14 | Scientific array manifests | Explicit array-index mappings with validation and bounded reads |
| A16 | Sampling capability inspector | Separate Tower reads from upstream collection and show missing configuration evidence |

Read the [phase one guide](guides/phase-one.md) for supported controls and limits.
These additions do not implement automatic job recovery, workflow supervision,
scientific acceptance testing, or changes to scheduler configuration.

## Phase two: prevent avoidable failures

Planned, not implemented by phase one:

| Proposal | Addition | Dependency or important limit |
| --- | --- | --- |
| P01 | Storage readiness cards | Per-filesystem capacity, user/project quota, and inode evidence; no repeated directory walks |
| P02 | Edit pending jobs | Field/state/version permission checks and a reread after applying changes |
| P03 | Existing array concurrency controls | Real array parents only; preserve Slurm's zero-means-unlimited semantics |
| P04 | Reservation and maintenance timeline | Private reservations and external maintenance notices can remain unavailable |
| P05 | Software-license inventory | Distinguish Slurm's inventory from the vendor license server |
| A05 | Slurm installation health checks | Read-only service and connectivity evidence; no automatic service restarts |
| A20 | Recover retained batch scripts | Respect scheduler retention and permissions; never substitute the current local script |
| A19 | Allocation shell and step attachment | Explicit terminal handoff, exact allocation, minimal requested resources, and clean return |

## Phase three: reproducible and scientifically valid runs

Planned, not implemented by phase one:

| Proposal | Addition | Dependency or important limit |
| --- | --- | --- |
| A01 | Recreate software environments | Lockfiles, image identity, and compute-node compatibility evidence |
| A02 | CPU, NUMA, and GPU placement verification | Keep requested topology separate from measured placement |
| A04 | Scientific acceptance tests | Project-defined tolerances; missing results cannot pass |
| A07 | Statistical comparisons | Independent experimental units, explicit pairing, uncertainty, and small-sample limits |
| A08 | Verified intermediate-result reuse | Complete declared dependencies, validated outputs, and an explicit reuse policy |
| A15 | Dependency-chain repair | Preserve successful branches; report partial application of non-transactional scheduler changes |

## Phase four: durable campaigns and data movement

Planned, not implemented by phase one:

| Proposal | Addition | Dependency or important limit |
| --- | --- | --- |
| S01 | Checkpoint-aware recovery | Application-specific checkpoint validation and restart compatibility |
| S03 | Persistent monitoring service | Reconnectable UI, single-writer ownership, restart reconciliation, and site-approved hosting |
| S04 | Input staging and verified output return | Persistent transfer manifests, verification, and explicit retention policies |
| A06 | Adaptive parameter searches | Bound trial budgets; distinguish infrastructure failures from scientific outcomes |
| A09 | Short-task packing | Use an executor adapter; retain logical-task identity and enforce resource bounds |
| A10 | Elastic Dask worker pools | Coordinate with one scaling controller and count queued as well as connected workers |
| A11 | Workflow-engine connectors | Observe native engine identities first; preserve execution ownership |
| A12 | Heterogeneous allocations | Component-level requests, launch semantics, and site restrictions |

Tower already has reviewed workflow execution and durable submission receipts.
These proposals extend their scope. They do not describe those existing
capabilities as missing.

## Phase five: scale and infrastructure diagnosis

Planned, not implemented by phase one:

| Proposal | Addition | Dependency or important limit |
| --- | --- | --- |
| S02 | Distributed bottleneck explorer | Bounded profiler imports, rank/node identity, and evidence for communication or I/O delays |
| S05 | Concurrent multi-cluster workspace | Cluster and attempt identity, independent timeouts, and isolated collector failure |
| A17 | Historical infrastructure-incident correlation | Permission-aware node events; an overlap is evidence, not proof of cause |
| A18 | Energy per useful result | Distinguish job, node, and device attribution; include failed attempts in campaign totals |

## Separate 5.0 proposal: on-demand stack tracing

The live stack tracer remains a design proposal. Phase one does not add a Trace
button or attach a debugger. The planned direction is an explicit per-job
Details action backed by runtime-specific, node-local collection. It must bind
results to a job attempt, node, process ID, and process start time; report
permission and runtime limits; and keep collection outside the UI thread.

## Compatibility and validation gates

Every implementation phase must account for interactions with existing controls:

- Publish immutable or isolated collector results. UI movement must not start
  filesystem reads, scheduler commands, or profiler work.
- Preserve the selected job and execution attempt across source refreshes.
  Results from an earlier selection must not replace the current view.
- Keep collection intervals, display windows, and source production rates
  separate. Faster reads cannot promise faster upstream measurements.
- Reuse shared readers and bounded caches. Invalidate them when identity,
  content, configuration, or adapter selection changes.
- Keep missing, unsupported, inaccessible, stale, and measured-zero values
  distinct. Remote and simulated backends must not silently read local data.
- Check the new controls with mouse capture, keyboard focus, overlays,
  selection, grouping, and Single/Multi worker transitions.
- Test malformed and oversized inputs, empty data, partial writes, source
  disappearance, command failure, stale results, and repeated actions.
- Run focused unit and integration tests, terminal rendering checks, and the
  existing regression suite. Document limits that require real hardware or a
  site Slurm installation.

Proposal IDs `S01`–`S05` and `P01`–`P05` identify the earlier substantial and
practical lists. `A01`–`A20` identify the twenty additional proposals. They are
tracking labels, not new commands or configuration keys.
