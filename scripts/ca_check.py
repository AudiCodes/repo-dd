"""Who deployed a Solana token, what else they launched, and who funded them.

    python3 ca_check.py <mint> [--scan 1000] [--hops 3]

Deployer: pump.fun keeps the creator in the bonding-curve account (offset 49),
one call. Other mints fall back to the fee payer of the mint's oldest tx.

Past deploys: every CREATE in the deployer's last --scan transactions, from
Helius parsed history (its labels caught 12 launches where hand-parsing
instructions caught 5). The output says when the scan cap fired.

Funding: who sent the dev SOL (plain transfers >= 0.05 SOL) in that window,
each funder profiled one hop back; then the dev wallet's origin: its first
inbound transfer, then that funder's, up to --hops. A wallet with more than
BUSY txs is treated as an exchange or service and the trail stops there.
"""
import argparse
import base64
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sol import b58decode, b58encode, enhanced, pda, rpc, signatures  # Helius with public-RPC failover and enhanced-API pacing

PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
META = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"  # Metaplex token metadata
BUSY = 1000
MIN_FUND = 50_000_000  # lamports; below this it is dust or rent


def fetch(url, body=None):
    for attempt in range(8):
        try:
            req = urllib.request.Request(url, json.dumps(body).encode() if body else None,
                                         {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception:
            if attempt == 7:
                raise
            time.sleep(2 ** attempt * 0.5)


def history(address, cap):
    """Newest first. Returns (txs, capped)."""
    out, before = [], None
    while len(out) < cap:
        page = enhanced(f"addresses/{address}/transactions", limit=100, before=before)
        if not page:
            return out, False
        out += page
        before = page[-1]["signature"]
    return out, True


def when(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M") if ts else "?"


def deployer(mint):
    acct = rpc("getAccountInfo", [pda([b"bonding-curve", b58decode(mint)], PUMP), {"encoding": "base64"}])
    if acct and acct.get("value"):
        data = base64.b64decode(acct["value"]["data"][0])
        if len(data) >= 81 and any(data[49:81]):  # curves from before pump.fun stored the creator hold zeros here
            return b58encode(data[49:81]), "pump.fun bonding curve"
    # the metadata account is written once at launch, so its oldest tx is the create even on a mint with millions of txs
    sigs = rpc("getSignaturesForAddress", [pda([b"metadata", b58decode(META), b58decode(mint)], META), {"limit": 1000}])
    how = "fee payer of the metadata create"
    if not sigs or len(sigs) == 1000:
        sigs, capped = signatures(mint, 200_000)
        if capped or not sigs:
            return None, "mint history over 200k txs, oldest tx not reached"
        how = "fee payer of the mint's first tx"
    first = rpc("getTransaction", [sigs[-1]["signature"], {"maxSupportedTransactionVersion": 1, "encoding": "json"}])
    return first["transaction"]["message"]["accountKeys"][0], how


def inflows(address, txs):
    for t in txs:
        if t["type"] != "TRANSFER" or t.get("transactionError"):
            continue
        for n in t.get("nativeTransfers") or []:
            if n["toUserAccount"] == address and n["fromUserAccount"] != address and n["amount"] >= MIN_FUND:
                yield {"from": n["fromUserAccount"], "sol": n["amount"] / 1e9, "time": t["timestamp"]}


def first_funder(address):
    if len(signatures(address, BUSY)[0]) >= BUSY:  # busy wallets are services; skip before paying for pages
        return None, BUSY, True
    txs, busy = history(address, BUSY)
    if busy:
        return None, len(txs), True
    oldest = list(inflows(address, reversed(txs)))
    return (oldest[0] if oldest else None), len(txs), False


def names(mints):
    out = {}
    for i in range(0, len(mints), 30):
        try:
            for p in fetch(f"https://api.dexscreener.com/tokens/v1/solana/{','.join(mints[i:i + 30])}"):
                t = p["baseToken"]["address"]
                if t not in out or (p.get("marketCap") or 0) > out[t]["mcap"]:
                    out[t] = {"symbol": p["baseToken"]["symbol"], "mcap": p.get("marketCap") or 0}
        except Exception:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mint")
    ap.add_argument("--scan", type=int, default=1000)
    ap.add_argument("--hops", type=int, default=3)
    a = ap.parse_args()

    dev, how = deployer(a.mint)
    print(f"DEPLOYER {dev}  ({how})")
    if not dev:
        return
    print(f"  solscan.io/account/{dev}")

    txs, capped = history(dev, a.scan)
    span = f"{when(txs[-1]['timestamp'])} to {when(txs[0]['timestamp'])}" if txs else ""
    launches = []
    for t in txs:
        if t["type"] == "CREATE" and not t.get("transactionError"):
            mints = [x["mint"] for x in t.get("tokenTransfers") or [] if x.get("mint")]
            if mints:
                launches.append({"mint": mints[0], "time": t["timestamp"], "via": t["source"]})
    meta = names([l["mint"] for l in launches])
    alive = sum(1 for l in launches if l["mint"] in meta and meta[l["mint"]]["mcap"] >= 50_000)
    print(f"\nPAST DEPLOYS: {len(launches)} in last {len(txs)} txs ({span}); {alive} above $50k mcap now"
          + ("  [scan cap hit, older launches not checked]" if capped else ""))
    for l in launches[:25]:
        m = meta.get(l["mint"])
        tag = f"{m['symbol']}  mcap ${m['mcap']:,.0f}" if m else "no live pair (dead or never traded)"
        mark = "  <- this token" if l["mint"] == a.mint else ""
        print(f"  {when(l['time'])}  {l['mint']}  {l['via']}  {tag}{mark}")
    if len(launches) > 25:
        print(f"  ... {len(launches) - 25} more")

    by = {}
    for f in inflows(dev, txs):
        b = by.setdefault(f["from"], {"sol": 0.0, "n": 0, "last": 0})
        b["sol"] += f["sol"]
        b["n"] += 1
        b["last"] = max(b["last"], f["time"] or 0)
    print(f"\nWHO SENDS THE DEV SOL (transfers >= 0.05 SOL, same window)")
    top = sorted(by.items(), key=lambda kv: -kv[1]["sol"])[:5]
    with ThreadPoolExecutor(5) as pool:
        profiles = list(pool.map(first_funder, [src for src, _ in top]))
    for (src, b), (f, n, busy) in zip(top, profiles):
        profile = f"{n}+ txs: exchange/service" if busy else f"{n} txs, first funded by {f['from'] if f else '?'}"
        print(f"  {src}  {b['sol']:.2f} SOL over {b['n']} tx, last {when(b['last'])}  [{profile}]")
    if not by:
        print("  none")

    print("\nORIGIN OF THE DEV WALLET")
    cur = dev
    for hop in range(a.hops):
        f, n, busy = first_funder(cur)
        if busy:
            print(f"  {cur} has {n}+ txs: exchange/service or too busy to trace, trail stops")
            break
        if not f:
            print(f"  {cur}: no inbound transfer found in {n} txs")
            break
        print(f"  hop {hop + 1}: {f['from']} sent {f['sol']:.3f} SOL on {when(f['time'])}  (funded wallet had {n} txs)")
        cur = f["from"]


if __name__ == "__main__":
    main()
