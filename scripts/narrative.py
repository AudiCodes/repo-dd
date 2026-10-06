"""What people are saying a token is about: every X post naming the CA (the feed Axiom shows on the chart).

    python3 narrative.py <CA> [--ticker ENS] [--max 300]

Prints posts biggest account first, with copy-paste bot templates collapsed into one line with a count,
so the few real takes stand out from the shill farm. Cost: SocialData, $0.0002 per post.
"""
import argparse
import re
import time
from collections import defaultdict


def pull(query, cap):
    """SocialData search. Returns posts and authors in the X API's shape."""
    from quick import socialdata
    posts, users, cursor = [], {}, None
    while len(posts) < cap:
        r = socialdata("search", query=query, type="Latest", **({"cursor": cursor} if cursor else {}))
        for t in r.get("tweets", []):
            u = t["user"]
            users[u["id_str"]] = {"username": u["screen_name"], "created_at": u["created_at"],
                                  "public_metrics": {"followers_count": u["followers_count"]}}
            posts.append({"author_id": u["id_str"], "text": t.get("full_text") or t.get("text") or "",
                          "created_at": t["tweet_created_at"], "public_metrics": {"like_count": t.get("favorite_count", 0)}})
        cursor = r.get("next_cursor")
        if not cursor or not r.get("tweets"):
            break
    return posts, users


def template(text):
    """Bot farms post one template with the numbers swapped; strip numbers, links and mentions to match them."""
    return re.sub(r"https?://\S+|@\w+|0x[0-9a-fA-F]{40}|[\d.,$%]+[KkMm]?", "", text).lower().split()[:12].__str__()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ca")
    ap.add_argument("--ticker")
    ap.add_argument("--max", type=int, default=300)
    a = ap.parse_args()
    t0 = time.time()
    q = f"({a.ca} OR ${a.ticker})" if a.ticker else a.ca
    posts, users = pull(q + " -is:retweet", a.max)

    groups = defaultdict(list)
    for p in posts:
        groups[template(p.get("note_tweet", {}).get("text") or p["text"])].append(p)
    rows = []
    for g in groups.values():
        p = max(g, key=lambda p: users.get(p["author_id"], {}).get("public_metrics", {}).get("followers_count", 0))
        u = users.get(p["author_id"], {})
        rows.append((u.get("public_metrics", {}).get("followers_count", 0), len(g), u.get("username", "?"),
                     u.get("created_at", "")[:7], p))
    rows.sort(key=lambda r: -r[0])

    first = min((p["created_at"] for p in posts), default="")
    print(f"{len(posts)} posts, {len(rows)} distinct, first {first[11:16]}Z  query: {q}")
    for followers, n, name, joined, p in rows:
        text = (p.get("note_tweet", {}).get("text") or p["text"]).replace("\n", " ")
        likes = p["public_metrics"]["like_count"]
        tag = f" x{n} SAME TEMPLATE" if n > 1 else ""
        print(f"\n{followers:>8,} @{name} (joined {joined}) {p['created_at'][11:16]}Z {likes}♥{tag}\n  {text[:400]}")
    print(f"\n[{time.time() - t0:.1f}s, ~${len(posts) * 0.0002:.2f}]")


if __name__ == "__main__":
    main()
