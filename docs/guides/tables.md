# Table controls and job inspection

Tower reads scheduler observations in a background task. Table controls use
those observations. They do not run a scheduler query on each key press.

A **facet** is a filter on a named field. A **sort priority** specifies which
column Tower uses first to order rows. A **view** stores a table configuration.

| Command table name | Page or section |
|---|---|
| `jobs` | Active jobs on Jobs |
| `recent` | Recents on Jobs |
| `history` | Completed jobs on History |
| `group` | Account jobs on Group |
| `nodes` | The node table on Nodes |
| `cluster` | Partitions on Cluster |
| `sources` | Data sources on Sources |

Enter commands with `:`. Press Enter to run a command. Press Esc to close an
overlay. Tower saves column settings, filters, sort priorities, named views,
History date ranges, and the normal Recents limit in local UI state.
A freeze and a temporary Recents expansion apply to the current session.

<a id="feature-01"></a>

## 1. Edit sort priorities

1. Enter `:sorteditor jobs`.
2. Press Up or Down to select a rule.
3. Press Left to increase its priority. Press Right to decrease its priority.
4. Press Space or Enter to change its direction.
5. Press `d`, Delete, or Backspace to remove the selected rule.
6. Press Esc to close the overlay.

Press `a` to open the column picker and add a sort rule. The first rule has the
highest priority. The next rule resolves equal values. For example, use
`name asc`, then `cpus desc` to put names in alphabetical order and put the
largest CPU allocation first within each name.

Tower retains the selected job ID when the order changes. Pinned jobs remain
first. Unknown values remain after known values in both directions.

<a id="feature-02"></a>

## 2. Sort with the keyboard

1. Enter `:headers history`.
2. Press Up or Down to select a column.
3. Press Enter or Space to cycle through ascending, descending, and off.
4. Press Esc to return to the table.

Press Left to set ascending order. Press Right to set descending order.
You can also click a displayed column heading. A heading such as `NAME ^1`
shows ascending order at priority 1. `CPU v2` shows descending order at
priority 2. These indicators work in Unicode and ASCII modes.

Use `:sortby jobs clear` to remove all explicit sort rules and restore source
order. The existing `:sort` command selects a legacy default and removes the
explicit sort configuration for that table.

JOBID uses numeric ordering, including array tasks. Thus, `9` comes before
`10`, and `123_2` comes before `123_10`. Actions use the complete ID.

<a id="feature-03"></a>

## 3. Configure columns

1. Enter `:columns nodes`.
2. Press Up or Down to select a column.
3. Press Space to show or hide it.
4. Press Left or Right to change its position.
5. Press `+` or `-` to change its width by one terminal cell.
6. Press Enter or Esc when the configuration is correct.

Press `a` to restore automatic width for the selected column. Press `r` to
reset order, widths, and visibility. Identity and state columns cannot be hidden.

Use commands for exact settings:

~~~text
:columns jobs order id,cpus,name,part
:columns jobs width name 24
:columns jobs width name auto
:columns jobs hide gpu%,mem%
:columns jobs show gpu%
:columns jobs reset
~~~

A width must be from 2 through 120 terminal cells. Keys omitted from an `order`
command follow the specified keys in their original order. Tower can clip or
omit optional columns when the terminal is too narrow. It measures wide
characters in terminal cells.

<a id="feature-04"></a>

## 4. Filter numeric resources

~~~text
:where jobs cpus>=8 memory>16GiB cpu_eff<30%
:where history elapsed>=2h rss>8GiB
:where nodes cpus>=32 memory>=64GiB
:where cluster nodes>10
:where jobs clear
~~~

Comparisons on the same table use AND. A new comparison replaces an existing
comparison with the same field and operator. Unknown measurements do not match.
A measured zero is valid.

Job tables accept `cpus`, `gpus`, `memory`, `rss`, `cpu_eff`, `mem_eff`,
`elapsed`, `priority`, and `nodes`. Nodes accepts `cpus`, `memory`, and `rss`.
Cluster accepts `nodes`.

| Field | Meaning |
|---|---|
| `memory` | Requested job memory; total node memory |
| `rss` | Reported peak job memory; used node memory |
| `cpu_eff` | CPU time divided by elapsed time and allocated CPUs |
| `mem_eff` | Reported peak memory divided by requested memory |
| `elapsed` | Reported elapsed seconds |
| `priority` | Reported scheduler priority |

Use `>`, `>=`, `<`, `<=`, `=`, or `!=`. Memory units use powers of 1024.
Efficiencies accept `30%` or `0.3`. Durations accept `2h30m`, `01:30:00`, or
a number of seconds. Tower uses values before display rounding.

A table can have up to 16 numeric rules. A malformed command preserves the
previous rules.

<a id="feature-05"></a>

## 5. Build and remove filters

1. Enter `:filters jobs`.
2. Press Up or Down to select a field.
3. Press Enter.
4. Type a value. For a numeric field, type a comparison such as `>=8`.
5. Press Enter to apply the value.

An empty value removes the field filter. For a numeric field, it removes all
comparisons for that field. Press Ctrl-U to clear the edit buffer.
Press Esc to cancel the edit. The overlay previews matches for a valid draft.
An incomplete draft leaves current filters in use. Press `c` outside the edit
buffer to clear field and numeric filters.

Applied filters appear as chips above the page. Click a chip to remove that
filter. For example, click `[partition=gpu x]` to remove the partition facet
without changing CPU or memory rules.

`state`, `partition`, `id`, and `user` accept comma-separated exact choices.
`name` matches text. `tag` matches a complete tag.
Resource pickers show fields available on that resource.

<a id="feature-06"></a>

## 6. Keep separate table filters

Each table has its own text filter, facets, and numeric rules. A Jobs search does
not change History or Recents.

Use `/` or `:filter TEXT` for the current page. Specify a table in a field or
numeric command:

~~~text
:facet history state=FAILED,TIMEOUT
:facet recent name=train
:where jobs cpus>=8
:where history cpu_eff<30%
~~~

Switch pages to restore their previous searches. Use `:facet TABLE clear` and
`:where TABLE clear` to remove field and numeric rules. Use an empty `:filter`
command to clear the current page's text search.

<a id="feature-07"></a>

## 7. Save and select views

1. Configure filters, columns, and sort priorities.
2. Enter `:savedview jobs save "GPU training"`.
3. Enter `:viewpicker`.
4. Select the view with Up or Down.
5. Press Enter to load it.

The picker shows the target table, search or facets, sort order, and column
visibility. Press `d` to delete the selected view.

A view includes column order and widths, hidden columns, text filters, facets,
numeric rules, sort priorities, and the History window. A History view also
includes its exact date range.

~~~text
:savedview list
:savedview load "GPU training"
:savedview delete "GPU training"
~~~

Tower supports up to 32 views. Names can contain letters, numbers, spaces, dots,
and hyphens. A name must have 1 through 64 characters. Tower validates a saved
view before it changes the page.

<a id="feature-08"></a>

## 8. Select exact History dates

~~~text
:historyrange today
:historyrange yesterday
:historyrange week
:historyrange 2026-10-01 2026-10-05
:historyrange all
~~~

Dates use the local timezone of the machine that runs Tower. Both dates are
included. The range applies to accounting End. Records without a reported End
timestamp do not match an exact range.

Tower requests a larger accounting window when necessary. Cached matches appear
immediately. Other matches appear after the accounting source refreshes.
The maximum lookback is 3650 days. `all` removes the exact-date filter. It does
not request unlimited accounting history. The summary shows the active interval.

<a id="feature-09"></a>

## 9. Adjust Recents

~~~text
:recents 5
:recents 10
:recents 25
:recents window 2h
:recents window all
~~~

Tower selects the latest candidate records before it applies the Recents sort.
The Jobs sort does not change Recents. Departed jobs remain visible while
accounting data is pending.

Use `:recents auto` to adapt the initial preview when several jobs finish.
Use `:recents expand` for an initial preview of 25 records.
Use `:recents collapse` to restore the configured preview.
These choices do not impose a hard history limit.

Drag the grey divider above Recents to change its share of Jobs Main.
A larger section shows more records.
Use the wheel inside Recents, or click a recent row and use arrow or page keys, to reach older matching jobs.
Home reaches the first recent job.
End loads the matching history needed to reach the last job.
Tower grows the candidate prefix in bounded pages as you navigate.
The `window` filter uses accounting End.
Pending accounting records remain visible with their explicit status.
The accounting window and filters determine the available history.
See [Scrollable Recents](adaptive-workspaces.md#show-more-recent-jobs) for selection and layout behaviour.

<a id="feature-10"></a>

## 10. Page by the visible row count

Press Page Up or Page Down to move by the visible row count minus one.
The shared row provides context. A one-row viewport moves by one row.

Tower recalculates the page size after a resize or layout change. Jobs includes
the active and recent rows in the current viewport. Log browsers have their own
viewport-based paging.

<a id="feature-11"></a>

## 11. Review marked jobs

1. Mark jobs with the normal controls.
2. Enter `:marked`.
3. Review the exact IDs and their visibility.
4. Press Enter for details, or `l` for logs.

Hidden jobs remain marked. An ID without a current record remains listed with
an unavailable status.

Use `:marked hidden`, `:marked visible`, `:marked active`, or `:marked finished`
for a subset. Press `s` to cycle subsets. Press `d`, Delete, or Space to remove
one mark. Press `c` to clear only the displayed subset.

These controls change marks. Scheduler actions retain applicability checks and
confirmations.

<a id="feature-12"></a>

## 12. Freeze inspection

Enter `:freeze on` to hold the current scheduler observation. The sampler
continues to collect observations. A FROZEN indicator shows elapsed time and
accumulated queue changes.

Enter `:freeze off` to display current observations. Tower reports accumulated
queue changes. The observation is copied once and remains private to the
session. Actions validate the live state. Freezing does not make a completed
job eligible for an active-job action.

<a id="feature-13"></a>

## 13. Use the job action menu

Enter `:jobactions` for the selected job, or `:jobactions 123_2` for an exact ID.
Select an action with Up or Down. Press Enter.

The menu includes logs, scheduler evidence, ID copying, comparison, and research
evidence. It includes scheduler actions when an active job and an action backend
are available.

Scheduler operations use existing exact-ID checks and confirmations. A filter
change does not replace the menu's job ID. Before execution, Tower checks every
confirmed ID against the live queue. If any job is unavailable, has a different
submission identity, or is no longer eligible, Tower aborts the complete action.
Select the jobs and review a new confirmation.

<a id="feature-14"></a>

## 14. Inspect a node

Click a node table row or resource-matrix row. You can also enter
`:node NODE_NAME`.

On the cluster map, click the desired node cell. Tower uses its terminal
coordinates, including after a resize or layout change.

The overlay shows state, CPU allocation, load, memory, GPU resources, measurement
age, and reported source problems. It lists observed jobs on the node. That
list can be incomplete if the account-wide source is unavailable.

Select a job. Press Enter for details, or `l` for logs. Press Esc to return.
An unknown value is distinct from a measured zero.

<a id="feature-15"></a>

## 15. Open partition and user job lists

Click a partition row on Cluster to open matching jobs. Click a user summary
row on Group to show that user's jobs.

~~~text
:drill partition gpu
:drill user alex
~~~

Tower adds a partition or user facet to the target table. Its existing filters
remain active. Remove a chip if another filter hides expected jobs.

Use Back to restore the overview, cursor, filters, and sort order.
A user drill-down on the current Group page also records the previous overview.

## Public integration methods

These methods are for extensions and tests. They use the existing event loop.

| Module and method | Purpose |
|---|---|
| `table_ui.initialize(app)` | Create table preferences. |
| `table_ui.restore(app, data)` / `save(app)` | Validate and restore preferences; return JSON-compatible state. |
| `table_ui.command_names()` / `run_command(app, args)` | List and run column, facet, view, grouping, and sort commands. |
| `table_ui.handle_key(app, key)` / `overlay(views, snap, app, width, height)` | Handle the column editor and array folds; place an overlay. |
| `table_ui.definitions(table)` / `ordered_definitions(app, table)` | Return available columns in default or configured order. |
| `table_ui.columns(app, table, original)` | Apply order, visibility, widths, and sort indicators. |
| `table_ui.matches(app, table, record, snap)` | Apply facets and numeric rules to a typed record. |
| `table_ui.chips(app, table, width, ascii_=False)` | Draw chips and retain exact click bounds. |
| `table_ui.fingerprint(app, table)` / `facets_fingerprint(app, table)` | Return selection-cache identities for settings or facets. |
| `table_ui.group_rows(app, rows)` | Apply array folds without replacing task IDs. |
| `table_sort.validate_chain(table, value)` / `chain(app, table)` | Validate or read ordered sort rules. |
| `table_sort.set_sort(app, table, column, direction)` / `cycle_sort(app, table, column)` | Change a rule while retaining the others' priorities. |
| `table_sort.clear_sort(app, table)` / `reset_sort(app, table)` | Select source order or the legacy default. |
| `table_sort.describe_sort(app, table)` / `sort_fingerprint(app, table)` | Return a label or cache identity. |
| `table_sort.normalize(value, kind="text")` | Normalize a value for comparison. |
| `table_sort.sort_rows(app, table, rows, value=None)` | Sort the full source before viewport slicing. |
| `table_sort.history_value(record, key, snap=None)` | Read unrounded accounting values. |
| `table_sort.header_hits(table, cells, y)` / `valid_header(payload)` | Construct or validate header click geometry. |
| `table_tools.initialize(app)` / `restore(app, data)` / `save(app)` | Create, validate, and serialize tool preferences. Session freezes are excluded. |
| `table_tools.command_names()` / `run_command(app, args)` | List and run the commands in this guide. |
| `table_tools.handle_key(app, key)` / `handle_mouse(app, y, x, button="left", shift=False)` | Handle modal lists and chips. |
| `table_tools.overlay(views, snap, app, width, height)` | Place the current overlay and its click bounds. |
| `table_tools.handle_click_hit(app, y, x, hits, button="left", shift=False)` | Open exact node, partition, and user targets. |
| `table_tools.filter_text(app, table)` / `set_filter_text(app, table, text)` | Read or set an independent text filter. |
| `table_tools.parse_rule(text)` / `validate_numeric(value)` | Parse unit-aware comparisons or validate saved rules. |
| `table_tools.numeric_rules(app, table)` / `numeric_value(app, record, snap, field)` | Read rules or a raw measurement. |
| `table_tools.numeric_matches(app, table, record, snap)` | Test comparisons with unknown-value handling. |
| `table_tools.validate_dates(value)` / `history_matches(app, record)` / `date_label(app)` | Validate, apply, or describe an accounting End interval. |
| `table_tools.recent_limit(app)` / `recent_matches(app, record)` | Read the Recents limit or test its time window. |
| `table_tools.record_page(app, table, visible)` / `page_size(app, table, fallback=10)` | Record visible rows and calculate page movement. |
| `table_tools.snapshot(app, snap)` / `freeze_status(app, live_snap=None)` | Read the display observation or describe live changes. |
| `table_tools.focused_column(app)` | Return the table and column under keyboard focus. |
| `table_tools.select_resource(app, table, names)` / `selected_record(app, table, snap)` | Preserve resource IDs and resolve a complete Node, Partition, or Health record. |
| `table_tools.marked_rows(app, snap=None)` | Return marked IDs, records, and hidden flags for a subset. |
| `table_tools.extra_fingerprint(app, table)` | Return text, numeric, date, and Recents preference identities. |

Use the live Store for scheduler-action checks. Use `snapshot` for display and
read-only inspection. A drawing callback must not read files, write UI state,
or query Slurm for each row.
