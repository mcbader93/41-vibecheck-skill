"""Deterministic pricing. Prices come only from data/pricing.json, per model and per token type.

Write tokens with unknown TTL are priced at the TTL the analysis measured or inferred.
"""

import json
import pkgutil
import time
from datetime import date
from typing import Dict, Optional

from .records import CallRecord



def load_pricing(path: Optional[str] = None) -> dict:
    if path:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    # pkgutil works from a folder, a wheel and a single-file zipapp alike
    return json.loads(pkgutil.get_data("vibecheck", "data/pricing.json").decode("utf-8"))


class Pricer:
    def __init__(self, pricing: Optional[dict] = None, profile: str = "list", default_ttl: str = "5m"):
        self.pricing = pricing or load_pricing()
        if profile not in self.pricing["profiles"]:
            raise ValueError("unknown pricing profile: %s" % profile)
        self.profile = profile
        self.models: Dict[str, dict] = self.pricing["profiles"][profile]["models"]
        self.label = self.pricing["profiles"][profile]["label"]
        self.default_ttl = default_ttl
        self.cheaper_model = self.pricing.get("cheaper_model", "claude-sonnet-5")

    @property
    def checked_on(self) -> str:
        return self.pricing.get("checked_on", "unknown")

    def age_days(self, today: Optional[date] = None) -> Optional[int]:
        try:
            d = date.fromisoformat(self.checked_on)
        except ValueError:
            return None
        return ((today or date.fromtimestamp(time.time())) - d).days

    def known(self, model: Optional[str]) -> bool:
        return bool(model) and model in self.models

    def _rates(self, c: CallRecord, model: str, prompt: int) -> Optional[dict]:
        """The price row for one call, or None if it has no price.

        Fast-mode calls use the model's "fast" row; a model without one is unpriced rather than billed at
        normal rates. A model with an "over_100k" row bills the whole call at that row once its prompt
        (input + cache read + all cache writes) passes 100k tokens. The single place all three
        price methods get their rates from, so they cannot disagree on the tier.
        """
        if not self.known(model):
            return None
        p = self.models[model]
        # fast applies to the model the call actually ran on; re-pricing onto another model is standard
        if c.speed == "fast" and model == c.model:
            p = p.get("fast")
            if p is None:
                return None
        if prompt > 100_000 and "over_100k" in p:
            p = p["over_100k"]
        return p

    def rates(self, call_or_model) -> Optional[dict]:
        """The price row for a call (fast and long-prompt tiers applied) or, given a model name, its base row.
        None when unpriced. The public way for other modules to read prices, so there is one pricing path."""
        if isinstance(call_or_model, str):
            return self.models.get(call_or_model)
        return self._rates(call_or_model, call_or_model.model, call_or_model.ctx) if call_or_model.model else None

    def _wu_price(self, p: dict) -> float:
        return p["cache_write_1h"] if self.default_ttl == "1h" else p["cache_write_5m"]

    def cost(self, c: CallRecord, model: Optional[str] = None, ctx_override: Optional[int] = None) -> Optional[float]:
        """USD for one call, or None if usage was not recorded or the model has no price.

        ctx_override reprices the call as if it had carried that much context: the context is cut from
        cache reads first, then cache writes, then uncached input (what a fresh session would not carry).
        Web searches are a flat per-request fee on top; trimming context does not remove them.
        """
        m = model or c.model
        if not c.usage_recorded or not self.known(m):
            return None
        inp = c.input or 0
        cr = c.cache_read or 0
        w5 = c.cache_write_5m or 0
        w1 = c.cache_write_1h or 0
        wu = c.cache_write_unknown or 0
        if ctx_override is not None:
            # trim order: cache reads, 1h writes, 5m writes, unknown-TTL writes, uncached input
            parts = [cr, w1, w5, wu, inp]
            excess = max(0, sum(parts) - max(0, ctx_override))
            for i in range(len(parts)):
                cut = min(parts[i], excess)
                parts[i] -= cut
                excess -= cut
            cr, w1, w5, wu, inp = parts
        # tier is chosen after trimming: a shorter context can fall back to the cheaper tier
        p = self._rates(c, m, inp + cr + w5 + w1 + wu)
        if p is None:
            return None
        usd = (
            inp * p["input"]
            + (c.output or 0) * p["output"]
            + cr * p["cache_read"]
            + w5 * p["cache_write_5m"]
            + w1 * p["cache_write_1h"]
            + wu * self._wu_price(p)
        ) / 1e6
        return usd + (c.web_searches or 0) * self.pricing.get("web_search_usd_per_request", 0.0)

    def write_price(self, c: CallRecord) -> Optional[float]:
        """USD per token for this call's cache writes (blended over its TTL mix)."""
        p = self._rates(c, c.model, c.ctx) if c.model else None
        if p is None:
            return None
        w5, w1, wu = c.cache_write_5m or 0, c.cache_write_1h or 0, c.cache_write_unknown or 0
        tot = w5 + w1 + wu
        if tot == 0:
            return self._wu_price(p) / 1e6
        return (w5 * p["cache_write_5m"] + w1 * p["cache_write_1h"] + wu * self._wu_price(p)) / tot / 1e6

    def breakdown(self, c: CallRecord) -> Optional[Dict[str, float]]:
        """Token cost split into input/output/cache_read/cache_write.

        Web search fees are deliberately not a key: analysis.py sums these four fixed keys into the report,
        so a fifth would need report changes. Totals come from cost(), which includes the fee.
        """
        p = self._rates(c, c.model, c.ctx) if c.usage_recorded and c.model else None
        if p is None:
            return None
        return {
            "input": (c.input or 0) * p["input"] / 1e6,
            "output": (c.output or 0) * p["output"] / 1e6,
            "cache_read": (c.cache_read or 0) * p["cache_read"] / 1e6,
            "cache_write": ((c.cache_write_5m or 0) * p["cache_write_5m"]
                            + (c.cache_write_1h or 0) * p["cache_write_1h"]
                            + (c.cache_write_unknown or 0) * self._wu_price(p)) / 1e6,
        }

    def most_expensive_model(self, models) -> Optional[str]:
        known = [m for m in models if self.known(m)]
        if not known:
            return None
        return max(known, key=lambda m: self.models[m]["output"])
