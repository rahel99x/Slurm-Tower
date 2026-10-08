# Read and adjust charts

Tower draws charts with terminal characters. Unicode curves use connected opaque
quadrants. ASCII curves use connected strokes. Filled area graphs retain their
block presentation. Both modes use the
same samples, time windows, and scale limits. No chart control starts a job or
requests extra scheduler data.

## Open a chart

1. Select a job in Jobs or History.
2. Open Experiment to load its application metrics, or use session resource data.
3. Enter `:chart METRIC`. Use the exact metric ID. Quote an ID that has spaces.
4. Use the arrow keys to select a sample. Use Home or End to select an endpoint.
5. Press Tab or Shift-Tab to change the metric. Tower selects the nearest sample
   time in the new metric.
6. Press Esc to return.

Use Page Up and Page Down to read rows that do not fit in a small terminal.

The selected sample shows its original timestamp, value, and reported step. A
display preference does not change these values. The chart stays attached to the
job that was selected when you opened it.

## Read a long Job series page

Open **Analytics → Job series** in the compact native layout and select the required job.
Use the mouse wheel, Page Up, and Page Down to scroll the metric document.
Use `:series-scroll home` or `:series-scroll end` to reach its first or last rows.
The job heading and navigation controls remain visible.
Up, Down, Home, and End continue to change the job.
Changing the job returns the document to its first row.

Point at the metric content when scrolling with the wheel.
A wheel event over Job history scrolls that browser instead.
Inside Jobs Details, use the Details column's normal scroll controls.
When a slider or directional button focus owns the keys, its controls take priority.

## Point at a metric graph

Move the pointer inside a visible metric plot with recorded data.
Tower draws a cyan dotted crosshair with `+` at the pointer.
Unicode uses `·` for the dots; ASCII uses `.`.
The crosshair stays inside the measured plot, outside its labels and controls.
It marks the pointer's coordinates and does not turn a missing sample into a measurement.

Hover uses the published graph geometry.
It does not reload the source, change the selected job, or rasterize the curve again.
The terminal must report mouse movement.
Use `:terminaltest` when movement reports are missing.

## Follow a running metric

A running job can show a Live control and a time-window slider above each metric.
Each metric has its own setting. A curve and its filled companion share one setting.

1. Open the exact running job's metric view.
2. Click **Live off** to enable Live.
3. Drag the slider toward the left for five seconds, or toward the right for one millisecond.
4. Read the duration beside the toggle. Wider rows label it `Δ`, or `dt` in ASCII mode.
5. Click **Live ON** to return to the ordinary retained view.

**Expected result:** Live displays the interval from the dashboard's current time minus the chosen duration to its current time.
The slider uses logarithmic steps between `5s` and `1ms`.
Subsecond axes show fractional seconds in their timestamp labels.
Labels use available terminal space and do not imply a finer source cadence.
Each metric retains its own duration. A completed job has no active Live control.
The control row needs at least 24 available terminal columns.
Compact rows use `○ Live` and `● Live`, or `o Live` and `+ Live` in ASCII mode.
The empty symbol is off; the filled symbol is on. Both slider endpoints remain labelled.

Select the slider with the mouse or directional button focus.
Use Left and Right for one slider step, Page Up and Page Down for five steps,
Home for five seconds, and End for one millisecond.
Press Enter or Esc to leave slider focus.
Press Esc during a drag to restore its previous duration.
A page, source, geometry, or terminal-size change also discards an unfinished drag.

The control graph assigns a temporary token such as `m1` to each visible source.
Use `:metric-live TOKEN on|off|toggle` and `:metric-window TOKEN SECONDS`
with that visible token, or `:metric-window TOKEN focus` for keyboard adjustment.
Tokens are session controls, not project metric IDs. Commands reject a hidden or nonrunning source.
Live preferences do not survive a restart.

Live changes the displayed interval. It does not increase Slurm polling or create measurements.
The Live clock requests at most ten scheduled display refreshes per second while an uncaptured Live plot is visible.
Input and scrolling animations can request other display refreshes.
A one-millisecond window can therefore contain no recorded observations.
Valid empty axes retain their Live controls and time labels, but have no crosshair or rectangular selection until recorded data is visible.
Read the source-age and sampling-cadence note below the graph before interpreting a sparse window.
Missing observations and sampling outages remain gaps.
Current resource captures retain their timestamp precision.
Older saved captures can retain the earlier 0.1-second rounding.
A precise capture timestamp does not establish equally frequent source measurements.

During a rectangular selection, Tower holds that plot's painted time mapping fixed.
Cancelling the selection resumes Live.
Committing a valid rectangle turns Live off and keeps the selected bounds.
Enabling Live again clears that metric's completed rectangular zoom.

## Zoom a rectangular area

1. Press the left mouse button inside the required metric plot.
2. Keep the button pressed and move to the opposite corner of the required area.
3. Check the dotted rectangle.
4. Release inside the same plot.

**Expected result:** The graph uses the rectangle's horizontal and vertical bounds.
The selection must span at least two columns and one row.
A click without that area leaves the view unchanged.
The operation changes the display bounds and preserves the original measurements.
Between adjacent known samples, a zoom can show their connected line even when
the selected interval contains no original sample. The sample count still
reports zero for that interval. Missing values and sampling outages remain gaps.

Press `u` while pointing at the graph to undo the last rectangular zoom.
Press `0` while pointing at it to restore its original rectangular view.
Use `:chartzoom undo` or `:chartzoom reset` for the last selected or zoomed graph.
In the chart inspector, use the Undo zoom and Reset zoom buttons, or
`:chart undo` and `:chart reset`, for the current metric.
The existing `+`, `-`, time presets, and axis commands remain available.

Each zoom belongs to an exact metric, source, job, and run attempt.
Another job cannot inherit it.
Zooms are session display state; they do not change files or sampler intervals.
Tower retains at most 128 zoom entries and 16 undo steps per entry.

Press Esc before release to discard the preview.
Releasing outside the plot also discards it.
Changing the page, job, source, graph bounds, panel geometry, or terminal size cancels capture.
Opening a menu, dialog, or startup preview cancels it too.
A missing release times out after 15 seconds.
Cancellation keeps the previous completed zoom.
On a logarithmic graph, vertical selection uses that graph's logarithmic coordinates.

<a id="feature-41"></a>

## Time window

Press `t` to change the time window. The control row shows these presets:

| Preset | Result |
| --- | --- |
| `5m` | Show the last five minutes of retained samples. |
| `30m` | Show the last thirty minutes of retained samples. |
| `2h` | Show the last two hours of retained samples. |
| `all` | Show all retained samples. |

Use `:chart preset 5m`, `:chart preset 30m`, `:chart preset 2h`, or
`:chart preset all` to select a preset directly. Use `:chart window SECONDS` for
a custom window. Tower accepts a positive duration of up to 365 days. A preset
does not load samples that are outside the retained history.

Use `+` or `-` to change the zoom. Use `[` or `]` to move the time window. Use
`:chart zoom FACTOR` for a factor from 1 to 1024. Use `:chart pan FRACTION` for a
position from 0 to 1. Zero selects the beginning; one selects the end.

<a id="feature-42"></a>

## Axis scale

| Control | Result |
| --- | --- |
| `a` or `:chart axis auto` | Calculate a linear scale from the visible data. |
| `:chart axis fixed LOW HIGH` | Use the specified linear limits. |
| `g` or `:chart axis log` | Calculate a base-10 logarithmic scale. |
| `:chart axis log LOW HIGH` | Use positive logarithmic limits. |

The lower limit must be less than the upper limit. Both limits must be finite.
For a logarithmic axis, both limits must be positive.

Tower labels the active scale. It shows how many visible values are outside
fixed limits. On a logarithmic axis, zero and negative samples are undefined.
Tower draws a gap for these samples and shows their count. The original values
remain available in the sample inspector and interval statistics.

<a id="feature-43"></a>

## Preserve spikes

When samples share a terminal column, Tower retains the first, minimum, maximum,
and last known values in source order. This envelope preserves short spikes.
Unicode curves draw the range with opaque quadrant strokes. ASCII curves use
`/`, `\`, `-`, `:`, and `+`; an isolated sample uses `.`. If a bucket contains an unknown sample, the bucket stays
unknown. Tower does not draw a bridge through that bucket or a detected outage.
It connects known samples without smoothing their values. Fixed or zoomed
vertical bounds clip a crossing line. A segment wholly outside those bounds stays
blank instead of appearing as a flat measurement on the scale edge.

<a id="feature-44"></a>

## Sample interval

1. Move to the first sample of interest.
2. Press `r` to set the start of the interval.
3. Use the arrow keys to move to its end. Tower highlights the selected chart
   interval. The statistics change as you move.
4. Press `r` again to finish the selection.

Use `:chart range FIRST LAST` to select two visible sample numbers. Numbering
starts at one. Endpoints are included. Use `:chart range clear` to remove the
selection. The interval is attached to the metric ID and source timestamps.

Tower reports the known sample count, missing sample count, minimum, median,
mean, maximum, and the 5th, 95th, and 99th percentiles. Percentiles use linear
interpolation between sorted known samples. The mean uses finite arithmetic
that avoids overflow for extreme values.

Sample coverage is the fraction of selected samples with a known value. Time
coverage is the fraction of the interval covered by adjacent known samples
within 2.5 median sampling intervals. Tower calculates the median cadence from
the complete retained series. It does not fill gaps. A single sample has no
measurable time interval, so its time coverage is unavailable.

<a id="feature-45"></a>

## Observed events

The `Events e` strip marks observed events at their actual timestamps. A diamond
in Unicode mode, or an asterisk in ASCII mode, indicates more than one event in
the same terminal column. Only events for the chart's job and global observed
events are eligible. Resource samples are not repeated as event markers.

Press `e` or enter `:chart events` to open the event picker. Use the arrow keys,
Home, End, Page Up, and Page Down to select an event. Press Enter to open its
exact job or cited source file. Press Esc to return to the chart. Use
`:chart event NUMBER` to open an event directly. The picker shows the full event
numbers, source paths, and original line numbers when they are available.

Use `:chart events off` to hide the strip. Use `:chart events on` to show it.

Phase changes, alerts, checkpoints, and log events appear only when a published
observation includes a timestamp. Tower does not infer earlier phase changes or
checkpoint times. If an event has a source path but no original line number,
Tower opens the exact file and reports that its exact line is unavailable.

<a id="feature-46"></a>

## Comparison scales

Enter `:diff JOBID JOBID` to compare two jobs. You can supply up to six IDs.
Resource curves align on each job's first observed sample.

Shared scales are on by default. Each metric uses the same vertical limits for
every compared job. Press `s` to toggle between shared and independent limits.
You can also use `:chart shared on` or `:chart shared off`. The comparison shows
the active setting. A fixed scale for a metric applies to all its curves.

Tower compares measurements of the same metric. It does not combine CPU,
memory, and GPU values into one scale. If a job has no measured samples, Tower
shows that condition instead of drawing a curve.

## Read GPU utilisation and busy mean

Job Series can show a GPU utilisation curve and an observed busy-mean curve for each available device.
Utilisation is the recorded busy percentage.
The busy mean is the cumulative mean of valid utilisation observations in the retained series.
It is an activity indicator, not FLOP efficiency, throughput, or the fraction of allocated devices used.
Missing and invalid device readings remain gaps and do not enter the mean.

Session telemetry identifies devices by `node:index` and retains utilisation, used memory, and total memory.
An application's job trace uses `<WorkDir>/logs/gpu-util-<jobid>.csv` with rows
`timestamp,index,utilisation_percent,memory_used_MiB`.
Tower keeps that trace attached to the exact job.
An index-only trace cannot establish which node or allocated device produced a reading.
See [GPU trace](../reference.md#the-gpu-trace) for the producer procedure.

The view shows at most four session devices and four trace indices.
The corresponding stable graph IDs are `gpu:<node:index>:rate`,
`gpu:<node:index>:busy-mean`, `gpu-trace:<index>:rate`, and `gpu-trace:<index>:busy-mean`.
These graph identities remain stable as observations arrive or the glyph mode changes.
Unavailable telemetry produces no invented utilisation or busy-mean measurement.

<a id="feature-47"></a>

## Metric display

Use the exact metric ID with these commands:

```text
:metricdisplay loss label Validation loss
:metricdisplay loss precision 4
:metricdisplay samples_per_second unit samples/s
:metricdisplay loss reset
```

| Preference | Accepted value |
| --- | --- |
| `label` | Printable text of up to 96 characters. |
| `unit` | An explicitly declared unit of up to 96 characters. |
| `precision` | An integer from 0 to 12 decimal places. |
| `reset` | Remove the metric's display preferences. |

These preferences change presentation only. They do not convert units or rewrite
measurements. Declare a unit that matches the reported data. Tower does not infer
an application metric's unit from its name. Session CPU and GPU percentages use
percent units. Session memory samples use GiB because their source bytes are
divided by 1024 cubed; their existing metric ID remains `Memory (GB)` for saved
view compatibility. The chart shows the original metric ID and the declared
unit. Exact sample inspection always retains the original numeric precision.

Tower saves labels, units, precision, axis limits, event visibility, and the
comparison scale setting. It does not restore a live chart, selected job, or
temporary sample interval after a restart.

## Data limits

- Tower uses published metric snapshots and in-memory resource samples.
- A metric chart retains at most 10,000 points. A dashboard has at most 64 metrics.
- An event picker has at most 512 observed events.
- Plot dimensions are limited to 2,048 terminal columns and 128 rows.
- The interaction registry holds at most 96 plots in one published frame.
- Rectangular zoom retains at most 128 source keys and 16 undo steps per key.
- Live retains at most 128 metric identities and uses only visible running-source controls.
- Unknown and nonfinite values remain gaps. A measured zero remains a value.
- Sampling outages remain visible after zooming or compression.
- No rendering path loads a metric file or queries the scheduler.

## Python methods

These methods are internal application interfaces. A project integration should
publish the reporting schema. It does not need to call these methods.

### `tower.chart_tools`

| Method | Purpose and result |
| --- | --- |
| `finite(value)` | Check that a value is a finite number. Reject Boolean values. |
| `text(value, limit=96)` | Check printable, nonempty preference text. |
| `restore(saved)` | Return bounded, validated display and axis preferences. |
| `valid_axis(axis)` | Check the scale mode and finite limits. |
| `display(state, name)` | Return the display label, declared unit, and precision. |
| `preference(state, name)` | Return the source unit and explicit metric preferences. |
| `format_value(value, preference)` | Format a value without changing its numeric data. |
| `axis_values(values, axis)` | Return plot coordinates, limits, and the nonpositive log sample count. |
| `percentile(sorted_values, fraction)` | Calculate an interpolated percentile from sorted known values. |
| `statistics_for(points, full_points=None)` | Calculate sample statistics and observed-interval coverage. Supply normalized points in timestamp order. |
| `interval(points, state, name)` | Select source timestamps between the stored interval endpoints. |

### `tower.charts`

All drawing methods return rows of `(text, style)` segments. They do not perform
file or process I/O. Use `Glyphs(True)` for ASCII output.

| Method | Purpose and result |
| --- | --- |
| `resample(values, width, how="mean")` | Compress samples to mean or maximum buckets. Keep unknown buckets. |
| `envelope_points(values, width)` | Retain first, minimum, maximum, and last samples in each equally spaced bucket. |
| `fmt_num(value, unit="")` | Format a compact numeric label. |
| `time_axis(t0, t1, width, ...)` | Draw timestamp or elapsed-time labels. |
| `vbar_chart(g, values, width, height, ...)` | Draw a filled area graph with scale labels and optional timestamps. |
| `hbar_rows(g, items, width, ...)` | Draw horizontal bars with measured values. |
| `braille_chart(g, values, width, height, ...)` | Draw connected opaque Unicode quadrant strokes or equivalent ASCII strokes. The historical method name remains compatible. |
| `heatmap(g, matrix, width, ...)` | Draw a shared-scale measured matrix. Mark unknown cells. |
| `stacked_bar(g, items, width, ...)` | Draw a composition bar with a numeric legend. |
| `histogram(g, values, bins, width, ...)` | Count values in specified bins and draw horizontal bars. |
| `gantt(g, jobs, t0, t1, width, ...)` | Draw observed queue and run intervals. |
| `summary_line(g, parts, indent=" ")` | Join styled summary values into a row. |

`vbar_chart` and `braille_chart` accept `envelope=True` to preserve extremes.
Use `envelope=False` only when a mean representation is intended. Their optional
`axis_formatter` formats plotted coordinates; their `sample_times` and
`sample_interval` preserve actual time spacing and known sampling outages.

### `tower.chart_interaction`

The interaction layer reads published plot geometry. It performs no file or scheduler I/O.
Renderers begin one outer frame, stage local plots, map them through the final layout,
then publish the visible geometry. A `Rect` uses exclusive `(top, left, bottom, right)` edges.
Zoom bounds use plotted coordinates; logarithmic vertical bounds remain base-10 logarithms.

| Method | Purpose and result |
| --- | --- |
| `initialize(app)` | Create bounded transient pointer, capture, and zoom state. |
| `key(app, metric, source, jid=None, ...)` | Identify the exact source, job, and run attempt without truncating paths. |
| `begin_frame(app, width=None, height=None)` | Start the outer frame and clear pending geometry. |
| `mark(app)` | Record the first pending plot for a nested renderer. |
| `record(app, identity, metadata, ...)` | Stage the plot rectangle and axis bounds in local cells. |
| `place_since(app, first, dy=0, dx=0, clip=None)` | Translate and clip the nested plots after layout. |
| `take_since(app, first)` | Detach a layout candidate so discarded probes publish no plots. |
| `put_records(app, records)` | Restore the selected layout candidate's geometry. |
| `map_records(records, mapping, ...)` | Map plots through wrapping and sticky headers; reject disordered plot rows. |
| `publish(app, width=None, height=None)` | Freeze the final visible geometry and validate capture. |
| `hover(app, y, x)` | Update cosmetic pointer feedback from the published plots. |
| `active(app)` | Report whether a rectangular drag is active. |
| `tick(app, now=None)` | Cancel stale, blocked, or timed-out capture. |
| `cancel(app)` | Discard an unfinished preview without changing completed zoom. |
| `handle_mouse(app, y, x, button="left", shift=False)` | Apply plot press, motion, and valid-release controls. |
| `bounds(app, identity, scale=None)` | Return completed source-specific display bounds. |
| `undo(app, identity=None)` | Restore the previous rectangular view. |
| `reset(app, identity=None)` | Remove rectangular zoom for the selected source. |
| `handle_key(app, key)` | Apply cancellation, undo, and reset controls in plot context. |
| `command_names()` | Return the interaction command names. |
| `run_command(app, args)` | Apply `chartzoom undo` or `chartzoom reset`. |
| `feedback(app, ascii_=None)` | Return the bounded crosshair or rectangle feedback overlay. |
| `overlay(views, snap, app, width, height)` | Return no full modal overlay; feedback belongs to the current plot. |

### `tower.metric_live`

This layer uses published exact-job status and chart geometry.
It changes display state without source reads or scheduler requests.
A filled companion uses the same canonical identity as its resource curve.

| Method | Purpose and result |
| --- | --- |
| `initialize(app)` | Create bounded, transient per-metric duration and control state. |
| `canonical(identity)` | Share a resource area's Live identity with its source curve. |
| `fraction(delta)`, `delta_at(value)` | Convert between durations and the logarithmic slider position. |
| `format_delta(value)` | Format the duration in seconds or milliseconds. |
| `set_running(app, identity, running)` | Publish exact source eligibility and stop a finished source. |
| `window(app, identity, now=None)` | Return the active display interval, or the captured plot's fixed mapping. |
| `enabled(app, identity)` | Check that Live is enabled for the current running source. |
| `set_enabled(app, identity, value)` | Toggle Live and clear its rectangular zoom when enabling it. |
| `stop_for_zoom(app, identity)` | Stop Live after a valid rectangular zoom. |
| `set_delta(app, identity, value)` | Set a finite duration from 0.001 to 5 seconds. |
| `controls(g, app, identity, width, ...)` | Render and stage the running metric's control row. |
| `publish(app, records)` | Freeze controls after final layout transformation. |
| `descriptors(app)` | Return visible toggle and slider actions for the control graph. |
| `active(app)`, `cancel(app)`, `tick(app, now=None)` | Check capture, restore a cancelled duration, and reject stale capture. |
| `handle_mouse(app, y, x, button="left", shift=False)` | Handle the toggle and slider press, drag, and release. |
| `handle_key(app, key)` | Apply keyboard slider steps and cancellation. |
| `command_names()`, `run_command(app, args)` | Expose and apply temporary-token Live and duration commands. |
| `document_revision(app)`, `document_interval(app)` | Report changed display state and the active display-refresh deadline. |
| `feedback(app, g)` | Return the small control-row overlay between document refreshes. |
| `overlay(views, snap, app, width, height)` | Return no full modal overlay. |

### `tower.analysis_ui`

| Method | Purpose and result |
| --- | --- |
| `initialize(app)` | Create bounded analysis state. |
| `restore(app, ui)` | Restore preferences and reject malformed saved values. |
| `save(app)` | Return persistent preferences without a live modal or job selection. |
| `command_names()` | Return the analysis command names for the command palette. |
| `dashboard_names(app, series)` | Return visible metric IDs in dashboard order. |
| `observe_metrics(app, result, jid)` | Record an observed, timestamped phase change. |
| `memory_series(app, jid)` | Read bounded in-memory resource samples. No file is loaded. |
| `chart_data(app, snap)` | Select published application metrics or session resource samples. |
| `viewport(points, state, normalized=False)` | Select the current time window. Set `normalized=True` only for validated, timestamp-sorted points. |
| `chart_rows(g, app, points, width, height, ...)` | Draw the chart, exact sample, scale, selected interval, and source status. Pass `snapshot` to reuse the published frame. |
| `chart_events(app, snap, times=None)` | Return observed events for the pinned chart job, with original citations. |
| `event_markers(g, events, times, width)` | Draw timestamp-aligned event marks. |
| `open_inspector(app, jid=None)` | Open an active, recent, or historical job by its exact ID. |
| `timeline_events(app, snap)` | Collect bounded, deduplicated published observations. |
| `passport_rows(g, passport, differences=None, ...)` | Draw passport data and substantive differences. |
| `run_command(app, args)` | Validate and execute an analysis command. Return whether it was handled. |
| `handle_key(app, key)` | Apply context-specific chart or analysis controls. |
| `overlay(views, snap, app, width, height)` | Draw the active analysis overlay from published data. |
