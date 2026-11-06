"""Command line. With no subcommand, `agy-bridge` runs the MCP server (what Claude
Code launches); the subcommands set it up and check it.

  agy-bridge install     copy the example agent and skills, register the MCP server
  agy-bridge uninstall   remove what install added
  agy-bridge doctor      check AGY, the agent, the Claude skill and the registration

install records what it wrote in ~/.agy-bridge/install.json, with a hash of each
file, so it can update its own files later without touching files the user changed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from . import paths, selfcheck

SERVER_NAME = "agy"
EXAMPLE_AGENT = "code-reviewer"


# ----- what install puts where ------------------------------------------------------


def _dest_dirs(project: Path | None) -> dict[str, Path]:
    """Asset folder prefix -> destination folder, for a global or project install."""
    if project:
        return {"agy/agents": project / ".agents" / "agents",
                "agy/skills": project / ".agents" / "skills",
                "claude/skills": project / ".claude" / "skills"}
    return {"agy/agents": paths.GLOBAL_AGENTS_DIR,
            "agy/skills": paths.GLOBAL_SKILLS_DIR,
            "claude/skills": paths.CLAUDE_SKILLS_DIR}


def _planned(project: Path | None) -> list[tuple[Path, bytes]]:
    """Every asset file with its destination and rendered content."""
    dests = _dest_dirs(project)
    root = Path(str(resources.files("agy_bridge") / "assets"))
    out = []
    for src in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = src.relative_to(root).as_posix()
        prefix = next((k for k in dests if rel.startswith(k + "/")), None)
        if prefix is None:
            continue
        text = src.read_text().replace("{{SKILLS_DIR}}", str(dests["agy/skills"]))
        out.append((dests[prefix] / rel[len(prefix) + 1:], text.encode()))
    return out


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_manifest() -> dict[str, Any]:
    try:
        return json.loads(paths.INSTALL_MANIFEST.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_manifest(manifest: dict[str, Any]) -> None:
    paths.ensure_dirs()
    fd, tmp = tempfile.mkstemp(dir=paths.STATE_DIR, prefix=".install.", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    os.replace(tmp, paths.INSTALL_MANIFEST)


# ----- the command Claude Code should run -------------------------------------------


def _real_exe(path: str) -> str:
    """Resolve pyenv/asdf shims: Claude Code may start servers without them on PATH."""
    if "/shims/" not in path:
        return path
    name = Path(path).name
    for tool in ("pyenv", "asdf"):
        try:
            out = subprocess.run([tool, "which", name], capture_output=True, text=True,
                                 timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    return path


def server_command() -> list[str]:
    """How to start this install of agy-bridge, as an absolute command."""
    root = Path(__file__).resolve().parents[2]
    pyproject = root / "pyproject.toml"
    if pyproject.is_file() and 'name = "agy-bridge"' in pyproject.read_text():
        uv = shutil.which("uv")
        if uv:  # a source checkout
            return [_real_exe(uv), "run", "--quiet", "--project", str(root), "agy-bridge"]
    exe = str(Path(sys.argv[0]).resolve())
    if "/archive-v" in exe or "/builds-v" in exe:
        uvx = shutil.which("uvx")  # an ephemeral `uvx agy-bridge install`: in uv's cache
        if uvx:
            print("  note: registering `uvx agy-bridge`, which runs the latest PyPI release. "
                  "If you installed from git or a file, use `uv tool install` first, or pass "
                  "--server-command.")
            return [_real_exe(uvx), "agy-bridge"]
    found = shutil.which("agy-bridge")  # `uv tool install`, pipx or pip
    if found:
        return [_real_exe(found)]
    return [sys.executable, "-m", "agy_bridge"]


def _mcp_get(claude: str, cwd: Path | None) -> dict[str, Any] | None:
    try:
        out = subprocess.run([claude, "mcp", "get", SERVER_NAME], capture_output=True,
                             text=True, timeout=60, cwd=cwd)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or not out.stdout.lstrip().startswith(f"{SERVER_NAME}:"):
        return None
    info: dict[str, Any] = {}
    for line in out.stdout.splitlines():
        key, _, value = line.strip().partition(": ")
        if key in ("Scope", "Status", "Command", "Args"):
            info[key.lower()] = value.strip()
    info["argv"] = [info.get("command", "")] + info.get("args", "").split()
    return info


def _registered(project: Path | None) -> list[str] | None:
    """The command registered for our server in exactly this scope, if any.

    `claude mcp get` shows only the entry that wins across scopes, so read the scope's
    own file: ~/.claude.json for user scope, <project>/.mcp.json for project scope.
    """
    config = project / ".mcp.json" if project else paths.HOME / ".claude.json"
    try:
        server = json.loads(config.read_text()).get("mcpServers", {}).get(SERVER_NAME)
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return None
    if not isinstance(server, dict) or "command" not in server:
        return None
    return [server["command"], *server.get("args", [])]


def _register(cmd: list[str], project: Path | None, force: bool, dry: bool) -> dict | None:
    scope = "project" if project else "user"
    add = ["claude", "mcp", "add", "--scope", scope, SERVER_NAME, "--", *cmd]
    claude = shutil.which("claude")
    if not claude:
        print("  ! Claude Code CLI not found. Register the server yourself:\n    "
              + shlex.join(add))
        return None
    existing = _registered(project)
    if existing:
        if existing == cmd:
            print(f"  = MCP server '{SERVER_NAME}' already registered ({scope} scope)")
            return {"scope": scope, "argv": cmd}
        if not force:
            print(f"  ! MCP server '{SERVER_NAME}' is registered with another command:\n"
                  f"      {shlex.join(existing)}\n    use --force to replace it")
            return None
        if not dry:
            subprocess.run([claude, "mcp", "remove", SERVER_NAME, "-s", scope],
                           capture_output=True, cwd=project)
    print(f"  + register MCP server '{SERVER_NAME}' ({scope} scope): {shlex.join(cmd)}")
    if not dry:
        out = subprocess.run([claude, *add[1:]], capture_output=True, text=True, cwd=project)
        if out.returncode != 0:
            print(f"  ✗ claude mcp add failed: {(out.stderr or out.stdout).strip()}")
            return None
    return {"scope": scope, "argv": cmd}


# ----- install / uninstall ----------------------------------------------------------


def install(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve() if args.project else None
    if project and not project.is_dir():
        print(f"not a directory: {project}")
        return 1
    key = str(project) if project else "global"
    manifest = _load_manifest()
    entry = manifest.setdefault(key, {})
    files = entry.setdefault("files", {})
    stamp = time.strftime("%Y%m%d-%H%M%S")
    skipped = 0
    print(f"Installing agy-bridge ({'project ' + key if project else 'global'})"
          + (" [dry run]" if args.dry_run else ""))

    for dest, content in _planned(project):
        new = _sha(content)
        if dest.exists():
            current = _sha(dest.read_bytes())
            if current == new:
                print(f"  = {dest}")
                files[str(dest)] = new
                continue
            ours = files.get(str(dest)) == current  # unchanged since we wrote it
            if not ours and not args.force:
                print(f"  ! {dest} exists and differs: kept. Use --force to replace it "
                      "(a .bak copy is kept).")
                skipped += 1
                continue
            if not ours and not args.dry_run:
                shutil.copy2(dest, dest.with_name(f"{dest.name}.bak-{stamp}"))
        print(f"  + {dest}")
        if not args.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            files[str(dest)] = new

    if not args.no_register:
        cmd = shlex.split(args.server_command) if args.server_command else server_command()
        registered = _register(cmd, project, args.force, args.dry_run)
        if registered:
            entry["mcp"] = registered
        elif shutil.which("claude"):
            skipped += 1

    if not args.dry_run:
        _save_manifest(manifest)
    if project:
        print("\nNote: the agent file holds an absolute skill path. On another machine, "
              "edit its skills: path to match that checkout.")
    print("\nNext: restart Claude Code, then run `agy-bridge doctor`."
          + ("\nSome items were kept; see the ! lines above." if skipped else ""))
    return 0


def _remove_empty_parents(dest: Path, project: Path | None) -> None:
    """Remove folders left empty: up to the project root, or only a skill's own folder
    in the shared global agents/skills folders."""
    stop = project or (dest.parent.parent if dest.name == "SKILL.md" else dest.parent)
    d = dest.parent
    while d != stop and stop in d.parents and not any(d.iterdir()):
        d.rmdir()
        d = d.parent


def uninstall(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve() if args.project else None
    key = str(project) if project else "global"
    manifest = _load_manifest()
    entry = manifest.get(key)
    if not entry:
        print(f"Nothing recorded for {key}: agy-bridge install was not run there.")
        return 0
    kept = {}
    for dest_s, sha in entry.get("files", {}).items():
        dest = Path(dest_s)
        if not dest.exists():
            continue
        if _sha(dest.read_bytes()) != sha and not args.force:
            print(f"  ! {dest} was changed since install: kept (--force removes it)")
            kept[dest_s] = sha
            continue
        print(f"  - {dest}")
        if not args.dry_run:
            dest.unlink()
            _remove_empty_parents(dest, project)

    mcp = entry.get("mcp")
    keep_mcp = False
    claude = shutil.which("claude")
    if mcp and not claude:
        print(f"  ! Claude Code CLI not found. Remove the server yourself:\n    "
              f"claude mcp remove {SERVER_NAME} -s {mcp['scope']}")
        keep_mcp = True
    elif mcp:
        existing = _registered(project)
        if existing == mcp["argv"]:
            print(f"  - MCP server '{SERVER_NAME}' ({mcp['scope']} scope)")
            if not args.dry_run:
                out = subprocess.run([claude, "mcp", "remove", SERVER_NAME, "-s", mcp["scope"]],
                                     capture_output=True, text=True, cwd=project)
                if out.returncode != 0:
                    print(f"  ✗ claude mcp remove failed: {(out.stderr or out.stdout).strip()}")
                    keep_mcp = True
        elif existing:
            print(f"  ! MCP server '{SERVER_NAME}' was registered again with another "
                  "command since install: kept")

    if not args.dry_run:
        rest = {**({"files": kept} if kept else {}), **({"mcp": mcp} if keep_mcp else {})}
        if rest:
            manifest[key] = rest
        else:
            manifest.pop(key, None)
        _save_manifest(manifest)
    print("Done. Sessions, backups and scratch folders in "
          f"{paths.STATE_DIR} are kept; delete that folder to remove them too.")
    return 0


# ----- doctor -----------------------------------------------------------------------


class _Report:
    def __init__(self) -> None:
        self.failed = 0

    def ok(self, msg: str) -> None:
        print(f"  ✓ {msg}")

    def warn(self, msg: str) -> None:
        print(f"  ! {msg}")

    def fail(self, msg: str) -> None:
        print(f"  ✗ {msg}")
        self.failed += 1


def doctor(args: argparse.Namespace) -> int:
    cwd = str(Path(args.cwd).expanduser().resolve())
    r = _Report()
    print("agy-bridge doctor")

    try:
        agy = paths.agy_binary()
    except FileNotFoundError as e:
        r.fail(str(e))
        return 1
    try:
        version = asyncio.run(selfcheck.agy_version())
    except (OSError, TimeoutError) as e:
        r.fail(f"can't run {agy}: {e}")
        return 1
    r.ok(f"agy {version} at {agy}")
    if warning := selfcheck.version_warning(version):
        r.warn(warning)

    try:
        models = asyncio.run(selfcheck.models(refresh=True))
    except (OSError, TimeoutError):
        models = []
    if models:
        r.ok(f"AGY answers and lists {len(models)} models (logged in)")
    else:
        r.fail("`agy models` listed nothing: run `agy` once to log in")

    agent_file = selfcheck.find_agent_file(EXAMPLE_AGENT, cwd)
    if agent_file is None:
        r.warn(f"agent '{EXAMPLE_AGENT}' not found from {cwd}: run `agy-bridge install` "
               "(fine if you use only your own agents)")
    else:
        text = agent_file.read_text()
        if "{{" in text:
            r.fail(f"{agent_file} still has a {{{{...}}}} placeholder: reinstall it")
        try:
            print("  … checking the agent against AGY's tools (the first run takes a minute)")
            asyncio.run(selfcheck.check_agent(EXAMPLE_AGENT, cwd))
            r.ok(f"agent '{EXAMPLE_AGENT}' ({agent_file}) uses only tools AGY has")
        except (ValueError, RuntimeError, OSError) as e:
            r.fail(str(e) or type(e).__name__)
        for skill in _agent_skills(text):
            if not Path(skill).is_dir():
                r.fail(f"agent '{EXAMPLE_AGENT}' lists a skill folder that doesn't exist: {skill}")

    skill_dirs = [d / ".claude" / "skills" / "agy" for d in [Path(cwd), *Path(cwd).parents]]
    skill = next((d for d in [*skill_dirs, paths.CLAUDE_SKILLS_DIR / "agy"]
                  if (d / "SKILL.md").is_file()), None)
    if skill:
        r.ok(f"Claude skill at {skill}")
    else:
        r.fail("Claude skill 'agy' not found: run `agy-bridge install`")

    claude = shutil.which("claude")
    if not claude:
        r.warn("Claude Code CLI not on PATH: can't check the MCP registration")
    else:
        info = _mcp_get(claude, Path(cwd))
        if info is None:
            r.fail(f"MCP server '{SERVER_NAME}' is not registered with Claude Code: "
                   "run `agy-bridge install`")
        elif "connected" in info.get("status", "").lower():
            r.ok(f"Claude Code connects to MCP server '{SERVER_NAME}' ({info.get('scope')})")
        else:
            r.fail(f"MCP server '{SERVER_NAME}' is registered but not healthy: "
                   f"{info.get('status')} (command: {shlex.join(info['argv'])})")

    try:
        paths.ensure_dirs()
        probe = paths.STATE_DIR / ".doctor"
        probe.write_text("ok")
        probe.unlink()
        r.ok(f"state folder {paths.STATE_DIR} is writable; transcript logging is "
             + ("ON (AGY_BRIDGE_LOG)" if paths.LOGGING else "off"))
    except OSError as e:
        r.fail(f"can't write to {paths.STATE_DIR}: {e}")

    print("\nAll good." if not r.failed else f"\n{r.failed} problem(s) found.")
    return 1 if r.failed else 0


def _agent_skills(text: str) -> list[str]:
    if not text.startswith("---"):
        return []
    try:
        front = yaml.safe_load(text.split("---", 2)[1]) or {}
    except yaml.YAMLError:
        return []
    return [s for s in front.get("skills") or [] if isinstance(s, str)]


# ----- entry point ------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agy-bridge",
        description="MCP server that lets Claude Code run AGY reviewer agents. "
                    "With no command, runs the server.")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("install", help="install the example agent and skills, register the server")
    p.add_argument("--project", metavar="DIR",
                   help="install into DIR/.agents and DIR/.claude instead of your home folder")
    p.add_argument("--force", action="store_true",
                   help="replace files and registrations that differ (keeps .bak copies)")
    p.add_argument("--no-register", action="store_true",
                   help="copy files only; don't register the MCP server with Claude Code")
    p.add_argument("--server-command", metavar="CMD",
                   help="command Claude Code should run to start the server "
                        "(default: worked out from how agy-bridge is installed)")
    p.add_argument("--dry-run", action="store_true", help="show what would change")

    p = sub.add_parser("uninstall", help="remove what install added")
    p.add_argument("--project", metavar="DIR")
    p.add_argument("--force", action="store_true", help="also remove files you changed")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("doctor", help="check that everything is set up")
    p.add_argument("--cwd", default=".", help="project to check from (default: here)")

    sub.add_parser("serve", help="run the MCP server (the default)")

    args = parser.parse_args(argv)
    if args.command == "install":
        return install(args)
    if args.command == "uninstall":
        return uninstall(args)
    if args.command == "doctor":
        return doctor(args)
    from .server import main as serve

    serve()
    return 0
