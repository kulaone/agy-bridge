"""agy-bridge: an MCP server that lets Claude Code run and converse with AGY reviewer agents."""


def main() -> None:
    from .cli import main as _main

    raise SystemExit(_main())
