"""Original-universe V4 DEX discovery: evidence-only, no trading or ownership claims.

Official market cap/free-float ownership cannot be inferred from DEX liquidity.
This module never classifies pump-and-dump or manipulation as proven facts.
"""
from __future__ import annotations
import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote

PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"
PAIRS = "https://api.dexscreener.com/token-pairs/v1"
MAX_PROFILES = 24
MIN_LIQUIDITY_USD = 15000
MAX_LIQUIDITY_USD = 2000000
MIN_VOLUME24_USD = 10000
MIN_AGE_HOURS = 24
MAX_AGE_DAYS = 180
ALLOWED_CHAINS = {"solana", "ethereum", "base", "bsc", "arbitrum"}
MAX_RESPONSE_BYTES = 2500000

def fetch_json(url):
    req = Request(url, headers={"User-Agent": "EAR-V4-research/1.0", "Accept": "application/json"})
    with urlopen(req, timeout=12) as response:
        if response.status != 200:
            raise ValueError("HTTP_" + str(response.status))
        content = response.read(MAX_RESPONSE_BYTES + 1)
        if len(content) > MAX_RESPONSE_BYTES:
            raise ValueError("OVERSIZED_RESPONSE")
    return json.loads(content)

def positive(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        v = float(value)
        return v if math.isfinite(v) and v >= 0 else None
    except (TypeError, ValueError):
        return None

def classify_pair(p, observed_ms, chain_id, token_address):
    if not isinstance(p, dict) or p.get("chainId") != chain_id:
        return None
    if p.get("dexId") is None or p.get("pairAddress") is None:
        return None
    base = p.get("baseToken") or {}
    quote_token = p.get("quoteToken") or {}
    # DexScreener priceUsd is the BASE token price. A target that is only
    # the quote side cannot safely inherit base-token price or liquidity.
    if token_address != base.get("address"):
        return None
    liq = positive((p.get("liquidity") or {}).get("usd"))
    volume = positive((p.get("volume") or {}).get("h24"))
    cap = positive(p.get("marketCap"))
    fdv = positive(p.get("fdv"))
    age_ms = positive(p.get("pairCreatedAt"))
    age_hours = ((observed_ms - age_ms) / 3600000 if age_ms is not None else None)
    if age_hours is not None and age_hours < 0:
        age_hours = None
    candidate = (liq is not None and MIN_LIQUIDITY_USD <= liq <= MAX_LIQUIDITY_USD
                 and volume is not None and volume >= MIN_VOLUME24_USD
                 and age_hours is not None and MIN_AGE_HOURS <= age_hours <= MAX_AGE_DAYS * 24)
    # Ownership, float and fundamentals are never manufactured from FDV/marketCap.
    return {"chain": chain_id, "dex": p.get("dexId"), "pair_address": p["pairAddress"],
            "token_address": token_address, "base_symbol": base.get("symbol"),
            "quote_symbol": quote_token.get("symbol"),
            "liquidity_usd": liq, "volume_24h_usd": volume,
            "market_cap_usd_unverified": cap, "fdv_usd_unverified": fdv,
            "price_usd_snapshot_unverified": positive(p.get("priceUsd")),
            "price_identity": "BASE_TOKEN_ONLY_UNVERIFIED_SNAPSHOT",
            "pair_age_hours": round(age_hours, 2) if age_hours is not None else None,
            "liquidity_to_fdv": round(liq / fdv, 5) if liq is not None and fdv and fdv > 0 else None,
            "source": "DEXSCREENER_PUBLIC_AGGREGATOR",
            "source_observed_ms": observed_ms,
            "screen_watch": candidate, "signal_status": "RESEARCH_WATCH_ONLY" if candidate else "SCREEN_REJECT",
            "float_verified": False, "holder_concentration_verified": False,
            "lock_and_contract_security_verified": False,
            "fundamentals_verified": False, "trade_authorized": False}

def scan(fetch=fetch_json, now_ms=None, limit=MAX_PROFILES):
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    result = {"schema": "EAR.V4.original_universe.v1", "observed_ms": now_ms,
              "primary_goal": "SMALL_FLOAT_SHALLOW_BOOK_EARLY_ACCUMULATION_RESEARCH",
              "coverage": {"dex": "PUBLIC_DISCOVERY", "us_equities": "NOT_CONNECTED", "bist_equities": "NOT_CONNECTED"},
              "trading_authorized": False, "live_orders": False, "errors": [], "observations": [],
              "limitations": ["TOKEN_PROFILES_ARE_DISCOVERY_NOT_COMPLETE_MARKET_UNIVERSE",
                              "MARKET_CAP_AND_FDV_ARE_NOT_FLOAT",
                              "NO_VERIFIED_TOKEN_HOLDER_CONCENTRATION",
                              "NO_VERIFIED_POOL_LOCKS_OR_CONTRACT_SECURITY",
                              "NO_POINT_IN_TIME_HISTORICAL_UNIVERSE",
                              "NO_PRICE_PREDICTION_OR_PUMP_PROOF"]}
    try:
        profiles = fetch(PROFILES)
        if not isinstance(profiles, list):
            raise ValueError("BAD_PROFILES_SCHEMA")
    except (Exception,) as exc:
        result["errors"].append({"stage": "profiles", "error": type(exc).__name__ + ":" + str(exc)[:120]})
        result["status"] = "SOURCE_OUTAGE_NO_SIGNAL"
        return result
    seen = set()
    for profile in profiles:
        if len(seen) >= min(limit, MAX_PROFILES):
            break
        if not isinstance(profile, dict):
            continue
        chain = profile.get("chainId")
        address = profile.get("tokenAddress")
        if chain not in ALLOWED_CHAINS or not isinstance(address, str) or not address:
            continue
        if (chain, address) in seen:
            continue
        seen.add((chain, address))
        try:
            raw_pairs = fetch(PAIRS + "/" + quote(chain, safe="") + "/" + quote(address, safe=""))
            if not isinstance(raw_pairs, list):
                raise ValueError("BAD_PAIR_LIST_SCHEMA")
            parsed = [x for p in raw_pairs if (x := classify_pair(p, now_ms, chain, address)) is not None]
            # Prefer most USD liquidity; do not sum across unverified venues.
            if parsed:
                result["observations"].append(max(parsed, key=lambda r: r["liquidity_usd"] if r["liquidity_usd"] is not None else -1))
        except (Exception,) as exc:
            result["errors"].append({"stage": "pairs", "chain": chain, "token_address": address,
                                     "error": type(exc).__name__ + ":" + str(exc)[:120]})
    result["discovered_tokens"] = len(seen)
    result["observed_pairs"] = len(result["observations"])
    result["research_watch_count"] = sum(x["screen_watch"] for x in result["observations"])
    result["status"] = ("RESEARCH_OBSERVATIONS_NOT_VALIDATED_ALPHA" if result["observations"]
                        else "INSUFFICIENT_EVIDENCE_NO_SIGNAL")
    return result

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="out/v4_original_universe")
    args = p.parse_args()
    r = scan()
    path = Path(args.out)
    path.mkdir(parents=True, exist_ok=True)
    (path / "discovery.json").write_text(json.dumps(r, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf8")
    lines = ["# Original early accumulation target-universe discovery", "",
             "**Research only: NO TRADING SIGNAL OR PAPER STRATEGY CHANGE.**", "",
             f"Status: {r['status']}; seen tokens: {r.get('discovered_tokens',0)}; watch observations: {r.get('research_watch_count',0)}", "",
             "DEX listings are discovery samples. Float/holder concentration, security, fundamentals and historical first-seen universe are not verified.", "",
             "US small-cap and BIST feeds are NOT connected. Never treat absent data as a passing gate.", "",
             "| Chain | Token | Liquidity USD | 24h Volume USD | Age h | Watch only |",
             "|---|---|---:|---:|---:|---|"]
    for row in r["observations"]:
        lines.append(f"| {row['chain']} | {row['base_symbol'] or row['token_address'][:10]} | {row['liquidity_usd']} | {row['volume_24h_usd']} | {row['pair_age_hours']} | {row['screen_watch']} |")
    if r["errors"]:
        lines.extend(["", "## Source errors", ""] + ["- " + str(e) for e in r["errors"][:25]])
    (path / "report.md").write_text("\n".join(lines) + "\n", encoding="utf8")
    print("V4_ORIGINAL_UNIVERSE", r["status"], "watch", r.get("research_watch_count", 0), "errors", len(r["errors"]))
    return r

if __name__ == "__main__":
    main()
