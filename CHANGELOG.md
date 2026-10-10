# Changelog

## 4.14.0

Phase one adds measurement and submission checks while retaining the terminal
interface and optional-adapter architecture.

- Inspect Tower polling separately from Slurm collection capabilities.
- Select NVIDIA, AMD, or Intel GPU collection where the required vendor tool
  and allocation access are available.
- Run explicit local shell syntax checks and optional ShellCheck analysis
  without executing the batch script.
- Attach a validated scientific manifest to a Slurm array using actual task
  indices rather than submission order.
- Keep inspection-dialog mouse events isolated from hidden panes.
- Preserve fitted graph geometry during selection when retained samples expire.
- Keep the selected source visible in short panes and clear stale retry delays
  when the GPU provider changes.

See the [phase one guide](docs/guides/phase-one.md) for controls, data contracts,
and limits. The [roadmap](docs/ROADMAP.md) tracks the remaining proposals.

For earlier releases, see the [README release notes](README.md#changes-in-tower-4130).
