# repo-dd

A Claude Code skill for due diligence on crypto tokens and the tech projects behind them. Send Claude a contract address, an X post, a GitHub link or a project site. Claude finds the rest (X account, site, repo, CA), checks every claim the project makes, and returns a one-screen card with the verdict on the first line. An illustrative card:

```
VERDICT   OVERSOLD
          live product is real, the "no admin key" claim is false

RED FLAGS
  - the program's upgrade authority is the deployer wallet
  - first bundle took 19% at launch, holds 3% now

CLAIMS    1 hold, 1 partial, 1 false, 1 unverifiable
  ✗ no admin key         program upgradeable, authority is the deployer
  ~ live on mainnet      program deployed, 41 txs total
  ? audited              no report published
  ✓ open source          repo builds the deployed program
...
```

## Install

You need [Claude Code](https://claude.com/claude-code) and Python 3.9 or newer. There is nothing to `pip install`: the scripts use only the standard library.

### Set up with Claude

Paste this into Claude Code:

```
Install the repo-dd skill from https://github.com/AudiCodes/repo-dd and walk me through the setup.
```

Claude clones it, follows [Setup steps for Claude](#setup-steps-for-claude) below, and asks you for each API key with a link to get it.

### Set up by hand

1. Clone the repo into your skills folder:

   ```sh
   git clone https://github.com/AudiCodes/repo-dd ~/.claude/skills/repo-dd
   ```

2. Run the onboarding script:

   ```sh
   python3 ~/.claude/skills/repo-dd/onboard.py
   ```

   It asks for each API key, tests it with one live call, and saves it to `.env` in the skill folder (readable only by you). Press Enter to skip an optional key. Run it again any time to check that every key still works.

3. Restart Claude Code so it picks up the new skill.

### API keys

| Key | Needed for | Cost | Get one |
|---|---|---|---|
| `HELIUS_API_KEY` | every Solana check | free tier works | [dashboard.helius.dev](https://dashboard.helius.dev) |
| `SOCIALDATA_API_KEY` | X posts, X Articles, who is posting the CA | about $0.0002 per item, a few cents per DD | [socialdata.tools](https://socialdata.tools) |
| `ETHERSCAN_API_KEY` | optional: EVM deployer history | free on Ethereum and Robinhood Chain | [etherscan.io/apis](https://etherscan.io/apis) |
| `X_BEARER_TOKEN` | optional: `xcheck.py`, `wallet_claim.py` | X API pay per use | [developer.x.com](https://developer.x.com) |

`gh` (GitHub CLI) and `dig` are used when installed. Without them, the repo and DNS checks are skipped.

### Setup steps for Claude

1. `git clone https://github.com/AudiCodes/repo-dd ~/.claude/skills/repo-dd`. If that folder already exists, ask the user before touching it.
2. Run `python3 ~/.claude/skills/repo-dd/onboard.py`. Without a terminal it asks nothing: it tests the keys already in `.env` and lists the missing ones with where to get each.
3. For each missing required key (`HELIUS_API_KEY`, `SOCIALDATA_API_KEY`), give the user the signup link from the table above and ask them to paste the key. Tell them they can instead add it to `~/.claude/skills/repo-dd/.env` themselves if they'd rather not paste it into the chat. Write each key as a `NAME=value` line in that `.env`, then run `onboard.py` again. Offer the optional keys once.
4. When `onboard.py` prints `Ready`, tell the user to restart Claude Code, then send a CA or an x.com link to try it.

## Using it

Paste one of these into Claude Code:

```
<a Solana mint or 0x contract address>
https://x.com/someproject
https://someproject.fun
dd this: github.com/someone/somerepo
```

The skill triggers on its own when you send a CA or a link. You can also call it by name with `/repo-dd`.

What happens next:

1. **Within about 10 seconds, a first read.** Market cap, the deployer, who is posting the CA, how much of the supply the launch bundle took and still holds, and the one fact that matters most so far. Anything that changes the call (a serial launcher, a copycat of a bigger token, a bundle that already sold) is said the moment it is found.
2. **In 10 to 60 seconds, the full card.** Every claim the project makes, each marked holds, partial, false or unverifiable, with the evidence. Plus the deployer and its funding, the launch bundle, the website's builder platform, and whether the code is a copy.
3. **Then a `TRIED` block.** Claude uses the product itself, up to the point of a wallet signature, and reports what would stop a new user, such as a broken flow or a capped payout.

For a token with no tech behind it, ask "what's the narrative" instead. Claude pulls every X post naming the CA, biggest accounts first, with copy-paste bot posts collapsed into one line.

## What it checks

- **On-chain:** the deployer, its past launches and how they ended, who funded it, the launch bundle and how much of it has sold, program upgrade authorities, and holder overlap with known team wallets. Solana, Base and Robinhood Chain.
- **X:** every post and X Article from the project and the dev (Articles are fetched one by one, since they never show up in timeline APIs), who is posting the CA, bot-template shill waves, and "followed by" claims.
- **Code:** what the repo does, how much of it is AI-written, spoofed commit times, and whether it is a scrubbed copy of someone else's project.
- **Website:** Lovable, v0, Framer, n8n and other builder-platform fingerprints.

## Running the scripts directly

Each script also works without Claude:

```sh
cd ~/.claude/skills/repo-dd/scripts
python3 dd.py <@handle | x.com link | CA | site>   # everything below, in parallel
python3 quick.py <CA>                              # market, copycats, X, deployer, in ~3s
python3 ca_check.py <mint>                         # Solana deployer, past launches, funding
python3 bundle.py <mint>                           # launch bundle: got at launch vs holds now
python3 fomo_share.py <CA>                         # share of supply in FOMO-app wallets
python3 evm_relation.py <token> --chain base       # EVM deployer, dev %, holder scan
python3 wallet_claim.py <addr> --person <handle>   # "deployed by <famous person>'s wallet"?
python3 narrative.py <CA>                          # who is pushing the CA on X
```

## Speed

`bench/bench.py` runs `dd.py` on a list of inputs and logs when each section finished to `bench/results.jsonl`. Time until the full first wave finished, with empty caches:

| Input | Before | After |
|---|---|---|
| X handle, CA in bio | 57s | 17s |
| X handle, CA in posts | 18s | 8s |
| Project website | 169s | 16s |
| Bare CA | 53s | 17s |

Two changes did most of it. The supply-share lookup moved from Helius's enhanced API (2 calls per second) to `getTransactionsForAddress` (100 transactions per call, paced across processes), and gives identical results on the tokens tested. The chain and site checks now start from the X profile alone instead of waiting for every post to load. On a Helius plan without `getTransactionsForAddress`, the scripts fall back to the old path automatically.

## Known limits

- Base deployer funding: Etherscan's free tier no longer covers Base, and Base Blockscout is usually behind a Cloudflare challenge, so `evm_relation.py` reports funding as not checked.
- `fomo_share.py` measures one trading app's wallets (fomo.family). Skip it if that flow doesn't matter to you.
- None of this is financial advice. The card is a fast read on public evidence, and many claims can't be checked from outside.

## License

MIT
