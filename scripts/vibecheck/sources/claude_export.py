"""claude.ai data export (Settings > Privacy > Export data): a ZIP or a conversations.json.

The export has no token counts, so this source is ESTIMATED:
- tokens per message = characters / 4
- what the person typed goes through signals.analyse() for the habit checks (lengths, flags, per-run hashes);
  no text is stored
- each assistant reply re-reads the whole conversation so far (input = all earlier messages)
- no cache, model or tool data, so D3, D5, D6 and D7 are off and figures are a share of usage, not dollars

The export layout is not documented by Anthropic. This parser accepts the commonly seen shape
(a list of conversations with chat_messages[], each with sender, created_at and text or content[]) and
skips anything else rather than guessing.
"""

import json
import zipfile
from typing import Any, List, Optional

from ..records import CallRecord, Dataset, PromptRecord
from ..util import h, parse_ts
from . import signals

CHARS_PER_TOKEN = 4.0


def _len_of(msg: dict) -> int:
    n = 0
    t = msg.get("text")
    if isinstance(t, str):
        n = len(t)
    content = msg.get("content")
    if isinstance(content, list):
        m = 0
        for b in content:
            if isinstance(b, dict):
                for k in ("text", "thinking", "input", "content"):
                    v = b.get(k)
                    if isinstance(v, str):
                        m += len(v)
                    elif isinstance(v, (dict, list)):
                        m += len(json.dumps(v))
        n = max(n, m)
    for att in msg.get("attachments") or []:
        if isinstance(att, dict):
            v = att.get("extracted_content")
            if isinstance(v, str):
                n += len(v)
            elif isinstance(att.get("file_size"), int):
                n += att["file_size"]
    return n


def _load_json(path: str) -> Any:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.split("/")[-1] == "conversations.json"]
            if not names:
                return None
            with z.open(names[0]) as f:
                return json.loads(f.read().decode("utf-8", "replace"))
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8", "replace"))


def sniff(path: str) -> bool:
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as z:
                return any(n.split("/")[-1] == "conversations.json" for n in z.namelist())
        except zipfile.BadZipFile:
            return False
    try:
        with open(path, "rb") as f:
            head = f.read(65536).decode("utf-8", "replace")
    except OSError:
        return False
    return '"chat_messages"' in head


def parse_file(path: str) -> Dataset:
    ds = Dataset(estimated=True)
    try:
        data = _load_json(path)
    except (ValueError, OSError, zipfile.BadZipFile):
        ds.notes.append("could not read %s as a Claude export" % path.split("/")[-1])
        return ds
    if isinstance(data, dict):
        data = data.get("conversations") or []
    if not isinstance(data, list):
        ds.notes.append("unrecognized Claude export layout")
        return ds
    convs = 0
    for conv in data:
        if not isinstance(conv, dict):
            continue
        msgs = conv.get("chat_messages")
        if not isinstance(msgs, list) or not msgs:
            continue
        convs += 1
        sid = h(conv.get("uuid") or conv.get("id") or id(conv))
        carried = 0
        last_ts: Optional[float] = None
        turn = sid
        for m in msgs:
            if not isinstance(m, dict):
                continue
            ts = parse_ts(m.get("created_at") or m.get("updated_at")) or last_ts or 0.0
            toks = int(round(_len_of(m) / CHARS_PER_TOKEN))
            sender = m.get("sender") or m.get("role")
            if sender in ("human", "user"):
                turn = h(sid + str(m.get("uuid") or ts))
                text = m.get("text") if isinstance(m.get("text"), str) else "\n".join(
                    b.get("text") for b in m.get("content") or [] if isinstance(b, dict) and isinstance(b.get("text"), str))
                first = not any(p.session_id == sid for p in ds.prompts[-1:])
                fl = signals.analyse(text, first=first)
                if fl is not None:
                    ds.prompts.append(PromptRecord(session_id=sid, turn_id=turn, ts=ts, first=first, **fl))
                carried += toks
                last_ts = ts
                continue
            if sender != "assistant":
                continue
            start = last_ts if last_ts is not None and last_ts <= ts else ts
            ds.calls.append(CallRecord(
                source="claude_export", session_id=sid, turn_id=turn, ts_start=start, ts_end=ts,
                model=None, input=carried, output=toks, cache_read=0, cache_write_unknown=0,
                estimated=True))
            carried += toks
            last_ts = ts
    ds.sources.append("Claude chat export (%d conversation%s, estimated)" % (convs, "" if convs == 1 else "s"))
    return ds
