"""Pre-entry read in ~5 seconds: the facts that most often turn a believed 3 into a 1.

    python3 quick.py <CA>

All checks run at once and avoid Helius's rate-limited enhanced API:
  market      chain, MC, liquidity, age, last hour (DexScreener)
  copycat     an older token with the same name and more liquidity = this is probably the copy
  X           who is posting the CA: real accounts or bot/call farms; the project account's age and size
  deployer    Solana: creator, wallet age and tx count, % held. EVM (Etherscan): creator, % held,
              its funder, and whether that funder is a serial launcher (disperse batches, repeat launches)
Lines starting with !! are the ones to read before sizing. The deep DD (ca_check, devwatch, fomo_share) comes after.
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from env import key as env_key

UA = {"User-Agent": "Mozilla/5.0"}
CHAIN_IDS = {"robinhood": 4663, "base": 8453, "ethereum": 1}  # Etherscan v2 free tier
RPCS = {"robinhood": "https://rpc.mainnet.chain.robinhood.com", "base": "https://mainnet.base.org",
        "ethereum": "https://ethereum-rpc.publicnode.com", "bsc": "https://bsc-dataseed.binance.org"}


def get(url, headers=UA, body=None):
    for attempt in range(4):  # RPCs and Etherscan throttle in bursts; a short retry beats a missing line
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, body, headers), timeout=15))
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 3:
                raise
            time.sleep(0.4 * (attempt + 1))


def ago(ts):
    h = (time.time() - ts) / 3600
    return f"{h * 60:.0f}m" if h < 1 else f"{h:.1f}h" if h < 48 else f"{h / 24:.0f}d"


def market(ca):
    pairs = get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}").get("pairs") or []
    if not pairs:
        return None
    p = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
    born = min(x.get("pairCreatedAt") or 9e15 for x in pairs) / 1000
    x = next((s["url"].rstrip("/").split("/")[-1] for s in (p.get("info") or {}).get("socials", []) if s.get("type") == "twitter"), None)
    return {"chain": p["chainId"], "symbol": p["baseToken"]["symbol"], "name": p["baseToken"]["name"], "mc": p.get("marketCap") or 0,
            "liq": (p.get("liquidity") or {}).get("usd") or 0, "born": born, "h1": (p.get("priceChange") or {}).get("h1"), "x": x}


def copies(m, ca):
    hits = get("https://api.dexscreener.com/latest/dex/search?" + urllib.parse.urlencode({"q": m["name"]})).get("pairs") or []
    out = {}
    for p in hits:
        b = p["baseToken"]
        if b["address"].lower() == ca.lower() or b["symbol"].lower() != m["symbol"].lower():
            continue
        liq = (p.get("liquidity") or {}).get("usd") or 0
        if liq >= 5000 and liq > out.get(b["address"], {}).get("liq", 0):
            info = p.get("info") or {}
            out[b["address"]] = {"chain": p["chainId"], "liq": liq, "mc": p.get("marketCap") or 0, "born": (p.get("pairCreatedAt") or 0) / 1000,
                                 "socials": bool(info.get("websites") or info.get("socials"))}
    return sorted(out.items(), key=lambda kv: kv[1]["born"])


def socialdata(path, **params):
    key = env_key("SOCIALDATA_API_KEY")
    return get(f"https://api.socialdata.tools/twitter/{path}?" + urllib.parse.urlencode(params),
               {**UA, "Authorization": f"Bearer {key}", "Accept": "application/json"})


def x_read(ca, handle):
    """SocialData search: cheaper than the X API and covers more than 7 days."""
    tweets = socialdata("search", query=ca, type="Latest").get("tweets", [])
    fol = sorted({(t["user"]["followers_count"], t["user"]["screen_name"]) for t in tweets})
    proj = None
    if handle:
        u = socialdata(f"user/{handle}")
        if u.get("screen_name"):
            proj = {"handle": handle, "followers": u["followers_count"], "joined": time.strftime("%Y-%m-%d", time.strptime(u["created_at"][:19], "%Y-%m-%dT%H:%M:%S")),
                    "last": f"{u.get('statuses_count', '?')} posts", "ca_in_bio": ca.lower() in (u.get("description") or "").lower()}
    return {"posts": len(tweets), "authors": len(fol), "small": sum(1 for f, _ in fol if f < 1000), "top": fol[-3:][::-1], "project": proj}


def sol_deployer(mint):
    from ca_check import deployer
    from sol import rpc, signatures
    dev, how = deployer(mint)
    if not dev:
        return {"note": how}
    sigs, capped = signatures(dev, 3000)
    bal = sum(float(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"] or 0)
              for a in rpc("getTokenAccountsByOwner", [dev, {"mint": mint}, {"encoding": "jsonParsed"}])["value"])
    supply = float(rpc("getTokenSupply", [mint])["value"]["uiAmount"])
    return {"dev": dev, "txs": f"{len(sigs)}{'+' if capped else ''}", "age": ago(sigs[-1]["blockTime"]) if sigs else "?",
            "held": bal / supply * 100 if supply else 0}


def evm_deployer(ca, chain):
    if chain not in CHAIN_IDS:
        return {"note": f"deployer not checked on {chain} (no free explorer API)"}
    key = env_key("ETHERSCAN_API_KEY")
    es = lambda q: get(f"https://api.etherscan.io/v2/api?chainid={CHAIN_IDS[chain]}&{q}&apikey={key}").get("result")
    dev = es(f"module=contract&action=getcontractcreation&contractaddresses={ca}")[0]["contractCreator"]
    call = lambda data: get(RPCS[chain], {"Content-Type": "application/json", **UA}, json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": ca, "data": data}, "latest"]}).encode())["result"]
    held = int(call("0x70a08231" + "0" * 24 + dev[2:]), 16) / int(call("0x18160ddd"), 16) * 100
    txs = es(f"module=account&action=txlist&address={dev}&sort=asc") or []
    internal = es(f"module=account&action=txlistinternal&address={dev}&sort=asc") or []
    launches = sum(1 for t in txs if "launch" in (t.get("functionName") or "").lower() and t["from"].lower() == dev.lower())
    inbound = sorted([t for t in txs + internal if t["to"].lower() == dev.lower() and int(t["value"]) > 0], key=lambda t: int(t["timeStamp"]))
    funder, serial = None, None
    if inbound:
        f = inbound[0]
        # funding through a disperse contract: the real funder is whoever called it
        funder = get_tx_from(chain, f["hash"]) if f in internal else f["from"]
        ft = es(f"module=account&action=txlist&address={funder}&sort=desc&page=1&offset=1000") or []
        serial = {"txs": len(ft), "disperses": sum(1 for t in ft if (t.get("functionName") or "").lower().startswith(("airdrop", "disperse", "multisend")))}
    return {"dev": dev, "held": held, "txs": len(txs), "launches": launches, "funder": funder, "serial": serial}


def get_tx_from(chain, h):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionByHash", "params": [h]}).encode()
    return get(RPCS[chain], {"Content-Type": "application/json", **UA}, body)["result"]["from"]


def main(ca):
    t0 = time.time()
    m = market(ca)
    if not m:
        return print(f"{ca}: no pair on DexScreener")
    with ThreadPoolExecutor(4) as pool:
        cp = pool.submit(copies, m, ca)
        xr = pool.submit(x_read, ca, m["x"])
        dv = pool.submit(sol_deployer if m["chain"] == "solana" else evm_deployer, ca, *([] if m["chain"] == "solana" else [m["chain"]]))
        results = {}
        for name, f in (("copies", cp), ("x", xr), ("dev", dv)):
            try:
                results[name] = f.result()
            except Exception as e:
                results[name] = {"error": str(e)[:80]}
    out = [f"{m['symbol']} ({m['name']}) on {m['chain']}  MC ${m['mc']:,.0f}  liq ${m['liq']:,.0f}  age {ago(m['born'])}  1h {m['h1']}%"]

    cps = results["copies"]
    cps = cps if isinstance(cps, list) else []
    # a same-ticker token with no site or socials is a ticker snipe, never the original
    bigger = [kv for kv in cps if kv[1]["born"] < m["born"] and kv[1]["mc"] > m["mc"] and kv[1]["socials"]]
    if bigger:  # older, bigger by market cap, with its own project: this one is probably the copy
        a, o = bigger[0]
        out.append(f"!! COPY: older, bigger {m['symbol']}: {a[:10]}… on {o['chain']}, {ago(o['born'])} old, MC ${o['mc']:,.0f}")
    elif cps:
        out.append(f"Same name: {len(cps)} other {m['symbol']} token(s), none older and bigger with its own site or X")

    x = results["x"]
    if "error" in x:
        out.append(f"!! X not checked: {x['error']}")
    else:
        top = ", ".join(f"@{u} {f:,}" for f, u in x["top"]) or "none"
        out.append(f"X: {x['posts']} posts from {x['authors']} accounts, {x['small']} under 1k followers. Biggest: {top}")
        if x["authors"] and x["small"] == x["authors"]:
            out.append("!! nobody over 1k followers is posting the CA: bots and call farms only")
        p = x["project"]
        if p:
            out.append(f"Project @{p['handle']}: {p['followers']:,} followers, joined {p['joined']}, {p['last']}"
                       + ("" if p["ca_in_bio"] else ", CA not in bio"))
            if p["followers"] < 500:
                out.append(f"!! project account has {p['followers']} followers")

    d = results["dev"]
    if "error" in d or "note" in d:
        out.append(f"Deployer: {d.get('error') or d.get('note')}")
    elif m["chain"] == "solana":
        out.append(f"Deployer {d['dev'][:8]}…: {d['txs']} txs, wallet {d['age']} old, holds {d['held']:.1f}%")
    else:
        out.append(f"Deployer {d['dev'][:10]}…: {d['txs']} txs, {d['launches']} launches, holds {d['held']:.1f}%")
        if d["serial"]:
            s = d["serial"]
            out.append(f"Funder {d['funder'][:10]}…: {s['txs']}{'+' if s['txs'] >= 1000 else ''} txs, {s['disperses']} disperse batches")
            if s["disperses"] >= 10:
                out.append("!! SERIAL LAUNCHER: the funder seeds fresh wallets in batches")
    if d.get("held", 0) >= 10:
        out.append(f"!! dev holds {d['held']:.1f}% against ${m['liq']:,.0f} liquidity")
    print("\n".join(out) + f"\n[{time.time() - t0:.1f}s]")


if __name__ == "__main__":
    main(sys.argv[1])
