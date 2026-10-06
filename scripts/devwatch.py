"""Dev-cluster sell watcher for a Solana token.

python3 devwatch.py <mint> [--slots 2] [--depth 3] [--add addr,addr] [--once]

1. Seeds: the deployer plus every wallet that bought in the first --slots slots after the create
   (the first bundle and the snipers beside it).
2. Tree: from each seed, follow SOL >= 0.05 in and out and every transfer of this token out, to
   --depth hops. Wallets with 1000+ txs (exchanges, bots, services) are kept as leaves, never expanded.
3. Watch: one getProgramAccounts call per poll gives every holder. When a tree wallet's balance
   drops, its newest txs say what happened:
     SELL      it got SOL back in the same tx
     TRANSFER  the tokens went to another wallet, which joins the tree (and alerts on its own sells)
     MOVED     the tokens went to a program account (a lock, an LP) with no SOL back
   The tree re-expands every 10 minutes, so wallets the cluster funds later are picked up.

Alerts print, and also go to ntfy.sh/<NTFY_TOPIC> when that env var is set. Tree and events: data/devwatch/<mint>.json.
"""
import argparse
import json
import os
import time
import urllib.request

from ca_check import deployer as ca_deployer
from fomo_share import on_curve
from sol import b58decode, enhanced, pda, rpc, signatures

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_SOL = 0.05
BUSY = 1000
META = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"  # Metaplex token metadata
PASS = 5
POLL, REEXPAND = 20, 600


def notify(title, msg, url):
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        req = urllib.request.Request(f"https://ntfy.sh/{topic}", msg.encode(), {"Title": title, "Click": url, "Priority": "high"})
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass


def create_slot(mint):
    """Slot and time of the create. The Metaplex metadata account is written once at launch, so its oldest
    tx is the create even when the mint itself has 100k+ txs. Token-2022 mints have none: page the mint."""
    sigs = rpc("getSignaturesForAddress", [pda([b"metadata", b58decode(META), b58decode(mint)], META), {"limit": 1000}])
    if not sigs:
        sigs, _ = signatures(mint, 1_000_000)
    return sigs[-1]["slot"], sigs[-1]["blockTime"]


def first_buyers(mint, slots):
    """Deployer + wallets whose balance of the mint rose in the first `slots` slots after the create,
    with how many tokens each one got there."""
    s0, created = create_slot(mint)
    deployer = ca_deployer(mint)[0]
    seeds, bought = {deployer: "deployer"}, {}
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
    return seeds, bought, created


def txcount(addr):
    return len(rpc("getSignaturesForAddress", [addr, {"limit": BUSY}]))


def node(parent, how, depth, addr):
    """A pass-through wallet (<= PASS txs, the hop-to-hide pattern) costs no depth."""
    n = txcount(addr)
    return {"parent": parent, "how": how, "depth": depth + (n > PASS), "busy": n >= BUSY}


def links(addr, mint, limit=100):
    """(counterparty, how) for SOL >= MIN_SOL in/out and this token out, from addr's newest txs."""
    out = []
    for t in enhanced(f"addresses/{addr}/transactions", limit=limit):
        for x in t.get("nativeTransfers", []):
            if x["amount"] < MIN_SOL * 1e9:
                continue
            if x["toUserAccount"] == addr and x["fromUserAccount"] != addr:
                out.append((x["fromUserAccount"], f"sent {x['amount'] / 1e9:.2f} SOL to"))
            elif x["fromUserAccount"] == addr and x["toUserAccount"] != addr:
                out.append((x["toUserAccount"], f"got {x['amount'] / 1e9:.2f} SOL from"))
        for x in t.get("tokenTransfers", []):
            if x["mint"] == mint and x["fromUserAccount"] == addr and x["toUserAccount"] not in ("", addr):
                out.append((x["toUserAccount"], f"got {x['tokenAmount']:,.0f} tokens from"))
    return [(a, how) for a, how in out if on_curve(a)]


def expand(tree, mint, depth):
    """Breadth-first from every non-busy node below depth. tree: addr -> {parent, how, depth, busy}."""
    frontier = [a for a, n in tree.items() if not n["busy"] and n["depth"] < depth]
    while frontier:
        nxt = []
        for a in frontier:
            for b, how in links(a, mint):
                if b in tree:
                    continue
                tree[b] = node(a, f"{how} {a[:6]}", tree[a]["depth"], b)
                if not tree[b]["busy"] and tree[b]["depth"] < depth:
                    nxt.append(b)
        frontier = nxt


def holders(mint):
    program = rpc("getAccountInfo", [mint, {"encoding": "base64"}])["value"]["owner"]
    filters = [{"memcmp": {"offset": 0, "bytes": mint}}] + ([{"dataSize": 165}] if program.startswith("Tokenkeg") else [])
    out = {}
    for t in rpc("getProgramAccounts", [program, {"encoding": "jsonParsed", "filters": filters}]):
        i = t["account"]["data"]["parsed"]["info"]
        out[i["owner"]] = out.get(i["owner"], 0) + float(i["tokenAmount"]["uiAmount"] or 0)
    return out


def classify(addr, mint, since, limit=20):
    """What addr did with the mint since `since`: [(kind, tokens, sol, counterparty)]."""
    events = []
    for t in enhanced(f"addresses/{addr}/transactions", limit=limit):
        if t["timestamp"] < since:
            break
        sent = [x for x in t["tokenTransfers"] if x["mint"] == mint and x["fromUserAccount"] == addr]
        if not sent:
            continue
        tokens = sum(x["tokenAmount"] for x in sent)
        sol = next((d["nativeBalanceChange"] for d in t["accountData"] if d["account"] == addr), 0) / 1e9
        sol += sum(x["tokenAmount"] for x in t["tokenTransfers"]
                   if x["mint"] == "So11111111111111111111111111111111111111112" and x["toUserAccount"] == addr)
        to = sent[0]["toUserAccount"]
        kind = "SELL" if sol > 0.001 else "TRANSFER" if on_curve(to) else "MOVED"
        events.append((kind, tokens, sol, to))
    return events


def short(a):
    return f"{a[:4]}…{a[-4:]}"


def print_tree(tree, held, supply):
    kids = {}
    for a, n in tree.items():
        kids.setdefault(n["parent"], []).append(a)

    def walk(a, pad):
        n = tree[a]
        pct = held.get(a, 0) / supply * 100
        tag = n["how"] + (" [busy]" if n["busy"] else "")
        print(f"{pad}{short(a)}  {pct:5.2f}%  {tag}")
        for b in sorted(kids.get(a, []), key=lambda b: -held.get(b, 0)):
            walk(b, pad + "  ")

    for root in sorted(kids.get(None, []), key=lambda b: -held.get(b, 0)):
        walk(root, "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mint")
    ap.add_argument("--slots", type=int, default=2)
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--add", default="", help="extra wallets to treat as seeds, comma-separated")
    ap.add_argument("--once", action="store_true", help="build and print the tree, then exit")
    ap.add_argument("--quick", action="store_true", help="~15s: deployer + first bundle, got at launch vs hold now, no tree")
    a = ap.parse_args()

    path = f"{HERE}/data/devwatch/{a.mint}.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    state = json.load(open(path)) if os.path.exists(path) else {"tree": {}, "events": []}
    tree = state["tree"]
    if not tree:
        seeds, bought, state["created"] = first_buyers(a.mint, a.slots)
        for s, how in seeds.items():
            tree[s] = node(None, how, -1, s) | {"depth": 0, "bought": bought.get(s, 0)}
    if a.quick:
        supply = float(rpc("getTokenSupply", [a.mint])["value"]["uiAmount"])
        held = holders(a.mint)
        rows = sorted(tree.items(), key=lambda kv: -kv[1].get("bought", 0))
        got = sum(n.get("bought", 0) for _, n in rows) / supply * 100
        now = sum(held.get(w, 0) for w, _ in rows) / supply * 100
        print(f"First bundle: {len(rows)} wallets got {got:.2f}% at launch, hold {now:.2f}% now")
        for w, n in rows:
            print(f"  {short(w)}  got {n.get('bought', 0) / supply * 100:5.2f}%  holds {held.get(w, 0) / supply * 100:5.2f}%  {n['how']}")
        return
    for s in filter(None, a.add.split(",")):
        tree.setdefault(s, node(None, "added", -1, s) | {"depth": 0})
    t0 = time.time()
    expand(tree, a.mint, a.depth)
    supply = float(rpc("getTokenSupply", [a.mint])["value"]["uiAmount"])
    held = holders(a.mint)
    print_tree(tree, held, supply)
    total = sum(held.get(w, 0) for w in tree) / supply * 100
    print(f"\n{len(tree)} wallets, {total:.2f}% of supply, built in {time.time() - t0:.0f}s -> {path}")
    got = sum(n.get("bought", 0) for n in tree.values()) / supply * 100
    seeds = [w for w, n in tree.items() if n["parent"] is None]
    out = [w for w in seeds if held.get(w, 0) < tree[w].get("bought", 0) * 0.5]
    print(f"First bundle: {len(seeds)} wallets got {got:.2f}% at launch; the whole tree holds {total:.2f}% now; "
          f"{len(out)} of {len(seeds)} seeds have dumped or moved over half")
    json.dump(state, open(path, "w"), indent=1)
    if a.once:
        return

    url = f"https://dexscreener.com/solana/{a.mint}"
    last, last_expand = time.time(), time.time()
    while True:
        time.sleep(POLL)
        try:
            now_held = holders(a.mint)
            for w in [w for w in tree if now_held.get(w, 0) < held.get(w, 0) - 1]:
                for kind, tokens, sol, to in classify(w, a.mint, last - POLL):
                    pct = tokens / supply * 100
                    n = tree[w]
                    line = f"{short(w)} ({n['how']}) {kind} {pct:.2f}% of supply"
                    line += f" for {sol:.2f} SOL" if kind == "SELL" else f" to {short(to)}"
                    if kind == "TRANSFER" and to not in tree:
                        tree[to] = node(w, f"got {tokens:,.0f} tokens from {w[:6]}", n["depth"], to)
                    left = sum(now_held.get(x, 0) for x in tree) / supply * 100
                    notify(f"DEV CLUSTER {kind}", f"{line}. Cluster now holds {left:.2f}%.", url)
                    state["events"].append({"time": int(time.time()), "wallet": w, "kind": kind, "pct": pct, "sol": sol, "to": to})
                    print(time.strftime("%H:%M:%S"), line)
            held, last = now_held, time.time()
            if time.time() - last_expand > REEXPAND:
                expand(tree, a.mint, a.depth + 1)
                last_expand = time.time()
            json.dump(state, open(path, "w"), indent=1)
        except Exception as e:  # RPC hiccups: keep watching
            print(time.strftime("%H:%M:%S"), "poll failed:", e)


if __name__ == "__main__":
    main()
