"""Command line: `vibecheck` writes the report.

Everything runs locally. There is no network code in this package.
"""

import argparse
import json
import os
import sys
import time
import webbrowser
from datetime import datetime
from typing import List, Optional

from . import __version__
from .analysis import analyze
from .records import Dataset
from .report.render import render
from .sources import claude_code_jsonl as ccj
from .sources.detect import load_paths
from .texts import FIX_TITLES, Fmt, headline, is_plan, period

EPILOG = """examples:
  vibecheck                          report on all local Claude Code sessions
  vibecheck --days 7 --project .     last 7 days, this project only
  vibecheck traces.otlp.json         report on an OpenTelemetry export
  vibecheck claude-export.zip        estimated report from a claude.ai data export
"""


def _out(msg: str = "") -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))
    except BrokenPipeError:  # output piped into head or similar
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass


def _err(msg: str) -> None:
    try:
        sys.stderr.write(msg + "\n")
    except UnicodeEncodeError:
        sys.stderr.write(msg.encode("ascii", "replace").decode("ascii") + "\n")


def _default_out_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "vibecheck")


def _load(args) -> Dataset:
    since = time.time() - args.days * 86400 if args.days else None
    if args.paths:
        ds = load_paths(args.paths)
    else:
        home = ccj.claude_home()
        files = ccj.find_session_files(home, project_dir=args.project, since=since)
        if not files:
            where = os.path.join(home, "projects")
            if not os.path.isdir(where):
                raise SystemExit("No Claude Code sessions found: %s does not exist.\n"
                                 "Point the vibe check at a file or folder: vibecheck <path>" % where)
            raise SystemExit("No Claude Code sessions found in %s%s.\nClaude Code deletes sessions after 30 days by "
                             "default (cleanupPeriodDays). Use Claude Code for a bit and run this again." % (
                                 where, " for this project" if args.project else ""))
        ds = ccj.load(files)
    if ds.session_dirs:
        from .sources import setup
        ds.setup = setup.scan(ds.session_dirs, ccj.claude_home())
    if since is not None:
        keep = [i for i, c in enumerate(ds.calls) if c.ts_end >= since]
        remap = {old: new for new, old in enumerate(keep)}
        ds.calls = [ds.calls[i] for i in keep]
        ds.tools = [t for t in ds.tools if t.ts >= since]
        ds.prompts = [p for p in ds.prompts if p.ts >= since]
        ds.interrupts = [x for x in ds.interrupts if x[3] >= since]
        ds.compactions = [x for x in ds.compactions if x[2] >= since]
        for t in ds.tools:
            t.after_call = remap.get(t.after_call) if t.after_call is not None else None
        ds.bill_scope = [remap[i] for i in ds.bill_scope if i in remap]
        if not ds.bill_scope:
            ds.bill_usd = None
    return ds


def _summary(res: dict, path: Optional[str]) -> None:
    f = Fmt(res["money"], res["total_usd"])
    v = res["vibe"]
    _out("")
    _out("41 vibe check · %s" % period(res))
    if not v:
        _out("Not enough data yet: no model calls with usage were found.")
    else:
        _out("Level %d of 5: %s · %d/100 (100 is best)%s" % (v["level"], v["name"], v["score"], " (provisional)" if v["provisional"] else ""))
        if res.get("previous"):
            from .texts import since_line
            _out(since_line(res))
        _out("")
        _out(headline(res, f))
        if res["fixes"]:
            _out("")
            _out("Where you could improve:")
            plan = is_plan(res)
            for k, fx in enumerate(res["fixes"]):
                if plan:
                    s = "frees about %s of your limit" % Fmt.share(fx.get("limit_share", 0))
                    if fx.get("monthly_usd") is not None and f.mode == "api_equivalent":
                        s += " (%s a month at API prices)" % f.money(fx["monthly_usd"], approx=True)
                elif fx.get("monthly_usd") is not None and f.mode != "usage_share":
                    s = "%s per month" % f.money(fx["monthly_usd"], approx=True)
                else:
                    s = f.money(fx["saving_usd"], approx=True)
                _out("  %d. %s: %s" % (k + 1, FIX_TITLES[fx["key"]], s))
    if path:
        _out("")
        _out("Report: %s" % path)
    _out("Nothing left this machine.")


def cmd_report(args) -> int:
    args.out = os.path.expanduser(args.out) if args.out else None
    args.json = os.path.expanduser(args.json) if args.json else None
    ds = _load(args)
    res = analyze(ds, profile=args.profile, bill_usd=args.bill, experimental=args.experimental)
    if not args.paths and not args.no_history and res.get("vibe"):
        res["previous"] = _history(res)
    out = args.out
    if not out:
        d = _default_out_dir()
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, "vibecheck-%s.html" % datetime.now().strftime("%Y-%m-%d-%H%M"))
    else:
        parent = os.path.dirname(os.path.abspath(out))
        os.makedirs(parent, exist_ok=True)
    html = render(res, title="41 vibe check: %s" % (res["vibe"]["name"] if res["vibe"] else "no data"))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            # habits are left out of the JSON: the free output names none
            json.dump({k: v for k, v in res.items() if k not in ("habits", "habit_groups")}, fh, indent=1, default=str)
    if not args.quiet:
        _summary(res, os.path.abspath(out))
    if args.open:
        _open(out)
    return 0


def _history(res: dict) -> Optional[dict]:
    """Remember a one-line summary of each local run; return the previous one (older than an hour)."""
    path = os.path.join(_default_out_dir(), "history.jsonl")
    prev = None
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                # only compare like with like: older entries were scored on fewer axes
                if isinstance(e, dict) and isinstance(e.get("score"), int) and e.get("at", 0) < res["generated_at"] - 3600 \
                        and e.get("scoring") == res.get("scoring_version"):
                    prev = e
    except OSError:
        pass
    v = res["vibe"]
    entry = {"at": int(res["generated_at"]), "scoring": res.get("scoring_version"), "score": v["score"], "level": v["name"], "total_usd": round(res["total_usd"], 4),
             "avoidable_share": round(res["combined_share"], 4), "days": round(res["period"]["days"], 2)}
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass
    return prev


def _open(path: str) -> None:
    try:
        from pathlib import Path
        webbrowser.open(Path(os.path.abspath(path)).as_uri())
    except Exception:  # noqa: BLE001 - opening a browser is best effort
        pass


def _common(p: argparse.ArgumentParser) -> None:
    """Adds the arguments the report command takes."""
    p.add_argument("paths", nargs="*", help="files or folders (default: your local Claude Code sessions)")
    p.add_argument("--days", type=float, default=None, help="only the last N days")
    p.add_argument("--project", default=None, help="only sessions of this project folder (e.g. .)")
    p.add_argument("--profile", default="list", help="price profile from pricing.json (default: list)")
    p.add_argument("--experimental", action="store_true", help="include experimental detectors (D8)")
    p.add_argument("--out", default=None, help="output file")
    p.add_argument("--quiet", action="store_true", help="no terminal summary")


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-V", "--version", "version"):
        _out("41 vibe check %s" % __version__)
        return 0
    # "report" stays accepted as an explicit name for the only command
    if argv and argv[0] == "report":
        argv = argv[1:]
    p = argparse.ArgumentParser(prog="vibecheck", description="41 vibe check: where the money in your Claude sessions goes.",
                                epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    _common(p)
    p.add_argument("--bill", type=float, default=None, help="your real bill in USD for the same period (for coverage)")
    p.add_argument("--json", default=None, help="also write the numbers as JSON")
    p.add_argument("--open", action="store_true", help="open the report in your browser")
    p.add_argument("--no-history", action="store_true", help="don't record this run in ~/vibecheck/history.jsonl")
    args = p.parse_args(argv)
    try:
        return cmd_report(args)
    except (FileNotFoundError, ValueError) as e:
        _err("vibecheck: %s" % e)
        return 2
