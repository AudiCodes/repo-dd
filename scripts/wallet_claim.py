"""'Deployed by <famous person>'s wallet': is it really them, or someone holding their old key?

    python3 wallet_claim.py <deployer> [--chain robinhood|base|ethereum] [--person <x handle>] [--mint-block N]

Signing from an address proves the KEY signed, not the person. Everything here
tests who holds the key today:
  1. EIP-7702 on every chain: delegated to different unknown contracts = the key is out, sweepers own it.
  2. Etherscan history on the token's chain: funder, what the deployer did, decoded function names
     (sweep*/withdrawNative = sweeper bots), and whether funding, launch and inbound calls land in the same second.
  3. Balances and nonces per chain: dust everywhere + a handful of txs = an old test wallet, not a live one.
  4. Where the address is tied to the person publicly: full-archive X search (who posted it, when) and
     GitHub code search (course code, repos). Old public ties explain why shills say "it's his".
  5. The person today: when they last posted, and whether they mention the token.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from env import key as env_key

HERE = os.path.dirname(os.path.abspath(__file__))
CHAINS = {"ethereum": (1, "https://ethereum-rpc.publicnode.com"), "base": (8453, "https://mainnet.base.org"),
          "robinhood": (4663, "https://rpc.mainnet.chain.robinhood.com")}
SWEEPER = ("sweep", "withdrawnative", "drain", "rescue", "withdrawall", "forward")
UA = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}


def fetch(url, data=None, headers=UA):
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=20))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}


def rpc(chain, method, params):
    return fetch(CHAINS[chain][1], json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()).get("result")


def chain_state(chain, a):
    code = rpc(chain, "eth_getCode", [a, "latest"]) or "0x"
    return chain, {"delegate": "0x" + code[8:48] if code.startswith("0xef0100") else None, "has_code": code != "0x",
                   "nonce": int(rpc(chain, "eth_getTransactionCount", [a, "latest"]) or "0x0", 16),
                   "eth": int(rpc(chain, "eth_getBalance", [a, "latest"]) or "0x0", 16) / 1e18}


def etherscan(chain, a, action):
    key = env_key("ETHERSCAN_API_KEY")
    url = (f"https://api.etherscan.io/v2/api?chainid={CHAINS[chain][0]}&module=account&action={action}"
           f"&address={a}&sort=asc&apikey={key}")
    r = fetch(url)
    return r.get("result") if isinstance(r.get("result"), list) else []


def x_archive(a):
    """Every public post of the address, oldest first: X API full archive, then SocialData for anything older."""
    bearer = env_key("X_BEARER_TOKEN")
    out = []
    for q in (a, a.lower()):
        r = fetch("https://api.x.com/2/tweets/search/all?" + urllib.parse.urlencode(
            {"query": q, "max_results": 100, "tweet.fields": "created_at", "expansions": "author_id"}),
            headers={"Authorization": f"Bearer {bearer}"})
        users = {u["id"]: u["username"] for u in r.get("includes", {}).get("users", [])}
        out += [(t["created_at"][:10], users.get(t["author_id"], "?"), t["text"]) for t in r.get("data", [])]
    sd = env_key("SOCIALDATA_API_KEY")
    r = fetch("https://api.socialdata.tools/twitter/search?" + urllib.parse.urlencode(
        {"query": f"{a} until:{time.strftime('%Y-%m-%d', time.gmtime(time.time() - 30 * 86400))}", "type": "Latest"}),
        headers={"Authorization": f"Bearer {sd}"})
    out += [(t["tweet_created_at"][:10], t["user"]["screen_name"], t["full_text"]) for t in r.get("tweets", [])]
    seen, rows = set(), []
    for d, u, t in sorted(out):
        if (d, u, t[:60]) not in seen:
            seen.add((d, u, t[:60]))
            rows.append((d, u, t))
    return rows


def github(a):
    out = subprocess.run(["gh", "api", "-X", "GET", "search/code", "-f", f"q={a[2:]}",
                          "--jq", ".items[]|.repository.full_name+\" \"+.path"], capture_output=True, text=True)
    return out.stdout.split("\n")[:8]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("address")
    ap.add_argument("--chain", default="robinhood", choices=CHAINS)
    ap.add_argument("--person")
    a = ap.parse_args()
    addr, t0 = a.address, time.time()
    with ThreadPoolExecutor(12) as pool:
        states = [pool.submit(chain_state, c, addr) for c in CHAINS]
        txs, internal = pool.submit(etherscan, a.chain, addr, "txlist"), pool.submit(etherscan, a.chain, addr, "txlistinternal")
        posts, repos = pool.submit(x_archive, addr), pool.submit(github, addr)
        person = pool.submit(subprocess.run, [sys.executable, f"{HERE}/xcheck.py", "--who", a.person], capture_output=True, text=True) if a.person else None
        states = dict(f.result() for f in states)
        txs, internal, posts, repos = txs.result(), internal.result(), posts.result(), repos.result()

    print(f"WALLET {addr}")
    delegates = {c: s["delegate"] for c, s in states.items() if s["delegate"]}
    for c, s in states.items():
        print(f"  {c:9s} nonce {s['nonce']:>4}  {s['eth']:.6f} ETH  " +
              (f"7702 -> {s['delegate']}" if s["delegate"] else "contract" if s["has_code"] else "plain EOA"))
    if len(set(delegates.values())) > 1:
        print("  !! delegated to DIFFERENT contracts on different chains: several parties hold this key")

    print(f"\nON {a.chain.upper()} ({len(txs)} txs, oldest first)")
    blocks = {}
    for t in txs:
        fn = (t.get("functionName") or t.get("methodId") or "").split("(")[0]
        mine = t["from"].lower() == addr.lower()
        flag = "  <- SWEEPER" if not mine and any(k in fn.lower() for k in SWEEPER) else ""
        blocks.setdefault(t["timeStamp"], []).append(fn or "transfer")  # same second: RH blocks are sub-second
        print(f"  {time.strftime('%m-%d %H:%M:%S', time.gmtime(int(t['timeStamp'])))}  "
              f"{'OUT' if mine else 'IN '} {(t['to'] if mine else t['from'])[:12]}  {int(t['value']) / 1e18:.4f}  {fn}{flag}")
    for t in internal[:5]:
        print(f"  {time.strftime('%m-%d %H:%M:%S', time.gmtime(int(t['timeStamp'])))}  internal {t['from'][:12]} -> {t['to'][:12]}  {int(t['value']) / 1e18:.6f}")
    busy = {b: f for b, f in blocks.items() if len(f) >= 3}
    for b, f in busy.items():
        print(f"  !! {len(f)} txs in the same second ({', '.join(f)}) at {time.strftime('%H:%M:%SZ', time.gmtime(int(b)))}: "
              "funded, used and swept at once = someone racing sweeper bots for a leaked key")
    first_in = next((t for t in txs if t["to"].lower() == addr.lower() and int(t["value"]) > 0), None)
    if first_in:
        print(f"  funder: {first_in['from']}")

    print(f"\nPUBLIC TIES ({len(posts)} X posts with this address)")
    for d, u, t in posts[:12]:
        print(f"  {d}  @{u}: {t.replace(chr(10), ' ')[:90]}")
    for r in filter(None, repos):
        print(f"  github: {r}")

    if person:
        print(f"\nTHE PERSON TODAY\n{person.result().stdout.rstrip()}")
    print(f"\n[{time.time() - t0:.1f}s]")


if __name__ == "__main__":
    main()
