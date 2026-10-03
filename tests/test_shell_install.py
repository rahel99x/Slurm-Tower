"""Exercise actual Bash expansion and preservation of personal configuration."""
import importlib.util
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tower_install_shell", ROOT / "scripts/install_shell.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_alias_preserves_argument_boundaries_and_reads_current_account(tmp_path):
    root = tmp_path / "checkout with 'quotes'"
    (root / "scripts").mkdir(parents=True)
    launcher = root / "scripts/tower"
    launcher.write_text('#!/bin/sh\nprintf "%s\\0" "$@"\n')
    launcher.chmod(0o755)
    block = tmp_path / "shell block"
    block.write_text(installer.shell_block(root))
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", '''shopt -s expand_aliases
tower() { return 99; }
dash2() { return 99; }
alias tower='false'
alias dash='false'
source "$1"
alias dash >/dev/null 2>&1 && exit 90
declare -F dash2 >/dev/null && exit 91
CARC_ACCOUNT="current account"
tower --once --tab history "argument with spaces"
''', "bash", str(block)], capture_output=True, text=True,
        env={**os.environ, "TOWER_CONFIG": "", "SLURM_TOWER_PROFILE": ""},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split("\0")[:-1] == [
        "--config", str(root / "docs/config.example.json"), "--profile", "carc", "--ascii",
        "--account", "current account", "--once", "--tab", "history", "argument with spaces",
    ]


def test_real_alias_uses_the_project_launcher_from_another_directory(tmp_path):
    block = tmp_path / "alias.bash"
    block.write_text(installer.shell_block(ROOT))
    result = subprocess.run(["bash", "--noprofile", "--norc", "-c", '''shopt -s expand_aliases
source "$1"
tower --fake --doctor
''', "bash", str(block)], cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, "CARC_ACCOUNT": "", "TOWER_CONFIG": "", "SLURM_TOWER_PROFILE": ""}, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "Prerequisites ready" in result.stdout


def test_update_backs_up_and_preserves_unrelated_settings_and_is_repeatable(tmp_path):
    path = tmp_path / ".bashrc"
    original = b"export KEEP='unchanged'\nalias dash='old-dashboard'\nalias tower='old-tower'\nalias other='echo keep'\n"
    path.write_bytes(original)
    path.chmod(0o640)
    assert installer.main(["--bashrc", str(path), "--apply"]) == 0
    result = path.read_text()
    assert result.startswith(original.decode())
    backups = list(tmp_path.glob(".bashrc.slurm-tower-*.bak"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert path.stat().st_mode & 0o777 == 0o640
    assert installer.main(["--bashrc", str(path), "--apply"]) == 0
    assert path.read_text() == result and list(tmp_path.glob(".bashrc.slurm-tower-*.bak")) == backups


def test_preview_never_replaces_original_or_existing_output(tmp_path):
    path = tmp_path / ".bashrc"
    path.write_text("export KEEP=yes\n")
    preview = tmp_path / "preview"
    assert installer.main(["--bashrc", str(path), "--output", str(preview)]) == 0
    assert path.read_text() == "export KEEP=yes\n"
    assert preview.stat().st_mode & 0o777 == 0o600
    assert installer.main(["--bashrc", str(path), "--output", str(preview)]) == 1


def test_invalid_shell_and_malformed_managed_blocks_leave_config_untouched(tmp_path):
    path = tmp_path / ".bashrc"
    for original in ["if then\n", installer.BEGIN + "\nunfinished\n"]:
        path.write_text(original)
        assert installer.main(["--bashrc", str(path), "--apply"]) == 1
        assert path.read_text() == original
        assert not list(tmp_path.glob("*.bak"))


def test_apply_preserves_a_bashrc_symlink(tmp_path):
    target = tmp_path / "dotfiles/bashrc"
    target.parent.mkdir()
    target.write_text("export KEEP=yes\n")
    link = tmp_path / ".bashrc"
    link.symlink_to(target)
    assert installer.main(["--bashrc", str(link), "--apply"]) == 0
    assert link.is_symlink() and installer.BEGIN in target.read_text()
