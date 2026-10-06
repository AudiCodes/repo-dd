"""One Solana client for every script, so Helius limits never stall a check.

Measured on a Helius developer key: RPC takes 30+ parallel calls; the enhanced API (/v0) holds
2/s sustained (bursts of ~5 pass); batch POSTs are refused. So:
  rpc()        Helius, and on a 429 the same call goes to the public mainnet RPC instead of waiting.
  enhanced()   token bucket (burst 5, then 2/s) across all threads and processes (file lock), so it never trips the limit.
  signatures() plain-RPC paging, 1000 per call: use it for counts and the oldest tx, never enhanced pages.
"""
import fcntl
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

from env import key

KEY = key("HELIUS_API_KEY")
HELIUS = f"https://mainnet.helius-rpc.com/?api-key={KEY}"
PUBLIC = "https://api.mainnet-beta.solana.com"
ENHANCED_PER_SEC, BURST = 2, 5

PACE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", ".enhanced_pace")  # shared by every process
os.makedirs(os.path.dirname(PACE_FILE), exist_ok=True)
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
P = 2 ** 255 - 19
D = -121665 * pow(121666, P - 2, P) % P


def _slot():
    """Reserve the next enhanced-API slot across all processes (the key's 2/s is shared)."""
    with open(PACE_FILE, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        nxt = float(f.read() or 0)
        now = time.time()
        nxt = max(nxt, now - BURST / ENHANCED_PER_SEC) + 1 / ENHANCED_PER_SEC
        f.seek(0), f.truncate(), f.write(str(nxt))
    return nxt - 1 / ENHANCED_PER_SEC - now


def _open(url, body=None):
    req = urllib.request.Request(url, json.dumps(body).encode() if body else None,
                                 {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def rpc(method, params):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    for attempt in range(4):
        for url in (HELIUS, PUBLIC):
            try:
                r = _open(url, body)
                if "error" not in r or r["error"].get("code") != 429:
                    return r.get("result")
            except urllib.error.HTTPError as e:
                if e.code != 429:
                    raise
        time.sleep(0.3 * (attempt + 1))
    raise RuntimeError(f"{method}: rate limited on Helius and public RPC")


def enhanced(path, **params):
    """GET api.helius.xyz/v0/<path>, paced so parallel callers stay under the limit."""
    url = f"https://api.helius.xyz/v0/{path}?api-key={KEY}" + "".join(f"&{k}={v}" for k, v in params.items() if v)
    for attempt in range(7):
        wait = _slot()
        if wait > 0:
            time.sleep(wait)
        try:
            return _open(url)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 6:
                raise
            time.sleep(0.5 * 2 ** attempt)  # other processes share the key


def signatures(address, cap=100_000):
    """Newest first, 1000 per RPC call. Returns (sigs, capped)."""
    out, before = [], None
    while len(out) < cap:
        page = rpc("getSignaturesForAddress", [address, {"limit": 1000, **({"before": before} if before else {})}])
        out += page
        if len(page) < 1000:
            return out, False
        before = page[-1]["signature"]
    return out, True


def b58decode(s):
    n = 0
    for ch in s:
        n = n * 58 + B58.index(ch)
    raw = n.to_bytes(32, "big") if n else b"\0" * 32
    pad = len(s) - len(s.lstrip("1"))
    return b"\0" * pad + raw[-(32 - pad):] if pad else raw


def b58encode(b):
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


def on_curve(blob):
    """Is this 32-byte value a valid ed25519 point? Wallets are; PDAs (pools, vaults) are not."""
    y = int.from_bytes(blob, "little") & ((1 << 255) - 1)
    if y >= P:
        return False
    u, v = (y * y - 1) % P, (D * y * y + 1) % P
    x2 = u * pow(v, P - 2, P) % P
    return x2 == 0 or pow(x2, (P - 1) // 2, P) == 1


def pda(seeds, program):
    for bump in range(255, -1, -1):
        h = hashlib.sha256(b"".join(seeds) + bytes([bump]) + b58decode(program) + b"ProgramDerivedAddress").digest()
        if not on_curve(h):
            return b58encode(h)
