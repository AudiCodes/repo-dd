"""Is an EVM token tied to a known team? Dev wallet trace plus a full holder scan.

    python3 evm_relation.py <token> [--chain base|robinhood] [--team 0xabc,0xdef] [--lookback N]

Deployer is the sender of the tx that emitted the first mint Transfer, so it
works for factory launches (flap.sh, Virtuals) where explorers show no creator.
When that tx went through the 4337 EntryPoint (FOMO and other embedded wallets)
the deployer is the smart-account sender of the user op that minted.
Reports: deployer funding (first inbound ETH, Base only: the Robinhood Chain
explorer sits behind Cloudflare), how much of supply the dev still holds, and
every address that ever sent or received the token, checked against --team.
Pull team wallets from the real project's contract owner() and its treasury
flows before running this.
"""
import argparse
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
USER_OP = "0x49628fd1471006c1482da88028e9ce4dbb080b815c9b0344d39e5a8e6ec1419f"
ENTRYPOINTS = {"0x0000000071727de22e5e9d8baf0edac6f37da032", "0x5ff137d4b0fdcd49dca30c7cf57e578a026d2789"}
ZERO = "0x" + "0" * 40
# rpc, blockscout api, max getLogs range, default lookback in blocks (~2 days on Base, ~23 days on RH)
CHAINS = {
    "base": ("https://mainnet.base.org", "https://base.blockscout.com/api/v2", 500, 100_000),  # public RPC: 500-block getLogs cap
    "robinhood": ("https://rpc.mainnet.chain.robinhood.com", None, 2_000_000, 20_000_000),
}


def fetch(url, body=None):
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, json.dumps(body).encode() if body else None,
                                         {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
            return json.load(urllib.request.urlopen(req, timeout=30))
        except Exception:
            if attempt == 5:
                raise
            time.sleep(2 ** attempt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("token")
    ap.add_argument("--chain", choices=CHAINS, default="base")
    ap.add_argument("--team", default="", help="comma-separated team wallets")
    ap.add_argument("--rpc", help="override the chain's default RPC")
    ap.add_argument("--lookback", type=int, help="blocks to scan back for the mint")
    a = ap.parse_args()
    rpc_url, blockscout, chunk, lookback = CHAINS[a.chain]
    rpc_url, lookback = a.rpc or rpc_url, a.lookback or lookback
    token = a.token.lower()
    team = {t.strip().lower() for t in a.team.split(",") if t.strip()}

    def rpc(method, params):
        r = fetch(rpc_url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if "error" in r:
            raise SystemExit(f"{method}: {r['error']}")
        return r["result"]

    def balance(holder):
        data = "0x70a08231" + holder[2:].rjust(64, "0")
        return int(rpc("eth_call", [{"to": token, "data": data}, "latest"]), 16)

    def logs(start):
        return rpc("eth_getLogs", [{"address": token, "topics": [TRANSFER],
                                    "fromBlock": hex(start), "toBlock": hex(min(start + chunk - 1, head))}])

    head = int(rpc("eth_blockNumber", []), 16)
    supply = int(rpc("eth_call", [{"to": token, "data": "0x18160ddd"}, "latest"]), 16)
    addrs, mint, n = set(), None, 0
    with ThreadPoolExecutor(8) as pool:
        for page in pool.map(logs, range(max(head - lookback, 0), head + 1, chunk)):
            for log in page:
                src, dst = "0x" + log["topics"][1][-40:], "0x" + log["topics"][2][-40:]
                addrs |= {src, dst}
                n += 1
                if mint is None and src == ZERO:
                    mint = log
    if mint is None:
        raise SystemExit(f"no mint in the last {lookback} blocks; raise --lookback")

    tx = rpc("eth_getTransactionByHash", [mint["transactionHash"]])
    dev, via = tx["from"].lower(), f"tx nonce {int(tx['nonce'], 16)}"
    if (tx["to"] or "").lower() in ENTRYPOINTS:
        receipt = rpc("eth_getTransactionReceipt", [mint["transactionHash"]])
        mint_idx = int(mint["logIndex"], 16)
        op = next(l for l in receipt["logs"] if l["topics"][0] == USER_OP and int(l["logIndex"], 16) > mint_idx)
        dev, via = "0x" + op["topics"][2][-40:], f"4337 user op sender, bundler {tx['from'][:10]}"
    minted_at = int(rpc("eth_getBlockByNumber", [mint["blockNumber"], False])["timestamp"], 16)
    print(f"token     {token}  supply {supply / 1e18:,.0f}  ({a.chain})")
    print(f"minted    block {int(mint['blockNumber'], 16)}  {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime(minted_at))}")
    print(f"deployer  {dev}  ({via})")
    held = balance(dev)
    print(f"dev holds {held / 1e18:,.0f}  = {held / supply:.1%} of supply")

    try:
        txs = fetch(f"{blockscout}/addresses/{dev}/transactions").get("items", []) if blockscout else None
    except Exception as e:  # Base Blockscout sits behind a Cloudflare challenge more often than not
        txs, blockscout = None, f"Blockscout failed ({str(e)[:40]})"
    if txs is not None:
        funding = [t for t in txs if t["to"] and t["to"]["hash"].lower() == dev and int(t["value"]) > 0]
        if funding:
            f = funding[-1]
            src = f["from"]["hash"]
            info = fetch(f"{blockscout}/addresses/{src}")
            print(f"funded by {src}  {int(f['value']) / 1e18:.4f} ETH at {f['timestamp']}"
                  f"  (funder holds {int(info.get('coin_balance') or 0) / 1e18:,.1f} ETH,"
                  f" tags {[t.get('display_name') for t in info.get('public_tags') or []]})")
        print(f"dev tx history (newest first, {len(txs)} shown):")
        for t in txs[:15]:
            print(f"  {t['timestamp']}  {t['from']['hash'][:10]} -> {(t['to'] or {}).get('hash', '')[:10]}"
                  f"  {t.get('method') or '-'}  {int(t['value']) / 1e18:.4f} ETH")
    else:
        print(f"funding   not checked: {blockscout or 'no explorer API for this chain'}")

    print(f"\ntransfers {n}, distinct addresses {len(addrs)} (full history since mint)")
    if team:
        hits = sorted(addrs & team)
        print(f"team wallets checked {len(team)}, hits {len(hits)}: {hits}")
        with ThreadPoolExecutor(8) as pool:
            for t, b in zip(sorted(team), pool.map(balance, sorted(team))):
                print(f"  {t} holds {b / 1e18:,.0f}")


if __name__ == "__main__":
    main()
