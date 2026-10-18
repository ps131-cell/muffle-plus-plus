# How we work

## Branches and pull requests
- Nobody commits to `main` directly; merge only with green CI. Until the repo is public, a local
  pre-push hook refuses pushes to `main` (GitHub protection comes with #17).
- One branch per task: `<area>/<short-topic>`, e.g. `data/tcga-loader`, `fl/fedprox`.
- Keep branches short-lived (≤ 2 days); `git pull --rebase origin main` before opening a PR.
- Squash-merge, delete the branch, link the issue (`Closes #12`).

## Daily loop
```bash
git checkout main && git pull
git checkout -b data/my-task
# ...work...
make test
git add -p && git commit -m "data: add TCGA clinical parser"
git push -u origin data/my-task      # then: gh pr create --fill
```

## Commit messages
`<area>: <what changed>` — areas: `data`, `model`, `fl`, `eval`, `app`, `infra`, `docs`.

## Split of work (edit as you go)
| Area | Lead | Files |
|---|---|---|
| Data (TCGA, harmonization, site splits) | Kimberley | `src/muffle/data/`, `scripts/` |
| Model, loss, metrics, evaluation | Prakhar | `src/muffle/models/`, `losses.py`, `metrics.py` |
| Federated training | shared | `src/muffle/fl/`, `jobs/`, `docs/NEBIUS.md` |
| Nemotron report + demo + video | shared | `src/muffle/report/`, `app/` |

## Rules that protect us
- **Never commit data** (no TCGA files, patient IDs, CSV/NPZ) — `data/` is ignored.
- **Never commit secrets** — keys go in `.env` (ignored).
- Clear notebook outputs before committing (`make clean-nb`).
- Log decisions (dataset, metrics, architecture) in `docs/decisions.md` with a date.
- The repo goes public for the hackathon: write commit messages and comments accordingly.
