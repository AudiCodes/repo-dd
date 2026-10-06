"""X facts for token DD, all calls in parallel on the X API (~0.3-0.8s total).

    python3 xcheck.py --who devhandle,projecthandle --ca <CA> [--q "project chain"]

--who  for each handle: profile, when they last posted, their last 10 posts
--ca   who posted the contract address in the last 7 days, and when
--q    any extra search (last 7 days)

Bearer: X_BEARER_TOKEN (env or .env). Pay-per-use: $0.010/profile, $0.005/post.
"""
import argparse
import calendar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from env import key

API = "https://api.x.com/2"
TOKEN = key("X_BEARER_TOKEN")


def get(path, **params):
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(2):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"}), timeout=15))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                time.sleep(1)
                continue
            return {"error": f"HTTP {e.code}: {e.read()[:150].decode(errors='ignore')}"}


def when(tweet_id):
    """Snowflake id -> UTC time, so a profile lookup alone dates the last post."""
    return time.strftime("%Y-%m-%d %H:%MZ", time.gmtime(((int(tweet_id) >> 22) + 1288834974657) / 1000))


def ago(ts):
    d = time.time() - ts
    return f"{d / 86400:.0f}d ago" if d > 86400 else f"{d / 3600:.1f}h ago" if d > 3600 else f"{d / 60:.0f}m ago"


def person(handle):
    u = get(f"/users/by/username/{handle}", **{"user.fields": "most_recent_tweet_id,created_at,public_metrics,description,verified"})
    if "data" not in u:
        return handle, u, None
    posts = get(f"/users/{u['data']['id']}/tweets", max_results=10, **{"tweet.fields": "created_at", "exclude": "retweets"})
    return handle, u, posts


def search(q):
    return q, get("/tweets/search/recent", query=q, max_results=10, expansions="author_id",
                  **{"tweet.fields": "created_at", "user.fields": "public_metrics"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--who", default="")
    ap.add_argument("--ca")
    ap.add_argument("--q", action="append", default=[])
    a = ap.parse_args()
    t0 = time.time()
    handles = [h.lstrip("@") for h in a.who.split(",") if h]
    queries = ([a.ca] if a.ca else []) + a.q
    with ThreadPoolExecutor(16) as pool:  # every person and search at once
        people = [pool.submit(person, h) for h in handles]
        found = [pool.submit(search, q) for q in queries]
        people, found = [f.result() for f in people], [f.result() for f in found]
    for handle, u, posts in people:
        if "data" not in u:
            print(f"@{handle}: {u.get('error') or u.get('errors', [{}])[0].get('detail', 'not found')}")
            continue
        d, m = u["data"], u["data"]["public_metrics"]
        last = when(d["most_recent_tweet_id"]) if d.get("most_recent_tweet_id") else "never"
        print(f"@{d['username']}  {m['followers_count']:,} followers  joined {d['created_at'][:10]}  last post {last}")
        print(f"  bio: {(d.get('description') or '').replace(chr(10), ' ')[:110]}")
        for t in (posts or {}).get("data", [])[:5]:
            print(f"  {t['created_at'][:16]}  {t['text'].replace(chr(10), ' ')[:90]}")
    for q, r in found:
        users = {u["id"]: u for u in r.get("includes", {}).get("users", [])}
        tweets = r.get("data", [])
        print(f"search {q[:44]}: {len(tweets)} in last 7d" + (f"  {r['error']}" if "error" in r else ""))
        for t in tweets:
            au = users.get(t["author_id"], {})
            ts = calendar.timegm(time.strptime(t["created_at"][:19], "%Y-%m-%dT%H:%M:%S"))
            print(f"  {t['created_at'][11:16]}Z {ago(ts):>8}  @{au.get('username', '?')} "
                  f"({au.get('public_metrics', {}).get('followers_count', 0):,})  {t['text'].replace(chr(10), ' ')[:70]}")
    print(f"[{time.time() - t0:.2f}s]")


if __name__ == "__main__":
    main()
