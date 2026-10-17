# Kickoff prompt for Claude Code

Run `cd ~/PycharmProjects/muffle-plus-plus && claude`, then paste everything below the line.

---

Set up our hackathon project on this Mac and on my GitHub. Two teammates share this Mac and this
GitHub account. Ask me before anything irreversible, and never print or commit API keys.

1. Tools: check for git, make, Homebrew, gh (GitHub CLI) and python3 (needs 3.10–3.13). Install
   what's missing: Xcode Command Line Tools via `xcode-select --install`, Homebrew from brew.sh,
   then `brew install gh python@3.12`. Tell me when I need to approve something or enter my Mac
   password.
2. This folder is the project and already has one git commit on main (`git log` to check; if git
   complains about the repo, run `git status` and repair it rather than deleting .git). Read
   CLAUDE.md, README.md, SETUP.md, docs/HACKATHON.md and docs/decisions.md.
3. GitHub: run `gh auth login` (GitHub.com, HTTPS, log in with a web browser) and walk me through
   the browser step. Set git user.name/user.email from my GitHub account. Then
   `gh repo create muffle-plus-plus --private --source=. --remote=origin --push`. It stays
   private until we're ready to submit.
4. Environment: run `make setup` (or `make setup PY=python3.12` if the default python3 is too old
   or too new). Then `make test` and `make lint`. The PyTorch/NVFlare parts have never been run,
   so expect some failures. Fix them in the code (never by deleting tests) on a branch
   `infra/local-bringup`.
5. Pipeline: run `make local` and `make fl`. If the NVFlare job fails, check `pip show nvflare`
   and that version's docs (FedAvgRecipe + SimEnv recipe API), then fix jobs/fedavg_job.py and
   src/muffle/fl/client.py. Show me a table of C-index per site: centralized vs local-only vs
   FedAvg. FedAvg should land between local-only and centralized; if it doesn't, investigate.
6. Demo: start `.venv/bin/streamlit run app/streamlit_app.py --server.headless true` for about
   20 seconds to confirm it launches. Without an API key, the report should use the offline
   template.
7. Ship: commit, push the branch, open a PR with `gh pr create --fill`, run
   `gh pr checks --watch`, and fix until CI is green. Then `gh pr merge --squash --delete-branch`
   and pull main.
8. Protect main with `gh api`: require the `tests` status check, block force pushes, no required
   approvals (a single account can't approve its own PRs). Show me the command before running it.
9. Planning: create labels data, model, fl, eval, app, infra, docs. Create one GitHub issue per
   row of the 14-day plan and per unchecked requirement in docs/HACKATHON.md, each with the
   right label.
10. Report back: what works, the results table, the repo URL, the open issues, and the steps I
    still have to do myself (register on Devpost as a team, Nebius account + hackathon credits,
    Token Factory key into .env, Tavily key, Nebius CLI login). Once I've put NEBIUS_API_KEY in
    .env, run `python -m muffle.report.nemotron --list-models`, set NEMOTRON_MODEL in .env, and
    test one live report.

## Starting later sessions
`cd ~/PycharmProjects/muffle-plus-plus && claude`, then describe the task
(e.g. "pick up issue #3, the TCGA loader"). CLAUDE.md carries the rules and deadline.
