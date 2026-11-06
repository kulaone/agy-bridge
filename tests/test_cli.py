"""install / uninstall / doctor, in a throwaway home with fake `agy` and `claude`."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import run_cli

CMD = "/opt/uv run agy-bridge"


def files(env: dict) -> dict[str, Path]:
    home = Path(env["HOME"])
    return {"agent": home / ".gemini/config/agents/code-reviewer.md",
            "skill": home / ".gemini/config/skills/code-review/SKILL.md",
            "claude": home / ".claude/skills/agy/SKILL.md"}


def registered(config: Path) -> list[str] | None:
    if not config.exists():
        return None
    server = json.loads(config.read_text()).get("mcpServers", {}).get("agy")
    return [server["command"], *server["args"]] if server else None


def test_install_fills_in_paths_and_registers(env: dict) -> None:
    out = run_cli(env, "install", "--server-command", CMD)
    assert out.returncode == 0, out.stderr
    f = files(env)
    assert all(p.exists() for p in f.values())
    agent = f["agent"].read_text()
    assert "{{" not in agent
    assert f"- {f['skill'].parent}\n" in agent
    assert registered(Path(env["HOME"]) / ".claude.json") == CMD.split()


def test_install_ships_the_design_reviewer(env: dict) -> None:
    run_cli(env, "install", "--server-command", CMD)
    gemini = Path(env["HOME"]) / ".gemini/config"
    skill = gemini / "skills/architecture-review"
    assert (skill / "SKILL.md").exists() and (skill / "references/principles.md").exists()
    assert f"- {skill}\n" in (gemini / "agents/design-reviewer.md").read_text()


def test_reinstall_is_a_no_op(env: dict) -> None:
    run_cli(env, "install", "--server-command", CMD)
    out = run_cli(env, "install", "--server-command", CMD)
    assert "+ " not in out.stdout and "already registered" in out.stdout


def test_user_changes_are_kept_unless_forced(env: dict) -> None:
    run_cli(env, "install", "--server-command", CMD)
    skill = files(env)["skill"]
    skill.write_text(skill.read_text() + "# my note\n")
    out = run_cli(env, "install", "--server-command", CMD)
    assert "exists and differs: kept" in out.stdout
    assert skill.read_text().endswith("# my note\n")

    out = run_cli(env, "install", "--force", "--server-command", CMD)
    assert not skill.read_text().endswith("# my note\n")
    backups = list(skill.parent.glob("SKILL.md.bak-*"))
    assert len(backups) == 1 and backups[0].read_text().endswith("# my note\n")


def test_pre_existing_files_are_not_overwritten(env: dict) -> None:
    agent = files(env)["agent"]
    agent.parent.mkdir(parents=True)
    agent.write_text("my own agent\n")
    run_cli(env, "install", "--no-register")
    assert agent.read_text() == "my own agent\n"


def test_other_registration_needs_force(env: dict) -> None:
    run_cli(env, "install", "--server-command", "/other/cmd")
    out = run_cli(env, "install", "--server-command", CMD)
    assert "registered with another command" in out.stdout
    config = Path(env["HOME"]) / ".claude.json"
    assert registered(config) == ["/other/cmd"]
    run_cli(env, "install", "--force", "--server-command", CMD)
    assert registered(config) == CMD.split()


def test_dry_run_changes_nothing(env: dict) -> None:
    out = run_cli(env, "install", "--dry-run", "--server-command", CMD)
    assert "[dry run]" in out.stdout
    assert not any(p.exists() for p in files(env).values())
    assert not (Path(env["HOME"]) / ".claude.json").exists()


def test_project_install_and_uninstall(env: dict, tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    run_cli(env, "install", "--server-command", CMD)  # a global install alongside
    out = run_cli(env, "install", "--project", str(proj), "--server-command", CMD)
    assert out.returncode == 0, out.stderr
    agent = proj / ".agents/agents/code-reviewer.md"
    assert f"- {proj / '.agents/skills/code-review'}\n" in agent.read_text()
    assert (proj / ".claude/skills/agy/SKILL.md").exists()
    assert registered(proj / ".mcp.json") == CMD.split()

    run_cli(env, "uninstall", "--project", str(proj))
    assert not (proj / ".agents").exists() and not (proj / ".claude").exists()
    assert registered(proj / ".mcp.json") is None
    # The global install is untouched.
    assert files(env)["agent"].exists()
    assert registered(Path(env["HOME"]) / ".claude.json") == CMD.split()


def test_uninstall_keeps_changed_files_and_foreign_registration(env: dict) -> None:
    run_cli(env, "install", "--server-command", CMD)
    f = files(env)
    f["claude"].write_text("changed by me\n")
    run_cli(env, "install", "--force", "--no-register")  # replaces it, keeps a .bak
    f["claude"].write_text("changed again\n")
    run_cli(env, "install", "--force", "--server-command", "/someone/else")
    f["claude"].write_text("changed after install\n")

    out = run_cli(env, "uninstall")
    assert "was changed since install: kept" in out.stdout
    assert f["claude"].read_text() == "changed after install\n"
    assert not f["agent"].exists() and not f["skill"].parent.exists()
    skills = Path(env["HOME"]) / ".gemini/config/skills"
    assert not (skills / "architecture-review").exists()  # nested references/ too
    assert f["agent"].parent.exists() and skills.exists()  # shared AGY folders stay
    assert registered(Path(env["HOME"]) / ".claude.json") is None  # it was ours (forced)


def test_uninstall_without_install(env: dict) -> None:
    out = run_cli(env, "uninstall")
    assert out.returncode == 0 and "Nothing recorded" in out.stdout


def test_doctor_all_good(env: dict, tmp_path: Path) -> None:
    run_cli(env, "install", "--server-command", CMD)
    out = run_cli(env, "doctor", cwd=tmp_path)
    assert out.returncode == 0, out.stdout
    assert "All good." in out.stdout and "logging is off" in out.stdout
    for name in ("code-reviewer", "design-reviewer"):
        assert f"agent '{name}'" in out.stdout


def test_doctor_finds_problems(env: dict, tmp_path: Path) -> None:
    out = run_cli(env, "doctor", cwd=tmp_path)
    assert out.returncode == 1
    assert "agent 'code-reviewer' not found" in out.stdout
    assert "Claude skill 'agy' not found" in out.stdout
    assert "is not registered with Claude Code" in out.stdout


def test_doctor_without_agy(env: dict, tmp_path: Path) -> None:
    out = run_cli({**env, "AGY_BIN": "", "PATH": "/usr/bin:/bin"}, "doctor", cwd=tmp_path)
    assert out.returncode == 1 and "agy not found" in out.stdout


def test_doctor_with_a_wrong_agy_bin(env: dict, tmp_path: Path) -> None:
    out = run_cli({**env, "AGY_BIN": str(tmp_path / "nope")}, "doctor", cwd=tmp_path)
    assert out.returncode == 1 and "not an executable file" in out.stdout
    assert "Traceback" not in out.stderr
