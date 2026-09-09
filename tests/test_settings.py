import argparse
import os
import tempfile
from pathlib import Path

from node_audit.cli import normalize_argv, cmd_run
from node_audit.paths import app_dir, default_ini_path, default_out_dir, is_frozen
from node_audit.settings import load_settings, write_template_if_missing


def test_normalize_argv_empty_is_run():
    assert normalize_argv([]) == ["run"]
    assert normalize_argv(["--version"]) == ["--version"]
    assert normalize_argv(["audit", "--yes"]) == ["audit", "--yes"]
    assert normalize_argv(["run", "--yes"]) == ["run", "--yes"]


def test_not_frozen_in_tests():
    assert is_frozen() is False
    assert app_dir() == Path.cwd()
    assert default_out_dir() == Path.cwd() / "node-audit-report"
    assert default_ini_path() == Path.cwd() / "node-audit.ini"


def test_write_template_and_defaults():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "node-audit.ini"
        assert write_template_if_missing(p) is True
        assert p.is_file()
        assert write_template_if_missing(p) is False
        s = load_settings(p)
        assert s.mode == "isolated"
        assert s.include is None
        assert s.limit is None
        assert s.speed_bytes == "10MB"
        assert s.skip_speed is False
        assert s.deep == "auto"
        assert s.config_name is None
        assert s.open_report is True


def test_load_settings_overrides():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "node-audit.ini"
        p.write_text(
            "[audit]\n"
            "mode = attach\n"
            "include = 台湾\n"
            "limit = 3\n"
            "skip_speed = true\n"
            "workers = 5\n"
            "deep = off\n"
            "services = none\n"
            "config_name = 家里\n"
            "core = verge-mihomo.exe\n"
            "config = clash-verge.yaml\n"
            "[output]\n"
            "dir = reports-out\n"
            "open_report = false\n",
            encoding="utf-8",
        )
        s = load_settings(p)
        assert s.mode == "attach"
        assert s.include == "台湾"
        assert s.limit == 3
        assert s.skip_speed is True
        assert s.workers == 5
        assert s.deep == "off"
        assert s.services == "none"
        assert s.config_name == "家里"
        assert s.core == "verge-mihomo.exe"
        assert s.config == "clash-verge.yaml"
        assert s.out == "reports-out"
        assert s.open_report is False


def test_load_settings_missing_file():
    s = load_settings(Path("/no/such/node-audit.ini"))
    assert s.mode == "isolated"
    assert s.open_report is True


def test_cmd_run_menu_open_report_then_audit_then_quit():
    import builtins
    import node_audit.cli as cli

    orig_audit = cli.cmd_audit
    orig_open = cli._open_html
    orig_input = builtins.input
    orig_inter = cli._interactive
    calls = []
    answers = iter(["2", "1", "q"])

    def fake_audit(ns):
        calls.append(("audit", bool(ns.dry_run)))
        return 0

    cli.cmd_audit = fake_audit
    cli._open_html = lambda p: calls.append(("open", Path(p).name)) or True
    cli._interactive = lambda: True
    builtins.input = lambda *a, **k: next(answers)
    try:
        with tempfile.TemporaryDirectory() as td:
            ini = Path(td) / "node-audit.ini"
            out = Path(td) / "out"
            out.mkdir()
            (out / "latest.html").write_text("ok", encoding="utf-8")
            ini.write_text(
                "[audit]\nmode = isolated\n[output]\ndir = %s\nopen_report = false\n"
                % out.as_posix(),
                encoding="utf-8",
            )
            rc = cmd_run(argparse.Namespace(ini=str(ini), no_open=True, yes=False))
            assert rc == 0
            assert calls[0] == ("open", "latest.html")
            assert calls[1] == ("audit", False)
            assert [c[0] for c in calls].count("audit") == 1
    finally:
        cli.cmd_audit = orig_audit
        cli._open_html = orig_open
        cli._interactive = orig_inter
        builtins.input = orig_input


def test_cmd_run_yes_invokes_audit_and_logs():
    import node_audit.cli as cli
    orig = cli.cmd_audit
    seen = []

    def fake(ns):
        seen.append(ns)
        return 0

    cli.cmd_audit = fake
    try:
        with tempfile.TemporaryDirectory() as td:
            ini = Path(td) / "node-audit.ini"
            out = Path(td) / "out"
            ini.write_text(
                "[audit]\nmode = isolated\ninclude = 台湾\n"
                "[output]\ndir = %s\nopen_report = false\n" % out.as_posix(),
                encoding="utf-8",
            )
            rc = cmd_run(argparse.Namespace(ini=str(ini), no_open=True, yes=True))
            assert rc == 0
            assert len(seen) == 1
            assert seen[0].yes is True
            assert seen[0].mode == "isolated"
            assert seen[0].include == "台湾"
            logs = list(out.glob("audit-*.log"))
            assert logs, "should write a timestamped log"
            assert (out / "latest.log").is_file()
            guide = out / "使用说明.html"
            assert guide.is_file()
            assert "node-audit.ini" in guide.read_text(encoding="utf-8")
            text = (out / "latest.log").read_text(encoding="utf-8")
            assert "node-audit" in text
            assert "开始全量审计" in text
    finally:
        cli.cmd_audit = orig
