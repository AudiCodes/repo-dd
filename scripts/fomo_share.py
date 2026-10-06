"""How much of a token's supply sits in wallets of the FOMO trading app (fomo.family).

    python3 fomo_share.py <mint or 0x token> [--chain solana|robinhood|base|bsc]

FOMO wallets are recognizable on-chain:
  Solana: FOMO sponsors gas, so its paymaster AgmLJB…zN51 is the fee payer on a FOMO user's txs.
  EVM:    FOMO wallets are EIP-7702 delegated to 0xe6ca…555b (same delegate on every chain).
Holders come from one bulk call (Solana getProgramAccounts on the mint; EVM Transfer logs since mint),
and the FOMO test is one batch: EVM getCode over all holders; Solana the mint's parsed history (fee payer).
"""
import argparse
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


PAYMASTER = "AgmLJBMDCqWynYnQiPCuj9ewsNNsBJXyzoUhD9LJzN51"
DELEGATE = "0xef0100e6cae83bde06e4c305530e199d7217f42808555b"
MAX_PAGES = 50  # Solana history cap: 5,000 most recent txs
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
# rpc, getLogs chunk, lookback blocks
EVM = {"robinhood": ("https://rpc.mainnet.chain.robinhood.com", 2_000_000, 20_000_000),
       "base": ("https://mainnet.base.org", 500, 100_000),  # public RPC: 500-block getLogs cap
       "bsc": ("https://bsc-dataseed.binance.org", 5000, 200_000)}


def post(url, body):
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
            return json.load(urllib.request.urlopen(req, timeout=30))
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 5:
                raise
            time.sleep(1 + attempt)


B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
P25519 = 2 ** 255 - 19
D25519 = -121665 * pow(121666, P25519 - 2, P25519) % P25519


def on_curve(addr):
    """Real wallets are ed25519 points; pools and vault authorities are PDAs, which are off the curve."""
    n = 0
    for ch in addr:
        n = n * 58 + B58.index(ch)
    y = int.from_bytes(n.to_bytes(32, "big"), "little") & ((1 << 255) - 1)
    if y >= P25519:
        return False
    u, v = (y * y - 1) % P25519, (D25519 * y * y + 1) % P25519
    x2 = u * pow(v, P25519 - 2, P25519) % P25519
    return x2 == 0 or pow(x2, (P25519 - 1) // 2, P25519) == 1



def solana(mint):
    from sol import enhanced, rpc
    program = rpc("getAccountInfo", [mint, {"encoding": "base64"}])["value"]["owner"]  # Token or Token-2022
    filters = [{"memcmp": {"offset": 0, "bytes": mint}}] + ([{"dataSize": 165}] if program.startswith("Tokenkeg") else [])
    holders = {}
    for t in rpc("getProgramAccounts", [program, {"encoding": "jsonParsed", "filters": filters}]):
        i = t["account"]["data"]["parsed"]["info"]
        if float(i["tokenAmount"]["uiAmount"] or 0) > 0:
            holders[i["owner"]] = holders.get(i["owner"], 0) + float(i["tokenAmount"]["uiAmount"])
    supply = float(rpc("getTokenSupply", [mint])["value"]["uiAmount"])

    # the mint's parsed history, 100 txs a call: every wallet whose tx FOMO's paymaster paid for is a FOMO wallet
    fomo, before, seen = set(), "", 0
    for _ in range(MAX_PAGES):
        page = enhanced(f"addresses/{mint}/transactions", limit=100, before=before)
        for t in page:
            if t["feePayer"] == PAYMASTER:
                fomo |= {x["toUserAccount"] for x in t["tokenTransfers"] if x["mint"] == mint}
                fomo |= {x["fromUserAccount"] for x in t["tokenTransfers"] if x["mint"] == mint}
        seen += len(page)
        if len(page) < 100:
            break
        before = page[-1]["signature"]
    return holders, {h: h in fomo and on_curve(h) for h in holders}, supply, seen


def evm(token, chain):
    url, chunk, lookback = EVM[chain]
    rpc = lambda m, p: post(url, {"jsonrpc": "2.0", "id": 1, "method": m, "params": p}).get("result")
    head = int(rpc("eth_blockNumber", []), 16)

    def logs(lo):
        return rpc("eth_getLogs", [{"address": token, "topics": [TRANSFER], "fromBlock": hex(lo), "toBlock": hex(min(head, lo + chunk - 1))}]) or []

    bal = {}
    with ThreadPoolExecutor(8) as pool:
        for page in pool.map(logs, range(max(0, head - lookback), head + 1, chunk)):
            for l in page:
                v = int(l["data"], 16)
                a, b = "0x" + l["topics"][1][-40:], "0x" + l["topics"][2][-40:]
                bal[a] = bal.get(a, 0) - v
                bal[b] = bal.get(b, 0) + v
    holders = {a: v / 1e18 for a, v in bal.items() if v > 0 and a != "0x" + "0" * 40}
    supply = int(rpc("eth_call", [{"to": token, "data": "0x18160ddd"}, "latest"]), 16) / 1e18
    with ThreadPoolExecutor(12) as pool:
        codes = list(pool.map(lambda a: rpc("eth_getCode", [a, "latest"]) or "0x", holders))
    return holders, {a: c.lower() == DELEGATE for a, c in zip(holders, codes)}, supply, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("token")
    ap.add_argument("--chain", default=None, choices=["solana", *EVM])
    a = ap.parse_args()
    t0 = time.time()
    chain = a.chain or ("solana" if not a.token.startswith("0x") else "robinhood")
    holders, flags, supply, seen = solana(a.token) if chain == "solana" else evm(a.token.lower(), chain)
    fomo = sorted(((v, h) for h, v in holders.items() if flags[h]), reverse=True)
    held = sum(v for v, _ in fomo)
    print(f"FOMO holds {held / supply * 100:.2f}% of supply: {len(fomo)} of {len(holders)} holders ({chain})"
          + (f", from the last {seen:,} txs" if seen else ""))
    for v, h in fomo[:8]:
        print(f"  {v / supply * 100:6.2f}%  {h}")
    print(f"[{time.time() - t0:.1f}s]")


if __name__ == "__main__":
    main()
