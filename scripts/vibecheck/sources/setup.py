"""Setup checks: the files that ride along in every Claude Code call, read locally.

For each project folder the sessions ran in, this measures CLAUDE.md files (size only) and lists the MCP servers
configured for it. Nothing from the files' contents is kept: memory files become a token estimate and a line count,
MCP config becomes server names, which the report shows so you know which one to remove.
"""

import json
import os
from typing import Dict, List

CHARS_PER_TOKEN = 4.0
_MEMORY_FILES = ("CLAUDE.md", "CLAUDE.local.md", os.path.join(".claude", "CLAUDE.md"))


def _size(path: str) -> tuple:
    try:
        with open(path, "rb") as f:
            data = f.read(2_000_000).decode("utf-8", "replace")
    except OSError:
        return 0, 0
    return int(len(data) / CHARS_PER_TOKEN), data.count("\n") + (1 if data and not data.endswith("\n") else 0)


def _json(path: str) -> dict:
    try:
        with open(path, "rb") as f:
            d = json.loads(f.read().decode("utf-8", "replace"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def scan(session_dirs: Dict[str, str], claude_home: str) -> dict:
    """{"projects": {dir_key: {...}}, "session_project": {session_id: dir_key}, "global_memory": {...}}.
    dir_key is an opaque index; folder paths never leave this function."""
    user_mem = _size(os.path.join(claude_home, "CLAUDE.md"))
    cfg = _json(os.path.join(os.path.dirname(claude_home.rstrip(os.sep)), ".claude.json"))
    if not cfg:
        cfg = _json(os.path.join(claude_home, ".claude.json"))
    global_mcp = sorted((cfg.get("mcpServers") or {}).keys()) if isinstance(cfg.get("mcpServers"), dict) else []
    per_project_cfg = cfg.get("projects") if isinstance(cfg.get("projects"), dict) else {}
    projects: Dict[str, dict] = {}
    keys: Dict[str, str] = {}
    session_project: Dict[str, str] = {}
    for sid, d in session_dirs.items():
        if d not in keys:
            k = "p%d" % len(keys)
            keys[d] = k
            tokens = lines = 0
            files = 0
            for rel in _MEMORY_FILES:
                t, l = _size(os.path.join(d, rel))
                if t:
                    tokens, lines, files = tokens + t, lines + l, files + 1
            mcp = set(global_mcp)
            pc = per_project_cfg.get(d) if isinstance(per_project_cfg.get(d), dict) else {}
            if isinstance(pc.get("mcpServers"), dict):
                mcp.update(pc["mcpServers"].keys())
            proj_mcp = _json(os.path.join(d, ".mcp.json")).get("mcpServers")
            if isinstance(proj_mcp, dict):
                mcp.update(proj_mcp.keys())
            projects[k] = {"memory_tokens": tokens, "memory_lines": lines, "memory_files": files,
                           "exists": os.path.isdir(d), "mcp": sorted(str(m)[:60] for m in mcp)}
        session_project[sid] = keys[d]
    return {"projects": projects, "session_project": session_project,
            "user_memory_tokens": user_mem[0], "user_memory_lines": user_mem[1]}


def mcp_server_of(tool: str) -> List[str]:
    """Server-name candidates for an MCP tool id (mcp__server__tool). Server names may contain underscores."""
    if not tool.startswith("mcp__"):
        return []
    rest = tool[5:]
    parts = rest.split("__")
    return ["__".join(parts[:i]) for i in range(1, len(parts))] or [rest]
