"""A stand-in for the `claude` CLI's `mcp add|remove|get`, writing the same config files
Claude Code uses: ~/.claude.json for user scope, ./.mcp.json for project scope."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def config(scope: str) -> Path:
    return Path.home() / ".claude.json" if scope == "user" else Path.cwd() / ".mcp.json"


def load(scope: str) -> dict:
    try:
        return json.loads(config(scope).read_text())
    except FileNotFoundError:
        return {}


def main() -> int:
    a = sys.argv[1:]
    if a[:2] == ["mcp", "add"]:
        scope = a[a.index("--scope") + 1]
        sep = a.index("--")
        data = load(scope)
        data.setdefault("mcpServers", {})[a[sep - 1]] = {
            "type": "stdio", "command": a[sep + 1], "args": a[sep + 2:]}
        config(scope).write_text(json.dumps(data))
        return 0
    if a[:2] == ["mcp", "remove"]:
        scope = a[a.index("-s") + 1]
        data = load(scope)
        data.get("mcpServers", {}).pop(a[2], None)
        config(scope).write_text(json.dumps(data))
        return 0
    if a[:2] == ["mcp", "get"]:
        for scope, label in (("project", "Project config"), ("user", "User config")):
            server = load(scope).get("mcpServers", {}).get(a[2])
            if server:
                print(f"{a[2]}:\n  Scope: {label}\n  Status: ✔ Connected\n  Type: stdio\n"
                      f"  Command: {server['command']}\n  Args: {' '.join(server['args'])}")
                return 0
        print(f'No MCP server named "{a[2]}"', file=sys.stderr)
        return 1
    print(f"fake claude: unsupported {a}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
