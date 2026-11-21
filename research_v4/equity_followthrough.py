"""Bounded, free, non-trading recovery of *previously registered* equity follow-ups.

The V5 currently selected survivor sample is NOT allowed to silently delete a
previous V12 signal when a symbol disappears from that sample. On later days,
we may retrieve real completed daily bars for settlement-only. This never
creates an as-of signal, does not establish a real fill or PIT universe, and
cannot resurrect a delisted ticker without price evidence.
"""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime
from research_v4.historical_real_data import yahoo_bars, validate

MAX_RECOVERY_SYMBOLS_PER_MARKET = 20
MAX_SIGNAL_AGE_DAYS = 120


def recover_settlement_universe(series, market, observations, now,
                                fetch=yahoo_bars,
                                max_symbols=MAX_RECOVERY_SYMBOLS_PER_MARKET):
    """Return separate settlement-only series and an auditable failure matrix.

    Request one symbol once; restrict recovery to symbols observed earlier by
    the sealed V12 ledger. Never use recovered series to create new signals.
    """
    if market not in ("BIST", "US") or now.tzinfo is None:
        raise ValueError("RECOVERY_MARKET_OR_TIME_INVALID")
    existing = {(m, s) for m, s in series}
    needed = {}
    for observation in observations:
        if observation.get("market") != market:
            continue
        sym = observation.get("symbol")
        if not isinstance(sym, str) or not re.fullmatch(r"[A-Z0-9.\-]{1,15}", sym):
            continue
        if (market, sym) in existing:
            continue
        try:
            observed = datetime.fromisoformat(observation["observed_utc"].replace("Z","+00:00"))
            age = (now - observed).days
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= age <= MAX_SIGNAL_AGE_DAYS:
            needed[sym] = True
    targets = sorted(needed)
    report = {
        "recovery_mode": "SETTLEMENT_ONLY_YAHOO_UNOFFICIAL_DAILY",
        "requested": len(targets),
        "attempted": 0,
        "symbols_recovered": [],
        "missing_symbols": targets[max_symbols:],
        "errors": {},
        "source_sha256": {},
        "coverage_complete": len(targets) <= max_symbols,
        "not_historical_pit": True,
        "not_executable_fill": True,
    }
    output = dict(series)
    for sym in targets[:max_symbols]:
        report["attempted"] += 1
        try:
            rows, host = fetch(sym, market, int(now.timestamp()*1000))
            valid = validate(rows, sym, market, min_bars=2)
            bars = []
            for _, _, day, op, hi, lo, close, vol, *_ in valid:
                from datetime import date
                d = date.fromisoformat(day)
                if d >= now.date():
                    continue
                bars.append({"date": d, "open": op, "high": hi, "low": lo,
                             "close": close, "volume": vol,
                             "pit": False, "actions": False})
            if len(bars) < 2:
                raise ValueError("RECOVERY_NO_TWO_COMPLETED_BARS")
            output[(market, sym)] = bars
            report["symbols_recovered"].append(sym)
            report["source_sha256"][sym] = hashlib.sha256(
                json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
        except (ValueError, TypeError, KeyError, IndexError, OSError) as exc:
            report["errors"][sym] = type(exc).__name__ + ": " + str(exc)[:110]
            report["missing_symbols"].append(sym)
    report["symbols_recovered"].sort()
    report["missing_symbols"].sort()
    return output, report
