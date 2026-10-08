# Mouse and button navigation

[README](../../README.md) · [Controls](../CONTROLS.md) · [Live workbench](live-workbench.md)

Use this guide for Tower 4.4.0's mouse feedback, button navigation, scrolling, and startup display.
All controls remain inside the terminal.

## Check terminal mouse support

1. Start Tower in an interactive terminal.
2. Move the pointer over a page label or button.
3. Check that the control highlights.
4. Click the control to activate it.
5. Open `:terminaltest` if the terminal does not report the expected input.
6. Press Esc to leave the test.

**Expected result:** The pointer highlights the control beneath it without changing the selected job or file.
Hover feedback requires a terminal that reports pointer movement.
Clicks and drag reports also depend on the terminal's mouse support.
The `mouse` configuration field must be `true`.

Tower updates cosmetic pointer feedback from the last published page.
It paints changed rows while data, actions, and resize still refresh the page.
Continuous movement does not postpone live results.
See [Display and input performance](ui-performance.md) for validation and connection limits.

Run `:terminaldoctor` to inspect terminal settings and connection evidence.
Check the terminal emulator and any intervening SSH or tmux session when events are missing.
Use keyboard controls when the terminal cannot report pointer movement.
An ordinary SSH connection can carry supported terminal mouse events.

## Select controls with the keyboard

Tower builds directional connections between the visible controls in the current display.
The connections follow the controls' positions and groups.
They update when the page, layout, menu, or terminal size changes.

1. Press F8 to focus the visible buttons and links.
2. Use arrow keys to select a nearby control in that direction.
3. Press Enter or Space to activate the focused control.
4. Press Esc to return arrow keys to the page content.

**Expected result:** A visible focus indicator identifies the control that Enter will activate.
Arrow movement does not execute the focused control.
Home and End select the first and last visible controls.
Tab and Shift-Tab traverse the visible controls in order while button focus is active.

Use `:focusbuttons on` or `:focusbuttons off` to select the same focus mode.
Use `:focusbuttons` to toggle it.
Click an ordinary button to keep button focus available for arrow navigation.
Click content or scroll to restore the content's normal controls.
Menus retain their F10 navigation and the slider retains its own keyboard controls.

Focus reaches controls that are visible in the current frame.
Scroll the content or use its page controls to reach further items.
The same activation rules apply to mouse clicks and keyboard activation.
Job-changing controls still require their normal review.

Click a column-editor checkbox to show or hide its optional column.
Required identity and state columns stay visible.
Use the editor's width and order controls to adjust those required fields.

Click a Chart Events or Timeline row to open its exact painted job or log citation.
Use `:timeline open EVENT_NUMBER` for the numbered current timeline event.
Event numbers start at one.
The existing `:timeline seek EVENT_NUMBER` command remains the replay-seeking operation.

## Adjust the update slider by dragging

1. Press the left mouse button on the top-right slider track.
2. Keep the button pressed and move the pointer horizontally.
3. Release the button at the required multiplier.

**Expected result:** The multiplier follows the pointer between 1x and 50x.
Dragging changes the requested fetching rate during the session.
It keeps source minimum intervals and retry backoff.

Use a direct track click when the terminal does not report dragging.
Use the wheel, `[-]` and `[+]`, or `:rate N` for exact one-step or numeric control.
See [Update rate](live-workbench.md#set-the-update-rate) for source limits and saved preferences.

## Resize a panel by dragging

Press the grey divider or one cell beside it.
Keep the left mouse button pressed, move it to the required position, then release it.
The full vertical divider has a centred blue diamond.
The horizontal divider above Recents changes its share of Jobs Main.
Press Esc during the drag to restore the starting size.
Page, dialog, and terminal-size changes also end capture and restore that size.

Click a divider to focus keyboard adjustment.
Use arrows along its movement axis, or Page Up and Page Down, then Enter or Esc to return to the page.
F8 navigation and `:pane-focus KEY` can focus the same control.
See [Panel dividers](adaptive-workspaces.md#change-panel-size) for complete commands, layout bounds, and persistence.

## Use a menu for several changes

1. Click File, Edit, View, or Help.
2. Move the pointer over a menu choice.
3. Click a choice to activate it.
4. Keep the pointer inside the dropdown to select another available choice.
5. Move the pointer outside the dropdown to dismiss it.

**Expected result:** A direct setting or navigation choice leaves the menu available for the next change.
An editable prompt or action review remains beneath the dropdown until you dismiss the menu.
Then use that dialog's controls to complete or cancel the operation.
Esc and F10 also dismiss a menu.

The toolbar label row also permits switching between menus without dismissal.
Clicks or releases outside the dropdown do not activate a hidden page control.
The menu's hover highlight identifies the choice beneath the pointer.
Hover does not execute that choice.
Use the menu's Up and Down keys to select choices without a mouse.
See [Toolbar menus](live-workbench.md#use-the-terminal-toolbar) for every menu choice.

## Mark several jobs by dragging

1. Press the left mouse button on a visible job row.
2. Keep the button pressed and move through the required rows.
3. Release the button to complete the marked range.
4. Press `c` when you need to review cancellation of the marked jobs.
5. Check every target ID before confirming the review.

**Expected result:** The marked range follows the table's current displayed order.
Sorting and filtering define that order.
A simple click continues to select one row without starting a range.
Hold Shift during a drag to add the range to existing marks.
Press Esc before release to cancel capture and restore the previous marks.
Runtime header changes do not add a job beneath a stationary pointer.
Resizing the terminal stops the drag and keeps its marked job IDs.

Marking jobs does not cancel them.
Supported group actions use the existing marked IDs and their normal review.
Range dragging is available for job rows in Jobs, Recents, History, Group, and Dependencies.
The terminal must report mouse press, movement, and release for a drag.
Use Space to mark individual jobs when those events are unavailable.

## Scroll without delayed input

Mouse-wheel scrolling moves the viewport toward the latest requested position.
Successive wheel events update that target.
Tower does not replay a long queue of old scroll movements after reaching an edge.
Changing direction updates the target immediately.

Keyboard arrows, page keys, Home, End, clicks, and copy operations retain immediate, exact positioning.
Scrolling does not increase the scheduler fetching rate.
Use the update slider separately when you need more frequent data sampling.

Use `:smoothscroll off` to disable viewport interpolation.
Use `:smoothscroll on` to restore it.
Use `:smoothscroll` or `:smoothscroll toggle` to change the current preference.
The View menu provides Enable smooth scrolling or Disable smooth scrolling.
The top-level `smooth_scrolling` configuration field sets its launch default.
Normal UI state retains the preference for the current profile and connection.

The reader theme and `animations = false` use immediate viewport movement.
These settings preserve mouse-wheel scrolling.
Static operation is useful when a terminal connection has limited display throughput.

## Control the startup display

Tower can show a short Unicode welcome animation when an interactive curses session starts.
The ASCII mode uses a compact static welcome.
One-frame output, JSON, scripts, and ANSI watch output do not show this display.

Use `:startup off` to disable the startup display.
Use `:startup on` to enable it.
Use `:startup toggle` to change the preference.
Use `:startup` to inspect the preference without changing it.
Use `:startup preview` to view it without changing the saved preference.
The View menu provides Enable startup animation, Disable startup animation, and Preview startup animation.

The top-level `startup_animation` configuration field sets the launch default.
Normal UI state retains the enabled preference for the current profile and connection.
The reader theme and `animations = false` suppress the startup display.
Very small terminals also skip it.
The Unicode welcome lasts less than one second.
ASCII mode shows its static welcome for about half a second.

Press a key, click, or use the wheel to dismiss the display immediately.
Tower then performs that input's normal action.
Pointer movement alone leaves the display running.
The welcome does not change sampler intervals or delay job actions behind an animation queue.

## Resolve an input problem

| Symptom | Action |
| --- | --- |
| Clicks work, but controls do not highlight under the pointer | Check movement reports with `:terminaltest`; the terminal must support pointer tracking |
| Slider clicks work, but dragging does not | Check drag reports; use `:rate N` or keyboard slider controls |
| Dragging does not mark job rows | Check press, movement, and release reports; use Space to mark individual jobs |
| Arrow keys move between buttons instead of content | Press Esc or `:focusbuttons off` |
| Arrow keys move content instead of buttons | Press F8 or `:focusbuttons on` |
| A menu hides before another toggle | Keep the pointer inside the visible dropdown; dismiss it before editing a prompt or completing a review |
| Scrolling produces too many intermediate frames | Use `:smoothscroll off` or the reader theme |
| The welcome does not appear | Check `:startup`, the theme, `animations`, terminal size, and launch mode |

Use [Controls](../CONTROLS.md) for complete key and command syntax.
Use [Live workbench](live-workbench.md) for inline Jobs views and persistent menu procedures.
