"""Claude Code local transcripts: ~/.claude/projects/<project>/<session>.jsonl (+ <session>/subagents/*.jsonl).

Facts this parser relies on (checked on real files, Oct 2026):
- One API response is written as several lines (one per content block), each repeating the full usage.
  We dedupe by message.id and keep the last line's usage.
- Usage keys: input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens and a
  cache_creation.{ephemeral_5m_input_tokens, ephemeral_1h_input_tokens} split, plus speed (enum) and
  server_tool_use.web_search_requests (count), which change the price.
- A "cost-state" line is a snapshot of Claude Code's own cost record (totalCostUSD, modelUsage). It covers
  the session up to the line where it was written, so D7 compares it with the transcript up to that line.

Read: type, timestamp, isMeta, isSidechain, isCompactSummary, cwd, message.{id, model, usage, stop_reason},
content block types, tool_use name/id/file path, tool_result tool_use_id/is_error/size, cost-state numbers, and
the text a person typed. That text goes straight to signals.analyse(), which keeps only lengths, flags and per-run
hashes. File paths become per-run hashes, cwd stays in memory for the setup checks. No text is stored.
"""

import json
import os
from typing import Dict, List, Optional

from ..models import normalize_model
from ..records import CallRecord, Dataset, PromptRecord, ToolRecord
from ..util import h, parse_ts, pick_int, to_int
from . import signals

_IN = ("input_tokens",)
_OUT = ("output_tokens",)
_CR = ("cache_read_input_tokens", "cache_read.input_tokens", "cacheReadInputTokens")
_CW = ("cache_creation_input_tokens", "cache_creation.input_tokens", "cacheCreationInputTokens")
_W5 = ("cache_creation.ephemeral_5m_input_tokens",)
_W1 = ("cache_creation.ephemeral_1h_input_tokens",)
_SEARCHES = ("server_tool_use.web_search_requests",)
_REASON = ("output_tokens_details.thinking_tokens", "reasoning_tokens", "thinking_tokens")


def _content_types(msg) -> List[dict]:
    c = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(c, list):
        return [b for b in c if isinstance(b, dict)]
    return []


def _is_human_prompt(o: dict) -> bool:
    if o.get("isMeta") or o.get("isCompactSummary"):
        return False
    msg = o.get("message")
    if not isinstance(msg, dict):
        return False
    c = msg.get("content")
    if isinstance(c, str):
        return True
    blocks = _content_types(msg)
    return bool(blocks) and not any(b.get("type") == "tool_result" for b in blocks)


_FILE_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"}


def _typed_text(msg) -> str:
    """What the person typed in a user message: the string content or its text blocks."""
    c = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(c, str):
        return c
    return "\n".join(b.get("text") for b in _content_types(msg)
                     if b.get("type") == "text" and isinstance(b.get("text"), str))


def _result_chars(block: dict) -> Optional[int]:
    c = block.get("content")
    if isinstance(c, str):
        return len(c)
    if isinstance(c, list):
        return sum(len(b.get("text") or "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return None


def parse_file(path: str, is_subagent: bool = False) -> Dataset:
    ds = Dataset()
    session_raw: Optional[str] = None
    turn_raw = "start"
    last_input_ts: Optional[float] = None
    msgs: Dict[str, dict] = {}       # message.id -> state
    order: List[str] = []
    tool_owner: Dict[str, str] = {}  # tool_use id -> message.id
    tool_name: Dict[str, str] = {}
    tool_events = []                 # (ts, tool_use_id, ok)
    snapshots = []                   # (n_messages_so_far, cost_usd, tokens)
    tool_file: Dict[str, str] = {}   # tool_use id -> per-run file hash
    prompts = []                     # (ts, turn_raw, flags)
    interrupts = []                  # (ts, turn_raw)
    compactions = []
    cwd: Optional[str] = None
    bad_lines = 0

    with open(path, "rb") as f:
        for raw in f:
            try:
                o = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                bad_lines += 1
                continue
            if not isinstance(o, dict):
                continue
            session_raw = session_raw or o.get("sessionId")
            if cwd is None and isinstance(o.get("cwd"), str):
                cwd = o["cwd"]
            typ = o.get("type")
            ts = parse_ts(o.get("timestamp"))
            if typ == "cost-state":
                cost = o.get("totalCostUSD")
                mu = o.get("modelUsage") or {}
                toks = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
                for v in mu.values() if isinstance(mu, dict) else []:
                    if isinstance(v, dict):
                        toks["input"] += to_int(v.get("inputTokens")) or 0
                        toks["output"] += to_int(v.get("outputTokens")) or 0
                        toks["cache_read"] += to_int(v.get("cacheReadInputTokens")) or 0
                        toks["cache_write"] += to_int(v.get("cacheCreationInputTokens")) or 0
                if isinstance(cost, (int, float)):
                    snapshots.append((len(order), float(cost), toks))
                continue
            if typ == "user":
                if o.get("isCompactSummary"):
                    compactions.append(ts or 0.0)
                if _is_human_prompt(o):
                    text = _typed_text(o.get("message"))
                    if signals.is_interrupt(text):
                        interrupts.append((ts, turn_raw))
                    turn_raw = o.get("promptId") or o.get("uuid") or str(ts)
                    if not is_subagent and not o.get("isSidechain") and not signals.is_interrupt(text):
                        flags = signals.analyse(text, first=not prompts)
                        if flags is not None:
                            prompts.append((ts, turn_raw, flags))
                for b in _content_types(o.get("message")):
                    if b.get("type") == "tool_result":
                        tool_events.append((ts, b.get("tool_use_id"), not bool(b.get("is_error")), _result_chars(b)))
                if ts is not None:
                    last_input_ts = ts
                continue
            if typ != "assistant":
                continue
            msg = o.get("message")
            if not isinstance(msg, dict):
                continue
            mid = msg.get("id") or o.get("requestId") or o.get("uuid")
            if mid is None:
                continue
            st = msgs.get(mid)
            if st is None:
                st = {"start": last_input_ts if last_input_ts is not None else ts, "end": ts,
                      "turn": turn_raw, "side": bool(o.get("isSidechain"))}
                msgs[mid] = st
                order.append(mid)
            if ts is not None:
                st["end"] = ts
                if st["start"] is None:
                    st["start"] = ts
            st["model"] = msg.get("model") or st.get("model")
            if isinstance(msg.get("usage"), dict):
                st["usage"] = msg["usage"]
            if msg.get("stop_reason"):
                st["stop"] = msg.get("stop_reason")
            for b in _content_types(msg):
                if b.get("type") == "tool_use" and b.get("id"):
                    tool_owner[b["id"]] = mid
                    tool_name[b["id"]] = str(b.get("name") or "unknown")[:80]
                    inp = b.get("input")
                    if b.get("name") in _FILE_TOOLS and isinstance(inp, dict):
                        fp = inp.get("file_path") or inp.get("notebook_path")
                        if isinstance(fp, str):
                            tool_file[b["id"]] = signals.file_key(fp)
            if ts is not None:
                last_input_ts = ts

    sid = h(session_raw or path)
    index: Dict[str, int] = {}
    for mid in order:
        st = msgs[mid]
        model = normalize_model(st.get("model"))
        if model is None and st.get("model") in ("<synthetic>",):
            continue  # client-side synthetic messages, no API call
        u = st.get("usage")
        start, end = st.get("start"), st.get("end")
        if start is None and end is None:
            start = end = 0.0
        start = start if start is not None else end
        end = end if end is not None else start
        if end < start:
            start, end = end, start
            ds.fixed_durations += 1
        rec = CallRecord(source="claude_code_jsonl", session_id=sid, turn_id=h(sid + str(st["turn"])),
                         ts_start=start, ts_end=end, model=model,
                         is_subagent=is_subagent or st["side"], finish_reason=st.get("stop"))
        if isinstance(u, dict):
            rec.input = pick_int(u, _IN)
            rec.output = pick_int(u, _OUT)
            rec.cache_read = pick_int(u, _CR)
            total_w = pick_int(u, _CW)
            w5, w1 = pick_int(u, _W5), pick_int(u, _W1)
            if w5 is not None or w1 is not None:
                rec.cache_write_5m, rec.cache_write_1h = w5 or 0, w1 or 0
                rest = (total_w or 0) - (w5 or 0) - (w1 or 0)
                rec.cache_write_unknown = rest if rest > 0 else 0
            else:
                rec.cache_write_unknown = total_w
            rec.reasoning = pick_int(u, _REASON)
            rec.web_searches = pick_int(u, _SEARCHES)
            # enum only: any other value (including free text) is dropped, never stored
            rec.speed = u.get("speed") if u.get("speed") in ("fast", "standard") else None
            if rec.input is None and rec.output is None and rec.cache_read is None and total_w is None:
                rec.usage_recorded = False
        else:
            rec.usage_recorded = False
        index[mid] = len(ds.calls)
        ds.calls.append(rec)

    for ts, tid, ok, size in tool_events:
        owner = tool_owner.get(tid)
        ci = index.get(owner) if owner else None
        turn = ds.calls[ci].turn_id if ci is not None else h(sid + "orphan")
        ds.tools.append(ToolRecord(session_id=sid, turn_id=turn, ts=ts or 0.0,
                                   tool=tool_name.get(tid, "unknown"), ok=ok, after_call=ci,
                                   result_chars=size, file_key=tool_file.get(tid)))
    for ts, traw, fl in prompts:
        ds.prompts.append(PromptRecord(session_id=sid, turn_id=h(sid + str(traw)), ts=ts or 0.0,
                                       first=traw == prompts[0][1], **fl))
    for ts, traw in interrupts:
        ds.interrupts.append(("me", sid, h(sid + str(traw)), ts or 0.0))
    for ts in compactions:
        ds.compactions.append(("me", sid, ts))
    if cwd and not is_subagent:
        ds.session_dirs[sid] = cwd

    if snapshots and not is_subagent:
        n_msgs, cost, toks = snapshots[-1]
        scope_mids = set(order[:n_msgs])
        ds.bill_scope = [index[m] for m in scope_mids if m in index]
        ds.bill_usd = cost
        ds.bill_tokens = toks
        ds.bill_label = "Claude Code's own cost record"
    if bad_lines:
        ds.notes.append("%d unreadable lines skipped" % bad_lines)
    return ds


def find_session_files(root: str, project_dir: Optional[str] = None, since: Optional[float] = None) -> List[tuple]:
    """(path, is_subagent) for every transcript under root/projects."""
    base = os.path.join(root, "projects")
    out = []
    if not os.path.isdir(base):
        return out
    projects = sorted(os.listdir(base))
    if project_dir:
        want = encode_project(project_dir)
        projects = [p for p in projects if p == want]
    for p in projects:
        pdir = os.path.join(base, p)
        if not os.path.isdir(pdir):
            continue
        for dirpath, _dirs, files in os.walk(pdir):
            for fn in files:
                if not fn.endswith(".jsonl"):
                    continue
                fp = os.path.join(dirpath, fn)
                if since is not None:
                    try:
                        if os.path.getmtime(fp) < since:
                            continue
                    except OSError:
                        continue
                out.append((fp, os.sep + "subagents" + os.sep in fp))
    return sorted(out)


def encode_project(path: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(path))


def claude_home() -> str:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        return os.path.expanduser(env)
    return os.path.join(os.path.expanduser("~"), ".claude")


def load(paths: List[tuple]) -> Dataset:
    ds = Dataset()
    sessions = 0
    windows = []   # (session_id, cutoff_ts) for each cost snapshot
    for fp, sub in paths:
        part = parse_file(fp, is_subagent=sub)
        if part.calls and not sub:
            sessions += 1
        if part.bill_scope:
            cutoff = max(part.calls[i].ts_end for i in part.bill_scope)
            windows.append((part.calls[0].session_id, cutoff))
        ds.extend(part)
    # Claude Code's cost record includes subagents, whose calls live in separate files with the same
    # session id. Bring those into the reconciliation window up to the snapshot time.
    if windows:
        scope = set(ds.bill_scope)
        for sid, cutoff in windows:
            for i, c in enumerate(ds.calls):
                if c.is_subagent and c.session_id == sid and c.ts_end <= cutoff:
                    scope.add(i)
        ds.bill_scope = sorted(scope)
    if paths:
        ds.sources.append("Claude Code (%d session%s)" % (sessions, "" if sessions == 1 else "s"))
    return ds
