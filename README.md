# repo-dd

A Claude Code skill for due diligence on crypto tokens and the tech projects behind them. Paste a contract address, an X post, a GitHub link or a project site, and Claude finds the rest (X account, site, repo, CA), checks every claim the project makes, and returns a one-screen card with the verdict on the first line. An illustrative card:

```
VERDICT   OVERSOLD
          live product is real, the "no admin key" claim is false

RED FLAGS
  - upgrade authority sits in the deployer's wallet tree
  - first bundle took 19% at launch, holds 3% now

CLAIMS    1 hold, 1 partial, 1 false, 1 unverifiable
  ✗ no admin key         program upgradeable, authority in dev tree
  ~ live on mainnet      program deployed, 41 txs total
  ? audited              no report published
  ✓ open source          repo builds the deployed program
...
```

## What it checks

- **On-chain:** the deployer, its past launches and how they ended, who funded it, the first-bundle wallet tree and how much of it has already sold, program upgrade authorities, and holder overlap with known team wallets. Solana, Base and Robinhood Chain.
- **X:** every post and X Article from the project and the dev (fetched one by one, since Articles never show up in timeline APIs), who is posting the CA, bot-template shill waves, and "followed by" claims.
- **Code:** what the repo does, how much of it is AI-written, spoofed commit times, and whether it is a scrubbed copy of someone else's project.
- **Website:** Lovable, v0, Framer, n8n and other builder-platform fingerprints.
- **The product:** Claude uses it up to the point of a wallet signature and reports whether anyone has a reason to use it.

`scripts/dd.py` runs the first wave in parallel and prints each section as it finishes. On a fresh pump.fun token the full run takes about 30 seconds.

## Install

```sh
git clone https://github.com/AudiCodes/repo-dd ~/.claude/skills/repo-dd
cp ~/.claude/skills/repo-dd/.env.example ~/.claude/skills/repo-dd/.env
# then fill in the keys
```

Python 3.9+, standard library only. `gh` (GitHub CLI) and `dig` are used when they're installed.

| Key | Used for | Cost |
|---|---|---|
| `HELIUS_API_KEY` | Solana RPC and parsed history | free tier works |
| `SOCIALDATA_API_KEY` | X search, profiles, posts | ~$0.0002 per item |
| `ETHERSCAN_API_KEY` | EVM wallet history | free tier: Ethereum and Robinhood Chain |
| `X_BEARER_TOKEN` | `xcheck.py`, `wallet_claim.py` | optional, X API pay-per-use |

Then send Claude a CA or a link. The skill triggers on its own, or you can call it with `/repo-dd`.

## Running the scripts directly

Each script also works without Claude:

```sh
cd ~/.claude/skills/repo-dd/scripts
python3 dd.py <@handle | x.com link | CA | site>   # everything below, in parallel
python3 quick.py <CA>                              # market, copycats, X, deployer, in ~3s
python3 ca_check.py <mint>                         # Solana deployer, past launches, funding
python3 devwatch.py <mint> --once                  # first-bundle wallet tree, got vs holds now
python3 evm_relation.py <token> --chain base       # EVM deployer, dev %, holder scan
python3 wallet_claim.py <addr> --person <handle>   # "deployed by <famous person>'s wallet"?
python3 narrative.py <CA>                          # who is pushing the CA on X
```

Leave out `--once` and `devwatch.py` keeps running and alerts when any wallet in the dev's tree sells. Set `NTFY_TOPIC` to get those alerts on your phone.

## Known limits

- Base deployer funding: Etherscan's free tier no longer covers Base, and Base Blockscout is usually behind a Cloudflare challenge, so `evm_relation.py` reports funding as not checked.
- `fomo_share.py` measures one trading app's wallets (fomo.family). Skip it if that flow doesn't matter to you.
- None of this is financial advice. The card is a fast read on public evidence, and many claims can't be checked from outside.

## License

MIT
