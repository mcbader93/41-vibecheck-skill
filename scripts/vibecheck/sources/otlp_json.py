"""OpenTelemetry (OTLP/JSON) traces and logs.

Supports:
- gen_ai semantic-convention traces: invoke_agent (turn) > chat (model call) > execute_tool spans
  (your trace exports, agent frameworks)
- Claude Code native beta traces: claude_code.interaction > claude_code.llm_request / claude_code.tool
- Claude Code native log events: api_request and tool_result (Claude Code's OpenTelemetry log export)
  plus the extended events (api_error, api_retries_exhausted, tool_decision, compaction, subagent_completed,
  assistant_response) as numbers and enums only
- a single OTLP JSON document, or JSON Lines with one OTLP document per line (collector file exporter)

Attribute names differ between sources and versions, so every field has a list of aliases. Only numeric,
model, id, status and tool-name fields are read. Descriptions, file paths and repo names are never read.

Two entry points: parse_file (reads a path) and parse_documents (already-decoded OTLP documents). parse_documents
has opt-in extras, all off by default and never enabled by parse_file: prompt text, caller-chosen attribute keys and OTLP
metrics. Typed prompt text is dropped unless the caller passes keep_prompt_text=True.
"""

import bisect
import json
import math
import re
from typing import Any, Callable, Dict, Iterable, List, Optional

from ..models import normalize_model
from ..records import (ApiErrorRecord, CallRecord, CompactionRecord, Dataset, PromptRecord, ResponseRecord,
                       RetryExhaustedRecord, SubagentRecord, ToolDecisionRecord, ToolRecord)
from . import signals
from ..util import h, parse_ts, pick, to_int

IN = ("gen_ai.usage.input_tokens", "input_tokens", "llm.usage.prompt_tokens")
OUT = ("gen_ai.usage.output_tokens", "output_tokens", "llm.usage.completion_tokens")
CR = ("gen_ai.usage.cache_read_input_tokens", "gen_ai.usage.cache_read.input_tokens",
      "gen_ai.usage.cache_read_tokens", "cache_read_tokens", "cache_read_input_tokens")
CW = ("gen_ai.usage.cache_creation_input_tokens", "gen_ai.usage.cache_creation.input_tokens",
      "gen_ai.usage.cache_write_tokens", "cache_creation_tokens", "cache_creation_input_tokens")
CW1 = ("gen_ai.usage.cache_creation.ephemeral_1h_input_tokens", "cache_creation_1h_tokens")
CW5 = ("gen_ai.usage.cache_creation.ephemeral_5m_input_tokens", "cache_creation_5m_tokens")
REASON = ("gen_ai.usage.reasoning_tokens", "gen_ai.usage.thinking_tokens", "reasoning_tokens", "thinking_tokens")
MODEL = ("gen_ai.response.model", "gen_ai.request.model", "model")
FINISH = ("gen_ai.response.finish_reasons", "finish_reason", "stop_reason")
SESSION = ("gen_ai.conversation.id", "session.id", "conversation.id")
TOOL = ("gen_ai.tool.name", "tool.name", "tool_name", "name")
TURN = ("claude_code.prompt.id", "prompt.id", "session.turn")
RECORDED = ("usage.recorded", "gen_ai.usage.recorded")
COST = ("cost_usd", "claude_code.cost_usd")
EFFORT = ("effort", "reasoning_effort")
QUERY_SOURCE = ("query_source",)
RESULT_SIZE = ("tool_result_size_bytes",)
INPUT_SIZE = ("tool_input_size_bytes",)
DURATION = ("duration_ms",)
DECISION_TYPE = ("decision_type",)
DECISION_SOURCE = ("decision_source",)
STATUS = ("status_code",)
RESPONSE_LEN = ("response_length",)
_ENUM_OK = re.compile(r"[a-z0-9_.:-]{1,40}$")


def _enum(v: Any) -> Optional[str]:
    """A short lower-case enum token, or None. Anything longer or with other characters (text, paths, ids) is
    dropped, so a field that is meant to be an enum can never smuggle typed content into a record."""
    if not isinstance(v, str):
        return None
    v = v.strip().lower()
    return v if _ENUM_OK.match(v) else None


def _flag(v: Any) -> Optional[bool]:
    """True/False from a boolean or "true"/"false" string; None for anything else."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "false"):
        return v.strip().lower() == "true"
    return None


def _num(v: Any) -> Optional[float]:
    """A finite, non-negative float, or None (garbage, NaN, negative and booleans are all "not recorded")."""
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x >= 0 else None


def _nat(v: Any) -> Optional[int]:
    """A non-negative integer, or None; goes through _num so "NaN" and "-3" are rejected the same way."""
    x = _num(v)
    return int(x) if x is not None else None


def _val(v: Any) -> Any:
    if not isinstance(v, dict):
        return v
    for k in ("stringValue", "boolValue", "doubleValue"):
        if k in v:
            return v[k]
    if "intValue" in v:
        return to_int(v["intValue"])
    if "arrayValue" in v:
        return [_val(x) for x in (v["arrayValue"] or {}).get("values", []) or []]
    if "kvlistValue" in v:
        return {kv.get("key"): _val(kv.get("value")) for kv in (v["kvlistValue"] or {}).get("values", []) or []}
    return None


def _attrs(lst: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if isinstance(lst, list):
        for a in lst:
            if isinstance(a, dict) and "key" in a:
                out[a["key"]] = _val(a.get("value"))
    return out


def _docs(path: str) -> Iterable[dict]:
    with open(path, "rb") as f:
        data = f.read()
    text = data.decode("utf-8", "replace").strip()
    if not text:
        return
    try:
        doc = json.loads(text)
        if isinstance(doc, list):
            for d in doc:
                if isinstance(d, dict):
                    yield d
        elif isinstance(doc, dict):
            yield doc
        return
    except ValueError:
        pass
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            yield d


def sniff(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(4096).decode("utf-8", "replace")
    except OSError:
        return False
    return '"resourceSpans"' in head or '"resourceLogs"' in head


def _kind(name: str, a: dict) -> Optional[str]:
    op = a.get("gen_ai.operation.name")
    n = name or ""
    if op in ("chat", "text_completion", "generate_content") or n.startswith("chat ") or n == "claude_code.llm_request":
        return "call"
    if op == "execute_tool" or n.startswith("execute_tool") or n == "claude_code.tool":
        return "tool"
    if op in ("invoke_agent", "create_agent") or n.startswith("invoke_agent") or n == "claude_code.interaction":
        return "turn"
    return None


def _usage(rec: CallRecord, a: dict) -> None:
    rec.input = to_int(pick(a, IN))
    rec.output = to_int(pick(a, OUT))
    rec.cache_read = to_int(pick(a, CR))
    total_w = to_int(pick(a, CW))
    w1, w5 = to_int(pick(a, CW1)), to_int(pick(a, CW5))
    if w1 is not None or w5 is not None:
        rec.cache_write_1h, rec.cache_write_5m = w1 or 0, w5 or 0
        rest = (total_w or 0) - (w1 or 0) - (w5 or 0)
        rec.cache_write_unknown = rest if rest > 0 else 0
    else:
        rec.cache_write_unknown = total_w
    rec.reasoning = to_int(pick(a, REASON))
    flag = pick(a, RECORDED)
    if flag is False or (isinstance(flag, str) and flag.lower() == "false"):
        rec.usage_recorded = False
    elif rec.input is None and rec.output is None and rec.cache_read is None and total_w is None:
        rec.usage_recorded = False
    fr = pick(a, FINISH)
    if isinstance(fr, list):
        fr = fr[0] if fr else None
    rec.finish_reason = str(fr) if fr is not None else None


def _identity(keys: Iterable[tuple], *attr_dicts: dict) -> Dict[str, str]:
    """Values of the caller-chosen (name, attribute) pairs found in the given attribute dicts (first dict wins).
    Empty dict when no keys were given or none are present."""
    out: Dict[str, str] = {}
    for name, key in keys:
        for a in attr_dicts:
            v = a.get(key)
            if isinstance(v, str) and v:
                out[name] = v
                break
    return out


def parse_file(path: str) -> Dataset:
    """Free-CLI entry: parse an OTLP file. Prompts, identities and metrics are deliberately off, so the free
    report is exactly what it was before parse_documents existed."""
    return parse_documents(_docs(path), with_prompts=False)


def parse_documents(docs: Iterable[dict], hasher: Callable[[Any], str] = h, keep_prompt_text: bool = False,
                    identity_cb: Optional[Callable[[Any, Dict[str, str]], None]] = None,
                    identity_keys: Optional[Iterable[tuple]] = None,
                    metrics_cb: Optional[Callable[[Dict[str, Any], Dict[str, str]], None]] = None,
                    with_prompts: bool = True) -> Dataset:
    """Parse decoded OTLP documents (dicts with resourceSpans / resourceLogs / resourceMetrics) into a Dataset.

    hasher: turns raw session/turn ids into stored ids (a caller may pass a salted one).
    keep_prompt_text: when True each PromptRecord gets a `.text` attribute and its flags come from the text;
      when False a user_prompt event yields a length-only record and the text is never read.
    identity_keys: (name, attribute key) pairs the caller wants read; with none, no attribute is read.
    identity_cb(record, {name: value}): called for every call, tool and prompt record whose source carried one
      of the caller-chosen keys. Values go nowhere else.
    metrics_cb(totals, identity): called once per identity with summed OTLP metrics (tokens by type, cost_usd,
      commits, lines added/removed, first/last timestamp); None means the metric was not sent. These are the
      fallback totals when a sender exports metrics but no logs/traces.
    Failure mode: malformed entries are skipped, never raised."""
    ds = Dataset()
    spans: List[dict] = []
    logs: List[dict] = []
    metrics: List[dict] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        for rs in doc.get("resourceSpans") or []:
            res = _attrs((rs.get("resource") or {}).get("attributes"))
            for ss in rs.get("scopeSpans") or rs.get("instrumentationLibrarySpans") or []:
                for s in ss.get("spans") or []:
                    if isinstance(s, dict):
                        spans.append({"s": s, "a": _attrs(s.get("attributes")), "res": res})
        for rl in doc.get("resourceLogs") or []:
            res = _attrs((rl.get("resource") or {}).get("attributes"))
            for sl in rl.get("scopeLogs") or []:
                for lr in sl.get("logRecords") or []:
                    if isinstance(lr, dict):
                        logs.append({"l": lr, "a": _attrs(lr.get("attributes")), "res": res})
        if metrics_cb is not None:
            for rm in doc.get("resourceMetrics") or []:
                res = _attrs((rm.get("resource") or {}).get("attributes"))
                for sm in rm.get("scopeMetrics") or []:
                    for m in sm.get("metrics") or []:
                        if isinstance(m, dict):
                            metrics.append({"m": m, "res": res})
    ctx = {"hasher": hasher, "keep_text": keep_prompt_text, "cb": identity_cb, "keys": tuple(identity_keys or ()), "prompts": with_prompts}
    if spans:
        _from_spans(ds, spans, ctx)
    if logs:
        _from_logs(ds, logs, ctx)
    if metrics and metrics_cb is not None:
        _from_metrics(metrics, metrics_cb, tuple(identity_keys or ()))
    return ds


# metric name -> (field, optional attribute filter). Claude Code sends lines_of_code.count with type=added|removed
# and token.usage with type=input|output|cacheRead|cacheCreation.
_TOKEN_TYPES = {"input": "input", "output": "output", "cacheread": "cache_read", "cachecreation": "cache_write"}


def _from_metrics(metrics: List[dict], cb: Callable[[Dict[str, Any], Dict[str, str]], None],
                  keys: tuple = ()) -> None:
    """Sum the Claude Code metrics we understand per identity and hand each group to cb. Data points are summed
    as-is (Claude Code exports deltas); only numbers are read, never attribute text beyond the type/enum keys."""
    groups: Dict[tuple, dict] = {}
    for x in metrics:
        m = x["m"]
        name = str(m.get("name") or "").replace("claude_code.", "")
        body = m.get("sum") or m.get("gauge") or {}
        for dp in body.get("dataPoints") or []:
            if not isinstance(dp, dict):
                continue
            val = dp.get("asInt", dp.get("asDouble"))
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue
            a = _attrs(dp.get("attributes"))
            ident = _identity(keys, a, x["res"])
            g = groups.setdefault(tuple(sorted(ident.items())), {
                "identity": ident, "tokens": None, "cost_usd": None, "commits": None, "lines_added": None,
                "lines_removed": None, "lines_changed": None, "ts_first": None, "ts_last": None,
                "pull_requests": None, "active_user_s": None, "active_cli_s": None,
                "edit_decisions": None, "sessions_by_start": None})
            if name == "token.usage":
                kind = _TOKEN_TYPES.get(str(a.get("type", "")).lower())
                if kind is None:
                    continue
                g["tokens"] = g["tokens"] or {}
                g["tokens"][kind] = int(g["tokens"].get(kind, 0) + val)
            elif name == "cost.usage":
                g["cost_usd"] = (g["cost_usd"] or 0.0) + val
            elif name == "commit.count":
                g["commits"] = int((g["commits"] or 0) + val)
            elif name == "lines_of_code.count":
                kind = str(a.get("type", "")).lower()
                if kind in ("added", "removed"):
                    k = "lines_" + kind
                    g[k] = int((g[k] or 0) + val)
                    g["lines_changed"] = int((g["lines_changed"] or 0) + val)
                else:
                    continue
            elif name == "pull_request.count":
                g["pull_requests"] = int((g["pull_requests"] or 0) + val)
            elif name == "active_time.total":
                kind = _enum(a.get("type"))
                if kind not in ("user", "cli"):
                    continue
                k = "active_%s_s" % kind
                g[k] = (g[k] or 0) + val
            elif name == "code_edit_tool.decision":
                # allowlist: tool_name is free text in the feed, only the four edit tools may pass
                tool = str(a.get("tool_name") or "")
                key = (_enum(a.get("decision")), _enum(a.get("source")), tool if tool in _EDIT_TOOLS else None)
                g["edit_decisions"] = g["edit_decisions"] or {}
                g["edit_decisions"][key] = int(g["edit_decisions"].get(key, 0) + val)
            elif name == "session.count":
                key = _enum(a.get("start_type")) or "unknown"
                g["sessions_by_start"] = g["sessions_by_start"] or {}
                g["sessions_by_start"][key] = int(g["sessions_by_start"].get(key, 0) + val)
            else:
                continue
            ts = parse_ts(dp.get("timeUnixNano"))
            if ts is not None:
                g["ts_first"] = ts if g["ts_first"] is None else min(g["ts_first"], ts)
                g["ts_last"] = ts if g["ts_last"] is None else max(g["ts_last"], ts)
    for g in groups.values():
        ident = g.pop("identity")
        cb(g, ident)


_EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def _emit_identity(ctx: dict, rec: Any, *attr_dicts: dict) -> None:
    """Hand a record's identity keys (if any) to the caller's callback. No-op for the free CLI (no callback)."""
    cb = ctx["cb"]
    if cb is None:
        return
    ident = _identity(ctx["keys"], *attr_dicts)
    if ident:
        cb(rec, ident)


def _command_name(a: dict) -> Optional[str]:
    """The user_prompt command_name, only if it is a built-in slash command; custom commands may be named after
    private things, so they are dropped."""
    name = a.get("command_name")
    name = name.strip().lstrip("/").lower() if isinstance(name, str) else None
    return name if name in signals.BUILTIN_COMMANDS else None


def _prompt_record(a: dict, sid: str, turn: str, ts: float, first: bool, keep_text: bool) -> Optional[PromptRecord]:
    """One typed message from a user_prompt event. Length-only unless keep_text: Claude Code only sends the text
    when the user turned on OTEL_LOG_USER_PROMPTS, and the free path must never read it even then."""
    text = a.get("prompt") if keep_text and isinstance(a.get("prompt"), str) else None
    if text is not None:
        fl = signals.analyse(text, first=first)
        if fl is None:
            return None
        rec = PromptRecord(session_id=sid, turn_id=turn, ts=ts, first=first, **fl)
        rec.text = text  # type: ignore[attr-defined]  # not a dataclass field: to_dict() never carries it
        rec.command = rec.command or _command_name(a)
        return rec
    n = to_int(a.get("prompt_length"))
    if n is None:
        return None
    return PromptRecord(session_id=sid, turn_id=turn, ts=ts, chars=n, words=0, first=first,
                        command=_command_name(a), has_text=False)


def _from_spans(ds: Dataset, spans: List[dict], ctx: dict) -> None:
    """Build call and tool records from gen_ai / Claude Code spans."""
    h = ctx["hasher"]
    by_id = {}
    for x in spans:
        sid = x["s"].get("spanId")
        if sid:
            by_id[sid] = x
        x["kind"] = _kind(x["s"].get("name", ""), x["a"])

    def turn_of(x: dict) -> dict:
        cur, seen = x, 0
        while cur is not None and seen < 50:
            if cur["kind"] == "turn":
                return cur
            cur = by_id.get(cur["s"].get("parentSpanId"))
            seen += 1
        return x

    call_index: Dict[str, int] = {}
    calls = sorted((x for x in spans if x["kind"] == "call"), key=lambda x: to_int(x["s"].get("startTimeUnixNano")) or 0)
    for x in calls:
        s, a, res = x["s"], x["a"], x["res"]
        start = parse_ts(s.get("startTimeUnixNano"))
        end = parse_ts(s.get("endTimeUnixNano"))
        if start is None and end is None:
            continue
        start = start if start is not None else end
        end = end if end is not None else start
        if end < start:
            start, end = end, start
            ds.fixed_durations += 1
        t = turn_of(x)
        session_raw = pick(a, SESSION) or pick(t["a"], SESSION) or pick(x["res"], SESSION) or s.get("traceId")
        turn_raw = (t["s"].get("spanId") if t["kind"] == "turn" else None) or pick(t["a"], TURN) or s.get("traceId")
        svc = str(res.get("service.name") or a.get("gen_ai.agent.name") or "")
        rec = CallRecord(source="otlp:claude-code" if "claude-code" in svc or "claude_code" in s.get("name", "") else "otlp",
                         session_id=h(session_raw), turn_id=h(str(session_raw) + str(turn_raw)),
                         ts_start=start, ts_end=end, model=normalize_model(pick(a, MODEL)),
                         is_subagent=bool(a.get("agent_id") or a.get("claude_code.agent_id")))
        _usage(rec, a)
        call_index[s.get("spanId") or str(id(x))] = len(ds.calls)
        ds.calls.append(rec)
        _emit_identity(ctx, rec, a, t["a"], res)

    for x in spans:
        if x["kind"] != "tool":
            continue
        s, a = x["s"], x["a"]
        ok = (s.get("status") or {}).get("code") not in (2, "STATUS_CODE_ERROR")
        succ = a.get("success")
        if succ is False or (isinstance(succ, str) and succ.lower() == "false"):
            ok = False
        name = pick(a, TOOL[:-1]) or str(s.get("name", "")).replace("execute_tool ", "") or "unknown"
        parent = by_id.get(s.get("parentSpanId"))
        ci = call_index.get(parent["s"].get("spanId")) if parent and parent["kind"] == "call" else None
        t = turn_of(x)
        session_raw = pick(a, SESSION) or pick(t["a"], SESSION) or pick(x["res"], SESSION) or s.get("traceId")
        turn_raw = (t["s"].get("spanId") if t["kind"] == "turn" else None) or pick(t["a"], TURN) or s.get("traceId")
        trec = ToolRecord(session_id=h(session_raw), turn_id=h(str(session_raw) + str(turn_raw)),
                          ts=parse_ts(s.get("endTimeUnixNano")) or 0.0, tool=str(name)[:80], ok=ok,
                          after_call=ci)
        ds.tools.append(trec)
        _emit_identity(ctx, trec, a, t["a"], x["res"])
    if calls:
        n_sessions = len({c.session_id for c in ds.calls})
        ds.sources.append("OTel traces (%d session%s)" % (n_sessions, "" if n_sessions == 1 else "s"))


def _api_error(ds: Dataset, a: dict, sid: str, tid: str, ts: float) -> Any:
    """api_error event -> ds.api_errors."""
    r = ApiErrorRecord(session_id=sid, ts=ts, model=normalize_model(pick(a, MODEL)), status_code=_nat(pick(a, STATUS)),
                       attempt=_nat(a.get("attempt")), duration_ms=_nat(pick(a, DURATION)))
    ds.api_errors.append(r)
    return r


def _retries_exhausted(ds: Dataset, a: dict, sid: str, tid: str, ts: float) -> Any:
    """api_retries_exhausted event -> ds.retries_exhausted."""
    r = RetryExhaustedRecord(session_id=sid, ts=ts, status_code=_nat(pick(a, STATUS)),
                             total_attempts=_nat(a.get("total_attempts")),
                             total_retry_duration_ms=_nat(a.get("total_retry_duration_ms")))
    ds.retries_exhausted.append(r)
    return r


def _tool_decision(ds: Dataset, a: dict, sid: str, tid: str, ts: float) -> Any:
    """tool_decision event -> ds.tool_decisions; a user_abort also lands in ds.interrupts (the interrupts habit)."""
    r = ToolDecisionRecord(session_id=sid, turn_id=tid, ts=ts, decision=_enum(a.get("decision")),
                           source=_enum(a.get("source")), tool_source=_enum(a.get("tool_source")))
    ds.tool_decisions.append(r)
    if r.source == "user_abort":
        ds.interrupts.append(("me", sid, tid, ts))
    return r


def _compaction(ds: Dataset, a: dict, sid: str, tid: str, ts: float) -> Any:
    """compaction event -> ds.compaction_events; every one that did not fail is also a (dev, session, ts) entry in
    ds.compactions, the shape the compactions habit already reads."""
    r = CompactionRecord(session_id=sid, ts=ts, trigger=_enum(a.get("trigger")), success=_flag(a.get("success")),
                         pre_tokens=_nat(a.get("pre_tokens")), post_tokens=_nat(a.get("post_tokens")))
    ds.compaction_events.append(r)
    if r.success is not False:
        ds.compactions.append(("me", sid, ts))
    return r


def _subagent(ds: Dataset, a: dict, sid: str, tid: str, ts: float) -> Any:
    """subagent_completed event -> ds.subagent_runs."""
    r = SubagentRecord(session_id=sid, ts=ts, total_tokens=_nat(a.get("total_tokens")),
                       total_tool_uses=_nat(a.get("total_tool_uses")), duration_ms=_nat(pick(a, DURATION)),
                       model=normalize_model(pick(a, MODEL)), model_swapped=_flag(a.get("model_swapped")),
                       is_built_in=_flag(a.get("is_built_in")))
    ds.subagent_runs.append(r)
    return r


def _response(ds: Dataset, a: dict, sid: str, tid: str, ts: float) -> Any:
    """assistant_response event -> ds.responses (the length only)."""
    r = ResponseRecord(session_id=sid, turn_id=tid, ts=ts, response_length=_nat(pick(a, RESPONSE_LEN)),
                       query_source=_enum(pick(a, QUERY_SOURCE)))
    ds.responses.append(r)
    return r


# log event name -> builder for the telemetry-only events; each reads an allowlist of numbers and enums
_EVENT_BUILDERS = {"api_error": _api_error, "api_retries_exhausted": _retries_exhausted,
                   "tool_decision": _tool_decision, "compaction": _compaction,
                   "subagent_completed": _subagent, "assistant_response": _response}


def _from_logs(ds: Dataset, logs: List[dict], ctx: dict) -> None:
    """Build call, tool and (length-only) prompt records from Claude Code log events."""
    h = ctx["hasher"]
    seen_sessions = set()
    bill = 0.0
    bill_seen = False
    scope = []
    for x in sorted(logs, key=lambda x: to_int(x["l"].get("timeUnixNano")) or 0):
        lr, a = x["l"], x["a"]
        ev = str(a.get("event.name") or (lr.get("body") or {}).get("stringValue") or "")
        ev = ev.replace("claude_code.", "")
        end = parse_ts(a.get("event.timestamp")) or parse_ts(lr.get("timeUnixNano")) or parse_ts(lr.get("observedTimeUnixNano"))
        if end is None:
            continue
        session_raw = pick(a, SESSION) or pick(x["res"], SESSION) or "otel-logs"
        turn_raw = pick(a, TURN) or end
        if ev == "api_request":
            dur = to_int(a.get("duration_ms"))
            start = end - dur / 1000.0 if dur and dur > 0 else end
            rec = CallRecord(source="otlp:claude-code", session_id=h(session_raw), turn_id=h(str(session_raw) + str(turn_raw)),
                             ts_start=start, ts_end=end, model=normalize_model(pick(a, MODEL)),
                             is_subagent=bool(a.get("agent_id")))
            _usage(rec, a)
            rec.cost_usd = _num(pick(a, COST))
            rec.effort = _enum(pick(a, EFFORT))
            rec.query_source = _enum(pick(a, QUERY_SOURCE))
            speed = _enum(a.get("speed"))
            rec.speed = {"normal": "standard"}.get(speed, speed)
            if rec.cost_usd is not None:
                bill += rec.cost_usd
                bill_seen = True
                scope.append(len(ds.calls))
            ds.calls.append(rec)
            _emit_identity(ctx, rec, a, x["res"])
        elif ev == "user_prompt" and ctx["prompts"]:
            sid = h(session_raw)
            first = session_raw not in seen_sessions
            seen_sessions.add(session_raw)
            prec = _prompt_record(a, sid, h(str(session_raw) + str(turn_raw)), end, first, ctx["keep_text"])
            if prec is not None:
                ds.prompts.append(prec)
                _emit_identity(ctx, prec, a, x["res"])
        elif ev == "tool_result":
            succ = a.get("success")
            ok = not (succ is False or (isinstance(succ, str) and succ.lower() == "false"))
            trec = ToolRecord(session_id=h(session_raw), turn_id=h(str(session_raw) + str(turn_raw)),
                              ts=end, tool=str(a.get("tool_name") or "unknown")[:80], ok=ok,
                              result_chars=_nat(pick(a, RESULT_SIZE)), tool_input_bytes=_nat(pick(a, INPUT_SIZE)),
                              duration_ms=_nat(pick(a, DURATION)), decision_type=_enum(pick(a, DECISION_TYPE)),
                              decision_source=_enum(pick(a, DECISION_SOURCE)))
            ds.tools.append(trec)
            _emit_identity(ctx, trec, a, x["res"])
        elif ev in _EVENT_BUILDERS:
            sid, tid = h(session_raw), h(str(session_raw) + str(turn_raw))
            rec = _EVENT_BUILDERS[ev](ds, a, sid, tid, end)
            if rec is not None:
                _emit_identity(ctx, rec, a, x["res"])
    if ds.calls:
        # attach tools to the latest call before them in the same session
        by_session: Dict[str, List[int]] = {}
        for i in sorted(range(len(ds.calls)), key=lambda i: ds.calls[i].ts_end):
            by_session.setdefault(ds.calls[i].session_id, []).append(i)
        ends = {k: [ds.calls[i].ts_end for i in v] for k, v in by_session.items()}
        for t in ds.tools:
            if t.after_call is None and t.session_id in by_session:
                j = bisect.bisect_right(ends[t.session_id], t.ts) - 1
                t.after_call = by_session[t.session_id][j] if j >= 0 else None
        n_sessions = len({c.session_id for c in ds.calls})
        ds.sources.append("Claude Code telemetry (%d session%s)" % (n_sessions, "" if n_sessions == 1 else "s"))
    if bill_seen:
        ds.bill_usd = bill
        ds.bill_scope = scope
        ds.bill_label = "Claude Code telemetry cost_usd"
