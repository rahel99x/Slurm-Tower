# Group jobs from one launch

[README](../../README.md) · [Controls](../CONTROLS.md) · [Project reporting standard](../PROJECT_STANDARD.md) · [Adjustable workspaces](adaptive-workspaces.md)

Tower uses available scheduler evidence and explicit launch markers to group related jobs.
Grouping works with jobs that were submitted before Tower started and jobs that arrive during the session.
It changes the displayed rows. Each member keeps its actual Slurm job ID, logs, measurements, and action target.

## Fold and open a batch

1. Open a list of jobs.
2. Find a row with a group-fold symbol.
3. Click that symbol to hide the other matching members.
4. Read the representative job ID and the group summary.
5. Click the symbol again to show the members.

**Expected result:** One row represents the closed group.
Opening it restores the matching members under the current filters and sort order.
The fold preference applies across job lists and their history browsers.
New groups start open.

The same controls apply to Jobs, Recents, History, account Group rows, and job-history browsers in Analytics, Dependencies, Logs, and Research.
Advisor's running-job list and independent dependency roots also support folding.
Dependency trees retain their relationship structure.
Aggregate charts, timelines, explicit comparison traces, and node ownership displays retain their full measurement context; their job-history browser supplies grouped job selection.

During ordinary job-row navigation, Left closes the selected job's group and Right opens it.
With directional button focus active, arrows move between controls instead.
Use F8, arrows, and Enter to focus and activate a visible fold control.
Use `:jobgroups off` to show individual jobs, or `:jobgroups on` to restore grouping.
Use `:jobgroup open GROUP_ID`, `:jobgroup close GROUP_ID`, or `:jobgroup toggle GROUP_ID` to change a known group directly.
Normal saved UI state retains grouping and closed-group preferences.

## Read the closed row

The group label identifies the launch and its matching record count (`records`, or `rec` in a compact browser).
The INFO cell shows compact state badges in the current theme.
Zero counts are omitted. Unicode separates badges with `·`; ASCII uses `|`.
For example:

```text
4 run · 2 pend · 3 dep · 1 never · 8 done
```

| Badge | Narrow form | Meaning |
| --- | --- | --- |
| `run` | `R` | Running jobs and scheduler transition states such as configuring or completing |
| `pend` | `P` | Pending jobs without a reported dependency wait |
| `dep` | `D` | Pending jobs with a dependency reason or dependency expression |
| `never` | `!` | Pending jobs with Slurm's `DependencyNeverSatisfied` reason |
| `done` | `C` | Completed jobs |
| `fail` | `F` | Failed jobs, including timeout, out of memory, node failure, preemption, and deadline failure |
| `cancel` | `X` | Cancelled jobs |
| `other` | `?` | Other reported states, including evidence that does not yet establish a terminal outcome |

A narrow cell puts the count after the short code, such as `R4 P2 D3 !1 C8`.
Point at the group control to read the fuller status description.

Each observed record contributes to one category only.
The pending count excludes `dep` and `never`.
These badges report scheduler evidence; `never` does not infer failure from a long wait.
Counts cover members that match the current list and its filters, not every job that might exist in Slurm.
Expanded group information can also show matching members against the total observed group membership.
Compressed Slurm array ranges count as observed records, not as an invented count of individual task states; the summary adds `(records)`.
Queue records take precedence over accounting records with the same exact job ID.

Recents and History add INFO when a closed group needs that summary.
Resource cells on a closed row are blank rather than showing one member's measurements as batch totals.
The narrowest layouts can clip badge text; enlarge the pane or expand the group to inspect its members.

## Mark a batch explicitly

Use an explicit marker when your project already knows which jobs form one launch.
Create one unique ID for that launch and pass it as the whole Slurm comment on each member.
Tower accepts `launch:ID` and `group:ID`.
The ID must start with a letter or digit and contain 1–128 letters, digits, `.`, `_`, or `-`.

For example, run these commands from one project working directory.
Replace the script paths with your project's actual batch entry points.

```bash
tower_batch_id="study-$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
sbatch --comment="launch:${tower_batch_id}" jobs/first.sbatch
sbatch --comment="launch:${tower_batch_id}" jobs/second.sbatch
sbatch --comment="launch:${tower_batch_id}" jobs/third.sbatch
```

**Expected result:** Tower groups available members that share the marker and its scope.
It reads comments from queue and accounting publications when Slurm supplies them.
Slurm must retain and expose job comments for that marker to remain available in historical accounting.
The full comment must match the supported marker; free text around it is not a launch ID.
An explicit marker does not add scheduler dependencies or change job resources.

Markers are scoped by cluster, owner, account, and working directory.
Use the same project working directory for all marked members that you want to group.
Use a new marker for each independent launch, including a new batch retry.
Reusing a marker in the same scope can combine otherwise separate launches.

You can tag jobs that already exist from Tower's command palette:

```text
:tag 101 102 103 launch:study-17
```

Use the actual available job IDs.
Local tags persist in the current Tower state directory; they are not written to Slurm and are not shared automatically with another installation.
Remove a local marker with `:untag 101 102 103 launch:study-17`.
Conflicting local marker tags do not establish a reliable local marker.
When an integration already publishes `TowerLaunchId`, `LaunchId`, `LaunchGroup`, or `JobGroup` in scheduler details, Tower also accepts that explicit ID.
An explicit scheduler detail takes precedence over a comment; a recognized comment takes precedence over local marker tags.

## Understand automatic deduction

Tower uses these evidence rules in order:

| Evidence | Requirement |
| --- | --- |
| Slurm array or heterogeneous component | Actual member IDs share their scheduler parent |
| Explicit launch marker | Matching marker within the same cluster, owner, account, and working-directory scope |
| Dependency-connected launch | Direct reported dependency links, matching owner, account, and working directory, submission span of at most 60 seconds, and numeric job ID span of at most 256 |
| Launch with at least three jobs | Matching owner, account, working directory, and name family; submission span of at most 30 seconds; each numeric ID gap at most eight; total ID span at most four times the number of gaps; observed script paths cannot conflict |
| Strong two-job launch | Matching nonempty owner, account, working directory, exact command, and name; adjacent numeric IDs; submission span of at most ten seconds |

A numbered name family removes a final numeric suffix preceded by `.`, `_`, or `-`.
For example, `fit-1`, `fit-2`, and `fit-3` share a family.
Submission spans are measured from the first member, so a chain of nearby submissions cannot extend a batch indefinitely.
The wider launch rule tolerates a few other users' jobs between your submissions.
When accounting lacks command fields, the three-job rule can use the remaining evidence; a known conflicting script still prevents that grouping.
Missing owner, account, working directory, or submission evidence prevents ordinary launch deduction.
Array identities and available explicit markers remain usable under their own rules.

An inferred launch is **likely**, not proof that all jobs used the same input or belong to one experiment.
Two independent submissions can satisfy these rules, and a sparse or slow real batch can fail them.
Use a unique explicit marker for reliable project-defined membership.
Use `:jobgroups off` to retain individual rows when a deduction is unsuitable.
Batch and extern steps do not become separate launch members.
A later submit time for a reused job ID identifies a new inferred attempt.

## Keep job actions exact

A closed row retains one real representative ID.
Opening Details, reading logs, and other single-job actions use that ID.
Closing a scheduler list group can move a hidden selected member to the representative.
A data page already opened for an exact job can retain that job while its browser group is closed.
Check the displayed job ID before acting.

Grouping does not select all hidden members for cancellation, export, comparison, or another bulk action.
Open the group and mark the actual jobs that you need.
Mouse range selection follows visible real rows and does not add hidden children.
Existing dependency-chain actions retain their own confirmation and target rules.
Review the target IDs in each confirmation.

## Load older batches

Grouping uses the queue, available account jobs, retained queue departures, and fetched accounting records.
It also uses their available metadata and local job tags.
It does not retrieve an unlimited scheduler archive.

1. Open History.
2. Use `:days 30`, or select the required History date range.
3. Wait for a successful accounting update.
4. Remove filters that exclude the required jobs.
5. Inspect the available groups.

**Expected result:** Eligible old jobs group as their records and evidence become available.
The configured `history_days` value sets the initial accounting window.
Source access, Slurm retention, permissions, and filters can limit the visible records.
Use Sources to check an accounting error or delayed update.
If Slurm rejects the optional accounting metadata fields, Tower falls back to its legacy history fields.
The job history remains available, but missing provenance can reduce automatic grouping.
Existing session recordings remain readable. An older recording without owner, account, command, or marker evidence cannot supply those missing grouping facts.

New queue and accounting publications update grouping without a restart.
A newly fetched record can complete a group that previously had only one known member.
Missing provenance remains unknown. Matching names alone do not establish a shared batch.

## Preserve each job's reports

A launch group is not a replacement for run identity.
Keep one run attempt and one exact `job_id` for each job or array task.
Continue to publish each task's `run.json`, `metrics.jsonl`, `logs.json`, and declared Research reports separately.
No new grouping field is required in these files.
See the [project reporting standard](../PROJECT_STANDARD.md#identity-and-path-rules) for the identity rules.

## Integration methods

The grouping layer reads supplied snapshots. It does not run Slurm commands or read files while it renders a group.

| Method | Purpose |
| --- | --- |
| `job_groups.Registry.ensure(snap)` | Refresh cached evidence from the supplied snapshot and return the current inferred group index |
| `job_groups.frame(app, snap)` | Share one inference check across a display composition, then release that frame scope |
| `job_groups.project_records(app, snap, records, tab, ...)` | Apply the current folds to a list and retain exact real records and representative metadata |
| `job_groups.project_rows(app, rows, snap=None, tab="jobs", ...)` | Apply group presentation to prepared queue rows |
| `job_groups.fold(app, group_id, collapsed=None)` | Change a known group's fold state and reanchor hidden list selection where required |
| `job_groups.status_counts(records)` | Count distinct observed records in disjoint state categories |
| `job_groups.summary_segments(records, ...)` | Return themed status text without changing job identity or marks |
