# Pointer input audit

[README](../../README.md) · [Pointer controls](pointer-navigation.md) · [Display performance](ui-performance.md)

Tower 4.8.2 corrects pointer routing and repeated display work across the application.
This guide records reproduced faults, tested fixes, and a manual check procedure.
The audit covers the shared input path and page-specific pointer handlers.
It does not establish that every terminal or future input sequence is free of faults.

## Reproduced faults and corrections

| Fault | Cause | Correction |
| --- | --- | --- |
| Movement opens Research | The decoder replayed legacy X10 coordinate bytes as keyboard input. An `r` coordinate activated the Research shortcut. | Decode SGR, X10, and urxvt mouse reports as pointer input. Discard malformed control sequences without replaying shortcut bytes. |
| A delayed click opens old content | A job, source, viewport, or pane changed after the hit map was published. | Bind activation to immutable hit contents, current geometry, and the exact job or source. |
| A double-click bypasses row validation | Follow-up activation used an old row without checking its horizontal location and current frame. | Validate the row before applying double-click activation. |
| Hover continues an old drag | A release report was lost before a known no-button report arrived. | End captures when the decoded protocol proves that no button is held. Preserve compatibility when native curses reports do not provide that evidence. |
| A new graph drag loses its release | A cancelled owner retained a release marker after another owner claimed the next press. | Clear old release markers before routing a new gesture. |
| Details activates another job's control | The action checked an old proxy identity without checking the current selected job. | Validate the current job and the visible Details rectangle. |
| Hover rebuilds the document | Uncaptured held-button reports were classified as content changes. | Treat those reports as cosmetic until a content capture requires an update. |
| Crosshair movement repeats large writes | Changed rows restored complete chart rows and many separate segments. | Compose the final cells and repaint changed runs. Restore wide and combining glyphs as complete characters. |
| Unchanged native charts rasterize repeatedly | Maintenance updates rebuilt the same measured curves. | Reuse bounded rasters keyed by complete data and rendering settings. Continue publishing current controls and source age. |
| Menus or drag handles use old geometry | Capture validation waited for the next paint. | Check context and geometry before handling the next event. |

The tests also cover invalid coordinates, changed nested hit payloads, sparse tall controls,
same-position drag reports, theme changes, overlays, and interrupted capture handoffs.
Pointer feedback performs no measurement-source I/O in the tested memory fixtures.
Scheduler actions retain their existing review step.

## Check the update in a terminal

**Prerequisites:** Install Tower 4.8.2 or later.
Use a terminal that reports pointer movement.

1. Open Jobs and select a running job.
2. Open Analytics → Job Series in Details.
3. Move the pointer repeatedly between job rows, the divider, and each graph.
4. Drag a graph interval and release inside its capture margin.
5. Right-click the graph to reset it.
6. Start another drag, press Esc, then start a new graph drag.
7. Resize the terminal and select another job.
8. Repeat movement in Analytics, Research, History, and Logs.
9. Enter a command after a burst of movement reports.

**Expected result:** Movement leaves the page and selected job unchanged.
The crosshair follows the latest reported cell.
Only a deliberate valid click activates a control.
Each new drag receives its own release.
Resizing or changing the source cancels a stale capture.
The command remains available after the movement burst.

Use `:terminaltest` to inspect missing movement, drag, or release reports.
Use `:terminaldoctor` to inspect terminal and connection settings.
Press Esc to leave the test.
See [display performance](ui-performance.md) for the synthetic benchmark and its limits.

## Run the regressions

Run the development tests from the source directory:

```bash
python3 -m pytest -q
```

Focused regression files include `test_mouse_protocol_safety.py`,
`test_hover_navigation_guards.py`, `test_mouse_capture_adversarial.py`,
`test_pane_hover_capture_safety.py`, `test_screen_cell_painter.py`,
and `test_native_metric_raster_cache.py` under `tests/`.
These tests exercise both ASCII and Unicode paths where applicable.
Installed-package checks exercise all main pages and Research views with synthetic Slurm data.
The tests do not require or modify a user's live scheduler jobs.

The 4.8.2 release check passed 8,949 tests on Python 3.12.
The installed wheel passed 44 ASCII and Unicode display checks and three native Slurm command-fixture checks.
Real curses input checks passed SGR, X10, and urxvt reports under `screen`, `screen-256color`,
`tmux-256color`, and `xterm-256color` terminal descriptions.
Runtime and launcher sources also passed a Python 3.10 grammar check.
These checks used a Linux cloud runner. They did not measure a live CARC or Fedora GPU allocation.
