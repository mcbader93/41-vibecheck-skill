"""Pick the right parser for a path (file, ZIP or folder)."""

import os
from typing import List

from ..records import Dataset
from . import claude_code_jsonl, claude_export, otlp_json


def _is_cc_jsonl(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(8192).decode("utf-8", "replace")
    except OSError:
        return False
    return '"sessionId"' in head and ('"type"' in head)


def load_paths(paths: List[str]) -> Dataset:
    ds = Dataset()
    cc_files = []
    for p in paths:
        p = os.path.expanduser(p)
        if os.path.isdir(p):
            if os.path.isdir(os.path.join(p, "projects")):
                cc_files.extend(claude_code_jsonl.find_session_files(p))
                continue
            for dirpath, _d, files in os.walk(p):
                for fn in sorted(files):
                    fp = os.path.join(dirpath, fn)
                    if fn.endswith(".jsonl") and _is_cc_jsonl(fp):
                        cc_files.append((fp, os.sep + "subagents" + os.sep in fp))
                    elif fn.endswith((".json", ".jsonl", ".zip")):
                        _load_one(ds, fp, quiet=True)
            continue
        if not os.path.isfile(p):
            raise FileNotFoundError(p)
        if p.endswith(".jsonl") and _is_cc_jsonl(p) and not otlp_json.sniff(p):
            cc_files.append((p, os.sep + "subagents" + os.sep in p))
        else:
            _load_one(ds, p, quiet=False)
    if cc_files:
        ds.extend(claude_code_jsonl.load(cc_files))
    return ds


def _load_one(ds: Dataset, p: str, quiet: bool) -> None:
    if otlp_json.sniff(p):
        ds.extend(otlp_json.parse_file(p))
    elif claude_export.sniff(p):
        ds.extend(claude_export.parse_file(p))
    elif not quiet:
        raise ValueError("%s: not a format the vibe check knows (Claude Code session, OTel JSON, Claude export)" % os.path.basename(p))
