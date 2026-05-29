"""Tests for the Tier 2 Kimi CLI agentic engine (W14-KIMI-CLI-TIER2).

All MOCKED (no real subprocess).  Pins the headless invocation
(``kimi --print --output-format text --final-message-only -w <dir> -p``),
live-key injection, isolated-workdir default, and failure/timeout handling.
"""
import subprocess

from harness.engines import kimi_cli as kc


def _engine(**kw):
    return kc.KimiCliEngine(api_key="sk-test", verify_binary=False, **kw)


class _FakeProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_name():
    assert _engine().name == "kimi-cli"


def test_build_command_shape():
    cmd = _engine()._build_command("do research", "", "/tmp/wd")
    assert "--print" in cmd
    assert "--final-message-only" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "text"
    assert cmd[cmd.index("-w") + 1] == "/tmp/wd"
    assert cmd[cmd.index("-p") + 1] == "do research"
    assert "-m" not in cmd  # no explicit model -> CLI default


def test_build_command_explicit_model():
    cmd = _engine()._build_command("q", "kimi-k2.6", "/tmp/wd")
    assert cmd[cmd.index("-m") + 1] == "kimi-k2.6"


def test_build_command_placeholder_model_uses_default():
    for placeholder in ("kimi-cli", "default", "auto", "", "kimi"):
        cmd = _engine()._build_command("q", placeholder, "/tmp/wd")
        assert "-m" not in cmd, f"placeholder {placeholder!r} should not add -m"


def test_build_env_injects_key():
    assert _engine()._build_env()["KIMI_API_KEY"] == "sk-test"


def test_dispatch_success(monkeypatch):
    cap = []

    def fake_run(cmd, **kw):
        cap.append({"cmd": cmd, "kw": kw})
        return _FakeProc(stdout="research summary\n", returncode=0)

    monkeypatch.setattr(kc.subprocess, "run", fake_run)
    r = _engine().dispatch("research X", "", {"work_dir": "/tmp/wd"})
    assert r.success and r.text == "research summary"
    assert cap[0]["kw"]["env"]["KIMI_API_KEY"] == "sk-test"
    assert cap[0]["kw"]["cwd"] == "/tmp/wd"


def test_dispatch_failure_surfaces_stderr(monkeypatch):
    monkeypatch.setattr(
        kc.subprocess, "run",
        lambda cmd, **kw: _FakeProc(stdout="", stderr="boom", returncode=1),
    )
    r = _engine().dispatch("q", "", {"work_dir": "/tmp/wd"})
    assert not r.success and "boom" in r.error


def test_dispatch_timeout(monkeypatch):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(kc.subprocess, "run", boom)
    r = _engine().dispatch("q", "", {"work_dir": "/tmp/wd", "timeout_s": 1})
    assert not r.success and "timeout" in r.error.lower()


def test_dispatch_defaults_to_isolated_tempdir(monkeypatch):
    cap = []

    def fake_run(cmd, **kw):
        cap.append(kw)
        return _FakeProc(stdout="ok", returncode=0)

    monkeypatch.setattr(kc.subprocess, "run", fake_run)
    r = _engine().dispatch("q", "", {})  # no work_dir
    assert r.success
    assert "kimi-cli-" in cap[0]["cwd"]  # isolated temp dir


def test_get_engine_kimi_cli(monkeypatch):
    import harness.engines.concrete as concrete
    import harness.secrets.resolve as resolve
    monkeypatch.setattr(resolve, "resolve_key", lambda *a, **k: "sk-live")
    e = concrete.get_engine("kimi-cli")
    assert e.name == "kimi-cli"
    assert e._api_key == "sk-live"
