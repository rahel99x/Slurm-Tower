# Contributing to Slurm Tower

Small fixes, cluster compatibility improvements, accessible visual design, and
clearer documentation are welcome. Open an issue for a substantial change so the
scope can be discussed before implementation.

## Start locally

```bash
git clone https://github.com/rahel99x/Slurm-Tower.git
cd Slurm-Tower
python3 scripts/setup.py --mode demo --dev --test
./scripts/tower --fake
.venv/bin/python -m build
```

Use a feature branch for your change. Keep the runtime dependency-free and compatible
with Python 3.10+. The demo backend makes development possible without an HPC account.
Test targeted behavior while iterating, then run `.venv/bin/python -m pytest -q`
before opening a pull request. CI also builds and smoke-tests the wheel.

## What makes a useful contribution

- Explain the problem, resulting behavior, and how you verified it in your pull request.
- Add a regression test for a bug or a meaningful new behavior. Use synthetic or sanitized Slurm output.
- Preserve confirmation before destructive job actions, bounded command timeouts, and source backoff.
- Keep charts readable without color; include units, empty states, and narrow-terminal behavior.
- Keep the application terminal-only with ASCII charts and plain-text reports; sanitize terminal control characters in untrusted text.
- Document flags and configuration changes in the runbook or reference.

Never include SSH keys, credentials, personal config, real job logs, or private
cluster information in an issue, fixture, or terminal capture. Report security issues
through the process in [SECURITY.md](SECURITY.md).

The [reference](docs/reference.md#architecture) maps the modules. Pure layout and
parsing functions sit alongside the store, sampler, controller, terminal renderer,
and ASCII report renderer; tests can exercise most behavior without curses or a live cluster.

By contributing, you agree that your contribution is available under the project's
[MIT license](LICENSE). Retain attribution when adapting third-party code.
