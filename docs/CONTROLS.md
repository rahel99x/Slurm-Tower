# Tower controls

Press Ctrl-C to exit an interactive session. A configured Ctrl-C binding takes precedence.
The terminal test and keybinding tester record this key without exiting.
Press Esc to leave either test.

[README](../README.md) · [Feature guides](QUALITY_OF_LIFE.md) · [Reference](reference.md)

This guide lists launch methods, default keys, mouse actions, and command families.
Use `?` inside Tower for contextual help.
Use the feature guides for complete procedures and operating limits.

## Control notation

A leading `:` means: open the command palette, then type the command.
Do not type the leading `:` after the palette opens.
`JOBID`, `FILE`, `DIR`, `NAME`, and `VALUE` are values that you supply.
Square brackets in command syntax identify optional arguments.
They are not characters to type unless the guide explicitly describes a key.
`A` and `a` identify different keys.

An overlay uses its own controls while it is open.
Its visible instructions take priority over page shortcuts.
Use `Esc` to return from an overlay.
Key bindings in configuration can replace the defaults below.

## Launch methods

| Method | Command | Purpose |
| --- | --- | --- |
| Checkout launcher | `./scripts/tower` | Use the checkout's virtual environment when available |
| Python module | `python3 -m tower` | Run directly from the checkout |
| Bash alias | `tower` | Use the launcher installed with `scripts/install_shell.py` |
| Installed entry point | `tower` | Use the Python package installed in the active environment |
| Demonstration | `tower --fake` | Run the simulated scheduler |
| One frame | `tower --once --tab history` | Print a page and exit |
| Updating text screen | `tower --watch` | Refresh an ANSI screen; Ctrl-C exits |
| Scripted command | `tower run COMMAND ARGUMENTS` | Execute one palette command |

Run `type tower` to identify which shell command will run.
Use the [runbook](runbook.md#use-one-tower-shell-command) to install or inspect the managed alias.

### Select a local setup profile

| Command | Function |
| --- | --- |
| `python3 scripts/setup.py --mode local` | Set up the default CARC profile |
| `python3 scripts/setup.py --mode local --profile desktop` | Set up local desktop Slurm settings |
| `python3 scripts/install_shell.py --profile desktop` | Preview the desktop alias |
| `python3 scripts/install_shell.py --profile desktop --apply` | Back up `.bashrc` and install the desktop alias |

Source the updated `.bashrc` to load the alias.
Use `tower --version`, `tower --doctor`, and `tower --once --tab sources` to inspect the installation.
Use the [Fedora desktop guide](DESKTOP.md) when Slurm is installed directly on your desktop.
Use the [runbook](runbook.md#3-adapt-setup-to-your-environment) for other setup modes.

## Global navigation keys

| Key | Function |
| --- | --- |
| `Tab`, `]` | Open the next page |
| `Shift-Tab`, `[` | Open the previous page |
| Up, `k` | Move one row or line up |
| Down, `j` | Move one row or line down |
| Page Up, Page Down | Move by the current view's page size |
| Home, `g` | Move to the beginning |
| End, `G` | Move to the end |
| Left, `,`; Right, `.` | Change subviews in Analytics, Nodes, and Research |
| `Ctrl-W`, F6 | Focus Main or Details |
| `z` | Maximize the focused panel outside Logs |
| `Ctrl-B`, Alt-Left | Restore the previous location |
| Alt-Right | Restore the next location after Back |
| `Ctrl-G` | Open universal jump search |
| `Ctrl-P` | Open the Research workspace picker |
| `Ctrl-A` | Open Activity |
| F10 | Open or close the terminal toolbar menu |
| `:` | Open the command palette |
| `/` | Filter the current list or search the current log |
| `?` | Open contextual searchable help |
| `Esc` | Close an overlay, end a selection, or clear the current filter or marks |
| `q` | Exit Tower |

Use `:maximize` for the panel layout action on Logs.
The [navigation guide](guides/navigation.md) describes Forward, saved locations, jump search, settings, and command editing.

## Page shortcuts

| Key | Page | Command identifier |
| --- | --- | --- |
| `1` | Jobs | `jobs` |
| `2` | Cluster | `cluster` |
| `3` | History | `history` |
| `4` | Nodes | `nodes` |
| `5` | Logs | `log` |
| `6` | Sources | `sources` |
| `7` | Analytics | `analytics` |
| `8` | Group | `group` |
| `9` | Dependencies | `deps` |
| `0` | Research | `research` |

Use `:tab IDENTIFIER` to open a page by command.
Use `:workspace NAME` to open a Research workspace.
Use `:view NAME` to select an Analytics or Research subview.

## Terminal toolbar and update slider

The first display row contains `x`, File, Edit, View, Help, and the update-rate control.
The toolbar remains available above pages and overlays.
Menu actions use the same commands and reviews as their keyboard equivalents.

| Control | Function |
| --- | --- |
| Click a menu label, F10, or `:menu [File\|Edit\|View\|Help]` | Open a menu |
| Left / Right, Tab / Shift-Tab in a menu | Select the previous or next menu |
| `f`, `e`, `v`, `h` in a menu | Select File, Edit, View, or Help |
| Up / Down, page keys, Home / End in a menu | Select a menu choice |
| Enter / Space, or click a menu choice | Activate the choice |
| Esc, `q`, F10, or click outside the menu | Dismiss the menu |
| Click `x` | Exit Tower |
| Click or drag the update track | Choose a requested multiplier from 1x to 50x |
| Click `[-]` / `[+]`, or use the wheel over the update control | Decrease or increase the multiplier by one |
| Click the multiplier, or View → Focus update-rate slider | Focus slider keyboard controls |
| Arrows, `-` / `+` with slider focus | Adjust the multiplier by one |
| Home / End with slider focus | Select 1x or 50x |
| Esc / Enter / Tab with slider focus | Return input to the page |
| `:rate [N\|reset]` | Inspect the multiplier, set 1–50, or restore 1x |
| `:about` | Open version and toolbar instructions |

A menu choice ending in `...` opens an editable command prompt.
Unavailable choices report their required context.
Clicking outside a menu dismisses it without activating the underlying page.
See [Live workbench](guides/live-workbench.md#use-the-terminal-toolbar) for every menu choice.
See [Update rate](guides/live-workbench.md#set-the-update-rate) for source limits and saved preferences.

## Navigation, settings, and input

| Command | Function |
| --- | --- |
| `:jump [QUERY]` | Search cached jobs, runs, logs, views, workspaces, and commands |
| `:forward` | Restore the next location after Back |
| `:location [list]` | Browse saved destinations |
| `:location save NAME` | Save the current destination |
| `:location open NAME` | Open a saved destination |
| `:location delete NAME` | Remove a saved destination |
| `:settings [reset]` | Open settings or preview defaults |
| `:keybindings [reset]` | Open key bindings or preview defaults |
| `:explain [TABLE] COLUMN` | Inspect a field's units, meaning, scope, and unavailable state |
| `:peek [TABLE] COLUMN` | Inspect an unclipped underlying field value |

In settings, Up/Down selects a setting.
Left/Right changes its value.
Space changes a Boolean value.
Use `D` to preview defaults.
Enter applies the draft.
Esc cancels the draft.

In key bindings, `e` or Enter edits the selected action.
Use `t` to test a key.
Use `a` to apply the draft.
Use `D` to preview defaults.
Esc cancels the draft.

In Peek, `y` copies the complete underlying value.
Explain and Peek use the focused header when one is available.
Otherwise, the default field is `name`.
See [Navigation](guides/navigation.md) for supported fields and exact value semantics.

### Command palette editing

| Key | Function |
| --- | --- |
| Left / Right | Move the input cursor |
| Home / End, Ctrl-A / Ctrl-E | Move to the input start or end |
| Ctrl-Left / Ctrl-Right, Alt-B / Alt-F | Move by words |
| Backspace / Delete | Remove a character |
| Ctrl-W, Alt-Backspace | Remove the previous word |
| Alt-D | Remove the next word |
| Ctrl-U / Ctrl-K | Remove input before or after the cursor |
| Alt-U / Ctrl-Z | Undo an input change |
| Alt-R / Ctrl-Y | Redo an input change |
| Up / Down | Select a suggestion |
| Tab | Insert a completion |
| Page Up / Page Down | Recall command history |
| Enter | Run the edited command |
| Esc | Cancel input |

Bracketed paste inserts editable input.
It does not execute pasted commands automatically.
Input is limited to 4096 characters.
See [Navigation](guides/navigation.md#feature-35) for multiline input and quoting.

## Job controls

| Key | Function |
| --- | --- |
| `Space` | Mark or unmark the selected job |
| `a` | Mark all visible jobs |
| `u` | Clear job marks |
| `p` | Pin or unpin selected or marked jobs |
| `Enter`, `d` | Open the selected job's details |
| `i` | Open scheduler details and steps |
| `I` | Open the structured job inspector |
| `l` | Open the exact selected job's logs |
| `A` | Start a clone-and-resubmit command |
| `c` | Review cancellation |
| `h` | Review hold or release |
| `R` | Review requeue |
| `t` | Review priority within your pending jobs |
| `s` | Resume the current page's legacy single-column sort |
| `S` | Reverse the legacy sort |
| `=` / `_` | Increase or decrease the accounting and Analytics day window |

Marked jobs are the target of supported group actions.
When no jobs are marked, the selected job is the target.
Inspect the complete target list in the action review.
Use Tab to choose Cancel or Confirm.
Press Enter to activate the selected review control.
For ordinary action reviews, `y` confirms and `n` or `Esc` cancels.

Click column headings for cascading sorts.
Use `:sortby [TABLE] COLUMN [asc|desc|off]` for the equivalent command.
Use `:sortby [TABLE] clear` to remove every rule in that table.
See [Tables](guides/tables.md) for sort editing, column controls, filters, marks, and drill-down.

### Jobs Details buttons

Jobs provides Inspector, Logs, Investigate, and Off buttons in Details.
The buttons inspect the selected active or recent job without leaving Jobs.

| Control | Function |
| --- | --- |
| Click a Details button | Select its mode and focus the button row |
| Arrow keys with button focus | Select and activate the previous or next button |
| Home / End with button focus | Select Inspector or Off |
| Enter / Tab with button or content focus | Toggle focus between buttons and content |
| Up / Down, page keys with content focus | Scroll inspection content or retained log lines |
| Left / Right with Logs content focus | Select the previous or next exact log file |
| Home / End with Logs content focus | Reach the oldest retained line or follow the tail |
| Click a log source button | Read that file and focus log content |
| Esc | Return input to the job rows |
| `:jobpanel [inspector\|logs\|investigate\|off\|focus]` | Select a mode or focus the buttons without a mouse |

Use the full Logs page for complete-file search and copying.
Off hides inspection content and starts no new log or evidence reads.
See [Live workbench](guides/live-workbench.md#inspect-a-job-inside-jobs) for procedures and layout behavior.

## Table inspection

Use a table identifier when you need a table other than the current one.
Identifiers include `jobs`, `recent`, `history`, `group`, `nodes`, `sources`, and `cluster`.

| Command | Function |
| --- | --- |
| `:sorteditor [TABLE]` | Open sort priority editing |
| `:headers [TABLE]` | Open keyboard header controls |
| `:columns [TABLE]` | Open column order, width, and visibility controls |
| `:columns [TABLE] order KEYS` | Set column order |
| `:columns [TABLE] width KEY WIDTH` | Set a width from two to one hundred twenty characters, or `auto` |
| `:columns [TABLE] show\|hide KEYS` | Change optional column visibility |
| `:columns [TABLE] reset` | Restore default column preferences |
| `:where [TABLE] CONDITION...` | Apply numeric resource conditions |
| `:where [TABLE] clear` | Clear numeric conditions |
| `:filters [TABLE]` | Open the interactive field filter builder |
| `:viewpicker [TABLE]` | Preview and select a saved table view |
| `:historyrange today\|yesterday\|week\|all` | Select a named History date interval |
| `:historyrange START END` | Select inclusive local calendar dates |
| `:recents 5\|10\|25\|auto` | Select the Recents size |
| `:recents expand\|collapse` | Change the Recents presentation |
| `:recents window DURATION\|all` | Select the completion time window |
| `:marked [all\|hidden\|visible\|active\|finished]` | Inspect a subset of marked jobs |
| `:freeze [on\|off]` | Hold or resume the inspection view |
| `:jobactions [JOBID]` | Open actions for the exact job |
| `:node NODE_NAME` | Open cached node details |
| `:drill partition NAME` | Inspect jobs in a partition |
| `:drill user NAME` | Inspect an account user's jobs |

Numeric conditions combine with AND.
For example, `:where jobs cpus>=8 memory>16GiB cpu_eff<30%` requires every condition to match.
Use the [table guide](guides/tables.md) for supported fields, units, and unknown values.

In the sort editor, Up/Down selects a rule.
Left/Right changes its priority.
Space changes its direction.
Use `d` to remove a rule.
Use `a` to add a rule.

In header controls, Enter or Space cycles ascending, descending, and off.
Left selects ascending order.
Right selects descending order.

In column controls, Left/Right changes column order.
Use `+` and `-` to change width.
Use `a` for automatic width.
Use `r` to reset column order, widths, and visibility.
Space changes optional visibility.
Enter closes the overlay.

In the filter builder, Enter edits a field.
An empty field removes its condition.
Use `c` to clear conditions.
Use Ctrl-U to clear the current edit.
Click a filter chip to remove its condition.

In saved views, Enter loads the selected view.
Use `d` to delete a view.
In marked jobs, `s` changes the subset, `d` removes one mark, and `c` clears the displayed subset.
Enter opens details.
Use `l` to open the selected marked job's exact logs.

## Log controls

| Key | Function |
| --- | --- |
| `O` | Open the grouped file list |
| Up, Down, page keys | Select a file or move the logical line cursor |
| `Enter` | Open the selected file |
| `Esc` | Return to the file list, then close it |
| `o` | Cycle the registered files |
| `e` | Select stdout or stderr |
| `f` | Change following state |
| End | Follow the end unless extending a selection |
| `w` | Change line wrapping |
| `L` | Open the current log in `less` |
| `/` | Search retained content |
| `N` / `P` | Move to the next or previous retained-content match |
| `v` | Start selecting original log lines at the cursor |
| `V` | Select the entire file |
| `y` | Copy the original selection |
| `Y` | Copy the entire exact selected source |
| `m` | Add a basic bookmark at the cursor |
| `'` | Visit the next basic bookmark |
| `+` / `-` | Increase or decrease the inline job log preview |

Shift-click or right-click extends a line selection.
The far-right marker identifies selected lines.
Display transformations do not replace original copy content.
Use `:copy all` for a full-file copy through a background worker.

### Complete-file search and source paging

| Command | Function |
| --- | --- |
| `:logolder [BYTE_POSITION]` | Read a bounded source page before the retained window |
| `:logsearch [--all] [--literal\|--regex] [--case\|--nocase] [--word] [--] QUERY` | Search a complete file or the registered source set |
| `:logsearchmode literal\|regex [case\|nocase] [word\|partial]` | Change retained-content search behavior |
| `:logresults` | Open the latest complete-file results |
| `:loggoto line N` | Open an absolute source line; line numbers start at one |
| `:loggoto byte N` | Open a source byte offset |
| `:loggoto percent PERCENT` | Open a source percentage between zero and one hundred |
| `:loggoto time ISO_TIMESTAMP` | Find a timestamped source location |
| `:logmark NAME` | Name the current source position |
| `:logmarks` | Open named source bookmarks |

In a source page, `[` and `]` load the previous or next file page.
In results and bookmark lists, Enter opens the exact selected source.
In a bookmark list, Delete or `d` removes the selected bookmark.
Use `Esc` to restore the originating results or retained-tail view.
See [Log search](guides/log-search.md) for coverage, cancellation, regex limits, and remote behavior.

### Structured, folded, and paired log views

| Command | Function |
| --- | --- |
| `:logview plain\|split\|json\|diff\|fold` | Select a presentation |
| `:logalign on\|off` | Change timestamp alignment in split view |
| `:logdiff [LEFT_ID RIGHT_ID] [exact\|ignore-time]` | Compare two registered sources |
| `:logjson FIELD VALUE` | Filter a dot-separated JSON field by text |
| `:logjson clear` | Remove the JSON field condition |
| `:logfold on\|off` | Fold or expand repeated messages |
| `:logunread` | Visit the first unread retained line |
| `:logpan OFFSET` | Change horizontal display offset |
| `:logpan 0` | Restore the left edge |
| `:loggroup GROUP` | Fold or expand a file-list group |
| `:loggroup all` | Expand every file-list group |
| `:logpreview on\|off` | Change file-list previews |

In JSON and folded views, Enter or Space expands the selected item.
In paired views, `[` and `]` choose the original copy source.
Use `o` to open the original row from a structured or folded view.
Use `Esc` to return to original lines.
Use `v` to return to original lines before selecting raw text.
Use `Y` for the complete exact source.
See [Log display](guides/log-view.md) for inspected-source coverage and timestamp limitations.

## Copy and export controls

| Key or command | Function |
| --- | --- |
| `v`, `V`, `y` outside Logs | Select screen lines, select the screen, and copy displayed text |
| `E` | Export the current page as text |
| `C` | Export the current table as CSV |
| `J` | Export selected or marked jobs and their recorded series as JSON |
| `:export text\|csv\|json\|report` | Export a page, table, jobs, or complete dashboard |
| `:copy` | Copy the current selection |
| `:copy FIRST LAST` | Copy a range of loaded log lines or screen rows; indices start at one |
| `:copy all` | Copy the entire log source, or the screen outside Logs |
| `:activity` | Inspect retained notices and background tasks |
| `:task cancel` | Request cancellation of supported background tasks |

The [operations guide](guides/operations.md) describes notice search and the export library.
A terminal can reject or limit clipboard requests.
Inspect the result notice and private export path after a large copy.

## Activity, diagnostics, completions, and alerts

| Command | Function |
| --- | --- |
| `:activity filter TEXT` | Search notice text and supported field terms |
| `:activity level VALUE` | Select notice severity |
| `:activity job JOBID` | Search job identity |
| `:activity task TEXT` | Search task labels |
| `:activity persistent on\|off` | Change optional restart retention |
| `:activity clear` | Remove retained notices |
| `:exports [show]` | Open the export library |
| `:exports filter TEXT` | Search export labels and paths |
| `:exports preview ID_OR_INDEX` | Read a bounded preview |
| `:exports copy ID_OR_INDEX` | Copy a path |
| `:exports label ID_OR_INDEX NAME` | Label a record |
| `:exports forget ID_OR_INDEX` | Remove metadata for one export |
| `:exports clear` | Remove export metadata |
| `:terminaldoctor` | Inspect terminal and path metadata |
| `:terminaltest` | Test glyphs, colors, keys, and mouse events |
| `:terminaltest clipboard` | Request delivery of explicit test text |
| `:inbox [unread\|all\|failed]` | Select completion records |
| `:inbox filter TEXT` | Search completion names, IDs, states, and partitions |
| `:inbox ack JOBID\|all` | Review records in the current filtered list |
| `:alerts [show]` | Inspect configured alert conditions and delivery controls |
| `:alerts snooze RULE SECONDS [JOBID]` | Snooze a rule or one exact job |
| `:alerts unsnooze [RULE [JOBID]]` | Remove snoozes |
| `:alerts quiet START END [ZONE]` | Set daily quiet hours |
| `:alerts quiet off` | Disable quiet hours |

In Activity, `/` edits the filter, `f` clears it, and `e` opens exports.
Enter expands a notice.
Use `y` to copy its path or text.
Use `c` to request background task cancellation.

In exports, Enter opens a preview, `y` copies a path, and `d` forgets a record.
Forgetting metadata preserves the exported file.
Export indices start at one in the current filtered list.

In terminal diagnostics, `t` opens input tests and `r` refreshes evidence.
In input tests, only Esc exits.
Other keys and mouse events are recorded without running job actions.

In the inbox, `u` selects unreviewed, `f` selects failed, and `a` selects all records.
Enter opens the exact job in History.
Use `l` for its logs, `r` to review one record, and `A` to review the filtered list.

In alert controls, `s` snoozes the selected rule for thirty minutes.
Use `u` to remove its general snooze.
Use `Q` to disable quiet hours.
Quiet times use `HH:MM` in the selected IANA zone.
An omitted zone uses `America/Los_Angeles`.
Muted delivery preserves active conditions and events.
See [Operations](guides/operations.md) for precise persistence, limits, and troubleshooting.

## Chart inspection

| Command | Function |
| --- | --- |
| `:chart METRIC` | Open exact sample inspection |
| `:chart preset 5m\|30m\|2h\|all` | Select a time window |
| `:chart window SECONDS` | Select a custom time window |
| `:chart zoom FACTOR` | Select a zoom factor from one to 1024 |
| `:chart pan FRACTION` | Select a position from zero to one |
| `:chart axis auto` | Fit the axis to available measurements |
| `:chart axis fixed LOW HIGH` | Apply fixed numeric bounds |
| `:chart axis log [POSITIVE_LOW POSITIVE_HIGH]` | Apply a logarithmic scale |
| `:chart range FIRST LAST` | Select visible samples by number; indices start at one |
| `:chart range clear` | Clear the selected sample interval |
| `:chart events` | Open the observed-event list |
| `:chart events on\|off` | Show or hide event markers |
| `:chart event NUMBER` | Open the numbered event's citation or exact job |
| `:chart shared on\|off` | Change the scale lock for comparisons |
| `:metricdisplay METRIC label TEXT` | Set a display label |
| `:metricdisplay METRIC unit DECLARED_UNIT` | Set a declared display unit |
| `:metricdisplay METRIC precision INTEGER` | Set decimal precision between zero and twelve |
| `:metricdisplay METRIC reset` | Remove display overrides |

In the chart inspector, arrows and Home/End move between samples.
Use `+` and `-` to change zoom.
Use `[` and `]` to pan.
Use Tab or Shift-Tab to change metrics.
Use `t` to cycle time presets.
Use `a` for an automatic axis.
Use `g` for a logarithmic axis.
Use `r` to set the start and end of a sample interval.
Use `e` to open observed events.
Use `s` to change shared-scale mode.

In Diff, `s` changes the comparison scale lock.
In the event picker, Enter opens the selected citation or job.
Display labels and precision do not change recorded values.
See [Charts](guides/charts.md) for coverage, axis restrictions, and declared units.

## Artifact inspection

| Command | Function |
| --- | --- |
| `:outputs` | Browse declared artifacts for the selected project run |
| `:artifact` | Open the selected artifact |
| `:artifact next\|prev` | Load the next or previous artifact page |
| `:artifact refresh` | Reload the preview |
| `:artifact columns NAME_OR_NUMBER...` | Select CSV columns by name or number; indices start at one |
| `:artifact sort COLUMN asc\|desc\|off` | Change the global CSV record order before paging |
| `:artifact json /POINTER` | Inspect a JSON Pointer |
| `:artifact text` | Open raw text pages from the first page |
| `:artifact structured` | Restore declared-format pages from the first page |

Use `[` and `]` for background page loading.
Use arrows and page keys to scroll the loaded content.
In CSV, Left/Right focuses a column.
Enter cycles ascending, descending, and off.
Use `c` to change the focused column's visibility.
In JSON, Enter or Space expands the selected node.
See [Artifacts](guides/artifacts.md) for size limits, source identity, and declared path rules.

## Command families

These commands are available through the palette.
The same command families are available through `tower run` when they do not require an interactive overlay.
Quoted arguments preserve paths that contain spaces.
Job-changing commands open a review; scripted changes require `--yes`.

| Family | Commands | Reference |
| --- | --- | --- |
| Help and command discovery | `menu`, `about`, `help`, `commands`, `quit` | [Live workbench](guides/live-workbench.md#use-the-terminal-toolbar) |
| Main navigation | `tab`, `view`, `workspace`, `workspaces`, `back`, `forward`, `jump`, `location` | [Navigation](guides/navigation.md) |
| Settings and field inspection | `settings`, `keybindings`, `explain`, `peek` | [Navigation](guides/navigation.md) |
| Panel layout | `density`, `focus`, `maximize`, `layout`, `panel-scroll` | [Workbench](WORKBENCH.md#shape-your-workspace) |
| Table inspection | `sort`, `sortby`, `sorteditor`, `headers`, `columns`, `facet`, `filters`, `where`, `savedview`, `viewpicker`, `jobgroups`, `filter`, `days`, `historyrange`, `recents`, `marked`, `freeze`, `jobactions`, `node`, `drill` | [Tables](guides/tables.md) |
| Job selection and annotations | `mark`, `unmark`, `pin`, `tag`, `untag`, `note`, `compare` | [Reference](reference.md#keys-remappable-in-the-config) |
| Job changes | `cancel`, `hold`, `release`, `requeue`, `top`, `resubmit`, `chain` | [Reference](reference.md#keys-remappable-in-the-config) |
| Selected job | `jobpanel`, `inspect`, `log`, `investigate`, `advise` | [Live workbench](guides/live-workbench.md#inspect-a-job-inside-jobs) |
| Log files and presentation | `find`, `wrap`, `bookmark`, `logview`, `logpan`, `loggroup`, `logpreview`, `logalign`, `logdiff`, `logjson`, `logfold`, `logunread` | [Log display](guides/log-view.md) |
| Complete-file log inspection | `logolder`, `logsearch`, `logsearchmode`, `logresults`, `loggoto`, `logmark`, `logmarks` | [Log search](guides/log-search.md) |
| Sampling and profiles | `rate`, `refresh`, `source`, `gpu`, `bell`, `profile`, `theme` | [Live workbench](guides/live-workbench.md#set-the-update-rate) |
| Activity and output | `activity`, `notifications`, `task`, `export`, `exports`, `copy` | [Operations](guides/operations.md) |
| Completion and alert delivery | `inbox`, `alerts` | [Operations](guides/operations.md) |
| Terminal diagnostics | `terminaldoctor`, `terminaltest` | [Operations](guides/operations.md) |
| Project and run selection | `project`, `runs`, `run`, `outputs`, `artifact` | [Project standard](PROJECT_STANDARD.md) |
| Application measurements | `metrics`, `metric`, `metricdisplay`, `dashboard`, `chart`, `timeline`, `diff` | [Charts](guides/charts.md) |
| Output contracts | `artifacts`, `validate` | [Research](RESEARCH.md) |
| Provenance | `passport` | [Research](RESEARCH.md) |
| Submission preparation | `prepare`, `preflight`, `submit`, `array` | [Research](RESEARCH.md) |
| Resource and queue evidence | `predict`, `forecast`, `blockers`, `tradeoffs`, `choose` | [Planning](WAVE_TWO.md) |
| Experiment and workflow execution | `scaling`, `workflow`, `orchestrate`, `execution` | [Planning](WAVE_TWO.md) |
| Recorded sessions | `replay` | [Reference](reference.md#recording-and-replay) |
| Snapshot expressions | `eval` | [Reference](reference.md#scripted-mode-and-expressions) |

Plugins can register additional commands.
Use `:commands` to inspect the commands loaded in your session.
The [plugin reference](reference.md#plugins) defines the extension interface.

## Command-line options

Run `tower --help` for the parser's complete current syntax.

| Option | Purpose |
| --- | --- |
| `-h`, `--help` | Print command-line help |
| `--version` | Print the application version |
| `--config FILE` | Select TOML or JSON configuration |
| `--write-config` | Create commented defaults without replacing an existing file |
| `--doctor` | Inspect demo, local, or remote prerequisites |
| `--profile NAME` | Apply a configured cluster profile |
| `--host HOST` | Run scheduler commands and log reads through SSH |
| `--ssh-user USER` | Select the remote SSH login |
| `--user USER` | Select the scheduler user |
| `--account ACCOUNT` | Select the account used for aggregate views |
| `--interval SECONDS` | Set the job sampling interval |
| `--rate MULTIPLIER` | Set the startup fetching multiplier from 1 to 50; override the saved preference |
| `--days DAYS` | Set the accounting lookback window |
| `--no-gpu` | Disable live GPU sampling |
| `--bell` | Ring on observed job starts |
| `--ascii` | Select portable character graphics |
| `--unicode` | Select block and braille graphics when encoding permits them |
| `--no-color` | Disable color |
| `--no-plugins` | Disable plugin loading |
| `--once` | Print one frame and exit |
| `--tab IDENTIFIER` | Select the initial page or export table |
| `--research-view NAME` | Select the initial Research workspace |
| `--metrics-file FILE` | Attach an application JSONL measurement stream |
| `--contract FILE` | Attach an output contract |
| `--workdir DIR` | Set the root for attached project files |
| `--passport FILE` | Attach an immutable run passport |
| `--planning-file FILE` | Attach planning observations or a recipe |
| `--json` | Print the complete snapshot as JSON |
| `--report [FILE]` | Write a complete ASCII report; omitted FILE means standard output |
| `--csv` | Print the current export table as CSV |
| `--watch` | Display an updating ANSI screen |
| `--fake` | Use simulated scheduler data |
| `--record FILE` | Record scheduler commands and responses |
| `--replay FILE` | Use recorded scheduler data |
| `--speed FACTOR` | Set replay speed |
| `--paused` | Start replay paused |
| `--run COMMAND` | Execute one palette command and exit |
| `--yes` | Confirm a scripted job-changing operation |
| `--eval EXPRESSION` | Print a snapshot expression result |
| `--wait-for EXPRESSION` | Wait until a snapshot condition is true |
| `--timeout SECONDS` | Limit a wait; zero means no timeout |
| `--poll SECONDS` | Set the interval for condition polling |
| `--alert EXPRESSION` | Add a session alert; this option can be repeated |
| `--no-state` | Disable normal UI state reads and writes |
| `--width COLUMNS` | Set report or one-frame output width |

Use `tower run COMMAND ARGUMENTS` as an alternative to `--run`.
Command-specific flags are passed to that palette command.
See the [scripted-mode reference](reference.md#scripted-mode-and-expressions) for exit codes.

## Configuration and environment variables

Use `--config`, `TOWER_CONFIG`, or the default file under `~/.config/tower/`.
Use `NO_COLOR=1` to disable color.
Use `--account ACCOUNT` for a single launch override.

| Variable | Managed Bash alias behavior |
| --- | --- |
| `SLURM_TOWER_PROFILE` | A nonempty value overrides the installed profile |
| `SLURM_TOWER_ACCOUNT` | Sets an account for any profile; an empty value suppresses legacy account injection |
| `CARC_ACCOUNT` | Provides a fallback only for the CARC profile when the generic account variable is unset |
| `TOWER_CONFIG` | Selects a custom configuration instead of the supplied example |
| `SLURM_TOWER_ROOT` | Selects the checkout used by the managed launcher |

The desktop alias ignores `CARC_ACCOUNT`.
See [Desktop account overrides](DESKTOP.md#account-and-profile-overrides) for examples.

The normal persistent state base is `~/.local/state/tower/`.
The desktop profile uses `state_namespace = "desktop"` to separate connection state.
See [Desktop state](DESKTOP.md#keep-desktop-state-separate) for the default directory layout.
The [configuration reference](reference.md#configuration) defines profiles, intervals, timeouts, thresholds, alerts, clipboard options, and plugins.
The [documentation style](DOCUMENTATION_STYLE.md) defines the terminology used in these guides.
