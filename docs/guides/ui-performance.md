# Display and input performance

[README](../../README.md) · [Mouse and button navigation](pointer-navigation.md) · [Reference](../reference.md)

Tower 4.3.1 improves pointer feedback and long inline views.
Hover, smooth scrolling, drag selection, menus, and live job updates remain available.
The display changes do not increase Slurm sampling rates.

## Check pointer feedback

1. Open Jobs.
2. Move the pointer across job rows and Details buttons.
3. Check that the highlight follows the pointer.
4. Click a job and open Analytics → Advisor in Details.
5. Scroll down, reverse direction, and scroll to the first row.
6. Enter a command immediately after scrolling.

**Expected result:** Pointer feedback follows the latest reported position.
Scrolling responds to the new direction without replaying old movements.
The next command remains available after a scroll burst.
Hover does not select a job or execute a button.

Use `:terminaltest` when the terminal does not report movement, wheel, drag, or release events.
Press Esc to leave the test.
See [Mouse and button navigation](pointer-navigation.md) for the complete controls.

## Keep the display responsive

Tower retains the last published page while pointer feedback changes.
It updates the affected terminal rows instead of rebuilding the whole page for each movement report.
The page still refreshes for changed data, deliberate input, resize, and active animations.
Continuous pointer movement does not postpone background-result publication.

The control graph indexes visible rows and control identities.
Advisor results and wrapped Details documents reuse their current published inputs.
These results update when their measurements, settings, selected job, or available width change.
Metric charts retain bounded prepared data for the current view.
Caches have fixed bounds and do not retain unlimited jobs, views, or terminal sizes.

Clicks, keyboard commands, and mouse releases retain their input order.
Drag selection keeps exact job IDs.
Cancellation still requires its normal review.
Log selections and copies retain their exact source positions and bytes.

Use the top-right update slider or `:rate N` to change source sampling.
Use `:smoothscroll off` to request immediate wheel movement.
These settings control different operations.
Disabling smoothing does not make Slurm commands complete sooner.

## Use a limited-throughput connection

1. Use `:smoothscroll off` if intermediate scrolling frames exceed the connection's display throughput.
2. Use `:theme reader` for plain ASCII text and static notices.
3. Keep the source rate appropriate for the cluster and connection.
4. Check Sources for slow commands, unavailable data, or retry backoff.

**Expected result:** Tower uses immediate viewport movement and a simpler display.
The requested source rate remains subject to source minimum intervals and backoff.

Terminal rendering, SSH transport, tmux, and Slurm command duration can each add delay.
The display optimizations reduce Tower's repeated work.
They do not impose a universal response-time guarantee.

## Release measurements

The release comparison used Tower 4.3.0 at `98b2d86` and the final 4.3.1 source.
Both revisions used Python 3.12 on the same Linux cloud runner.
Each pair ran sequentially with the same fixtures and options.

The public benchmark measured UI computation with a counting paint sink.
It used a 160-column by 48-row Unicode display and eight measured frames per case.
The following values are median frame times.
They exclude terminal transport and scheduled waiting.

| Workload | 4.3.0 | 4.3.1 |
| --- | ---: | ---: |
| Hover with 1,000 jobs | 54.29 ms | 0.13 ms |
| Hover with Advisor and 10,000 accounting records | 1,224.11 ms | 0.17 ms |
| Advisor wheel frame with 10,000 accounting records | 1,904.62 ms | 37.21 ms |
| Research refresh with 64 metrics and 10,000 points per metric | 152.34 ms | 28.10 ms |

A separate local pseudo-terminal test measured input processing through `curses.doupdate()`.
It used `screen-256color`, a 120-column by 36-row Unicode display, 500 jobs, and 2,000 accounting records across 128 names.
Eight jobs were running.
The linked project contained 64 metrics and 256 records.
A compact observation record followed each display update in both revisions.

| Input workload | 4.3.0 | 4.3.1 |
| --- | ---: | ---: |
| Final hover after 1,000 movement reports | 1,928.77 ms | 51.94 ms |
| Command after 1,000 movement reports | 7,226.90 ms | 635.95 ms |
| Accept the target from 700 wheel reports in Advisor | 2,958.29 ms | 563.95 ms |
| Reverse through 820 wheel reports, then complete a focus command | 9,142.47 ms | 793.37 ms |

The hover row is the median of three bursts.
The other terminal rows describe one observed burst each.
The forward-wheel row measures target acceptance; optional smooth motion settles afterward.
The keyboard rows require the command's visible state change after the queued reports.
These local pseudo-terminal times exclude SSH transport and terminal-emulator presentation.

Additional terminal checks used 80, 120, and 180 columns in Unicode and ASCII.
They checked drag release, resize, reversed scrolling, and keyboard input.
Actual fixture job completion and new metric publication remained visible during continuous pointer movement.
No scheduler-changing command ran in the tests.

## Validate a source change

Use the reproducible benchmark to measure UI work on your computer:

```bash
python3 scripts/benchmark_ui.py \
  --scenario advisor --gesture hover \
  --jobs 500 --history 2000 --width 120 --height 36 \
  --glyphs both --repeats 20 --output advisor-hover.json

python3 scripts/benchmark_ui.py \
  --scenario advisor --gesture wheel \
  --jobs 500 --history 2000 --width 120 --height 36 \
  --glyphs both --repeats 20 --output advisor-wheel.json
```

The benchmark uses synthetic data in memory.
It does not connect to Slurm or read personal configuration.
Its times exclude terminal and network transport.
The report includes median and 95th-percentile frame times, work counts, and attempted I/O.
Use identical options on the same computer when comparing revisions.
Use `--scenario research --metrics 64 --points 10000` to exercise metric charts.
Use `--gesture render` to measure a full document refresh.
Use `--source-root PATH --label REVISION` to benchmark a separate source checkout.

Run the focused regression checks from the repository:

```bash
python3 scripts/setup.py --mode demo --dev
.venv/bin/python -m pytest -q \
  tests/test_hover_render_budget.py \
  tests/test_responsive_input.py \
  tests/test_ui_state_budget.py \
  tests/test_workspace_render_budget.py \
  tests/test_advisor_render_budget.py \
  tests/test_chart_render_budget.py \
  tests/test_table_filter_budget.py
```

The checks cover bounded work, cache invalidation, input ordering, and continued publication.
Use [Contribution guidance](../../CONTRIBUTING.md) for the complete test suite.
Validate mouse behavior in an actual interactive terminal after changing input or painting code.
Include narrow and wide terminals, Unicode and ASCII, and tmux-compatible terminal types.
