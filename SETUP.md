# Setup

Both teammates work on **one Mac** with **one GitHub account**, and use Claude Code there.
The repo lives at `~/PycharmProjects/muffle-plus-plus`.

## 1. Local environment (done by Claude Code — see `docs/CLAUDE_CODE_KICKOFF.md`)

```bash
cd ~/PycharmProjects/muffle-plus-plus
python3 --version            # needs 3.10–3.13; if not: brew install python@3.12, then make setup PY=python3.12
make setup && make test && make local && make fl
```

On Apple Silicon, PyTorch uses the CPU (and can use the GPU via `mps`); that's plenty for the
synthetic data and for TCGA-BRCA (federated training runs in the NVFlare simulator on the
laptop).

## 2. Accounts and keys (you, in a browser — a few minutes each)

| What | Where | Goes in |
|---|---|---|
| Devpost registration (both teammates, same team) | nebiusglobalaihackathon.devpost.com | — |
| Nebius account + hackathon credits (code on the Devpost page) | nebius.com → console | — |
| Token Factory API key | Nebius Token Factory console → API keys | `.env` → `NEBIUS_API_KEY` |
| Tavily API key (optional, for the bonus prize) | tavily.com | `.env` → `TAVILY_API_KEY` |
| Nebius CLI (optional, only for `docs/NEBIUS.md`; not used in the submission) | `curl -sSL https://artifacts.nebius.cloud/cli/install.sh \| bash`, then `nebius profile create` | — |

`.env` is git-ignored. Never paste keys into code, issues or chat logs.

## 3. Working together on one machine / one account
- Each change goes on its own branch and through a pull request, even though one account
  merges them — it keeps `main` working and gives you a reviewable history.
- Mention who did the work in the commit message (e.g. `model: add FedProx (Kim)`), and set
  `Co-authored-by:` trailers if you want both names on GitHub's contributor graph.
- Merge only with green CI. GitHub branch protection needs a public repo on the free plan, so
  until the repo goes public a local pre-push hook refuses pushes to `main`; #17 turns on
  protection after that.

## 4. Shared files that are not code
| What | Where |
|---|---|
| TCGA / CHIMERA downloads, processed matrices | `data/` locally (ignored) |
| Checkpoints, run logs | `outputs/`, `workspaces/` (ignored) |
| Slides, video | shared Google Drive folder |
| Decisions, meeting notes | `docs/decisions.md` |

## 5. Data access
TCGA open-tier expression, methylation, copy number, clinical and survival data need no
application (GDC Data Portal or the UCSC Xena GDC hub). Raw somatic mutation calls are
controlled-access — use gene-level/open summaries. CHIMERA is CC BY-NC-SA (research use OK).
