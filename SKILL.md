---
name: repo-dd
description: Fast due diligence on a crypto token or tech project. Use whenever the user sends a token CA (Solana mint or EVM contract address), an x.com link or X post, a github.com link or repo name, or a project website, or says "dd this", "check this repo", "is this real", "is this possible". Finds the project's claims itself, verifies each one on-chain, in code and on X, and returns a one-screen card, verdict first.
---

# Repo DD

The user sends these when weighing a token or a dev, usually with minutes to decide. Answer the checklist and stop. Do not summarize the README back.

**Whatever they send, run the whole cycle.** A bare website, a tweet, an article, a CA or a repo all get the same treatment. Find the rest yourself: from a site, its X, repo, docs and CA; from a CA, the site and X; from a tweet, the site and the CA. Then find the claims and check each one. "Is this possible?" is answered by the claims table, not by an essay.

Speed is the priority. Target under 90 seconds wall clock. Never re-fetch what one batch already returned.

**Say crucial findings the moment they land.** If a check turns up something that changes the call (serial launcher, compromised or public-seed key, copycat of a bigger token, bundle wallets, the claimed person denying it), write it as a one-line update right away, then keep going. Everything else waits for the card.

**Bulk queries, never per-tx loops.** Answer "all launches on this program" or "every holder" with one call: getProgramAccounts with memcmp/dataSize filters (Solana), eth_getLogs by address/topic (EVM). Loop getTransaction only over a small, already-filtered set.

## Scripts

All scripts live in `scripts/` inside this skill's base directory. Below, `$S` means that path. Keys come from the environment or `.env` at the skill root (see `.env.example`); a script that needs a missing key says which one.

| Script | What it does | Time |
|---|---|---|
| `dd.py <handle, x.com link, CA or site>` | Wave 1 in one command: resolves the rest, then runs the scripts below in parallel and prints each section as it lands | ~30-120s |
| `quick.py <CA>` | Market, same-ticker copycats, who posts the CA on X, deployer age and % held | ~3s |
| `devwatch.py <mint> --once` | Deployer + first-bundle wallet tree, what the bundle got at launch vs holds now | ~10-60s |
| `ca_check.py <mint>` | Solana deployer, its past launches with live mcap, who funds it, origin trail | ~50s |
| `evm_relation.py <token> --chain base\|robinhood` | EVM deployer (4337-aware), dev % held, full holder scan, `--team` overlap | ~10-70s |
| `fomo_share.py <CA> [--chain]` | Share of supply in FOMO-app wallets (fomo.family), a retail-flow signal | ~20-40s |
| `xcheck.py --who h1,h2 --ca <CA> [--q ".."]` | X API: each handle's last post time and recent posts, 7-day search | ~1s |
| `wallet_claim.py <addr> --chain <c> --person <handle>` | "Deployed by <famous person>'s wallet": 7702 delegates, sweeper bots, public ties | ~2s |
| `narrative.py <CA> [--ticker X]` | Every X post naming the CA, biggest account first, bot templates collapsed | ~5s |

## First read in 60 seconds

Speed changes the outcome. In one real case the token went from $30k when it was sent, to $40k at the first scan, to $150k when the card landed, over a dozen serial tool calls. So:

1. **First tool call, always:** `cd $S && python3 dd.py <whatever they sent>` with `run_in_background`, output to the scratchpad.
2. **Read the output at ~10s and send a FIRST READ:** stage, the deciding fact, MC. Three to five lines.
3. Read the X Articles dd.py saved to `scripts/data/dd/<handle>/`, then test their specifics against the PROGRAMS and DEV TREE sections. Send the full card. Hand-run checks only for what dd.py doesn't cover (repo clone, product try).
4. Never trace funding hops, program authorities or bundles by hand: dd.py already did it.

## Run it in two waves, no more

The on-chain chain (deployer, then past launches, then funding) is serial by nature. It must never block the code checks.

**Wave 1, one message, every call at once:**
- shallow clone (`--depth 300`, scratchpad) plus `git log --format='%H|%ai|%ci|%an|%ae|%s' --shortstat` in the same command
- `gh api repos/O/R`, `gh api users/<owner>`, `gh api users/<owner>/repos`
- fxtwitter profile and recent posts for the project and the dev
- website: `curl -sIL`, `curl -sL`, `dig +short CNAME`
- GitHub code search for the upstream
- if the CA is already in hand: start check 9 now, in the background

**Wave 2, one message:** read the 2-3 core files, run the tests, finish the claims check from the wave 1 posts and site. If wave 1 turned up the CA, start check 9 in this same message.

Then wait for check 9 and write the card. A third round of tool calls needs something ambiguous in wave 2 to justify it. One short progress line per wave, not per command.

## Fast routes

- **"Followed by <big account>": is_following alone is not the answer.** The question is whether the account is bought and whether the follow is about this project. In one pass:
  1. SocialData `GET /twitter/user/<big_id>/following/<id>` gives is_following.
  2. The account ID snowflake gives the creation date. memory.lol `/v1/tw/id/<id>` gives the handle history; empty means no renames.
  3. SocialData `friends/list?user_id=<big_id>` shows where the account sits among the follows, newest first.
  4. The earliest public "followed by" post (search with `until:`) bounds the follow time, as does the start of the "follow back / collab" reply swarm. The follow is tied to this project only if it came after the account became this project and nothing was renamed after it.
- **Product revenue vs self-dealing:** trace every payer to a product's pay-to address one hop back. In one case both x402 payers were funded by the deployer.
- **X in under a second:** `python3 xcheck.py --who <every claimed dev, founder, partner> --ca <CA>`. A claimed dev who went quiet shows instantly from the last-post time. Same-template posts from <50-follower accounts in the same minute are a bot farm. For posts older than 7 days use SocialData search.
- **EVM wallet history:** Etherscan v2 `https://api.etherscan.io/v2/api?chainid=<id>&module=account&action=txlist&address=<a>&sort=asc&apikey=<k>` gives the funder (first inbound), everything the deployer did, and decoded function names (`sweepNative`, `withdrawNative` = sweeper bots). `action=txlistinternal` for internal ETH. The free tier covers Ethereum and Robinhood Chain, not Base.
- **"Deployed by <famous person>'s wallet":** `python3 wallet_claim.py <deployer> --chain <chain> --person <handle>`. Signing proves the key signed, not the person. 7702 delegates to different unknown contracts on different chains, or funding, launch and sweep in the same second, mean the key leaked and bots own it.

## Lead with the deciding fact

Lead with the fact that validates or kills the claim, not a list of worries. Put it first, in plain words: "the claimed person's own account hasn't posted since Aug 12 and said he's on a break", "the deployer key is compromised: sweeper bots are on it". A red flag that only raises doubt is not a verdict; say which facts would decide it and go get them.

## Checks

1. **Code quality.** Read the 2-3 core files, not the whole tree. Does it do something real, or is it glue around an API call? Tests present and meaningful? Would it run as shipped (missing files, hardcoded keys, TODO stubs in the hot path)?
2. **AI usage.** Estimate how much is AI-written and say what points to it: uniform over-commented style, `// Step 1:` narration, emoji READMEs, generic names, identical boilerplate across files, Co-Authored-By trailers for Claude/Copilot/Cursor, `.cursorrules` / `CLAUDE.md` / `AGENTS.md` files. AI-written is not disqualifying; say whether a human clearly understood and directed it.
3. **Spoofed times.** `git log --format='%H|%ai|%ci|%an|%ae|%s'`. Tells: author date == committer date to the second across many commits, root commit at 00:00:00, history older than GitHub `created_at`, bursts of hundreds of commits in minutes, padding commits that only touch comments (`--shortstat`), one giant "chore" commit holding the whole codebase.
4. **Claims: find them, then test each one. This is the core of the card.** Read every post and every X Article from the project and the dev before scoring. X Articles never show in timeline APIs or profile tweet counts: pull SocialData `GET /twitter/user/<id>/tweets-and-replies`, then fxtwitter each id; a `tweet.article` field holds the full text (dd.py does this). In one case the post alone looked thin, and the article that was missed matched the deployed program byte for byte. List every concrete claim (features, integrations, chains, numbers, "live", "no admin key", test results) and test each with the strongest check available:
   - against code: point to the file that builds it
   - against the chain: the contract has code, pools/balances/events exist, usage is real; admin claims via bytecode selectors (`owner()` 8da5cb5b, `upgradeTo` 3659cfe6, `pause()` 8456cb59) and the EIP-1967 slot
   - numbers they quote: recompute from live data or their own formula, and say how close
   - a claim nobody outside can check (tests on a private fork, "audited" with no report): UNVERIFIABLE, not true
   Mark each HOLDS / PARTIAL / FALSE / UNVERIFIABLE with the evidence in a few words. Unbuilt features sold as live, and numbers that only work under their chosen assumption, are the main findings. Put any number-crunching script in the scratchpad and name it.
5. **Project to token link.** Does the CA appear in the repo, the official website, or the dev's X? Did an address tied to the dev or project deploy or fund the token? If nothing links them, say so: the token may just be borrowing the repo.
6. **Who is the dev.** GitHub account age, other repos, contribution graph, linked X/website, prior projects and whether those shipped or rugged. Commit author emails (`%ae`) often expose the real identity or other accounts.
7. **Website: template and vibe-coding platform.** dd.py fingerprints the common ones. Name any builder platform with the exact fingerprint:
   - Lovable: `lovable.app`, `gptengineer.js`, `lovable-tagger`, `data-lov-id`, "Edit with Lovable" badge
   - Vercel: `*.vercel.app`, `x-vercel-id` / `server: Vercel`; v0: "generated by v0", v0 assets
   - n8n: `*.app.n8n.cloud`, `/webhook/` or `/form/` URLs (the "AI agent" backend is often just an n8n flow)
   - Bolt/StackBlitz, Replit, Base44, Bubble, Softr, Netlify (`x-nf-request-id`), Framer (`__framer`), Webflow (`data-wf-site`), Carrd, Wix, Squarespace, ThemeForest names, `generator` meta tag
   Also note stock copy, placeholder text and dead links. Say whether the "product" is just the site.
8. **Copy of another project.** Read every README and credit line in the project's repos, including repos holding its output, and check git history for removed attribution lines. In one case the engine was another developer's open-source tool, credited in one README and scrubbed from two others. Search GitHub for 2-3 distinctive function names, strings or contract names. Check `fork`/`parent` in the API. For contracts, diff against the likely upstream. Never call something original without having searched for the upstream.
9. **Deployer, past deploys, funding. Runs on every CA, and on every repo once its CA turns up. No CA anywhere: say so under Unchecked.**
   - Solana: `python3 ca_check.py <mint>` in the background. Deployer (pump.fun bonding-curve creator, else the metadata create's fee payer), every launch in the dev's recent history with live mcap, who sends the dev SOL with each funder profiled one hop back, and the dev wallet's origin trail.
   - EVM: `python3 evm_relation.py <token> --chain base|robinhood`. Deployer (resolving 4337 EntryPoint launches to the user-op sender), dev % held, every address that touched the token. Add `--team 0x..,0x..` for known project or partner wallets. "no mint in the last N blocks" means an older token: rerun with a bigger `--lookback`. For past deploys, `eth_getLogs` on the launchpad factory address and match the creator.
   - The point is links to teams and partnerships. For the deployer and each funder: does it appear in the project's, a team member's or a known protocol's wallets, ENS/SNS names, X posts, GitHub, or prior launches by the same team? A known team treasury or VC wallet supports the claim; a serial pump.fun deployer with many dead launches is a red flag. Say which, with the address.
   - Deployer and bundle wallets at ~0% soon after launch means the team has no skin in the game: a red flag, never "no overhang". Dev supply on its own is one line, not a headline; bundles stay a red flag.

## Try the product (every tech play)

After the card, use the product as a user would, then send a short `TRIED` block. Don't wait to be asked.

- Run every flow reachable without signing: open the app, walk the vote/stake/play/bet screens, hit its API, download and open what it ships, read the payout and limit numbers shown before a signature.
- **The main question is why anyone would use this.** Find the user's upside and its cap. One options product capped max profit at a tiny amount; a trader who bought the token tried it, saw the cap, and sold. A capped upside means no demand under the tech narrative.
- **Calibrate:** a tech play is a bet on attention, and attention brings users. Low usage today, a small fee to the dev, or entertainment-only value are context, not red flags. Flag only what would stop a new user: the product doesn't work, the output is broken, or the upside is capped so low nobody bothers.
- Also check what the user pays (burns, fees, where the fee goes), whether the flow breaks or stalls, and whether the claimed live usage matches the counters.
- If a login hides the deciding fact, ask the user before creating an account, and use a throwaway identity. Read-only backend calls only; never send admin or cheat messages.
- Stop at the signature. If a flow needs the user's wallet, name the one screen to open and what to read off it.

```
TRIED     <what I used, in one line>
  - <red flag, worst first: caps, fees, broken steps, no reason to use>
Use case  <who would use it and why, or "none: <reason>">
```

## Output (exactly this, nothing after it)

It has to scan in seconds. Inside a code block. **Every line under 80 characters.** One fact per line, no parenthetical asides, no semicolon chains. Shorten addresses to `0x7769…3e43`. If it doesn't change the call, cut it.

```
VERDICT   OVERSOLD
          <one line why, under 70 chars>

RED FLAGS
  - <the 1-4 findings that should change the decision, worst first>

Code      <quality in one line>
AI        <none/some/heavy>, <directed/vibe-coded>: <the one tell>
Times     <organic/spoofed/staged>: <the one tell>
CLAIMS    <X> hold, <Y> partial, <Z> false, <W> unverifiable
  ✗ <claim>              <what the check found instead>
  ~ <claim>              <what holds and what does not>
  ? <claim>              <why it can't be checked>
  ✓ <claim, short>       <evidence, short>

Token     <linked/unlinked/contradicts>: <how>
Deployer  <addr>, holds <X>%, <N> launches (<M> dead), funded by <who>
FOMO      <X>% of supply in <N> FOMO wallets
Team link <link found, or none found>
Dev       <who, account age, identity leaks>
Website   <custom / platform: fingerprint>
Copy of   <original / fork of repo: evidence>
Stage     <first run-up / day N, after first run-up>
Unchecked <what I did not verify>
```

List every claim, worst first (✗, then ~, ?, ✓). Keep each claim row under 80 characters; split into two rows if needed.

**Stage matters for tech.** On the first run-up, real + novel is the strongest tech signal there is; usage only starts to count days later. A verified build that isn't novel is not top tier.

**Everything is speculation.** Devs rarely publish everything. UNVERIFIABLE claims are normal and don't drag the verdict; judge on the visible evidence and commit to a call. Never close on "what would flip it is them publishing X" when they won't; name a watchable trigger instead. A doxxed dev scores high because trust itself drives price.

VERDICT is one of REAL / MOSTLY REAL / OVERSOLD / UNPROVEN / COPY / FAKE. UNPROVEN = the parts that can be checked hold, but the product has no real usage or the key claims can't be checked yet. Put "none" under RED FLAGS if there are none. Mark anything inferred with `(inferred)`.

## Non-tech play: "what's the narrative"

`python3 narrative.py <CA> [--ticker X]` pulls every X post naming the CA, biggest account first, with copy-paste bot templates collapsed (`xN SAME TEMPLATE`). Answer with: the narrative in one line, who is actually pushing it (real accounts vs bot farms), the claims inside it, and the one fact that makes or breaks it. Skip the full card unless asked.
