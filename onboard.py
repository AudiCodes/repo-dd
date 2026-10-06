"""Set up repo-dd: asks for each missing API key, tests every key with one live call, writes .env.

    python3 onboard.py

Run it again any time as a health check. Keys already in .env or the environment are tested, not asked for.
"""
import getpass
import json
import os
import shutil
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(ROOT, ".env")
UA = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
KEYS = [  # name, required, where to get it, what it unlocks
    ("HELIUS_API_KEY", True, "https://dashboard.helius.dev (free)", "every Solana check"),
    ("SOCIALDATA_API_KEY", True, "https://socialdata.tools (pay as you go, ~$0.0002 per item)", "X posts, articles, who posts the CA"),
    ("ETHERSCAN_API_KEY", False, "https://etherscan.io/apis (free)", "EVM deployer history on Ethereum and Robinhood Chain"),
    ("X_BEARER_TOKEN", False, "https://developer.x.com (pay per use)", "xcheck.py and wallet_claim.py"),
]


def get(url, body=None, headers=UA):
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(url, body, headers), timeout=20))
    except urllib.error.HTTPError as e:
        return {"http_error": e.code}


def rpc(key, method, params=None):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}).encode()
    return get(f"https://mainnet.helius-rpc.com/?api-key={key}", body)


def test(name, key):
    """-> (ok, note)"""
    if name == "HELIUS_API_KEY":
        if not isinstance(rpc(key, "getSlot").get("result"), int):
            return False, "Helius rejected the key"
        fast = rpc(key, "getTransactionsForAddress", ["So11111111111111111111111111111111111111112", {"limit": 1}])
        return True, "fast history path on" if "result" in fast else "fast history path off on this plan: checks still run, slower"
    if name == "SOCIALDATA_API_KEY":
        r = get("https://api.socialdata.tools/twitter/user/x", headers={**UA, "Authorization": f"Bearer {key}"})
        return ("id_str" in r), "ok" if "id_str" in r else f"SocialData said {r.get('http_error') or r.get('message')}"
    if name == "ETHERSCAN_API_KEY":
        r = get(f"https://api.etherscan.io/v2/api?chainid=1&module=stats&action=ethprice&apikey={key}")
        return r.get("status") == "1", "ok" if r.get("status") == "1" else f"Etherscan said {r.get('result')}"
    if name == "X_BEARER_TOKEN":
        r = get("https://api.x.com/2/users/by/username/x", headers={"Authorization": f"Bearer {key}"})
        if "data" in r:
            return True, "ok"
        return False, "out of credits (402): top up at developer.x.com" if r.get("http_error") == 402 else f"X said {r.get('http_error')}"


def load():
    env = {}
    if os.path.exists(ENV):
        for line in open(ENV):
            k, _, v = line.partition("=")
            if v.strip():
                env[k.strip()] = v.strip().strip("'\"")
    return env


def main():
    if sys.version_info < (3, 9):
        sys.exit("Python 3.9 or newer is needed")
    env = load()
    print("repo-dd setup\n")
    for name, required, where, unlocks in KEYS:
        key = os.environ.get(name) or env.get(name)
        if not key:
            print(f"{name}  ({'required' if required else 'optional'}: {unlocks})\n  get one at {where}")
            key = getpass.getpass("  paste it, or press Enter to skip: ").strip()
            if not key:
                print("  skipped\n")
                continue
        ok, note = test(name, key)
        print(f"  {'✓' if ok else '✗'} {name}: {note}\n")
        if ok:
            env[name] = key
    with open(ENV, "w") as f:
        f.writelines(f"{k}={v}\n" for k, v in env.items())
    os.chmod(ENV, 0o600)

    for tool, why in (("gh", "repo and code-search checks"), ("dig", "website CNAME check")):
        print(f"  {'✓' if shutil.which(tool) else '-'} {tool}{'' if shutil.which(tool) else f' not found: {why} will be skipped'}")
    missing = [n for n, req, *_ in KEYS if req and n not in env]
    skill = os.path.expanduser("~/.claude/skills/repo-dd")
    print(f"  {'✓' if os.path.realpath(skill) == ROOT else '-'} installed at {skill}"
          + ("" if os.path.realpath(skill) == ROOT else f"\n    run: ln -s {ROOT} {skill}"))
    print("\nReady. Send Claude a CA, an x.com link or a project site." if not missing
          else f"\nStill needed: {', '.join(missing)}. Run python3 onboard.py again once you have them.")


if __name__ == "__main__":
    main()
