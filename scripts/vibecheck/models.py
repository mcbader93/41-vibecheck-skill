"""Model id normalization: API ids, Bedrock and Vertex ids, dated ids all map to one key."""

import re
from typing import Optional

_TIERS = ("opus", "sonnet", "haiku", "fable", "mythos")


def normalize_model(raw: Optional[str]) -> Optional[str]:
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip().lower()
    if s in ("<synthetic>", "synthetic", "unknown"):
        return None
    s = s.split("/")[-1]                      # vertex publishers/.../models/x
    s = re.sub(r"^(?:[a-z]{2}\.)?anthropic\.", "", s)   # bedrock: us.anthropic.claude-...
    s = s.split("@")[0]                       # vertex: claude-x@20250101
    s = re.sub(r"-v\d+(:\d+)?$", "", s)       # bedrock suffix -v1:0
    s = re.sub(r"\[.*?\]$", "", s)            # [1m]
    s = re.sub(r"-\d{8}$", "", s)             # dated snapshot
    s = re.sub(r"-latest$", "", s)
    if not s.startswith("claude-"):
        return s
    # claude-3-5-sonnet style -> claude-sonnet-3-5
    m = re.match(r"claude-(\d+(?:-\d+)?)-(%s)$" % "|".join(_TIERS), s)
    if m:
        s = "claude-%s-%s" % (m.group(2), m.group(1))
    return s


def tier(model: Optional[str]) -> Optional[str]:
    if not model:
        return None
    for t in _TIERS:
        if t in model:
            return t
    return None


def pretty(model: Optional[str]) -> str:
    if not model:
        return "unknown model"
    m = re.match(r"claude-([a-z]+)-(\d+)(?:-(\d+))?$", model)
    if not m:
        return model
    name = m.group(1).capitalize()
    ver = m.group(2) + ("." + m.group(3) if m.group(3) else "")
    return "%s %s" % (name, ver)
