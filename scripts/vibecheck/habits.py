"""Habits: what the way you prompt, the tools you run and your setup cost you.

These read the prompt signals, tool output sizes and setup files the parsers collected (never text; see
sources/signals.py). The prompt and setup habits also feed two radar axes (D10 Clear prompting, D11 Lean setup;
see axes()). Each habit is a finding with a count and, where it can be priced, the usage it involved.

The habit names, advice and sentence templates live in data/habit_texts.json, filled with numbers computed here. That
is an optional text file, absent in this build: without it the detectors still run and the two axes are still
scored, but run() returns no named habits.
"""

import json
import pkgutil
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from .sources.setup import mcp_server_of
from .texts import Fmt, tokens

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
CHARS_PER_TOKEN = 4.0

DEFAULTS = {
    "repeat_min_sessions": 3,
    "thanks_min_ctx": 50000,
    "paste_min_chars": 6000,
    "noisy_min_chars": 20000,
    "churn_min_edits": 10,
    "compaction_min": 2,
    "dead_end_min_calls": 20,
    "dead_end_min_usd": 2.0,
    "memory_heavy_tokens": 5000,
    "no_memory_min_sessions": 3,
}

_texts_cache: Dict[str, Optional[dict]] = {}


def load_texts() -> Optional[dict]:
    """The optional habit texts (groups and item templates), or None when the file is absent, as in this build.
    Parsed once; pkgutil returns None for a missing file, which is the normal case here."""
    if "t" not in _texts_cache:
        raw = None
        try:
            raw = pkgutil.get_data("vibecheck", "data/habit_texts.json")
        except OSError:
            pass
        _texts_cache["t"] = json.loads(raw.decode("utf-8")) if raw else None
    return _texts_cache["t"]


def groups() -> list:
    """The habit groups [(id, title)] for display; empty when the texts are not available."""
    t = load_texts()
    return [tuple(g) for g in t["groups"]] if t else []


def _lin(value: float, good: float, bad: float) -> float:
    """100 at value <= good, 0 at value >= bad, linear between."""
    if bad == good:
        return 100.0 if value <= good else 0.0
    return max(0.0, min(100.0, 100.0 * (1.0 - (value - good) / (bad - good))))


def _norm(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


class Habits:
    def __init__(self, a, f: Fmt):
        self.a = a
        self.ds = a.ds
        self.f = f
        self.cfg = dict(DEFAULTS, **(a.cfg.get("habits") or {}))
        self.texts = (load_texts() or {}).get("items")
        self.m: Dict[str, float] = {}   # raw numbers behind the habits, for the Prompting and Setup axes
        self.by_stream: Dict[tuple, List[int]] = defaultdict(list)
        for i in a.calls:
            c = self.ds.calls[i]
            if not c.is_subagent:
                self.by_stream[(c.dev, c.session_id)].append(i)

    # ---------- money helpers ----------

    def _turn_usd(self, dev: str, turn_id: str) -> float:
        return sum(self.a._c(i) for i in self.a.turns.get(dev + ":" + turn_id, []))

    def _read_price(self, i: int) -> float:
        c = self.ds.calls[i]
        p = self.a.pricer.rates(c)
        if not p:
            return 0.0
        return (p["input"] if self.a.estimated else p["cache_read"]) / 1e6

    def _carried_usd(self, dev: str, sid: str, ts: float, toks: float) -> float:
        """Cost of carrying toks extra tokens in every later call of the session."""
        return sum(toks * self._read_price(i) for i in self.by_stream.get((dev, sid), [])
                   if self.ds.calls[i].ts_start > ts)

    def _share(self, usd: float) -> float:
        return usd / self.a.total if self.a.total else 0.0

    def _money(self, usd: float) -> str:
        return self.f.money(usd, approx=True)

    def _item(self, key: str, variant: str, group: str, flagged: bool, usd: Optional[float] = None,
              extra: Optional[dict] = None, **v) -> Optional[dict]:
        """One habit finding, its sentences filled from the "key.variant" template with the numbers in v.
        Returns None when the texts file is absent (file absent), so the habit is silently left out."""
        if not self.texts:
            return None
        # an integer field X also offers X_n (thousands separators) and X_s (plural "s"), so templates need no code
        for k, val in list(v.items()):
            if isinstance(val, int):
                v[k + "_n"] = "{:,}".format(val)
                v[k + "_s"] = "" if val == 1 else "s"
        t = {k: s.format(**v) for k, s in self.texts[key + "." + variant].items()}
        d = {"key": key, "group": group, "title": t["title"], "flagged": flagged, "stat": t["stat"], "saw": t["saw"],
             "do": t["do"], "usd": usd, "share": self._share(usd) if usd else None}
        if extra:
            d.update(extra)
        return d

    # ---------- prompts ----------

    def repeated(self) -> Optional[dict]:
        P = self.ds.prompts
        if not P:
            return None
        sessions = defaultdict(set)
        for p in P:
            for fp in p.fps:
                sessions[fp].add((p.dev, p.session_id))
        n_sess = len({(p.dev, p.session_id) for p in P})
        thr = self.cfg["repeat_min_sessions"]
        rep = sorted((len(s) for s in sessions.values() if len(s) >= thr), reverse=True)
        if n_sess >= thr:
            self.m["repeated"] = len(rep)
        if not rep:
            return self._item("repeated", "none", "prompts", False, thr=thr)
        return self._item("repeated", "one" if len(rep) == 1 else "many", "prompts", True,
                          n=len(rep), thr=thr, top=rep[0], n_sess=n_sess)

    def thanks(self) -> Optional[dict]:
        P = [p for p in self.ds.prompts if p.thanks]
        if not self.ds.prompts:
            return None
        rows = []
        for p in P:
            idx = self.a.turns.get(p.dev + ":" + p.turn_id, [])
            if idx and max(self.ds.calls[i].ctx for i in idx) >= self.cfg["thanks_min_ctx"]:
                rows.append(sum(self.a._c(i) for i in idx))
        usd = sum(rows)
        self.m["thanks_share"] = self._share(usd)
        if not rows:
            return self._item("thanks", "none", "prompts", False)
        return self._item("thanks", "found", "prompts", True, usd, n=len(rows), ctx=tokens(self.cfg["thanks_min_ctx"]),
                          total=self._money(usd), each=self._money(usd / len(rows)))

    def rework(self) -> Optional[dict]:
        P = self.ds.prompts
        typed = [p for p in P if p.chars and not p.first]
        if len(typed) < 5:
            return None
        rw = [p for p in typed if p.rework]
        rate = len(rw) / len(typed)
        # the answer each correction rejected: the turn before it in the same session
        prev_turn = {}
        by_sess = defaultdict(list)
        for p in sorted(P, key=lambda p: p.ts):
            by_sess[(p.dev, p.session_id)].append(p)
        for ps in by_sess.values():
            for a, b in zip(ps, ps[1:]):
                prev_turn[id(b)] = a
        usd = sum(self._turn_usd(prev_turn[id(p)].dev, prev_turn[id(p)].turn_id) for p in rw if id(p) in prev_turn)
        flagged = rate >= 0.1 and len(rw) >= 3
        self.m["rework_rate"] = rate
        self.m["rework_usd"] = usd
        if not rw:
            return self._item("rework", "none", "prompts", False, typed=len(typed))
        return self._item("rework", "flagged" if flagged else "minor", "prompts", flagged, usd, rate=Fmt.share(rate),
                          rw=len(rw), typed=len(typed), money=self._money(usd))

    def vague(self) -> Optional[dict]:
        first = [p for p in self.ds.prompts if p.first]
        if not first:
            return None
        v = [p for p in first if p.vague]
        if len(first) >= 3:
            self.m["vague_share"] = len(v) / len(first)
        if not v:
            return self._item("vague", "none", "prompts", False)
        return self._item("vague", "found", "prompts", len(v) >= 2, n=len(v), total=len(first))

    def pastes(self) -> Optional[dict]:
        if not self.ds.prompts:
            return None
        big = [p for p in self.ds.prompts if p.chars >= self.cfg["paste_min_chars"]]
        if not big:
            self.m["paste_share"] = 0.0
            return None
        toks = sum(p.chars for p in big) / CHARS_PER_TOKEN
        usd = sum(self._carried_usd(p.dev, p.session_id, p.ts, p.chars / CHARS_PER_TOKEN) for p in big)
        self.m["paste_share"] = self._share(usd)
        self.m["paste_usd"] = usd
        return self._item("pastes", "priced" if usd >= 0.01 else "unpriced", "prompts", True, usd, n=len(big),
                          min="{:,}".format(self.cfg["paste_min_chars"]), toks=tokens(toks), money=self._money(usd))

    # ---------- tools ----------

    def noisy(self) -> Optional[dict]:
        sized = [t for t in self.ds.tools if t.result_chars is not None]
        if not sized:
            return None
        big = [t for t in sized if t.result_chars >= self.cfg["noisy_min_chars"]]
        self.m["noisy_share"] = 0.0
        mn = "{:,}".format(self.cfg["noisy_min_chars"])
        if not big:
            return self._item("noisy", "none", "tools", False, min=mn)
        toks = sum(t.result_chars for t in big) / CHARS_PER_TOKEN
        usd = sum(self._carried_usd(t.dev, t.session_id, t.ts, t.result_chars / CHARS_PER_TOKEN) for t in big)
        self.m["noisy_share"] = self._share(usd)
        self.m["noisy_usd"] = usd
        top = Counter(t.tool for t in big).most_common(3)
        return self._item("noisy", "found", "tools", True, usd, {"tools": [{"tool": n, "count": k} for n, k in top]},
                          n=len(big), min=mn, toks=tokens(toks), top=", ".join("%s (%d)" % (n, k) for n, k in top),
                          money=self._money(usd))

    def churn(self) -> Optional[dict]:
        edits = defaultdict(Counter)
        for t in self.ds.tools:
            if t.tool in EDIT_TOOLS and t.file_key:
                edits[(t.dev, t.session_id)][t.file_key] += 1
        if not edits:
            return None
        thr = self.cfg["churn_min_edits"]
        hot = [(s, n) for s, c in edits.items() for n in c.values() if n >= thr]
        if not hot:
            return self._item("churn", "none", "tools", False, thr=thr)
        return self._item("churn", "found", "tools", True, n=len(hot), thr=thr, maxn=max(n for _, n in hot),
                          sess=len({s for s, _ in hot}))

    # ---------- sessions ----------

    def interrupts(self) -> Optional[dict]:
        if not self.ds.interrupts:
            return None if not self.ds.prompts else self._item("interrupts", "none", "sessions", False)
        turns = {(d, t) for d, _s, t, _ts in self.ds.interrupts}
        usd = sum(self._turn_usd(d, t) for d, t in turns)
        return self._item("interrupts", "once" if len(turns) == 1 else "many", "sessions", len(turns) >= 3, usd,
                          n=len(turns), money=self._money(usd))

    def compactions(self) -> Optional[dict]:
        if not self.ds.prompts and not self.ds.compactions:
            return None
        per = Counter((d, s) for d, s, _ in self.ds.compactions)
        heavy = {k: n for k, n in per.items() if n >= self.cfg["compaction_min"]}
        if not heavy:
            return self._item("compactions", "none", "sessions", False)
        return self._item("compactions", "found", "sessions", True, n=len(heavy), thr=self.cfg["compaction_min"],
                          maxn=max(heavy.values()))

    def dead_ends(self) -> Optional[dict]:
        if not any(t.tool in EDIT_TOOLS for t in self.ds.tools):
            return None
        edited = {(t.dev, t.session_id) for t in self.ds.tools if t.tool in EDIT_TOOLS}
        rows = []
        for (dev, sid), idx in self.by_stream.items():
            usd = sum(self.a._c(i) for i in idx)
            if (dev, sid) not in edited and len(idx) >= self.cfg["dead_end_min_calls"] and usd >= self.cfg["dead_end_min_usd"]:
                rows.append(usd)
        if not rows:
            return self._item("dead_ends", "none", "sessions", False)
        usd = sum(rows)
        return self._item("dead_ends", "found", "sessions", len(rows) >= 2, usd, n=len(rows),
                          calls=self.cfg["dead_end_min_calls"], money=self._money(usd))

    # ---------- setup ----------

    def memory(self) -> Optional[dict]:
        st = getattr(self.ds, "setup", None) or {}
        projects = st.get("projects") or {}
        if not projects:
            return None
        sp = st.get("session_project") or {}
        user_t = st.get("user_memory_tokens") or 0
        heavy_t = self.cfg["memory_heavy_tokens"]
        usd = 0.0
        heavy = []
        none = []
        sess_per_proj = Counter(sp.values())
        for k, p in projects.items():
            t = p["memory_tokens"] + user_t
            if t >= heavy_t:
                heavy.append(t)
            if p["exists"] and not p["memory_files"] and sess_per_proj[k] >= self.cfg["no_memory_min_sessions"]:
                none.append(k)
        for (dev, sid), idx in self.by_stream.items():
            k = sp.get(sid)
            if k is None:
                continue
            t = projects[k]["memory_tokens"] + user_t
            if t >= heavy_t:
                usd += sum(t * self._read_price(i) for i in idx)
        self.m["memory_tokens"] = max(p["memory_tokens"] for p in projects.values()) + user_t
        self.m["memory_missing"] = len(none)
        self.m["memory_usd"] = usd
        if heavy:
            return self._item("memory", "heavy", "setup", True, usd, tok=tokens(max(heavy)), n=len(heavy),
                              money=self._money(usd))
        if none:
            return self._item("memory", "missing_one" if len(none) == 1 else "missing_many", "setup", True,
                              n=len(none), thr=self.cfg["no_memory_min_sessions"])
        if not any(p["memory_files"] for p in projects.values()) and not user_t:
            return self._item("memory", "none_yet", "setup", False)
        return self._item("memory", "lean", "setup", False,
                          tok=tokens(max(p["memory_tokens"] for p in projects.values()) + user_t))

    def mcp(self) -> Optional[dict]:
        st = getattr(self.ds, "setup", None) or {}
        projects = st.get("projects") or {}
        configured = {m for p in projects.values() for m in p["mcp"]}
        if not configured:
            return None
        used = set()
        for t in self.ds.tools:
            for cand in mcp_server_of(t.tool):
                used.add(cand)
        unused = sorted(m for m in configured if _norm(m) not in used and m not in used)
        self.m["mcp_unused_share"] = len(unused) / len(configured)
        self.m["mcp_unused"] = len(unused)
        self.m["mcp_configured"] = len(configured)
        if not unused:
            return self._item("mcp", "all_used", "setup", False)
        return self._item("mcp", "unused_more" if len(unused) > 5 else "unused", "setup", True,
                          extra={"servers": unused[:10]}, unused=len(unused), configured=len(configured),
                          names=", ".join(unused[:5]), more=len(unused) - 5)

    def run(self) -> List[dict]:
        out = []
        for fn in (self.repeated, self.thanks, self.rework, self.vague, self.pastes, self.noisy, self.churn,
                   self.interrupts, self.compactions, self.dead_ends, self.memory, self.mcp):
            r = fn()
            if r:
                out.append(r)
        out.sort(key=lambda r: (not r["flagged"], -(r["usd"] or 0)))
        return out

    # ---------- the two habit axes on the radar ----------

    def axes(self) -> Dict[str, dict]:
        """D10 Clear prompting and D11 Lean setup, scored 0 to 100 (100 best) from the numbers run() collected.
        Each is the weighted average of the parts this source has data for (weights in scoring.json); n/a when it
        has none."""
        m = self.m
        c10 = self.a.cfg.get("d10") or {}
        c11 = self.a.cfg.get("d11") or {}
        parts10 = {}
        if "rework_rate" in m:
            parts10["corrections"] = _lin(m["rework_rate"], c10.get("rework_100_at", 0.03), c10.get("rework_0_at", 0.25))
        if "vague_share" in m:
            parts10["openers"] = _lin(m["vague_share"], 0.0, c10.get("vague_0_at", 0.3))
        if "repeated" in m:
            parts10["repeats"] = _lin(m["repeated"], 0, c10.get("repeated_0_at", 8))
        if self.ds.prompts and parts10:
            parts10["thanks"] = _lin(m.get("thanks_share", 0.0), 0.0, c10.get("thanks_0_at_share", 0.05))
            parts10["pastes"] = _lin(m.get("paste_share", 0.0), 0.0, c10.get("paste_0_at_share", 0.1))
        usd10 = m.get("rework_usd", 0.0) + m.get("thanks_share", 0.0) * self.a.total + m.get("paste_usd", 0.0)
        parts11 = {}
        if "memory_tokens" in m:
            mem = _lin(m["memory_tokens"], c11.get("memory_100_at", 3000), c11.get("memory_0_at", 20000))
            if m.get("memory_missing"):
                mem = min(mem, c11.get("missing_memory_score", 70))
            parts11["memory"] = mem
        if "mcp_unused_share" in m:
            parts11["mcp"] = _lin(m["mcp_unused_share"], 0.0, c11.get("mcp_0_at_share", 0.75))
        if "noisy_share" in m:
            parts11["tools"] = _lin(m["noisy_share"], 0.0, c11.get("noisy_0_at_share", 0.15))
        usd11 = m.get("memory_usd", 0.0) + m.get("noisy_usd", 0.0)
        out = {}
        for key, parts, usd in (("D10", parts10, usd10), ("D11", parts11, usd11)):
            if not parts:
                out[key] = {"available": False}
                continue
            w = (c10 if key == "D10" else c11).get("weights") or {}
            total_w = sum(w.get(k, 1.0) for k in parts)
            score = sum(v * w.get(k, 1.0) for k, v in parts.items()) / total_w
            out[key] = {"available": True, "score": score, "parts": parts,
                        "involved_usd": usd, "share": self._share(usd), "saving_usd": 0.0,
                        "metrics": {k: v for k, v in m.items()}}
        return out
