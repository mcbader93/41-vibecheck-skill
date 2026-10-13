"""Every sentence in the report, built from numbers the analysis produced. No model writes any of this.

House style: sentence case, no em dashes, "41" never starts a sentence.
"""

from datetime import datetime, timezone
from typing import Optional

from .models import pretty

FIX_TITLES = {
    "D4": "Start fresh after a break",
    "D2": "One session per task for small changes",
    "D1": "Keep context lean",
    "D6": "Route simple turns to a cheaper model",
    "D5": "Stop tool retries at the first failure",
}

AXIS_SHORT = {
    "D4": "idle cache rebuilds",
    "D1": "context bloat",
    "D2": "small edits on full context",
    "D3": "long agent loops",
    "D5": "tool errors",
    "D6": "model routing",
    "D10": "prompting habits",
    "D11": "setup weight",
}


class Fmt:
    """Money and share formatting for the three money modes."""

    def __init__(self, mode: str, total: float):
        self.mode = mode          # usd | api_equivalent | usage_share
        self.total = total or 0.0

    def money(self, usd: Optional[float], approx: bool = False) -> str:
        if usd is None:
            return "not recorded"
        if self.mode == "usage_share":
            return self.share(usd / self.total if self.total else 0.0) + " of usage"
        p = "about " if approx else ""
        if approx and abs(usd) >= 10:
            return "%s$%s" % (p, "{:,.0f}".format(usd))
        if abs(usd) >= 1000:
            return "%s$%s" % (p, "{:,.0f}".format(usd))
        if abs(usd) >= 100:
            return "%s$%.0f" % (p, usd)
        if abs(usd) >= 0.995 or usd == 0:
            return "%s$%.2f" % (p, usd)
        return "%s$%.2f" % (p, usd) if usd >= 0.005 else "%sunder $0.01" % p

    def money_short(self, usd: Optional[float]) -> str:
        if usd is None:
            return "n/a"
        if self.mode == "usage_share":
            return self.share(usd / self.total if self.total else 0.0)
        if usd >= 100:
            return "$%s" % "{:,.0f}".format(usd)
        return "$%.2f" % usd

    @staticmethod
    def share(x: Optional[float]) -> str:
        if x is None:
            return "n/a"
        v = 100.0 * x
        if v == 0:
            return "0%"
        if v < 1:
            return "%.1f%%" % v
        return "%.0f%%" % v


def multiple(x: Optional[float]) -> str:
    """1.9× style work multiple."""
    if not x:
        return "n/a"
    return ("%.0f×" % x) if x >= 10 else ("%.1f×" % x)


def is_plan(res: dict) -> bool:
    return bool((res.get("limits") or {}).get("plan"))


def plan_potential(res: dict, f: "Fmt") -> str:
    """Potential for people on a Claude plan: share of the limit back, and the work multiple."""
    lim = res["limits"]
    share = Fmt.share(lim["share_saved"])
    txt = "about %s of your usage limit back" % share
    if lim["share_saved"] >= 0.05:
        txt += ", so about %s the work on the same plan" % multiple(lim["multiple"])
    if res.get("combined_monthly_usd") is not None and f.mode == "api_equivalent":
        txt += " (%s a month at API prices)" % f.money(res["combined_monthly_usd"], approx=True)
    return txt


def tokens(n: Optional[float]) -> str:
    if n is None:
        return "n/a"
    n = float(n)
    if n >= 1e6:
        # whole millions from 10M up: these are estimates, and "184.58M" reads more exact than it is
        return ("%.0fM" % (n / 1e6)) if n >= 1e7 else ("%.1fM" % (n / 1e6)).replace(".0M", "M")
    if n >= 1e3:
        return "%.0fk" % (n / 1e3)
    return "%d" % n


def date_short(ts: Optional[float]) -> str:
    if not ts:
        return "n/a"
    d = datetime.fromtimestamp(ts, tz=timezone.utc)
    return "%s %d" % (d.strftime("%b"), d.day)


def period(res: dict) -> str:
    p = res["period"]
    if not p["start"]:
        return "no data"
    a, b = date_short(p["start"]), date_short(p["end"])
    days = p["days"]
    span = "under a day" if days < 1 else ("%.0f days" % days if days >= 2 else "1 day")
    return "%s to %s (%s)" % (a, b, span) if a != b else "%s (%s)" % (a, span)


def headline(res: dict, f: Fmt) -> str:
    """The findings line under the level text."""
    radar = [r for r in res["radar"] if r["available"]]
    if not radar:
        return "Not enough data to judge yet."
    det = res["detectors"]
    worst = min(radar, key=lambda r: (r["score"], -(r["usd"] or 0)))
    if res["fixes"]:
        # the biggest leak is where the biggest fix is, so the line reads consistently
        top_key = res["fixes"][0]["key"]
        worst = next((r for r in radar if r["key"] == top_key), worst)
    best = max(radar, key=lambda r: (r["score"], -(r["usd"] or 0)))
    parts = []
    if worst["score"] >= 90 and not res["fixes"]:
        parts.append("No real leaks found.")
    else:
        lead = "Biggest leak" if worst["score"] < 80 else "Only small leaks. The biggest"
        parts.append("%s: %s." % (lead, leak_phrase(worst["key"], det, f, res)))
    fixes = res["fixes"]
    if fixes:
        parts.append("Start with: %s." % FIX_TITLES[fixes[0]["key"]].lower())
        if is_plan(res):
            parts.append("Potential: %s." % plan_potential(res, f))
        elif res.get("combined_monthly_usd") is not None and f.mode != "usage_share":
            parts.append("Potential: %s per month." % f.money(res["combined_monthly_usd"], approx=True))
        else:
            parts.append("Potential: %s of your %s." % (Fmt.share(res["combined_share"]),
                                                         ("usage" if f.mode in ("usage_share", "api_equivalent") else "spend")))
    if best["key"] != worst["key"]:
        parts.append("Strongest: %s." % strength_phrase(best["key"], det, f, res))
    return " ".join(parts)


def leak_phrase(key: str, det: dict, f: Fmt, res: dict) -> str:
    d = det[key]
    if key == "D1":
        return "context bloat, %s of %s went to carrying context (%s)" % (
            Fmt.share(d["carried_share"]), ("usage" if f.mode in ("usage_share", "api_equivalent") else "spend"), f.money(d["carried_usd"], True))
    if key == "D4":
        likely = "likely " if d.get("likely") else ""
        if f.mode == "usage_share":
            return "%sidle cache rebuilds, %d %srebuild%s took %s" % (
                likely, d["rebuilds"], likely, "" if d["rebuilds"] == 1 else "s", f.money(d["involved_usd"]))
        return "idle cache rebuilds, %d rebuild%s cost %s (%s)" % (
            d["rebuilds"], "" if d["rebuilds"] == 1 else "s", f.money(d["involved_usd"]), Fmt.share(d["share"]))
    if key == "D2":
        return "small edits on full context, %d short turn%s cost %s" % (
            d["turns"], "" if d["turns"] == 1 else "s", f.money(d["involved_usd"]))
    if key == "D3":
        return "long agent loops, %d turn%s with %d+ calls cost %s" % (
            d["turns"], "" if d["turns"] == 1 else "s", d["threshold"], f.money(d["involved_usd"]))
    if key == "D5":
        return "tool errors, %s of tool calls failed or retried" % Fmt.share(d["rate"])
    if key == "D6":
        return "model routing, small turns on %s would cost %s less" % (pretty(d["top"]), f.money(d["saving_usd"]))
    if key == "D10":
        m = d.get("metrics") or {}
        if m.get("rework_rate", 0) >= 0.1:
            return "prompting, %s of your follow-ups were corrections" % Fmt.share(m["rework_rate"])
        if m.get("repeated"):
            return "prompting, %d instruction%s typed again and again" % (m["repeated"], "" if m["repeated"] == 1 else "s")
        return "prompting habits"
    if key == "D11":
        m = d.get("metrics") or {}
        if m.get("memory_tokens", 0) >= 5000:
            return "setup weight, a %s-token CLAUDE.md re-read on every call" % tokens(m["memory_tokens"])
        if m.get("mcp_unused"):
            return "setup weight, %d unused MCP server%s" % (m["mcp_unused"], "" if m["mcp_unused"] == 1 else "s")
        if m.get("noisy_share"):
            return "setup weight, noisy tool output took %s" % f.money(m.get("noisy_usd"), True)
        return "setup weight"
    return AXIS_SHORT[key]


def strength_phrase(key: str, det: dict, f: Fmt, res: dict) -> str:
    d = det[key]
    if key == "D1":
        return "lean context, median %s tokens per call" % tokens(d["median_ctx"])
    if key == "D4" and res.get("mode") == "estimated":
        return "no likely idle rebuilds" if not d["rebuilds"] else "few likely idle rebuilds"
    if key == "D4":
        return "warm caches, %s" % ("no idle rebuilds" if not d["rebuilds"] else "only %d idle rebuild%s" % (d["rebuilds"], "" if d["rebuilds"] == 1 else "s"))
    if key == "D2":
        return "no pricey small edits" if not d["turns"] else "few pricey small edits"
    if key == "D3":
        return "agent loops stay short"
    if key == "D5":
        return "clean tool use, %s of tool calls failed" % Fmt.share(d["errors"] / d["tool_calls"] if d["tool_calls"] else 0)
    if key == "D6":
        return "model choice fits the work"
    if key == "D10":
        return "clear prompting, few corrections"
    if key == "D11":
        return "lean setup"
    return AXIS_SHORT[key]


# The how-to for each improvement is a Pro feature; the free report shows this one fixed line on every card.
PRO_FIX_LINE = "The exact fix for your setup is in vibe check Pro."


def potential_line(res: dict, f: Fmt) -> str:
    """The potential sentence for Pro's team report (the free report no longer shows it): what the improvements
    free, and the extra tokens of work that buys.
    Tokens are traced tokens x (work multiple - 1): several fixes make tokens cheaper rather than fewer, so
    "tokens avoided" would be wrong. Without recorded tokens it says so instead of showing 0."""
    lim = res.get("limits") or {}
    total = res.get("tokens_total")
    if is_plan(res) and lim.get("share_saved", 0) >= 0.05 and lim.get("multiple"):
        if total is None:
            room = "tokens not recorded"
        else:
            room = "room for about %s more tokens of work" % tokens(total * (lim["multiple"] - 1))
        if f.mode == "api_equivalent":
            return "That frees about %s of your %s (at API prices): %s." % (
                f.money(res["combined_saving_usd"], approx=True).replace("about ", ""),
                f.money(res["total_usd"], approx=True).replace("about ", ""), room)
        return "That frees about %s of your usage limit: %s." % (Fmt.share(lim["share_saved"]), room)
    traced = "tokens not recorded" if total is None else "%s tokens traced" % tokens(total)
    if res.get("combined_monthly_usd") is not None and f.mode != "usage_share":
        return "%s of your spend is avoidable at your current pace, %s." % (Fmt.share(res["combined_share"]), traced)
    if f.mode == "usage_share":
        return "%s of your usage was avoidable in this period, %s." % (Fmt.share(res["combined_share"]), traced)
    # the headline above already shows the share, so this line gives the dollars instead of repeating it
    return "%s of your %s (%s) was avoidable in this period, %s." % (
        f.money(res["combined_saving_usd"], approx=True), f.money(res["total_usd"], approx=True).replace("about ", ""),
        Fmt.share(res["combined_share"]), traced)


def coverage_line(res: dict, f: Fmt) -> str:
    cov = res.get("coverage")
    if res["mode"] == "estimated":
        # the data-quality note already says it is estimated from message length, so this line must not repeat it
        return "No bill to reconcile."
    if not cov:
        return "No bill to compare with, so coverage is unknown."
    c = cov.get("coverage")
    if c is None:
        return "Bill recorded as zero."
    txt = "Traces cover %s of %s (%s of %s)." % (Fmt.share(min(c, 9.99)), cov.get("label") or "the bill",
                                                f.money(cov["traced_usd"]), f.money(cov["bill_usd"]))
    if c > 1.05:
        txt += " Traced cost is higher than the record, which usually means the record is older than the transcript."
    return txt


def since_line(res: dict) -> str:
    prev, v = res.get("previous"), res.get("vibe")
    if not prev or not v:
        return ""
    d = v["score"] - prev["score"]
    when = date_short(prev["at"])
    if d == 0:
        change = "same score"
    else:
        change = "%+d point%s" % (d, "" if abs(d) == 1 else "s")
    lvl = "" if prev.get("level") == v["name"] else ", up from %s" % prev["level"] if d > 0 else ", down from %s" % prev["level"]
    return "Since your last check on %s: %s%s." % (when, change, lvl)
