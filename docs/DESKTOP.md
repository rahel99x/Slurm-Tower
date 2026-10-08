# Run Tower on a Fedora desktop

[README](../README.md) · [Runbook](runbook.md) · [Controls](CONTROLS.md)

Use this guide when Slurm is already installed directly on Fedora.
Run Tower in a terminal as your normal desktop user.
Tower uses the existing Slurm controller and command-line tools.

## 1. Check the local environment

Run these checks in your desktop terminal:

```bash
python3 --version
python3 -c 'import curses, venv; print("Python terminal modules are available")'
git --version
command -v squeue
command -v scontrol
command -v sinfo
command -v sacct
command -v sstat
scontrol ping
sinfo
squeue -u "$USER"
```

**Expected result:** Python is version 3.10 or later.
The Python module check succeeds.
Slurm commands resolve to the local installation.
The scheduler responds to the read-only checks.

An empty `squeue` result is normal when your user has no jobs.
A scheduler connection error requires attention to the existing Slurm installation.
Tower setup does not start or configure Slurm services.

If Git or Python is missing, install those Fedora packages:

```bash
sudo dnf install git python3
```

Use your site's installation process when package installation is managed.
Continue with your normal user after installing the missing tools.
Use a Python build with curses and venv support.
Normal Tower setup does not download runtime packages.

## 2. Get or update the checkout

For a new checkout:

```bash
git clone https://github.com/rahel99x/Slurm-Tower.git
cd Slurm-Tower
```

For an existing checkout:

```bash
cd /path/to/Slurm-Tower
git pull --ff-only
```

Replace `/path/to/Slurm-Tower` with your actual checkout path.
Resolve local Git changes if the update fails.
Keep existing configuration and state files.

## 3. Select the desktop profile

Run setup from the checkout:

```bash
python3 scripts/setup.py --mode local --profile desktop
```

**Expected result:** Setup checks local capabilities and prints a desktop launch command.
Setup also validates simulated displays and writes its demonstration report.
The demonstration report does not replace live scheduler data.

The `desktop` profile is defined in `docs/config.example.json`.
It clears configured host, user, account, and partition restrictions.
It therefore uses local Slurm commands and normal identity detection.

| Setting | Desktop profile |
| --- | --- |
| Job sampling | Every 2 seconds |
| Live resource sampling | Every 5 seconds |
| Accounting sampling | Every 10 seconds |
| Partition display | All reported local partitions, including idle CPU-only partitions |
| Live GPU sampling | Disabled |
| Queue forecast probes | Disabled |
| Allocation-budget queries | Disabled |
| Display | Unicode preference, with ASCII fallback |

Use `--profile desktop` explicitly for setup.
The default setup profile remains `carc` for existing CARC installations.
Profile selection does not create a scheduler account or partition.
The profile enables `show_all_partitions`.
A nonempty configured `partitions` list still restricts the displayed partitions.

### Keep desktop state separate

The desktop profile selects `state_namespace = "desktop"`.
Tower stores desktop preferences, log bookmarks, job tags, and recorded resource samples separately from CARC state.
Existing CARC state is retained.

The default desktop state path is:

```text
~/.local/state/tower/profiles/desktop/<connection_digest>/
```

The digest identifies the connection, scheduler user, local owner, and profile.
This separation prevents another cluster's saved filters or reused job IDs from affecting desktop records.
Use the [state configuration reference](reference.md#configuration) for custom namespaces and base paths.

## 4. Install the `tower` alias

```bash
python3 scripts/install_shell.py --profile desktop --apply
source ~/.bashrc
type tower
```

**Expected result:** `tower` uses this checkout's launcher and the desktop profile.
The helper backs up `.bashrc` before it changes the managed alias block.
It replaces old `tower`, `dash`, and `dash2` definitions.
It preserves the rest of the file.

Use this command to preview the block without changing `.bashrc`:

```bash
python3 scripts/install_shell.py --profile desktop
```

Keep the checkout at its current location.
Rerun the helper if you move it.
The launcher uses its own `.venv` when that environment exists.

### Account and profile overrides

The desktop alias ignores `CARC_ACCOUNT`.
Use `SLURM_TOWER_ACCOUNT` for an explicit desktop account override:

```bash
export SLURM_TOWER_ACCOUNT=YOUR_SLURM_ACCOUNT
tower
```

Replace `YOUR_SLURM_ACCOUNT` with a configured Slurm account.
Use `unset SLURM_TOWER_ACCOUNT` to restore normal account detection for desktop.
Use `tower --account ACCOUNT` to override the account for one invocation.

`SLURM_TOWER_PROFILE` overrides the profile selected during alias installation.
`SLURM_TOWER_ACCOUNT` applies to any resolved profile.
The CARC alias uses `CARC_ACCOUNT` only when the generic override is unset.
An explicitly empty `SLURM_TOWER_ACCOUNT` suppresses that legacy account injection.

A custom `TOWER_CONFIG` also overrides the alias's example configuration path.
That custom file must define the selected profile.
Use the direct launcher below to check the supplied desktop configuration independently.

## 5. Verify real desktop data

```bash
tower --version
tower --doctor
tower --once --tab jobs
tower --once --tab sources
tower
```

**Expected result:** Jobs reflects `squeue -u "$USER"`.
Sources reports actual command status, freshness, latency, and errors.
Press `?` for help.
Press `q` to exit.

To bypass an alias or custom configuration override, run:

```bash
./scripts/tower --config docs/config.example.json --profile desktop --doctor
./scripts/tower --config docs/config.example.json --profile desktop --once --tab sources
./scripts/tower --config docs/config.example.json --profile desktop
```

Do not use `--fake` to verify desktop scheduler data.
That option selects simulated data.
An empty Jobs table is normal when no jobs are running or pending for your user.

### Read accounting availability correctly

A local Slurm installation can run jobs without an accounting backend.
In that installation, `sacct` can be present while its queries are unavailable.
History and completed-job efficiency then remain unavailable or empty.
Sources reports the accounting error.
Tower does not manufacture completed jobs to fill History.

If Sources shows `finished: sacct: error: Slurm accounting storage is disabled`,
the scheduler has no active accounting storage backend.
Installing the `sacct` command alone does not enable that backend.
Follow [Enable Slurm accounting on a Fedora desktop](FEDORA_ACCOUNTING.md)
to add persistent job history with MariaDB and `slurmdbd`.

To stop unavailable accounting queries for the current Tower session,
enter `:source finished off` and `:source fin_details off` in the command palette.
These source toggles do not persist across Tower restarts.
They suppress the queries; they do not supply completed-job history.

When accounting is delayed, Recents can show jobs as awaiting accounting.
That status does not prove success or failure.
Keep the exact job's logs for application evidence.
Use the [project reporting standard](PROJECT_STANDARD.md) to retain explicit run and log identities.

## 6. Adjust the terminal and profile

Use a UTF-8 locale and a compatible monospace font for block graphics.
Try the portable display if characters are misaligned:

```bash
tower --ascii --no-color
```

Use `:terminaldoctor` for terminal and path evidence.
Use `:terminaltest` to check glyphs, keys, and mouse input.
Use `:settings` to adjust display preferences and active sampling intervals.

### Use live inspection controls

Select a job in Jobs or Recents.
Click Inspector, Logs, Investigate, Research, or Analytics in Details to inspect that job in place.
Select Off to hide the inspection content.
Use `:jobpanel focus` for keyboard entry.
The selected job and available files update during the session.
Research includes all twelve workspaces; Analytics includes all five subviews.
Choose a subview and scroll its content vertically.
Inline views fit the panel width without horizontal panning.

Press F8 to focus visible controls and use arrow keys to choose one.
Press Enter or Space to activate it, or Esc to return to content.
Hover highlights controls when the terminal reports pointer movement.
Drag visible job rows to mark a range; Shift preserves existing marks.
Review the complete target list before confirming a bulk action.

The top-right update slider requests a fetching multiplier from 1x to 50x.
Press and drag its track to adjust the multiplier.
Use `:rate` to inspect the active multiplier and effective Jobs interval.
Use `:rate N` to select a whole-number multiplier, or `:rate reset` to restore 1x.
The desktop Jobs interval starts at two seconds at 1x.
Source minimum intervals and retry backoff limit higher rates.
Sources shows the effective cadence.
See [Live workbench](guides/live-workbench.md) for the toolbar, controls, limits, and project reporting procedure.
Use `:smoothscroll off` for immediate wheel movement.
Use View → Disable startup animation or `:startup off` to suppress the welcome.
The reader theme and `animations = false` suppress both motion effects.
See [Mouse and button navigation](guides/pointer-navigation.md) for saved preferences and terminal input checks.

### Optional desktop clipboard

For a Fedora Wayland session, install the optional local clipboard helper:

```bash
sudo dnf install wl-clipboard
```

For an X11 session, use `sudo dnf install xclip` instead.
Run Tower as the user who owns that desktop session.
Tower detects these tools automatically.
Log selection uses `y`; complete log export uses `Y`.
If clipboard delivery is unavailable, the private exported file remains available in Activity and the export library.

Keep GPU sampling disabled until you choose to enable it for a valid allocation.
Live GPU sampling can create short `srun` steps.
The local desktop profile does not require GPU measurements for ordinary monitoring.

## 7. Use another scheduler environment

For Slurm inside a container, run Tower in the same container or scheduler namespace.
That environment must expose the Slurm commands and the referenced log paths.
Use your existing container entry procedure.

An existing SSH endpoint is another option when it can access the scheduler and logs:

```bash
./scripts/tower --config docs/config.example.json --profile desktop --host YOUR_SSH_ALIAS --doctor
./scripts/tower --config docs/config.example.json --profile desktop --host YOUR_SSH_ALIAS
```

Replace `YOUR_SSH_ALIAS` with a working alias from your SSH configuration.
Establish normal SSH access before you run the remote checks.

On Windows, use a suitable WSL environment with Python curses support.
Its Slurm command configuration must reach the intended scheduler.
A Slurm installation in another environment does not automatically configure WSL.
See [SSH transport](runbook.md#optional-ssh-transport) for remote prerequisites.

## 8. Troubleshoot desktop launch

| Symptom | Action |
| --- | --- |
| `tower` still uses the CARC profile | Rerun alias installation with `--profile desktop` and source `.bashrc` |
| An unexpected profile is selected | Inspect `SLURM_TOWER_PROFILE` |
| An unexpected account is selected | Inspect `SLURM_TOWER_ACCOUNT` and the invocation's `--account` value |
| A custom configuration has no desktop profile | Add that profile or use the direct example-config launcher |
| The scheduler connection fails | Compare `scontrol ping`, `sinfo`, and the error shown in Sources |
| Jobs is empty | Compare `squeue -u "$USER"` and the current table filters |
| History is empty or errors | Inspect `sacct` availability and the configured accounting backend |
| Source commands are unavailable | Use the terminal environment that exposes the existing Slurm installation |
| Log paths are unavailable | Run Tower where those paths exist or register exact accessible log locations |
| Unicode characters are misaligned | Use a compatible font or select `--ascii` |

Use the read-only checks in this guide to verify your existing desktop scheduler.
