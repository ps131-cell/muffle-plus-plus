# MuFFLe++ — Devpost submission (draft)

Text for the Devpost form, one section per field. Fill the two TODO links before submitting.

| Field | Value |
|---|---|
| Project name | MuFFLe++ |
| Tagline | Hospitals train one cancer survival model without sharing patient data; an NVIDIA Nemotron agent turns each prediction into a tumor-board note that cites only what its tools returned. |
| Track | Best Apps and Agents |
| Demo | TODO: Streamlit Community Cloud URL |
| Video | TODO: YouTube URL (≤ 3 min) |
| Code | https://github.com/ps131-cell/muffle-plus-plus (MIT) |
| Built with | Python, PyTorch, NVIDIA FLARE 2.9, NVIDIA Nemotron 3 Super, NVIDIA Nemotron 3 Ultra, Nebius Token Factory, Tavily, Streamlit, Altair, TCGA |
| New or existing? | New: the repository was created on Oct 17, 2026, after the Submission Period opened (Aug 26); all of it was built during the hackathon. |

---

## Inspiration

A breast cancer patient's genome, tumour expression and methylation say a lot about how the
disease will behave, but no single hospital has enough such patients to learn it well, and
hospitals can't pool them: the data is private and regulated. So prognosis models stay small
and site-specific. And a risk score alone doesn't help a tumor board, which needs to know what
drives the risk and what the literature says about it.

## What it does

**One survival model, trained across hospitals without moving patient data.** Three hospitals
(TCGA-BRCA tissue source sites grouped into three federated clients of 355, 355 and 354
patients) each train on their own copy number, RNA expression, methylation, protein and
clinical data. Only model weights travel, through NVIDIA FLARE. A hospital that never measured
a layer still takes part: the layer is masked.

**A case agent that explains one patient.** For a held-out patient:

1. **Nemotron 3 Super** (on Nebius Token Factory) plans: it calls our tools for the patient's
   risk and cohort percentile, how much each data layer moves that risk compared with a typical
   patient, the top genes of a layer, and a Tavily search for papers or clinical trials on
   those genes.
2. **Nemotron 3 Ultra** writes the tumor-board note (Summary, Drivers, Caveats, Literature)
   from the tool outputs.
3. **A grounding check** (plain code, no LLM) looks for any number, gene or link in the note
   that no tool returned. If it finds one, Ultra gets one rewrite; anything left is shown.

The app has three tabs:
- **Case review:** pick a held-out patient; see where they sit among all patients, what drives
  their risk, and what happens if a data layer were missing; then watch the agent's steps live,
  read the note with its grounding result and tool trace, and download it.
- **Federation:** the hospitals and their data, and the results below.
- **How it works:** method, privacy and limits.

Only derived numbers (risk, percentile, contributions, attribution scores) and gene names are
sent to Token Factory, never a patient's omics values.

## How we built it

- **Data:** open-access TCGA-BRCA from the UCSC Xena GDC hub: 1,064 patients, 148 deaths,
  overall survival, one primary tumour each. Real modality gaps: methylation covers 51–83% of
  a hospital's patients, protein 75–89%.
- **Model (PyTorch):** an encoder per data layer, masked additive fusion and a Cox (DeepSurv)
  head, trained with modality dropout that never drops clinical data. Clinical-anchored
  residual: the model first learns a clinical risk, then the omic layers may correct it by an
  amount chosen on hospitals it wasn't trained at.
- **Federated training:** NVIDIA FLARE 2.9's `FedAvgRecipe` in the simulator: 20 rounds for
  the clinical anchor, then 20 for the omic residual. The residual's weight is chosen by
  federated evaluation; each hospital shares only two pair counts per candidate.
- **Evaluation:** leave one hospital out (train on two, test on every patient of the third),
  5 reported seeds, every tuning choice made on 5 other seeds; plus calibration and fairness
  slices by age, stage and hospital.
- **Agent:** OpenAI-compatible tool calling on Token Factory, with the tools running our model
  locally. A hard spending cap reserves each call's worst-case cost before sending it. If Token
  Factory is unreachable, the same tools run in a fixed order and a template writes the note.
- **App:** Streamlit and Altair, hosted on Streamlit Community Cloud from a 0.9 MB bundle: the
  model weights, the inputs of 40 held-out patients, and derived numbers only.

## Results

Leave one hospital out, C-index on the unseen hospital, mean ± sd over 5 seeds:

| Model | C-index |
|---|---|
| **FedAvg, clinical-anchored residual** (no patient data shared) | **0.693 ± 0.017** |
| FedAvg, plain multi-omic fusion | 0.680 ± 0.008 |
| Pooled data, clinical-anchored residual | 0.700 ± 0.012 |
| Pooled data, plain fusion | 0.692 ± 0.026 |
| One hospital alone | 0.649 ± 0.032 |
| Clinical data only (stage, age, T/N/M) | 0.702 ± 0.004 |

- Federated training comes within 0.01 of pooling the hospitals' data, about the run-to-run
  noise of FedAvg itself, and beats a model trained at one hospital alone (by 0.044).
- Honest baseline: on overall survival in breast cancer, the omic layers don't add signal
  beyond stage and age yet. That's why the model anchors on clinical data and lets the omics
  correct it.
- The case agent: all 8 notes saved for the demo passed the grounding check; a note costs
  about $0.01 of Token Factory credit (8k–16k tokens). The whole project used $0.46.

## Challenges we ran into

- **Omics underperformed clinical data.** Copy number alone ranked patients worse than chance
  across hospitals (0.485), a sign of site and batch effects. The clinical-anchored residual,
  with its weight chosen on held-out hospitals, closed the gap to clinical-only.
- **Explanations read backwards.** Masking a layer shifts almost every patient's risk the same
  way, so some high-risk patients showed every layer "lowering" risk. We now subtract each
  layer's average effect, so contributions compare with a typical patient.
- **Agent reliability.** Notes left the clinical layer out, Ultra's reasoning sometimes ran
  past the token limit, and the planner sometimes stopped before the literature step. Fixes:
  the grounding check with one rewrite, Super writing the note when Ultra's reply is cut off,
  and one reminder turn for the search.
- **Literature quality.** Combined queries and unnamed gene ids returned generic survival
  pages, a coronary artery disease paper, a YouTube video. One query per gene, results that
  must name the gene and a cancer, and scholarly domains fixed it.
- **Free credits only.** The Token Factory account is billed automatically once the credit
  runs out, so we built our own spending cap.

## Accomplishments that we're proud of

- On real hospitals, federated training matches pooled training without moving any patient
  data.
- An evaluation we can defend: unseen hospitals, separate tuning seeds, and the clinical
  baseline reported even though it wins.
- Every claim in a note can be traced to a tool call, and the app shows the trace.

## What we learned

- How much a fair validation split matters: random patient splits flattered the omics; whole
  held-out hospitals didn't.
- Small and large Nemotron models work well together: Super for quick, structured tool calls,
  Ultra for the written synthesis.
- LLM output in medicine needs a check that doesn't trust the LLM; about a hundred lines of
  plain Python catch invented numbers, genes and links.

## What's next for MuFFLe++

- A pilot across real institutions, with secure aggregation or differential privacy.
- A second endpoint (progression-free interval) and a second cancer type.
- Running federated training as Nebius Serverless Jobs on GPUs.

## How we used NVIDIA and Nebius

- **NVIDIA Nemotron on Nebius Token Factory:** every note is one tool-calling conversation
  with Nemotron 3 Super and one or two Nemotron 3 Ultra calls (the note, and a rewrite if the
  grounding check finds something), following the track's advice to use Ultra for reasoning
  and Super for the fast calls.
- **NVIDIA FLARE 2.9:** federated training with the Recipe API in the simulator.
- **Tavily:** literature and clinical-trial search on the genes behind each patient's risk.
- **Nebius AI Cloud:** not used (see feedback).

## Testing instructions

- Open the demo URL; no login. If Streamlit has put the app to sleep, click the button to wake
  it (about a minute).
- **Case review:** patients marked ★ have a saved note (**Show the saved note**). **Write the
  note with Nemotron** runs the live agent (about 20–30 seconds, 5 live notes per session).
  Open **What if a data layer were missing?** to hide a layer and see the risk change.
- **Federation** and **How it works** need no input.
- Locally: `make setup`, then `.venv/bin/streamlit run app/streamlit_app.py`. Without the
  TCGA data it downloads the demo bundle from the GitHub release. Add `NEBIUS_API_KEY` and
  `TAVILY_API_KEY` to `.env` for live notes; without them the tools run offline.

## Data

TCGA-BRCA open-access data only (no controlled-access files), from the UCSC Xena GDC hub. The
results here are in whole or part based upon data generated by the TCGA Research Network:
https://www.cancer.gov/tcga. Research prototype, not for clinical use.

---

## Feedback on Nebius Token Factory, AI Cloud and NVIDIA tools

Each item: what happened, why it mattered, and a suggestion.

### Nebius Token Factory

1. **Out-of-credit errors are hard to read.** Before our promo credit was applied, every chat
   call returned HTTP 402 "exhausted your budget" while `models.list()` kept working, so it
   first looked like a key or model problem. *Suggestion:* say "no credit on this account"
   explicitly, link to the billing page, and show the balance (including trial credit) next to
   the API keys.
2. **No hard spending limit.** The account is billed automatically once the credit runs out,
   and there is no per-key or per-project cap. For a hackathon on free credits, and for a
   public demo that judges use for weeks, that's a real risk; we wrote our own ledger that
   reserves each call's worst-case cost. *Suggestion:* per-key hard caps, prepaid-only mode,
   and spend alerts.
3. **Prices are behind a login.** We had to take Nemotron 3 Super's and Ultra's prices from
   third-party trackers to budget. *Suggestion:* a public price page, and prices in the
   `/models` response, so code can budget itself.
4. **Inconsistent model ids.** The same family appears as
   `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, `nvidia/nemotron-3-super-120b-a12b`,
   `nvidia/Nemotron-3-Ultra-550b-a55b` and `nvidia/Nemotron-3_5-Lightning`. *Suggestion:* one
   lowercase scheme, or case-insensitive ids and aliases.
5. **Reasoning length is hard to bound.** Ultra's reasoning counts as output: one note was cut
   off mid-sentence at a 2,000-token limit, and with a long literature list another ran past
   3,000. `reasoning_content` and `usage.completion_tokens_details.reasoning_tokens` made this
   visible, and
   `chat_template_kwargs: {"enable_thinking": false}` works. *Suggestion:* a reasoning budget
   parameter (or effort levels), and a finish reason that says the reasoning used up the
   limit.
6. **What worked well:** OpenAI-compatible tool calling on Nemotron 3 Super worked on the first
   try, calls were fast (a full note took 7–10 s before we added literature search), and the
   costs were tiny (about $0.01 a note).

### Nemotron models (agent behaviour)

7. **Super calls tools one at a time unless told to batch,** and sometimes stops before the
   last useful tool; with a few turns allowed, it ran out before the literature search. Asking
   it to batch the first calls and giving it one reminder fixed it. *Suggestion:* document
   prompting patterns for parallel tool calls and "finish the plan" behaviour.
8. **Instruction sensitivity:** "clinical data is not an omic layer" made both Super and Ultra
   drop the clinical layer from the Drivers section entirely, until we wrote "every layer,
   clinical included". A note on negative instructions in the model cards would help.

### NVIDIA FLARE

9. **The Recipe API was the easy part:** `FedAvgRecipe` with `SimEnv` ran three clients on a
   Mac's CPU with little code.
10. **The initial global model isn't seeded,** so identical FedAvg runs differ by about 0.01
    C-index (0.668 vs 0.680 for the same config), which is as large as the effects we wanted to
    measure. *Suggestion:* a seed option for the initial model in the recipes.

### Nebius AI Cloud

11. **We didn't use it,** although running federated training as Serverless Jobs on GPUs was in
    our plan. With automatic billing and no hard cap, we couldn't be sure we'd stay within the
    free credits. *Suggestion:* a credits-only mode or per-project hard limit would let
    hackathon teams use Serverless Jobs and Endpoints without that risk.

### Tavily

12. **Search needed filtering for a clinical audience.** A query with several gene names
    returned generic survival-rate pages; a gene symbol that's also a word or a surname (CAMP)
    matched unrelated text; clinical-trial results were protocol PDFs rather than study pages.
    `include_domains` made the biggest difference. *Suggestion:* a scholarly / biomedical
    search mode.
