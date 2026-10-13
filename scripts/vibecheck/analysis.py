"""Detectors DQ and D1 to D9, the fix simulator, axis scores and the vibe score.

Everything here is deterministic. Every number in the report is produced by this module; templates only
place them. Thresholds come from data/scoring.json, level names and texts from data/levels.json.
"""

import bisect
import json
import pkgutil
import statistics
import time
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

from . import __version__
from .models import pretty
from .pricing import Pricer
from .records import CallRecord, Dataset
from .habits import Habits, groups as habit_groups
from .texts import Fmt


# Each axis is named for the good habit it measures; 100 is the best score.
AXES = [
    ("D4", "No idle rebuilds"),
    ("D1", "Lean context"),
    ("D2", "Lean small edits"),
    ("D3", "Short agent loops"),
    ("D5", "Clean tool runs"),
    ("D6", "Right model for the job"),
    ("D10", "Clear prompting"),
    ("D11", "Lean setup"),
]
AXIS_LABEL = dict(AXES)
RELIABILITY = {"D4": "highest", "D1": "high", "D2": "high", "D3": "medium", "D5": "medium", "D6": "option",
               "D10": "medium, from patterns in what you typed", "D11": "high"}
SCORING_VERSION = 2   # 2: eight axes (Prompting and Setup added). Kept at 2 when the cap was removed: the owner wants
                      # the trend to keep comparing with earlier (capped) scores.

ESTIMATED_PRICES = {"input": 1.0, "cache_write_5m": 1.25, "cache_write_1h": 2.0, "cache_read": 0.1, "output": 5.0}


def _load(name: str) -> dict:
    return json.loads(pkgutil.get_data("vibecheck", "data/" + name).decode("utf-8"))


def _is_cc(c: CallRecord) -> bool:
    return c.source.startswith("claude_code") or "claude-code" in c.source


def _lin(value: float, good: float, bad: float) -> float:
    """100 at value <= good, 0 at value >= bad, linear between."""
    if bad == good:
        return 100.0 if value <= good else 0.0
    x = (value - good) / (bad - good)
    return max(0.0, min(100.0, 100.0 * (1.0 - x)))


class Analysis:
    def __init__(self, ds: Dataset, profile: str = "list", bill_usd: Optional[float] = None,
                 scoring: Optional[dict] = None, levels: Optional[dict] = None, now: Optional[float] = None,
                 experimental: bool = False):
        self.ds = ds
        self.cfg = scoring or _load("scoring.json")
        self.levels = (levels or _load("levels.json"))["levels"]
        self.now = now or time.time()
        self.experimental = experimental
        self.estimated = ds.estimated or (bool(ds.calls) and all(c.estimated for c in ds.calls))
        self.user_bill = bill_usd
        self.ttl, self.ttl_how = self._ttl()
        self.pricer = Pricer(profile=profile, default_ttl=self.ttl)
        if self.estimated:
            self.pricer.models = dict(self.pricer.models)
            self.pricer.models["estimated"] = ESTIMATED_PRICES
            for c in ds.calls:
                if c.estimated and c.model is None:
                    c.model = "estimated"
        # order calls by stream and time
        self.calls = sorted(range(len(ds.calls)), key=lambda i: (ds.calls[i].ts_start, ds.calls[i].ts_end))
        self.cost: Dict[int, Optional[float]] = {i: self.pricer.cost(ds.calls[i]) for i in self.calls}
        self.priced = [i for i in self.calls if self.cost[i] is not None]
        self.total = sum(self.cost[i] for i in self.priced)
        self.gap = self._gaps()
        self.floor = self._floor()
        self.turns = self._turns()
        self._turn_of = {i: t for t, idx in self.turns.items() for i in idx}

    # ---------- shared inputs ----------

    def _ttl(self) -> Tuple[str, str]:
        if self.ds.calls and all(c.estimated for c in self.ds.calls):
            return "1h", "assumed for chat, an export has no cache data"
        w1 = sum(c.cache_write_1h or 0 for c in self.ds.calls)
        w5 = sum(c.cache_write_5m or 0 for c in self.ds.calls)
        if w1 or w5:
            return ("1h" if w1 >= w5 else "5m"), "measured from cache write records"
        # infer: does the cache survive pauses of 5 to 60 minutes?
        streams = defaultdict(list)
        for c in self.ds.calls:
            streams[(c.dev, c.session_id, c.is_subagent)].append(c)
        survived = expired = 0
        for cs in streams.values():
            cs.sort(key=lambda c: c.ts_start)
            for prev, cur in zip(cs, cs[1:]):
                g = cur.ts_start - prev.ts_end
                if 300 < g < 3600 and cur.ctx > 0 and cur.usage_recorded:
                    if (cur.cache_read or 0) >= 0.5 * cur.ctx:
                        survived += 1
                    else:
                        expired += 1
        if survived + expired >= 2:
            if survived >= 0.75 * (survived + expired):
                return "1h", "inferred: the cache survived %d of %d pauses of 5 to 60 min" % (survived, survived + expired)
            return "5m", "inferred: the cache expired in %d of %d pauses of 5 to 60 min" % (expired, survived + expired)
        return "1h", "assumed (subscription default, no pauses to measure it)"

    def _gaps(self) -> Dict[int, float]:
        """Seconds between a call's start and the previous call's end in the same stream."""
        streams = defaultdict(list)
        for i in self.calls:
            c = self.ds.calls[i]
            streams[(c.dev, c.session_id, c.is_subagent)].append(i)
        gap: Dict[int, float] = {}
        for idx in streams.values():
            prev_end = None
            for i in idx:
                c = self.ds.calls[i]
                gap[i] = -1.0 if prev_end is None else max(0.0, c.ts_start - prev_end)
                prev_end = max(prev_end or c.ts_end, c.ts_end)
        return gap

    def _floor(self) -> int:
        """Smallest context the user's own sessions start with (first call of each main stream)."""
        starts = [self.ds.calls[i].ctx for i in self.calls
                  if self.gap[i] < 0 and not self.ds.calls[i].is_subagent and self.ds.calls[i].ctx >= 2000
                  and self.ds.calls[i].usage_recorded]
        if not starts:
            starts = [self.ds.calls[i].ctx for i in self.calls if self.ds.calls[i].ctx >= 2000]
        return min(starts) if starts else 0

    def _turns(self) -> Dict[str, List[int]]:
        t: Dict[str, List[int]] = defaultdict(list)
        for i in self.calls:
            c = self.ds.calls[i]
            t[c.dev + ":" + c.turn_id].append(i)
        return dict(t)

    def _c(self, i: int) -> float:
        return self.cost.get(i) or 0.0

    # ---------- detectors ----------

    def dq(self) -> List[dict]:
        out = []
        unrec = [c for c in self.ds.calls if not c.usage_recorded]
        if unrec:
            out.append({"level": "warn", "text": "%d of %d model calls had no usage recorded. They are counted, not priced." % (len(unrec), len(self.ds.calls))})
        # every usage-recorded call without a price, not only unknown models: fast calls on a model with no fast row
        # also price to None and would otherwise vanish from the totals silently
        unknown = Counter((c.model or "unknown") + (" (fast)" if c.speed == "fast" and self.pricer.known(c.model) else "")
                          for c in self.ds.calls if c.usage_recorded and self.pricer.cost(c) is None)
        if unknown:
            names = ", ".join("%s (%d calls)" % (m, n) for m, n in unknown.most_common(5))
            out.append({"level": "warn", "text": "No price for %s. Those calls are shown but excluded from dollar figures." % names})
        if self.ds.fixed_durations:
            out.append({"level": "info", "text": "%d calls had end before start. Start and end were swapped." % self.ds.fixed_durations})
        for n in self.ds.notes:
            out.append({"level": "info", "text": n[0].upper() + n[1:] + "."})
        if self.estimated:
            out.append({"level": "info", "text": "Estimated from message length (about 4 characters per token). Figures are a share of usage, not dollars."})
        age = self.pricer.age_days()
        if age is not None and age > self.cfg.get("pricing_stale_days", 60):
            out.append({"level": "warn", "text": "Prices were last checked %d days ago. Update the tool for current prices." % age})
        if self.user_bill is None and self.ds.bill_usd is None and not self.estimated:
            out.append({"level": "info", "text": "No bill to compare with, so coverage is unknown. Pass --bill to add yours."})
        return out

    def d1(self) -> dict:
        ctxs = [self.ds.calls[i].ctx for i in self.priced if self.ds.calls[i].ctx > 0]
        if not ctxs:
            return {"available": False}
        med = statistics.median(ctxs)
        cr = sum(self.ds.calls[i].cache_read or 0 for i in self.priced)
        out_t = sum(self.ds.calls[i].output or 0 for i in self.priced)
        cr_cost = sum((self.pricer.breakdown(self.ds.calls[i]) or {}).get("cache_read", 0) for i in self.priced)
        cap = self.floor + self.cfg["brief_tokens"]
        upper = sum(self._c(i) - (self.pricer.cost(self.ds.calls[i], ctx_override=cap) or 0) for i in self.priced)
        good = self.floor + self.cfg["d1"]["score_100_at_over_floor"]
        bad = max(good + 1, self.cfg["d1"]["score_0_at_median_ctx"])
        c1 = self.cfg["d1"]
        floor_score = _lin(self.floor, c1["floor_score_100_at"], c1["floor_score_0_at"])
        w = c1["floor_weight"]
        score = (1 - w) * _lin(med, good, bad) + w * floor_score
        # in estimated mode there is no cache: re-read input is the "carried context" cost
        if self.estimated:
            cr_cost = sum((self.pricer.breakdown(self.ds.calls[i]) or {}).get("input", 0) for i in self.priced)
        return {
            "available": True, "score": score, "median_ctx": int(med), "min_ctx": min(ctxs), "max_ctx": max(ctxs),
            "reads_per_output": (cr / out_t) if out_t else None, "carried_usd": cr_cost,
            "carried_share": cr_cost / self.total if self.total else 0.0,
            "involved_usd": cr_cost, "upper_saving_usd": max(0.0, upper), "cap_tokens": cap,
            "floor_tokens": self.floor, "floor_score": floor_score,
        }

    def _small_turns(self) -> List[str]:
        c2 = self.cfg["d2"]
        out = []
        for t, idx in self.turns.items():
            o = sum(self.ds.calls[i].output or 0 for i in idx)
            cost = sum(self._c(i) for i in idx)
            if o >= c2["max_output_tokens"] or not any(self.cost[i] is not None for i in idx):
                continue
            if self.estimated:
                if max(self.ds.calls[i].ctx for i in idx) >= c2["min_turn_ctx_estimated"]:
                    out.append(t)
            elif cost > c2["min_turn_cost_usd"]:
                out.append(t)
        return out

    def d2(self) -> dict:
        turns = self._small_turns()
        cap = self.floor + self.cfg["brief_tokens"]
        involved = sum(self._c(i) for t in turns for i in self.turns[t])
        saving = sum(self._c(i) - (self.pricer.cost(self.ds.calls[i], ctx_override=cap) or 0)
                     for t in turns for i in self.turns[t])
        worst = None
        for t in turns:
            cost = sum(self._c(i) for i in self.turns[t])
            if worst is None or cost > worst[0]:
                worst = (cost, sum(self.ds.calls[i].output or 0 for i in self.turns[t]))
        share = involved / self.total if self.total else 0.0
        return {
            "available": bool(self.priced), "score": _lin(share, 0.0, self.cfg["d2"]["score_0_at_share"]),
            "turns": len(turns), "involved_usd": involved, "share": share, "saving_usd": max(0.0, saving),
            "avg_usd": involved / len(turns) if turns else 0.0,
            "worst_usd": worst[0] if worst else 0.0, "worst_output": worst[1] if worst else 0,
            "turn_ids": turns,
        }

    def d3(self) -> dict:
        tools_by_turn: Dict[str, Counter] = defaultdict(Counter)
        for t in self.ds.tools:
            tools_by_turn[t.dev + ":" + t.turn_id][t.tool] += 1
        cc = sum(1 for c in self.ds.calls if _is_cc(c)) > len(self.ds.calls) / 2
        thr = self.cfg["d3"]["min_calls_claude_code" if cc else "min_calls_chat"]
        loops = [t for t, idx in self.turns.items() if len(idx) >= thr]
        involved = sum(self._c(i) for t in loops for i in self.turns[t])
        worst = max(loops, key=lambda t: sum(self._c(i) for i in self.turns[t]), default=None)
        share = involved / self.total if self.total else 0.0
        w = None
        if worst:
            w = {"calls": len(self.turns[worst]), "usd": sum(self._c(i) for i in self.turns[worst]),
                 "tools": sum(tools_by_turn[worst].values()), "top_tools": tools_by_turn[worst].most_common(3)}
        c3 = self.cfg["d3"]
        return {"available": bool(self.priced) and not self.estimated,
                "score": _lin(share, c3["score_100_at_share"], c3["score_0_at_share"]),
                "threshold": thr, "turns": len(loops), "involved_usd": involved, "share": share, "worst": w,
                "saving_usd": 0.0}

    def _idle_calls(self) -> List[int]:
        c4 = self.cfg["d4"]
        idle_s = 60 * (c4["idle_minutes_1h"] if self.ttl == "1h" else c4["idle_minutes_5m"])
        out = []
        for i in self.priced:
            c = self.ds.calls[i]
            thr = c4["min_write_claude_code"] if _is_cc(c) else c4["min_write_chat"]
            if self.estimated:
                if self.gap[i] > idle_s and c.ctx > thr:
                    out.append(i)
            elif self.gap[i] > idle_s and c.cache_write > thr:
                out.append(i)
        return out

    def d4(self) -> dict:
        idle = self._idle_calls()
        cap = self.floor + self.cfg["brief_tokens"]
        involved = saving = 0.0
        toks = 0
        for i in idle:
            c = self.ds.calls[i]
            if self.estimated:
                wp = ESTIMATED_PRICES["input"] / 1e6
                involved += c.ctx * wp
                saving += max(0, c.ctx - cap) * wp
                toks += c.ctx
                continue
            # the rebuild is every cache write in the turn that resumes after the break (re-warming included)
            turn = self._turn_of[i]
            after = [j for j in self.turns[turn] if j >= 0 and self.ds.calls[j].ts_start >= c.ts_start]
            for j in after:
                cj = self.ds.calls[j]
                involved += cj.cache_write * (self.pricer.write_price(cj) or 0.0)
                toks += cj.cache_write
            saving += max(0, c.cache_write - cap) * (self.pricer.write_price(c) or 0.0)
        share = involved / self.total if self.total else 0.0
        longest = max((self.gap[i] for i in idle), default=0.0)
        fresh = cap * (self.pricer.write_price(self.ds.calls[idle[0]]) or 0) if idle and not self.estimated else 0.0
        return {"available": bool(self.priced), "score": _lin(share, 0.0, self.cfg["d4"]["score_0_at_share"]),
                "rebuilds": len(idle), "tokens": toks, "involved_usd": involved, "share": share,
                "saving_usd": saving, "longest_pause_h": longest / 3600.0,
                "avg_rebuild_usd": involved / len(idle) if idle else 0.0, "fresh_start_usd": fresh,
                "likely": self.estimated, "call_ids": idle}

    def d5(self) -> dict:
        tools = sorted(self.ds.tools, key=lambda t: (t.dev, t.session_id, t.ts))
        if not tools:
            return {"available": False}
        errs = [t for t in tools if not t.ok]
        by_tool = Counter(t.tool for t in errs)
        retries = 0
        for a, b in zip(tools, tools[1:]):
            if not a.ok and not b.ok and a.tool == b.tool and a.session_id == b.session_id and a.dev == b.dev:
                retries += 1
        # the model call that reads each error: next call in the same session after the failure
        by_session = defaultdict(list)
        for i in self.priced:
            c = self.ds.calls[i]
            by_session[(c.dev, c.session_id)].append(i)
        starts = {k: [self.ds.calls[i].ts_start for i in v] for k, v in by_session.items()}
        readers = set()
        for t in errs:
            key = (t.dev, t.session_id)
            idx = by_session.get(key)
            if not idx:
                continue
            j = bisect.bisect_left(starts[key], t.ts - 1e-6)
            if j < len(idx):
                readers.add(idx[j])
        involved = sum(self._c(i) for i in readers)
        rate = (len(errs) + retries) / len(tools)
        c5 = self.cfg["d5"]
        return {"available": True, "score": _lin(rate, c5["score_100_at_rate"], c5["score_0_at_rate"]),
                "tool_calls": len(tools), "errors": len(errs), "retries": retries, "rate": rate,
                "by_tool": by_tool.most_common(5), "involved_usd": involved,
                "share": involved / self.total if self.total else 0.0, "saving_usd": involved,
                "reader_ids": sorted(readers)}

    def d6(self) -> dict:
        if self.estimated or not self.priced:
            return {"available": False}
        models = {self.ds.calls[i].model for i in self.priced}
        top = self.pricer.most_expensive_model(models)
        cheaper = self.pricer.cheaper_model
        top_rates, cheaper_rates = self.pricer.rates(top) if top else None, self.pricer.rates(cheaper)
        if not top_rates or not cheaper_rates or top == cheaper or top_rates["output"] <= cheaper_rates["output"]:
            return {"available": True, "score": 100.0, "turns": 0, "saving_usd": 0.0, "involved_usd": 0.0,
                    "share": 0.0, "top": top, "cheaper": cheaper, "call_ids": []}
        ids = [i for t in self._small_turns() for i in self.turns[t] if self.ds.calls[i].model == top]
        saving = sum(self._c(i) - (self.pricer.cost(self.ds.calls[i], model=cheaper) or 0) for i in ids)
        share = saving / self.total if self.total else 0.0
        return {"available": True, "score": _lin(share, 0.0, self.cfg["d6"]["score_0_at_share"]),
                "turns": len({self.ds.calls[i].turn_id for i in ids}), "saving_usd": max(0.0, saving),
                "involved_usd": sum(self._c(i) for i in ids), "share": share, "top": top, "cheaper": cheaper,
                "call_ids": ids}

    def d7(self) -> Optional[dict]:
        if self.estimated:
            return None
        if self.user_bill is not None:
            return {"bill_usd": self.user_bill, "label": "your bill", "traced_usd": self.total,
                    "coverage": self.total / self.user_bill if self.user_bill else None, "tokens": None}
        if self.ds.bill_usd is None or not self.ds.bill_scope:
            return None
        scope = [i for i in self.ds.bill_scope if i < len(self.ds.calls)]
        traced = sum(self.cost.get(i) or 0.0 for i in scope)
        tok = None
        if self.ds.bill_tokens:
            t = Counter()
            for i in scope:
                c = self.ds.calls[i]
                t["input"] += c.input or 0
                t["output"] += c.output or 0
                t["cache_read"] += c.cache_read or 0
                t["cache_write"] += c.cache_write
            tok = {k: (t[k] / v if v else None) for k, v in self.ds.bill_tokens.items()}
        return {"bill_usd": self.ds.bill_usd, "label": self.ds.bill_label, "traced_usd": traced,
                "coverage": traced / self.ds.bill_usd if self.ds.bill_usd else None, "tokens": tok}

    def d8(self) -> dict:
        thr = self.cfg["d8"]["min_write"]
        idle = set(self._idle_calls())
        rows = []
        prev_by_stream: Dict[tuple, int] = {}
        for i in self.calls:
            c = self.ds.calls[i]
            key = (c.dev, c.session_id, c.is_subagent)
            p = prev_by_stream.get(key)
            prev_by_stream[key] = i
            if p is None or i in idle or c.cache_write <= thr or self.estimated:
                continue
            pc = self.ds.calls[p]
            if pc.model != c.model:
                cause = "model switch"
            elif c.ctx < 0.6 * pc.ctx:
                cause = "compaction or context reset"
            else:
                cause = "prompt prefix changed (CLAUDE.md, tools or settings)"
            rows.append({"ts": c.ts_start, "write_tokens": c.cache_write, "gap_min": self.gap[i] / 60.0,
                         "usd": c.cache_write * (self.pricer.write_price(c) or 0), "cause": cause})
        return {"count": len(rows), "rows": rows[:20], "usd": sum(r["usd"] for r in rows)}

    def d9(self) -> dict:
        out = sum((self.pricer.breakdown(self.ds.calls[i]) or {}).get("output", 0) for i in self.priced)
        return {"output_usd": out, "share": out / self.total if self.total else 0.0}

    # ---------- fix simulator ----------

    def simulate(self, det: dict) -> Tuple[List[dict], float]:
        """Apply fixes one after another on a copy of the call log. Each fix's saving is marginal to the ones
        before it, so the combined figure never double counts."""
        cap_fresh = self.floor + self.cfg["brief_tokens"]
        cap_task = self.floor + self.cfg["d1_fix_budget_tokens"]
        ctx_cap: Dict[int, int] = {}
        model: Dict[int, str] = {}
        removed = set()

        def total() -> float:
            s = 0.0
            for i in self.priced:
                if i in removed:
                    continue
                v = self.pricer.cost(self.ds.calls[i], model=model.get(i), ctx_override=ctx_cap.get(i))
                s += v or 0.0
            return s

        fixes = []
        base = total()
        steps = []
        if det["D4"].get("available") and det["D4"]["rebuilds"]:
            steps.append(("D4", lambda: [ctx_cap.__setitem__(i, min(ctx_cap.get(i, 1 << 62), cap_fresh)) for i in det["D4"]["call_ids"]]))
        if det["D2"].get("available") and det["D2"]["turns"]:
            steps.append(("D2", lambda: [ctx_cap.__setitem__(i, min(ctx_cap.get(i, 1 << 62), cap_fresh))
                                         for t in det["D2"]["turn_ids"] for i in self.turns[t]]))
        if det["D1"].get("available"):
            steps.append(("D1", lambda: [ctx_cap.__setitem__(i, min(ctx_cap.get(i, 1 << 62), cap_task)) for i in self.priced]))
        if det["D6"].get("available") and det["D6"].get("call_ids"):
            steps.append(("D6", lambda: [model.__setitem__(i, det["D6"]["cheaper"]) for i in det["D6"]["call_ids"]]))
        if det["D5"].get("available") and det["D5"].get("reader_ids"):
            steps.append(("D5", lambda: [removed.add(i) for i in det["D5"]["reader_ids"]]))
        cur = base
        for key, apply in steps:
            apply()
            nxt = total()
            fixes.append({"key": key, "saving_usd": max(0.0, cur - nxt)})
            cur = nxt
        return fixes, max(0.0, base - cur)

    # ---------- scores and summary ----------

    def level_for(self, score: float) -> dict:
        lv = self.levels[0]
        for i, l in enumerate(self.levels):
            if score >= l["min"]:
                lv = dict(l, index=i + 1)
        return lv

    def run(self) -> dict:
        det = {"D1": self.d1(), "D2": self.d2(), "D3": self.d3(), "D4": self.d4(), "D5": self.d5(), "D6": self.d6()}
        habits = Habits(self, Fmt(self.money_mode(), self.total))
        habit_items = habits.run() if self.priced else []
        det.update(habits.axes() if self.priced else {"D10": {"available": False}, "D11": {"available": False}})
        radar = []
        for key, label in AXES:
            d = det[key]
            radar.append({"key": key, "label": label, "available": bool(d.get("available")),
                          "score": round(d["score"]) if d.get("available") else None,
                          "usd": d.get("involved_usd") if key != "D6" else d.get("saving_usd"),
                          "share": d.get("share") if key != "D1" else d.get("carried_share")})
        avail = [r["score"] for r in radar if r["available"]] if self.priced else []
        mean = sum(avail) / len(avail) if avail else None
        fixes, combined = self.simulate(det)
        # The vibe score is the plain average of the available checks. Avoidable usage already lowers the
        # check scores themselves, so nothing is capped or adjusted on top: the number matches the radar.
        vibe = int(round(mean)) if mean is not None else None
        days = self.days()
        per_month = (lambda x: x / days * 30.0) if days >= self.cfg["monthly_min_days"] else None
        for f in fixes:
            f["monthly_usd"] = per_month(f["saving_usd"]) if per_month else None
        top = sorted([f for f in fixes if f["saving_usd"] > 0], key=lambda f: -f["saving_usd"])[:3]
        res = {
            "tool": "41 vibe check", "version": __version__, "generated_at": self.now,
            "mode": "estimated" if self.estimated else "measured",
            "money": self.money_mode(),
            "sources": self.ds.sources,
            "period": self.period(),
            "counts": {"calls": len(self.ds.calls), "priced": len(self.priced),
                       "sessions": len({(c.dev, c.session_id) for c in self.ds.calls}),
                       "turns": len(self.turns), "tool_calls": len(self.ds.tools),
                       "devs": sorted({c.dev for c in self.ds.calls})},
            "pricing": {"profile": self.pricer.profile, "label": self.pricer.label,
                        "checked_on": self.pricer.checked_on, "age_days": self.pricer.age_days()},
            "ttl": {"value": self.ttl, "how": self.ttl_how},
            "floor_tokens": self.floor, "brief_tokens": self.cfg["brief_tokens"],
            "total_usd": self.total, "tokens_total": self.tokens_total(), "breakdown": self.breakdown(),
            "models": self.model_mix(),
            "dq": self.dq(), "coverage": self.d7(),
            "detectors": {k: {kk: vv for kk, vv in v.items() if not kk.endswith("_ids")} for k, v in det.items()},
            "d8": self.d8() if self.experimental else None, "d9": self.d9(),
            "radar": radar, "fixes": top, "all_fixes": fixes,
            "combined_saving_usd": combined,
            "combined_monthly_usd": per_month(combined) if per_month else None,
            "combined_share": combined / self.total if self.total else 0.0,
            "limits": self.limits(combined, top),
            "vibe": None,
            "sessions": self.session_rows(det),
        }
        res["habits"] = habit_items
        res["scoring_version"] = SCORING_VERSION
        res["habit_groups"] = habit_groups()
        if vibe is not None:
            lv = self.level_for(vibe)
            res["vibe"] = {"score": vibe, "level": lv["index"], "name": lv["name"], "color": lv["color"],
                           "text": lv["text"], "provisional": self.provisional(days),
                           "levels": [{"min": l["min"], "name": l["name"], "color": l["color"]} for l in self.levels]}
        return res

    def limits(self, combined: float, fixes: List[dict]) -> dict:
        """Plan view. Anthropic doesn't publish plan limits; usage at API list prices is the proxy, so the share of
        avoidable usage is the share of the limit you'd get back, and 1 / (1 - share) is the work multiple."""
        share = combined / self.total if self.total else 0.0
        share = min(share, 0.9)
        for fx in fixes:
            fx["limit_share"] = fx["saving_usd"] / self.total if self.total else 0.0
        return {"plan": self.money_mode() in ("api_equivalent", "usage_share"), "share_saved": share,
                "multiple": 1.0 / (1.0 - share) if share < 1 else None}

    def tokens_total(self) -> Optional[int]:
        """All tokens (input, output, cache reads, every cache write) over calls that have a price, the same
        calls total_usd covers, so the "more tokens" figure matches the dollars.
        None when no call is priced, so the report says "not recorded" instead of showing 0."""
        used = [self.ds.calls[i] for i in self.priced]
        if not used:
            return None
        return sum((c.input or 0) + (c.output or 0) + (c.cache_read or 0) + c.cache_write for c in used)

    def days(self) -> float:
        if not self.ds.calls:
            return 0.0
        return max(0.0, (max(c.ts_end for c in self.ds.calls) - min(c.ts_start for c in self.ds.calls)) / 86400.0)

    def period(self) -> dict:
        if not self.ds.calls:
            return {"start": None, "end": None, "days": 0}
        return {"start": min(c.ts_start for c in self.ds.calls), "end": max(c.ts_end for c in self.ds.calls),
                "days": self.days()}

    def provisional(self, days: float) -> bool:
        p = self.cfg["provisional"]
        return len(self.priced) < p["min_calls"] or days < p["min_days"]

    def money_mode(self) -> str:
        if self.estimated:
            return "usage_share"
        w1 = sum(c.cache_write_1h or 0 for c in self.ds.calls)
        if self.user_bill is not None:
            return "usd"
        if self.ttl == "1h" and (w1 or "inferred" in self.ttl_how or "assumed" in self.ttl_how):
            return "api_equivalent"
        return "usd"

    def breakdown(self) -> dict:
        b = Counter()
        for i in self.priced:
            for k, v in (self.pricer.breakdown(self.ds.calls[i]) or {}).items():
                b[k] += v
        return {k: b.get(k, 0.0) for k in ("output", "cache_write", "cache_read", "input")}

    def model_mix(self) -> List[dict]:
        m = defaultdict(lambda: [0, 0.0])
        for i in self.calls:
            c = self.ds.calls[i]
            m[c.model][0] += 1
            m[c.model][1] += self._c(i)
        return [{"model": k, "name": pretty(k) if k != "estimated" else "estimated", "calls": v[0], "usd": v[1]}
                for k, v in sorted(m.items(), key=lambda kv: -kv[1][1])]

    def session_rows(self, det: dict) -> List[dict]:
        idle = set(det["D4"].get("call_ids") or [])
        small = {i for t in det["D2"].get("turn_ids") or [] for i in self.turns[t]}
        sess = defaultdict(list)
        for i in self.calls:
            c = self.ds.calls[i]
            sess[(c.dev, c.session_id)].append(i)
        rows = []
        for (dev, sid), idx in sess.items():
            cost = sum(self._c(i) for i in idx)
            leaks = {"Idle cache rebuilds": sum(self._c(i) for i in idx if i in idle),
                     "Small edits on full context": sum(self._c(i) for i in idx if i in small)}
            worst = max(leaks.items(), key=lambda kv: kv[1])
            rows.append({"dev": dev, "start": self.ds.calls[idx[0]].ts_start, "calls": len(idx), "usd": cost,
                         "median_ctx": int(statistics.median([self.ds.calls[i].ctx for i in idx])),
                         "worst": worst[0] if worst[1] > 0 else None, "worst_usd": worst[1]})
        rows.sort(key=lambda r: -r["usd"])
        return rows[:50]


def analyze(ds: Dataset, **kw) -> dict:
    res = Analysis(ds, **kw).run()
    # A dataset whose records carry more than one `dev` also gets one summary row per developer in res["team"].
    devs = res["counts"]["devs"]
    if len(devs) > 1:
        team = []
        for d in devs:
            sub = Dataset(calls=[c for c in ds.calls if c.dev == d], tools=[t for t in ds.tools if t.dev == d],
                          prompts=[p for p in ds.prompts if p.dev == d],
                          interrupts=[x for x in ds.interrupts if x[0] == d],
                          compactions=[x for x in ds.compactions if x[0] == d], estimated=ds.estimated)
            r = Analysis(sub, profile=kw.get("profile", "list"), now=kw.get("now")).run()
            worst = min((x for x in r["radar"] if x["available"]), key=lambda x: x["score"], default=None)
            team.append({"dev": d, "usd": r["total_usd"], "calls": r["counts"]["calls"],
                         "score": r["vibe"]["score"] if r["vibe"] else None,
                         "level": r["vibe"]["name"] if r["vibe"] else None,
                         "worst": worst["label"] if worst else None,
                         "saving_usd": r["combined_saving_usd"]})
        team.sort(key=lambda x: -x["usd"])
        res["team"] = team
    return res
