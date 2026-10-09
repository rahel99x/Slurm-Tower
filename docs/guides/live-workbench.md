# Live terminal workbench

[README](../../README.md) · [Controls](../CONTROLS.md) · [Project standard](../PROJECT_STANDARD.md)

Use this guide for Tower 4.3's toolbar, inline job inspection, and update-rate control.
All controls run inside the terminal.
Use the current job ID and source path to check the identity of displayed evidence.

## Connect a project to its jobs

Use the [project reporting standard](../PROJECT_STANDARD.md) when you create a new project.
It defines the directory layout, job identity, and source location for every Research workspace.
Use the [copyable reporter](../../examples/project-template/README.md) to write compatible inventories and measurements.

Automatic attachment uses the selected job's cached scheduler WorkDir.
Set that directory to the project root or a directory beneath `PROJECT/runs/<run_id>/`.
Register a root with `:project PROJECT` when the scheduler cannot supply that path.
Tower performs this bounded project discovery locally.
For SSH viewing, run Tower on the scheduler host to use the project picker and automatic attachment.

1. Create one directory at `runs/<run_id>/` for each execution attempt.
2. Write `run.json` with the run ID and actual scheduler job ID.
3. Append application measurements to `metrics.jsonl`.
4. Register required log files in `logs.json`.
5. Write final results to `summary.json`.
6. Declare any additional Research reports in that run's source paths.
7. Start Tower in the environment that owns the project files.
8. Open the project with `:project /absolute/project/path`.
9. Select the job in Jobs, Recents, or History.
10. Open Research and select the required workspace.

**Expected result:** An unambiguous exact job ID links the attempt's reports to the selected job.
The source paths identify that execution attempt.
Changing jobs updates the attachment without restarting Tower.

Use the same steps on CARC and native Fedora.
For CARC, start Tower on the login node where the project paths are available.
For native Fedora, select the desktop profile.
An absolute path identifies a file on the machine that owns the scheduler connection.

The twelve source routes cover Experiment, Arrays, Evidence, Artifacts, Passport, Submit,
Resources, Forecast, Blockers, Tradeoffs, Scaling, and Workflow.
Resources uses the `predict` command-line identifier.
The [per-view source table](../PROJECT_STANDARD.md#files-for-every-research-view) gives every exact location and required field.
See the [Research guide](../RESEARCH.md) for measurements, provenance, contracts, and submission preparation.
See the [planning guide](../WAVE_TWO.md) for evidence requirements and interpretation limits.

Keep measurements factual.
An unavailable report remains unavailable.
Resource utilization does not establish an application's scientific result.

### Publish reports while the job runs

Use one metrics stream per execution attempt.
Append only complete JSONL records.
Publish replacement JSON reports atomically after the complete file is ready.
The copied reporter can publish and declare a native per-view source:

```bash
python3 reporting.py report workflow .tower/definitions/workflow.json --run runs/my-run
```

Run that command from the copied project's root.
Replace the view, source file, and run directory with the actual values.
The reporter validates the source and records the destination in the run inventory.
See [Report publication](../PROJECT_STANDARD.md#publish-a-per-view-source-without-a-tower-dependency) for all supported views.

Tower rechecks inventories and bound source files in its background worker.
The normal Research interval is five seconds before a fetching multiplier is applied.
Late-created metrics, log indexes, contracts, planning reports, and verified passports can appear during the session.
Atomic replacements update subsequent reads.
The reader keeps the current page and selection under your control.
It does not run project code, generate an aggregate, or finalize an application's outcome.

### Resolve an attachment conflict

An array task ID matches only that task.
For example, `12345_7` does not match `12345` or `12345_8`.
Multiple attempts with one requeued job ID require explicit selection.
Invalid inventories or capped discovery coverage prevent a guessed attachment.

1. Open `:runs`.
2. Inspect the inventory notices with `!`.
3. Select the correct attempt, or use `:run select RUN_ID`.
4. Check the job ID and source paths before reading its reports.

**Expected result:** Your selected attempt remains attached until you select a different job.
Clicking a run row also binds that exact attempt.
Use `:run clear` to restore the earlier report settings.
The `:metrics` and `:artifacts` commands also leave the run binding.
These actions suppress automatic attachment for the current job until the job selection changes.
See [Automatic attachment](../PROJECT_STANDARD.md#automatic-attachment-and-runtime-updates) for discovery and path limits.

A captured Submit report is read-only evidence.
Viewing it does not prepare or submit a scheduler job.
Use the existing submission procedure and review when you want to run a script.

## Inspect a job inside Jobs

Select an active job or a job in Recents.
The Details panel provides seven buttons:

| Button | Purpose |
| --- | --- |
| Inspector | Inspect job identity, requests, resources, steps, paths, and source status |
| Logs | Read the exact job's available log sources |
| Investigate | Inspect bounded failure evidence and its source coverage |
| Research | Inspect all twelve project and planning workspaces inside Jobs |
| Analytics | Inspect Job series, History, Timeline, Advisor, and Compare inside Jobs |
| Quick Advisor | Request a summary of allocation and measured resource behaviour for the exact job |
| Off | Hide inspection content |

The selected job ID remains the evidence target.
Selecting another job updates the panel for that job.
Off retains the button row so that you can restore an inspection mode.

### Use the buttons

1. Click a Details button.
2. Use arrow keys to focus a nearby visible control.
3. Press Enter or Space to activate that control.
4. Click the content area to restore content navigation.
5. Use Up, Down, or page keys to scroll the content.
6. Press Esc to return keyboard input to the job rows.

**Expected result:** The selected inspection stays inside Jobs.
The active or recent job remains the target.
Mouse clicks use the same visible-control graph as F8 navigation.
Its arrows change focus without activating the destination.
Press Esc or F8 to leave graph focus before using native panel keys.

Use `:jobpanel focus` to reach the buttons without a mouse.
In native panel focus, arrows select and activate the previous or next Details mode.
Home selects Inspector; End selects Off.
Enter or Tab moves from the mode buttons to content.
Research and Analytics include a subview-button stop before content.
In that stop, arrows select a subview; Home and End select its first or last choice.
Enter or Tab returns from content to the mode buttons.
Use `:jobpanel inspector`, `:jobpanel logs`, `:jobpanel investigate`, or `:jobpanel off` to select a mode directly.
Use `:jobpanel research VIEW` or `:jobpanel analytics VIEW` to select an inline workspace directly.
Use `:jobpanel quick` to request Quick Advisor.
Restoring that saved mode leaves it idle until you select Analyze this job.
The inspection mode persists when normal state is enabled.
Button focus and the panel's selected log file last for the current session.

### Read multiple log sources

1. Select Logs in Details.
2. Click log content, or use native panel focus and press Enter.
3. Use Left or Right to select a source.
4. Use Up, Down, or page keys to scroll the retained content.
5. Press End to follow newly appended lines.

**Expected result:** The source path identifies the exact selected file.
The source buttons show the selected file and nearby choices.
Left and Right can traverse every available file.
Home reaches the oldest retained line; it does not load the complete file.
Clicking a source button selects that file.
Click the log content or leave graph focus before using its native scroll keys.
Inline Logs retains a bounded tail of up to 256 KiB per loaded file.

Use `l` after returning focus to the job rows to open the full Logs page.
That page provides complete-file search, copying, older pages, bookmarks, and the grouped file picker.
See [Log search](log-search.md) and [Log display](log-view.md) for those operations.

### Interpret inspection evidence

Inspector shows Overview, Resources, Steps, Files, and Evidence from the current snapshots.
The structured inspector opened with `I` provides clickable section buttons.
Use `:inspect section SECTION` in an open structured inspector for the equivalent command.
In inline Inspector, click StdOut or StdErr to open that exact log source.
Its log-browser link opens the complete source catalog.
Its Evidence link opens Research Evidence inside Details.
Investigate shows bounded multi-file findings, hypotheses, and inspected-source coverage.
Click a cited log path to open its exact source on the full Logs page.
A hypothesis is an explanation supported by cited evidence, not proof of the application's cause.
Readers update in the background as job records and files change.

The wide Jobs layout places Details beside the tables.
Narrow terminals stack the panels.
Use `Ctrl-W` or F6 for panel focus and `z` to maximize the focused panel.
Off suppresses selected-job content and starts no new log or evidence reads.
Drag the divider to change the panel sizes.
Use its keyboard focus when mouse drag reports are unavailable.
The horizontal divider above Recents controls how much matching history is visible.
See [Adjustable workspaces and job advice](adaptive-workspaces.md) for divider, Recents, grouping, docking, and Quick Advisor procedures.

### Inspect Research and Analytics without changing pages

1. Select an active or recent job in Jobs.
2. Click Research or Analytics in Details.
3. Click the required subview button.
4. Move the pointer into the content and use the wheel to scroll.
5. Use arrow or page keys when the content has keyboard focus.
6. Select another subview to inspect its reports.
7. Select Off to hide inline content.

**Expected result:** The selected job remains visible beside its reports.
The view fits the Details width without horizontal panning.
Long content scrolls vertically beneath the button rows.
Each subview retains its own vertical position.
Each rendered inline document remains bounded to 2,048 source rows and 2,048 fitted display rows.
Metric dashboards rasterize visible cards as you scroll.

| Group | Inline subviews |
| --- | --- |
| Research | Experiment, Arrays, Evidence, Artifacts, Passport, Submit, Resources, Forecast, Blockers, Tradeoffs, Scaling, Workflow |
| Analytics | Job series, History, Timeline, Advisor, Compare |

Use `predict` as the Resources command identifier.
Use `job` as the Job series command identifier.
For example, `:jobpanel research workflow` opens Workflow inside Details.
Use `:jobpanel analytics job` for the selected job's recorded series.

Research uses the exact selected job and its bound project reports.
Job series keeps that exact job ID even when no recorded samples are available.
Compare includes the selected job and the available explicit comparison or marked jobs.
History, Timeline, and Advisor keep their accounting-window context.
Check the selected-job header and the reported window when reading aggregate Analytics results.

The full Research and Analytics pages keep their own selections and view preferences.
Opening an inline view does not replace those pages' positions.
Click an explicit chart or cited-source control when you need its detailed inspection.
Click a Chart Events or Timeline row to open the exact displayed job or log citation.
Use `:timeline open EVENT_NUMBER` for a numbered current timeline event.
Use the opened dialog's Back or Esc control to return.
Research reports remain evidence; a captured Submit report does not submit a job.
Click a declared output row to expand its directory or open its bounded preview.
In a CSV preview, click a column button to focus it, then press Enter to cycle its sort direction.
Use `:artifact column NAME_OR_NUMBER` for column focus by command.

### Mark a job range with the mouse

1. Press the left mouse button on a visible job row.
2. Keep the button pressed and drag through the required rows.
3. Release the button to complete the marked range.
4. Press `c` to open cancellation review when cancellation is the required action.
5. Inspect every target ID and confirm only the intended jobs.

**Expected result:** The marked range follows the table's current visible order.
Hold Shift during the drag to retain existing marks and add the new range.
Press Esc before release to cancel capture and restore the earlier marks.
A simple click retains ordinary row selection.
Marking jobs does not change their scheduler state.
Supported actions retain their existing review and confirmation.
See [Mouse and button navigation](pointer-navigation.md) for mouse support and directional focus.

## Set the update rate

The top-right update control requests a rate from 1x to 50x.
At 1x, Tower uses the configured source intervals.
Higher values request more frequent updates.
The multiplier applies to fetching; it does not change recorded timestamps or metric values.

1. Click the slider track to choose a rate.
2. Keep the left mouse button pressed and drag horizontally to adjust the rate.
3. Click `[-]` or `[+]` to change the multiplier by one.
4. Use the mouse wheel over the control for one-step changes.
5. Click the multiplier label to focus keyboard controls.
6. Use arrows or `-` / `+` to adjust the multiplier.
7. Press Home for 1x or End for 50x.
8. Press Esc to return input to the current page.

**Expected result:** The multiplier label and effective source cadences update during the session.
View → Focus update-rate slider provides keyboard entry.
Enter or Tab also releases slider focus.
Release the mouse button to finish dragging.
The pointer position stays bounded to the 1x–50x track.
Use a track click or `:rate N` if the terminal cannot report drag events.

| Command | Function |
| --- | --- |
| `:rate` | Show the requested multiplier and effective Jobs interval |
| `:rate N` | Request a whole-number multiplier from 1 to 50 |
| `:rate reset` | Restore 1x |

For example, `:rate 5` requests a Jobs interval of two seconds from a ten-second base interval.
The same multiplier applies to scheduler sources, plugin sources, and supported file readers.
Tower keeps each base interval unchanged, so repeated adjustments do not compound.

### Read the limits

| Source | Minimum effective interval when speeding up |
| --- | --- |
| Ordinary Slurm and plugin sources | 0.5 seconds |
| GPU sampling inside an allocation | 5 seconds |
| Queue forecast probes and allocation-budget reads | 30 seconds |
| Local file readers | 0.25 seconds |
| Remote file readers | 1.5 seconds |

An explicitly configured base interval below a minimum keeps its existing faster interval.
At 1x, every source retains its configured base interval.
Source errors retain their existing retry backoff.
A higher multiplier does not start overlapping reads or increase the worker count.
Disabled sources remain disabled.

Sources shows effective fetching intervals.
Use that page to verify the actual cadence.
The requested multiplier can exceed the speed permitted by a source's minimum interval.
The preference persists with normal UI state and follows the selected state namespace.
Use the top-level `polling_multiplier` configuration field to set a launch default.
A valid saved multiplier overrides that default.
Use `tower --rate N` to override the saved multiplier at launch.
Use `:rate reset` to restore 1x in the active session.

## Use the terminal toolbar

The first display row contains File, Edit, View, Help, a copy-destination switch, and a quit control.
Use the menus for file workflows, preferences, navigation, and diagnostics.
Job-changing actions retain their existing review and confirmation.

### Open and traverse a menu

1. Click a menu label or press F10.
2. Use Left or Right to select another menu.
3. Use Up, Down, or page keys to select a choice.
4. Press Enter or Space to activate the selected choice.
5. Press Esc to close the menu without activating a choice.

**Expected result:** Opening a menu preserves the underlying screen.
Browsing menu choices does not execute an action.
A choice ending in `...` opens an editable command prompt.
Dismiss the dropdown, then complete the command's arguments before running it.

Tab and Shift-Tab change menus while a menu is open.
Home and End select the first or last choice.
The letters `f`, `e`, `v`, and `h` choose File, Edit, View, and Help while a menu is open.
F10 also closes an open menu.
Use `:menu File`, `:menu Edit`, `:menu View`, or `:menu Help` for command entry.
Use `:menu` to open File.

Unavailable choices appear dimmed.
Their activation reports the required job, project, file, or page context.
Close an unfinished job-action review before starting another reviewed action.
The toolbar remains above overlays.
On narrow terminals, it abbreviates menu labels and compresses the slider to its multiplier.
F10 keeps all four menus accessible.
Move the pointer over a menu choice to highlight it without activating it.
Direct choices leave the dropdown open while the pointer remains inside it.
This permits several setting changes without reopening the menu.
Move the pointer outside the dropdown to dismiss it.
Prompts and reviews remain beneath the dropdown while it keeps keyboard focus.
Dismiss the menu before using those dialogs' editing or review controls.
About replaces the dropdown with its own panel.
Focus update-rate slider leaves the menu and focuses the slider.

Click the top-left `x`, or choose File → Quit Tower, to exit.
Esc closes a menu; it does not exit Tower.
Click **Copy** to switch text delivery to **Yank**, or click **Yank** to restore clipboard copying.
Narrow terminals use `C` and `Y` for the same switch.
Yank targets a running local Vim or Neovim server; unavailable delivery retains the export and uses clipboard fallback.
See [Pane navigation](pane-navigation.md#send-text-to-vim-or-neovim) for server discovery and complete-payload limits.

### File menu

| Choice | Result or editable command |
| --- | --- |
| Open project... | Enter a project path with `project PATH` |
| Project runs and attempts | Open the selected project's run inventory |
| Run output artifacts | Browse declared artifacts for the selected run |
| Attach metrics stream... | Enter `metrics FILE` |
| Attach output contract... | Enter `artifacts CONTRACT ROOT` |
| Review batch script... | Enter `preflight SCRIPT [--workdir DIR]` |
| Capture run passport... | Complete `passport capture SCRIPT` and required path options |
| Export current page as text | Export the current page's text |
| Export current table as CSV | Export the current table |
| Export selected jobs as JSON | Export selected or marked jobs and their recorded series |
| Export complete terminal report | Start a background ASCII report export |
| Export library | Browse available exports |
| Execution receipts... | Complete an `execution` command to inspect or recover a receipt |
| Switch connection profile... | Enter `profile NAME` |
| Quit Tower | Exit the application |

The project inventory requires an open project.
Run artifacts require a selected project run.
Preparation and passport capture retain their existing file and path validation.
See [Research](../RESEARCH.md) and [execution recovery](../WORKBENCH.md#execute-a-reviewed-workflow-or-scaling-experiment) for those commands.

### Edit menu

| Choice | Result or editable command |
| --- | --- |
| Copy current selection | Copy the current text selection |
| Switch to Vim/Neovim yanking / Switch to clipboard copying | Change the destination for text and complete-log copies |
| Copy entire log / current page | Copy the complete selected log file, or the current page outside Logs |
| Start line selection | Start selection at the current cursor |
| Select entire log / current page | Mark the complete original log source, or select the currently painted pane elsewhere |
| Clear line selection | Clear the active text selection |
| Filter this page... | Enter `filter TEXT` |
| Clear this page's filter | Remove its text filter |
| Structured table filters | Open the field filter editor in Jobs or History |
| Choose table columns | Open the column editor in Jobs or History |
| Cascading sort editor | Open the sort editor in Jobs or History |
| Bookmark current log line | Bookmark the current line in an open Logs file |
| Pin / unpin selected jobs | Change pin status for the selected or marked jobs |
| Tag selected jobs... | Complete `tag` with tags and optional job IDs |
| Annotate selected job... | Complete `note` with a note and optional job ID |
| Save current location... | Enter `location save NAME` |
| Saved locations | Browse saved destinations |
| Terminal and sampler settings | Open the draft settings editor |
| Edit and test keybindings | Open keybinding editing and testing |

The log-specific choices require an open file on the full Logs page.
Table choices in this menu require Jobs or History.
The underlying table commands also support their documented explicit table identifiers.
See [Tables](tables.md), [Log display](log-view.md), and [Navigation](navigation.md) for complete procedures.

### View menu

| Choice | Result |
| --- | --- |
| Each of the ten page names | Open that page |
| Research: each workspace name | Open one of the twelve Research workspaces |
| Search Research workspaces | Open the searchable workspace picker |
| Jump to job, run, file, or view | Open universal jump search |
| Back to previous location | Restore the previous destination |
| Forward to next location | Restore the next destination after Back |
| Comfortable panel density | Select the comfortable panel layout |
| Compact panel density | Select the compact layout |
| Focused panel density | Select the focused layout |
| Focus job / main panel | Focus Main |
| Focus Details panel | Focus Details |
| Maximize / restore focused panel | Toggle the focused panel's maximized layout |
| Saved workspace layouts | List saved layouts |
| Pause inspection / Resume inspection | Freeze or resume the inspected snapshot; sampling continues |
| Pause / follow current log | Change follow mode on the full Logs page |
| Wrap / unwrap current log | Change wrapping on the full Logs page |
| Refresh all sources now | Request an immediate source refresh |
| Focus update-rate slider | Focus the multiplier's keyboard controls |
| Reset update rate to 1x | Restore the configured base fetching intervals |
| Navigate buttons with arrow keys (F8) | Focus visible buttons and links for directional navigation |
| Enable / Disable smooth scrolling | Toggle mouse-wheel viewport smoothing |
| Enable / Disable startup animation | Toggle the interactive welcome display |
| Preview startup animation | Preview the welcome without changing its saved preference |
| Plain ASCII reader mode | Select the reader theme |
| Theme: each available theme | Select that theme |

The page and workspace names match the [page table](../../README.md#5-select-a-page).
The theme choices are default, dark, light, terminal, mono, high, and cb.
Reader provides plain ASCII text and static notices.
Reader also uses immediate scrolling and skips the welcome.
Refreshing or speeding up fetching does not enable disabled sources.
See [Mouse and button navigation](pointer-navigation.md) for focus, startup, and scrolling preferences.

### Help menu

| Choice | Result |
| --- | --- |
| Page controls and searchable help | Open contextual help |
| Search all commands | Open command discovery |
| Terminal diagnostics | Inspect terminal and path evidence |
| Test keys, mouse, and glyphs | Open the terminal input and glyph test |
| Source health and freshness | Open Sources |
| Activity and background tasks | Open Activity |
| Completed-job review inbox | Open the completion inbox, including reviewed items |
| Alert and quiet-hour controls | Open alert preferences |
| About Tower and update controls | Show the version and toolbar operating instructions |

Use `:about` to open the About panel directly.
Esc, Enter, or `q` closes that panel and restores the underlying screen.

## Check runtime updates

Use Sources to check sampler freshness, errors, and retry backoff.
Use Activity to check background results and file errors.
Account for accounting delay when a job leaves the active queue.
Queue absence alone does not establish completion or failure.

Update controls keep source timeouts, worker limits, and source identity checks.
Readers publish bounded snapshots for the terminal display.
An error must remain visible rather than producing an invented result.
