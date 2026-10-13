"""Turns what a person typed into numbers and flags. The only place that looks at prompt text.

Nothing here returns text. A prompt becomes its length, a few yes/no flags and per-run hashes of its standing
instructions ("always use pnpm"), so repeats can be counted without keeping the words. The hash salt is random per
run, so the hashes mean nothing outside this process, and they are never written to the report.
"""

import hashlib
import re
import secrets
from typing import List, Optional, Tuple

_RUN_SALT = secrets.token_hex(16)

# system-generated wrappers Claude Code writes as "user" lines; these are not things a person typed
_SYSTEM_TAGS = ("task-notification", "system-reminder", "local-command-stdout", "local-command-stderr",
                "local-command-caveat", "command-message", "command-args", "bash-stdout", "bash-stderr",
                "user-memory-input", "artifact-content-authored-by-others", "teammate-message")
_TAG_BLOCK = re.compile(r"<(%s)\b[^>]*>.*?</\1>" % "|".join(re.escape(t) for t in _SYSTEM_TAGS), re.S)
_COMMAND = re.compile(r"<command-name>\s*/?([a-z0-9:_-]+)\s*</command-name>", re.I)
BUILTIN_COMMANDS = {"clear", "compact", "init", "model", "resume", "memory", "review", "cost", "context",
                    "config", "plan", "agents", "mcp", "permissions", "rewind", "usage", "status", "help",
                    "login", "logout", "doctor", "export", "add-dir", "hooks", "plugin", "vibecheck"}

_THANKS = re.compile(r"^(ok(ay)?[ ,]*)?(thanks?( you)?( so much| a lot)?|thx|ty|cheers|great|perfect|awesome|nice|"
                     r"cool|love it|looks good|lgtm|good job|well done|amazing|danke|merci|super)\b[\s!.,:)]*"
                     r"(thanks?( you)?)?[\s!.,:)]*$", re.I)
_REWORK = re.compile(r"^(no\b|nope\b|wrong\b|not (that|this|what)\b|that'?s (wrong|not)|this is (wrong|not)|"
                     r"revert\b|undo\b|roll ?back\b|that (did ?n[o']?t|does ?n[o']?t) work|it (still )?(does ?n[o']?t|did ?n[o']?t) work|"
                     r"still (not|broken|failing|wrong|the same|does)|you broke|stop\b|why did you|i said\b|"
                     r"try again\b|again\b)", re.I)
_VAGUE = re.compile(r"^(please )?(fix( it| this| that)?|make it work|do it|continue|go on|keep going|help( me)?|"
                    r"it'?s broken|broken|does ?n[o']?t work|not working|try again|again|same|you know what to do)"
                    r"( please)?[\s!.?]*$", re.I)
_STANDING = re.compile(r"\b(always|never|don'?t|do not|make sure|remember|please use|use|prefer|avoid|must|"
                       r"only|stick to|keep)\b", re.I)
_SPLIT = re.compile(r"[\n.!?;]+")
_WORD = re.compile(r"[a-z0-9']+")


def clean(text: str) -> Tuple[str, Optional[str]]:
    """Strip system wrappers. Returns (what the person typed, built-in command name or None)."""
    m = _COMMAND.search(text)
    cmd = None
    if m:
        name = m.group(1).lower()
        cmd = name if name in BUILTIN_COMMANDS else "other"
    body = _TAG_BLOCK.sub(" ", text)
    body = re.sub(r"<command-name>.*?</command-name>", " ", body, flags=re.S)
    return body.strip(), cmd


def _fp(sentence: str) -> str:
    return hashlib.sha256((_RUN_SALT + sentence).encode("utf-8", "replace")).hexdigest()[:16]


def standing_instructions(text: str) -> List[str]:
    """Per-run hashes of instruction-like sentences of 3 to 15 words ("always run the tests first")."""
    out = []
    for part in _SPLIT.split(text.lower()):
        words = _WORD.findall(part)
        if 3 <= len(words) <= 15 and _STANDING.search(part):
            out.append(_fp(" ".join(words)))
    return sorted(set(out))


def analyse(text: str, first: bool) -> Optional[dict]:
    """Flags for one typed message, or None if it holds nothing a person typed (a system wrapper)."""
    body, cmd = clean(text)
    if not body and not cmd:
        return None
    words = len(_WORD.findall(body.lower()))
    short = body[:200]
    return {
        "chars": len(body), "words": words, "command": cmd,
        "thanks": bool(body) and words <= 8 and bool(_THANKS.match(short)),
        "rework": bool(body) and not first and bool(_REWORK.match(short.lstrip("\"'*-> "))),
        "vague": bool(body) and first and words <= 6 and bool(_VAGUE.match(short)),
        "fps": standing_instructions(body) if body and len(body) < 20000 else [],
    }


def file_key(path: str) -> str:
    """Per-run hash of a file path, so edits to the same file can be counted without keeping the path."""
    return _fp("file:" + path)


def is_interrupt(text: str) -> bool:
    return text.lstrip().startswith("[Request interrupted by user")
