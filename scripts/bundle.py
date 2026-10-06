"""The launch bundle: what the deployer and the first-slot buyers got at launch, and what they hold now.

    python3 bundle.py <mint> [--slots 2]

Seeds are the deployer plus every wallet whose balance rose in the first --slots slots after the create.
A bundle that took 40% and holds 2% has already sold into the buyers; one that still holds is the overhang.
"""
import argparse
import time

from ca_check import deployer as ca_deployer
from fomo_share import on_curve
from sol import b58decode, pda, rpc, signatures

META = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"  # Metaplex token metadata


def create_slot(mint):
    """Slot of the create. The Metaplex metadata account is written once at launch, so its oldest tx is the
    create even when the mint itself has 100k+ txs. Token-2022 mints have none: page the mint."""
    sigs = rpc("getSignaturesForAddress", [pda([b"metadata", b58decode(META), b58decode(mint)], META), {"limit": 1000}])
    if not sigs:
        sigs, _ = signatures(mint, 1_000_000)
    return sigs[-1]["slot"]


def first_buyers(mint, slots):
    """{wallet: how} and {wallet: tokens got} for the deployer and the first-slot buyers."""
    s0 = create_slot(mint)
    seeds, bought = {ca_deployer(mint)[0]: "deployer"}, {}
    for slot in range(s0, s0 + slots + 1):
        block = rpc("getBlock", [slot, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1,
                                        "transactionDetails": "full", "rewards": False}])
        for t in (block or {}).get("transactions", []):
            if t["meta"]["err"]:
                continue
            pre = {b["owner"]: float(b["uiTokenAmount"]["uiAmount"] or 0) for b in t["meta"]["preTokenBalances"] if b["mint"] == mint}
            post = {b["owner"]: float(b["uiTokenAmount"]["uiAmount"] or 0) for b in t["meta"]["postTokenBalances"] if b["mint"] == mint}
            for o, v in post.items():
                if v > pre.get(o, 0) and on_curve(o):
                    seeds.setdefault(o, f"bundle slot+{slot - s0}")
                    bought[o] = bought.get(o, 0) + v - pre.get(o, 0)
    return seeds, bought


def holders(mint):
    program = rpc("getAccountInfo", [mint, {"encoding": "base64"}])["value"]["owner"]
    filters = [{"memcmp": {"offset": 0, "bytes": mint}}] + ([{"dataSize": 165}] if program.startswith("Tokenkeg") else [])
    out = {}
    for t in rpc("getProgramAccounts", [program, {"encoding": "jsonParsed", "filters": filters}]):
        i = t["account"]["data"]["parsed"]["info"]
        out[i["owner"]] = out.get(i["owner"], 0) + float(i["tokenAmount"]["uiAmount"] or 0)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mint")
    ap.add_argument("--slots", type=int, default=2)
    a = ap.parse_args()
    t0 = time.time()
    seeds, bought = first_buyers(a.mint, a.slots)
    supply = float(rpc("getTokenSupply", [a.mint])["value"]["uiAmount"])
    held = holders(a.mint)
    rows = sorted(seeds, key=lambda w: -bought.get(w, 0))
    got = sum(bought.values()) / supply * 100
    now = sum(held.get(w, 0) for w in rows) / supply * 100
    print(f"First bundle: {len(rows)} wallets got {got:.2f}% at launch, hold {now:.2f}% now")
    for w in rows:
        print(f"  {w[:4]}…{w[-4:]}  got {bought.get(w, 0) / supply * 100:5.2f}%  holds {held.get(w, 0) / supply * 100:5.2f}%  {seeds[w]}")
    print(f"[{time.time() - t0:.1f}s]")


if __name__ == "__main__":
    main()
