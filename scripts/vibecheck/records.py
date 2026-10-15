"""Normalized records. Every source maps to these.

Missing usage is None ("not recorded"), never 0. No record holds text: prompts are reduced to lengths, flags and
one-way hashes by sources/signals.py before they get here.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class CallRecord:
    source: str                      # "claude_code_jsonl" | "otlp" | "claude_export"
    session_id: str                  # hashed
    turn_id: str                     # hashed; one user request
    ts_start: float                  # unix seconds
    ts_end: float
    model: Optional[str]             # normalized model key, None if unknown
    input: Optional[int] = None
    output: Optional[int] = None
    cache_read: Optional[int] = None
    cache_write_5m: Optional[int] = None
    cache_write_1h: Optional[int] = None
    cache_write_unknown: Optional[int] = None   # write tokens with unknown TTL
    reasoning: Optional[int] = None
    finish_reason: Optional[str] = None
    speed: Optional[str] = None      # "fast" | "standard" (enum only); fast mode has its own prices
    web_searches: Optional[int] = None  # server-side web search requests, billed per request
    cost_usd: Optional[float] = None    # cost Claude Code itself reported for this request (telemetry only)
    effort: Optional[str] = None        # reasoning effort enum: "low" | "medium" | "high" | "max" ...
    query_source: Optional[str] = None  # which part of Claude Code made the call (enum, e.g. "repl_main_thread")
    is_subagent: bool = False
    usage_recorded: bool = True
    estimated: bool = False          # tokens estimated from text length (chat export)
    dev: str = "me"                  # developer label; always "me" for a single local run

    @property
    def cache_write(self) -> int:
        return (self.cache_write_5m or 0) + (self.cache_write_1h or 0) + (self.cache_write_unknown or 0)

    @property
    def ctx(self) -> int:
        """Context carried by this call: cache read + cache write + uncached input."""
        return (self.cache_read or 0) + self.cache_write + (self.input or 0)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ToolRecord:
    session_id: str
    turn_id: str
    ts: float
    tool: str
    ok: bool
    after_call: Optional[int] = None   # index of the CallRecord that requested the tool
    result_chars: Optional[int] = None # size of what the tool returned, None if not recorded
    file_key: Optional[str] = None     # per-run hash of the file a file tool touched; never written out
    tool_input_bytes: Optional[int] = None  # size of the tool's input (telemetry only; never the input itself)
    duration_ms: Optional[int] = None
    decision_type: Optional[str] = None     # enum: "accept" | "reject"
    decision_source: Optional[str] = None   # enum: "config" | "user_temporary" | "user_abort" ...
    dev: str = "me"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PromptRecord:
    """One message a person typed. Only derived numbers and flags; the text itself is never kept."""
    session_id: str
    turn_id: str
    ts: float
    chars: int
    words: int
    first: bool = False                # first prompt of its session
    thanks: bool = False               # a short thank-you or "great" with nothing else to do
    rework: bool = False               # starts by rejecting the last answer ("no", "revert", "still broken")
    vague: bool = False                # session opener with nothing to go on ("fix it")
    command: Optional[str] = None      # built-in slash command, e.g. "clear"
    fps: List[str] = field(default_factory=list)  # per-run hashes of standing instructions; never written out
    has_text: bool = True              # False when only the length was sent, so the text-derived flags mean nothing
    dev: str = "me"

    def to_dict(self) -> dict:
        return asdict(self)


# The records below come from Claude Code telemetry log events only. Numbers, booleans and short enums; no text.

@dataclass
class ApiErrorRecord:
    """A failed model request (api_error event)."""
    session_id: str
    ts: float
    model: Optional[str] = None
    status_code: Optional[int] = None
    attempt: Optional[int] = None
    duration_ms: Optional[int] = None
    dev: str = "me"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RetryExhaustedRecord:
    """A request given up on after all retries (api_retries_exhausted event)."""
    session_id: str
    ts: float
    status_code: Optional[int] = None
    total_attempts: Optional[int] = None
    total_retry_duration_ms: Optional[int] = None
    dev: str = "me"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ToolDecisionRecord:
    """A permission decision for one tool call (tool_decision event)."""
    session_id: str
    turn_id: str
    ts: float
    decision: Optional[str] = None      # enum: "accept" | "reject"
    source: Optional[str] = None        # enum: "config" | "user_temporary" | "user_abort" | "user_reject" ...
    tool_source: Optional[str] = None   # enum: "builtin" | "mcp" ...
    dev: str = "me"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CompactionRecord:
    """One context compaction (compaction event) with the context size before and after."""
    session_id: str
    ts: float
    trigger: Optional[str] = None       # enum: "auto" | "manual"
    success: Optional[bool] = None
    pre_tokens: Optional[int] = None
    post_tokens: Optional[int] = None
    dev: str = "me"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SubagentRecord:
    """One finished subagent run (subagent_completed event)."""
    session_id: str
    ts: float
    total_tokens: Optional[int] = None
    total_tool_uses: Optional[int] = None
    duration_ms: Optional[int] = None
    model: Optional[str] = None
    model_swapped: Optional[bool] = None
    is_built_in: Optional[bool] = None
    dev: str = "me"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResponseRecord:
    """The length of one assistant answer (assistant_response event); never the answer."""
    session_id: str
    turn_id: str
    ts: float
    response_length: Optional[int] = None
    query_source: Optional[str] = None
    dev: str = "me"

    def to_dict(self) -> dict:
        return asdict(self)


# Dataset lists of the telemetry-only records above; extend() merges them all by name.
_EVENT_LISTS = ("api_errors", "retries_exhausted", "tool_decisions", "compaction_events", "subagent_runs", "responses")


@dataclass
class Dataset:
    calls: List[CallRecord] = field(default_factory=list)
    tools: List[ToolRecord] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)        # human labels, e.g. "Claude Code (12 sessions)"
    bill_usd: Optional[float] = None                         # recorded cost for D7, if any source has one
    bill_label: Optional[str] = None
    bill_tokens: Dict[str, int] = field(default_factory=dict)
    bill_scope: List[int] = field(default_factory=list)      # indices of calls the bill covers
    notes: List[str] = field(default_factory=list)           # data quality notes from parsers
    fixed_durations: int = 0
    estimated: bool = False
    prompts: List[PromptRecord] = field(default_factory=list)
    interrupts: List[tuple] = field(default_factory=list)    # (dev, session_id, turn_id, ts)
    compactions: List[tuple] = field(default_factory=list)   # (dev, session_id, ts)
    api_errors: List[ApiErrorRecord] = field(default_factory=list)
    retries_exhausted: List[RetryExhaustedRecord] = field(default_factory=list)
    tool_decisions: List[ToolDecisionRecord] = field(default_factory=list)
    compaction_events: List[CompactionRecord] = field(default_factory=list)   # detail; .compactions is the habit's view
    subagent_runs: List[SubagentRecord] = field(default_factory=list)
    responses: List[ResponseRecord] = field(default_factory=list)
    session_dirs: Dict[str, str] = field(default_factory=dict)  # session_id -> project folder; private, for setup checks
    setup: dict = field(default_factory=dict)                 # sources/setup.scan() result; sizes and MCP names only

    def extend(self, other: "Dataset") -> None:
        offset = len(self.calls)
        self.calls.extend(other.calls)
        for t in other.tools:
            if t.after_call is not None:
                t.after_call += offset
            self.tools.append(t)
        self.prompts.extend(other.prompts)
        self.interrupts.extend(other.interrupts)
        self.compactions.extend(other.compactions)
        for name in _EVENT_LISTS:
            getattr(self, name).extend(getattr(other, name))
        self.session_dirs.update(other.session_dirs)
        self.sources.extend(other.sources)
        self.notes.extend(other.notes)
        self.fixed_durations += other.fixed_durations
        self.estimated = self.estimated or other.estimated
        if other.bill_usd is not None:
            self.bill_usd = (self.bill_usd or 0.0) + other.bill_usd
            self.bill_label = other.bill_label
            self.bill_scope.extend(i + offset for i in other.bill_scope)
            for k, v in other.bill_tokens.items():
                self.bill_tokens[k] = self.bill_tokens.get(k, 0) + v
