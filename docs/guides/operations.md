# Activity, diagnostics, completions, and alerts

[README](../../README.md) · [Controls](../CONTROLS.md) · [Feature index](../QUALITY_OF_LIFE.md)

Use this guide to review application results and control notifications.
These procedures do not submit or change scheduler jobs.
An explicit clipboard test sends a test copy request.

<a id="feature-39"></a>

## 39. Search Activity and exported files

### Find a notice

1. Press `Ctrl-A`, or enter `:activity`.
2. Press `/` to edit the notice filter.
3. Enter the required text.
4. Press Enter to finish the filter.
5. Select a notice with Up or Down.
6. Press Enter to expand its text.
7. Press `y` to copy its path or text.
8. Press Esc to return.

**Expected result:** Activity shows notices that match every filter term.
Plain terms match notice text, paths, job identity, and task labels.
Use `level=`, `job=`, or `task=` for field conditions.
These field conditions use case-insensitive text containment.

```text
:activity filter level=error job=123
:activity level warning
:activity job 12345
:activity task copy
:activity filter
```

Press `f` in Activity to clear the filter.
Press `e` to open the export library.
Press `c` to request cancellation of a supported background task.
Use `:task cancel` for the same cancellation request.
Cancellation takes effect at the next bounded operation checkpoint.

Activity retains at most 256 notices during a session.
Notice persistence is disabled by default.
Use `:activity persistent on` to retain the latest 128 notices across restarts.
Use `:activity persistent off` to disable that preference.
Normal state persistence must also be enabled.
Use `:activity clear` to remove retained notices.

A task shows bytes when it reports numerical progress.
Other background readers show a busy state.
Do not interpret a busy state as a measured completion percentage.

### Find an exported file

1. Enter `:exports`.
2. Press `/` to filter its labels or paths.
3. Select a record with Up or Down.
4. Press Enter to read a bounded preview.
5. Press `y` to copy the exact path.
6. Press Esc to return to the export list.

**Expected result:** Tower opens the selected file through the background reader.
A preview reads at most 64 KiB and 256 lines.
A visible notice identifies content outside that preview.
The original file remains available through the copied path.

The export library stores at most 128 path records.
Normal state persistence retains their metadata across restarts.
The library does not store a second copy of each export.
A missing or replaced file produces a preview error.

| Command | Result |
| --- | --- |
| `:exports [show]` | Open the export library |
| `:exports filter TEXT` | Filter labels, paths, jobs, and tasks |
| `:exports preview ID_OR_INDEX` | Open a bounded file preview |
| `:exports copy ID_OR_INDEX` | Copy the exact path |
| `:exports label ID_OR_INDEX NAME` | Set a readable record label |
| `:exports forget ID_OR_INDEX` | Remove one metadata record |
| `:exports clear` | Remove all metadata records |

Indices refer to the current filtered list and start at one.
The `d` key removes the selected record.
Forgetting or clearing metadata does not delete exported files.
File previews require a regular local file.
A symbolic link is not opened as an export preview.

### Troubleshoot Activity and exports

| Symptom | Action |
| --- | --- |
| No notice matches | Press `f` to clear the Activity filter |
| No export matches | Run `:exports filter` to clear the export filter |
| Preview reports a busy reader | Wait for the current background operation to finish |
| Preview reaches its limit | Copy the path with `y` and inspect the original file |
| Notices disappear after restart | Enable `:activity persistent on` and normal state persistence |
| An export path is unavailable | Check that the original file still exists on this machine |

<a id="feature-40"></a>

## 40. Inspect terminal compatibility

### Read capability evidence

1. Enter `:terminaldoctor`.
2. Wait for the background inspection to finish.
3. Use arrows and page keys to read its evidence.
4. Press `t` to open the interactive input test.
5. Press Esc to return.

**Expected result:** Tower reports terminal and path metadata.
The inspection checks output encoding, terminal type, color hints, and clipboard transports.
It also reports relevant SSH and tmux context.
Configuration and state checks inspect path types and access permissions.
The inspection does not create a file or open another SSH connection.

These results are capability evidence.
They do not prove that the local terminal accepted a clipboard request.
They do not automatically verify glyph width, mouse input, or key translation.
Use the interactive test for those observations.
Press `r` in diagnostics to refresh the evidence.

### Test glyphs, colors, keys, and mouse input

1. Enter `:terminaltest`.
2. Compare the block row with its numbered cell row.
3. Inspect the labeled color samples.
4. Press the keys that you want to test.
5. Click or scroll with the mouse.
6. Read the recorded key and mouse events.
7. Press Esc to close the test.

**Expected result:** The test records input without executing page or job actions.
The `q`, `c`, `h`, and other action keys are inert in this test.
Esc is the exit key.
The event list retains the latest 16 observations.

If blocks are misaligned, select a compatible monospace font.
Use a UTF-8 locale for Unicode output.
Use `tower --ascii --no-color` when those capabilities are unavailable.

### Test clipboard transport

1. Close the input test with Esc.
2. Enter `:terminaltest clipboard`.
3. Paste into a suitable local text field.
4. Check for `Slurm Tower clipboard test`.
5. Press Esc to close the input test.

The command requests delivery through the configured clipboard transports.
It can also write the normal private clipboard fallback.
The result notice identifies the requested transport or available fallback.
A sent OSC 52 request does not prove terminal acceptance.

For SSH, check the local terminal's clipboard settings.
For tmux, also check `set-clipboard` and OSC 52 forwarding.
Tower does not change those terminal settings automatically.
See the [runbook](../runbook.md#6-troubleshoot-the-specific-failure) for launch failures.

<a id="feature-48"></a>

## 48. Review the completion inbox

1. Enter `:inbox`.
2. Press `f` to show failed outcomes, or `a` to show all retained completions.
3. Select a record with Up or Down.
4. Press Enter to open that job in History.
5. Press `I` to inspect its files and evidence.

To open logs directly, select a record in the inbox and press `l`.
Use `r` to mark the selected record as reviewed without opening it.
Use `A` to mark the current filtered list as reviewed.
Press `/` to filter names, IDs, states, or partitions.
Press `u` to return to unreviewed records.

**Expected result:** Tower preserves the exact accounting job identity.
Successfully opening History or logs marks that record as reviewed.
A failed open leaves the record unreviewed.

| Command | Result |
| --- | --- |
| `:inbox [unread]` | Show unreviewed completions |
| `:inbox all` | Show retained completions |
| `:inbox failed` | Show terminal outcomes other than `COMPLETED` |
| `:inbox filter TEXT` | Filter the current completion view |
| `:inbox ack JOBID` | Review matching records in the current filtered list |
| `:inbox ack all` | Review every record in the current filtered list |

The inbox retains at most 256 confirmed terminal accounting records.
Unreviewed outcomes appear before reviewed outcomes.
Within those groups, failed outcomes appear before successful outcomes.
Records within each outcome group use the latest completion time first.

Queue disappearance alone does not establish completion.
Records loaded from the accounting window can appear unreviewed at startup.
Review state uses the job ID, timestamps, and terminal state.
It does not identify a retry by job ID alone.

Tower retains at most 512 reviewed record identities.
Normal state persistence saves these identities for the current user, host, and profile.
Switching scope does not acknowledge another scope's records.
Older records can return as unreviewed when the bounded review history expires.

If History cannot expose a record, expand its date window.
Inspect active filters if the record remains hidden.
The inbox does not select another job as a substitute.

### Troubleshoot completion review

| Symptom | Action |
| --- | --- |
| No unreviewed records appear | Use `:inbox all` and inspect the accounting source |
| A record is outside History | Expand the History date window and inspect active filters |
| The job ID identifies an active attempt again | Select the required History record before opening its evidence |
| Historical log paths are unavailable | Select the exact project run and use its declared log index |

An active attempt can reuse a historical job ID.
Tower refuses an ambiguous direct log action instead of opening the active attempt's logs.
Preserve separate project run identities and exact log declarations for reliable attempt inspection.

<a id="feature-49"></a>

## 49. Snooze alerts and set quiet hours

**Prerequisite:** Configure an alert rule.
See the [alert reference](../reference.md#alert-rules) for expressions and delivery actions.

### Snooze a rule

1. Enter `:alerts`.
2. Select a rule with Up or Down.
3. Press `s` to snooze its delivery for thirty minutes.
4. Inspect the active conditions and remaining snooze time.
5. Press `u` to remove that rule's general snooze.
6. Press Esc to return.

Use the palette for a custom duration or one exact job:

```text
:alerts snooze "idle gpu" 900
:alerts snooze "idle gpu" 900 12345
:alerts unsnooze "idle gpu" 12345
:alerts unsnooze "idle gpu"
:alerts unsnooze
```

Durations use seconds.
A duration must be greater than zero and no more than seven days.
An omitted job ID snoozes the complete rule.
An omitted rule in `unsnooze` removes all snoozes.
Tower retains at most 256 active snooze entries.

### Set daily quiet hours

```text
:alerts quiet 22:00 07:00 America/Los_Angeles
:alerts quiet 22:00 07:00
:alerts quiet off
```

Times use the 24-hour `HH:MM` format.
An omitted zone uses `America/Los_Angeles`.
Use an installed IANA time zone when you need another zone.
The start is inclusive and the end is exclusive.
An end earlier than the start defines an interval across midnight.
The start and end must differ.

Press `Q` in alert controls to disable quiet hours.
Normal state persistence saves snoozes and quiet hours for the current user, host, and profile.
The active configured time zone controls daylight-saving transitions.

**Expected result:** Quiet hours and snoozes suppress bell, notification, and command delivery.
Tower continues to evaluate conditions and record alert events.
Active conditions remain visible.
Suppressed deliveries are not queued for replay when the quiet period ends.
The existing rule interval still controls future delivery.

## Module methods

These methods integrate the procedures with the existing controller and worker.

| Method | Function |
| --- | --- |
| `Activity.post(text, level, path, job, task)` | Register a bounded notice and export metadata when a path is supplied |
| `Activity.start(label, source)` | Register a cancellable background task |
| `Activity.progress(task, done, total)` | Publish reported task progress |
| `Activity.finish(task, status)` | Publish the final task state |
| `activity_ui.export_items(app)` | Return the current filtered export records |
| `doctor.terminal_evidence(cfg, state_dir=...)` | Read terminal hints and path metadata |
| `session_tools.observe(app, snapshot)` | Register confirmed accounting completions |
| `session_tools.inbox_items(app)` | Return completion records in the active filter |
| `session_tools.unread_count(app)` | Count retained unreviewed records |
| `AlertEngine.snooze(rule, seconds, job)` | Suppress selected alert delivery temporarily |
| `AlertEngine.unsnooze(rule, job)` | Remove snooze controls |
| `AlertEngine.set_quiet(start, end, zone)` | Validate and store a daily quiet interval |
| `AlertEngine.notification_muted(rule, job, now)` | Check active delivery suppression |
| `AlertEngine.controls_snapshot()` | Export bounded alert preferences |
| `AlertEngine.restore_controls(data)` | Validate restored preferences |

`activity_ui` and `session_tools` also expose initialization, restore, save,
command dispatch, key handling, and overlay rendering methods.
Their display paths use retained data.
Their file previews and inspections use the shared background worker.
