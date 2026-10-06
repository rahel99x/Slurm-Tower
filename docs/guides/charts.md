# Read and adjust charts

Tower draws charts with terminal characters. Unicode mode uses a dot raster and
block graphs. ASCII mode uses an area graph and range marks. Both modes use the
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
Unicode mode draws the range with its dot raster. ASCII mode marks the range
inside its area graph. If a bucket contains an unknown sample, the bucket stays
unknown. Tower does not draw a bridge through that bucket or a detected outage.

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
| `braille_chart(g, values, width, height, ...)` | Draw a high-resolution Unicode curve or the ASCII area equivalent. |
| `heatmap(g, matrix, width, ...)` | Draw a shared-scale measured matrix. Mark unknown cells. |
| `stacked_bar(g, items, width, ...)` | Draw a composition bar with a numeric legend. |
| `histogram(g, values, bins, width, ...)` | Count values in specified bins and draw horizontal bars. |
| `gantt(g, jobs, t0, t1, width, ...)` | Draw observed queue and run intervals. |
| `summary_line(g, parts, indent=" ")` | Join styled summary values into a row. |

`vbar_chart` and `braille_chart` accept `envelope=True` to preserve extremes.
Use `envelope=False` only when a mean representation is intended. Their optional
`axis_formatter` formats plotted coordinates; their `sample_times` and
`sample_interval` preserve actual time spacing and known sampling outages.

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
