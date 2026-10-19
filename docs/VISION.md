# Vision: a multimodal, longitudinal cancer intelligence platform

MuFFLe++ is the first milestone of a larger idea: an AI-powered cancer **research and clinical
decision-support** platform for one carefully chosen cancer type. It brings together specialized
models, biomedical datasets and each patient's data over time into one continuously updated
understanding of that patient's disease. It is research support for qualified clinicians and
researchers, never a diagnosis or a prescription.

The milestone we build for the hackathon is smaller and rigorously evaluated. The table at the
end maps each part of the vision to what milestone 1 delivers and what stays on the roadmap.
Clinicians use the platform through a workspace with a deep workbench for each test type,
specified in [`WORKSPACE.md`](WORKSPACE.md).

## The idea
1. **Characterize the cancer from every test.** An orchestration layer connects specialized
   pretrained models (Hugging Face and other biomedical sources) with public datasets. From
   whatever a patient has (pathology slides, scans, blood tests, sequencing, expression data,
   clinical notes) it builds a detailed profile: type, subtype, stage, grade, receptor status,
   the driver mutations that were sequenced and, where nothing was sequenced, the alterations
   the other measurements suggest, with their uncertainty.
2. **Follow it over time in a patient file.** Each new result is added to the patient's file
   and the profile is re-estimated: what changed, why, and how confident the system is. Every
   earlier version of the report is kept.
3. **Track how this tumor evolves.** A tumor behaves like an organ of its own, and a limited set
   of driver alterations among many passengers drives its progression. Each observation makes
   some evolutionary paths more or less plausible. The file keeps the paths that still fit the
   evidence and forecasts what the next result is likely to show.
4. **Support evolution-informed treatment decisions.** At each step the platform gathers the
   treatment evidence for the current profile, including what is known to act on the tumor's
   most likely escape routes. The strategy it is built to support is to control the tumor while
   closing its likely resistance routes until a combination can block the rest, slowing its
   growth in between. This is an active research direction with early clinical support (part
   three). Clinicians decide; the platform never prescribes.
5. **Learn from the clinicians who use it.** With consent and governance, results that
   institutions add can improve the models through federated learning, so patient data stays
   at each site.
6. **Make every test explorable.** Each test type has its own workbench, as deep as a dedicated
   analysis tool: an interactive viewer, findings at tile or region level, measurements with
   their validation status, uncertainty and quality control ([`WORKSPACE.md`](WORKSPACE.md)).

## Guiding principles
- **Observations, inferences and hypotheses are kept apart.** Every finding is labeled as
  *observed* (measured directly, e.g. a sequenced mutation or the recorded stage), *model
  inference* (a prediction with stated uncertainty, e.g. a risk estimate or an inferred
  mutation status), or *hypothesis* (e.g. an evolutionary pathway or a literature lead).
- **Incomplete records are normal.** No patient has every test at every visit; the system works
  with whatever exists and says what is missing.
- **Simulated means labeled.** Simulated hospitals, synthetic patients and simulated arrival
  orders are always marked as such, never presented as real clinical deployments.
- **Evidence-linked, for clinician review.** Treatment information is evidence with sources
  (e.g. CIViC), never a recommendation.
- **Status is always visible.** Every module, finding and threshold shows whether it is
  implemented, experimentally validated or planned; a placeholder never looks validated.
- **Privacy and data rights first.** Data is used under its license; new data does not become
  training data without consent and governance; federated learning keeps patient data at its
  site.
- **Start small, add only what measurably helps.** A few validated, complementary models and
  datasets, each with defined inputs, outputs, limitations and an evaluation.

## Part one: cancer characterization and molecular analysis
**Choosing the cancer.** Pick the type with the best mix of public multimodal, molecular,
clinical and longitudinal data, relevant pretrained models, reliable progression measures and a
realistic scope. Lymphoma was a candidate; **breast cancer** won (TCGA-BRCA alone has ~1,060
multi-omic patients versus ~48 for TCGA's lymphoma cohort, and MSK-CHORD adds real timelines for
~5,400 breast cancer patients). Breast cancer also has the clearest clinical precedent for part
three: ESR1 mutations that emerge under aromatase-inhibitor therapy can be caught in blood before
the tumor progresses.

**Connecting specialized models and datasets.** An orchestration layer coordinates pretrained
models (Hugging Face and other biomedical resources) across pathology slides, radiology, blood
and lab tests, pathology reports and clinical notes, tumor type/subtype/grade/stage, sequencing
and mutations, gene expression and other molecular data, and treatment history and outcomes. It
cross-references findings with datasets and research evidence, and accounts for data quality,
missing tests, units and the timing of each observation. The result is an evidence-linked cancer
profile that separates confirmed findings from uncertain predictions.

**Mutations and cancer biology.** Solid tumors are abnormal organs made of cancer cells, stroma,
vessels and immune cells, not just clones of cancer cells (Egeblad et al. 2010). A cancer is an
evolving population of related but genetically distinct subpopulations. A typical tumor carries
two to eight driver gene mutations; the rest are passengers that give no growth advantage
(Vogelstein et al. 2013), and a pan-cancer analysis of 9,423 tumor exomes found 299 driver genes
(Bailey et al. 2018). Passengers are neutral rather than "benign", and copy-number changes,
epigenetic changes and shifts in cell state also drive progression and resistance, not only point
mutations. The platform distinguishes:
1. **Observed mutations**: identified directly by an appropriate molecular test.
2. **Supported molecular inferences**: alterations suggested by other measurements, with the
   uncertainty stated.
3. **Evolutionary hypotheses**: possible mutation orders or pathways inferred from molecular and
   longitudinal evidence.

Which tests can show a mutation:

| Test | Mutations | What it gives |
|---|---|---|
| Tumor sequencing (TCGA exomes, MSK-IMPACT panels) | observed, for that sample and time | variants, allele fractions, copy number |
| Blood ctDNA (liquid biopsy) | observed, repeatable | mutations from all tumor sites mixed together, over time; misses them when the tumor sheds little DNA |
| RNA, methylation, protein | no | patterns that suggest some alterations (model inference) |
| Pathology slides | no | tissue and tumor features; some mutations can be predicted with moderate accuracy (model inference) |
| Radiology scans, routine blood tests | no | size and spread, organ function, tumor markers |

It never assumes a mutation can be read from an image or a routine blood test, or that mutation
order can always be reconstructed; those conclusions need sequencing and informative samples
over time.

## Part two: longitudinal patient files and tumor evolution
**A patient timeline.** Each patient has a longitudinal file: at each timepoint whatever exists
(images, labs and tumor markers, biopsies and reports, molecular tests, stage, treatments and
their timing, observed tumor changes, response, side effects, outcomes). Each new result is
compared with the record so far and creates a new version of the report; the original
observations and earlier versions are preserved, and the system records which conclusions
changed, why, and how confident it is.

**How often results arrive.** The clinical schedule decides, not the platform: it takes whatever
arrives, whenever it arrives. Tissue biopsies are invasive, so they are repeated rarely (typically
when recurrence or progression is suspected). Imaging usually comes every few months during
treatment and blood counts before treatment cycles, while tumor markers and ctDNA can be followed
more often: SERENA-6 tested ctDNA every 2 to 3 months (Bidard et al. 2025). To follow mutations
over time, blood ctDNA is the practical test.

**Tracking progression and predicting change.** With each new result it looks for changes in
disease burden, progression or response, newly observed alterations, shifts in known
subpopulations where the data allow, resistance patterns, and plausible future trajectories with
their uncertainty. Every prediction is later checked against what actually happened, so
performance is measured and improved by properly validated research.

**Narrowing evolutionary pathways.** Repeated observations can make some evolutionary hypotheses
more or less plausible. New evidence can also open new ones, so the aim is to narrow uncertainty
where the evidence supports it, not to promise a small, fully predictable set of futures. The order
in which mutations arose can be partly read from a single sequenced sample: early (clonal)
mutations are in every cancer cell and later ones in only some, and copy-number gains date the
mutations they carry. The Pan-Cancer Analysis of Whole Genomes reconstructed driver timing this
way for 2,658 cancers, and found that late driver mutations come from a nearly four times more
diverse set of genes than early ones (Gerstung et al. 2020): the set of possible routes can grow
as well as shrink. Repeated samples over time make the reconstruction far more reliable.

## Part three: investigating treatment strategies
For each timepoint, summarize treatment evidence for the observed subtype and molecular profile,
treatments studied in comparable patients, known resistance mechanisms for the observed
alterations, research-supported combinations worth investigating, and the uncertainties,
contraindications and missing information that need clinical review. Two questions guide it: how
can the current tumor be controlled, and how might future resistance be anticipated?

**Evolution-informed strategies.** The idea is to treat with the tumor's evolution in mind. Each
treatment should shrink the tumor and close the escape routes it is most likely to take next, so
that fewer routes remain at each step, until a combination can block the remaining ones at once,
with drugs that slow growth holding it back in between. This is an active research field, and
the evidence for its parts differs:
- **Switching before progression works in breast cancer.** In PADA-1, patients whose blood showed
  a rising ESR1 mutation during aromatase inhibitor plus palbociclib therapy, without progression,
  did better when switched to fulvestrant plus palbociclib: median progression-free survival 11.9
  vs 5.7 months (Bidard et al. 2022). SERENA-6 confirmed the approach with camizestrant: 16.0 vs
  9.2 months (Bidard et al. 2025).
- **In models, combinations beat one drug at a time.** Dual therapy can control disease long term
  if no single mutation gives resistance to both drugs, and giving the drugs together works much
  better than giving them in sequence (Bozic et al. 2013). Closing routes one at a time gives the
  tumor time to find another.
- **"First strike, second strike" extinction therapy** first reduces the tumor's size and
  diversity, then quickly adds new treatments while the population is small and vulnerable; it is
  supported by mathematical models and the history of pediatric leukemia treatment (Gatenby et al.
  2020).
- **Adaptive therapy** aims for control rather than eradication when cure is out of reach: it
  doses so that drug-sensitive cells keep resistant ones in check. In a pilot trial in 11 men with
  prostate cancer, median time to progression was at least 27 months, against about 16.5 reported
  with standard dosing, using 47% of the standard cumulative dose (Zhang et al. 2017).
- **Evolutionary steering** uses one drug to push the tumor toward a state that another drug
  kills (collateral sensitivity); it has been shown in lung cancer cell models (Acar et al. 2020).

Whether a treatment prevents a given mutation or improves survival must come from scientific and
clinical evidence. The platform lays out the evidence, the tumor's likely escape routes and these
strategies as hypotheses for clinicians and researchers. Software that told clinicians which
treatment to give would be regulated as a medical device; this platform never prescribes.

## Part four: learning from contributed data
Start with public datasets and pretrained models; later, with permissions, governance, privacy
safeguards and validation, learn from data contributed by pathologists and research institutions
(more patients, more scanners and labs, independent validation, more longitudinal records,
under-represented patterns). Storing an observation, updating a research dataset and retraining a
model are different steps, and new data never becomes training data automatically. **Federated
learning** lets institutions contribute to training without centralizing patient data; prototype
sites are labeled as simulated. No real patient data comes from clinicians during the hackathon:
that needs consent, ethics approval and data agreements, so the mechanism is shown with simulated
hospitals.

## Part five: datasets, pretrained models and architecture
Systematically survey public datasets (pathology and radiology images, clinical and longitudinal
records, genomic and transcriptomic data, data linking molecules to treatment and outcome) and
pretrained biomedical models, with license, access, compute needs and validation evidence for
each (`docs/registry.md`). A central orchestration layer coordinates the models, each with
defined inputs, outputs, limitations and evaluation criteria; components are added only when they
measurably help. Each test type has its own analysis pipeline and viewer, and all of them feed one
shared patient record ([`WORKSPACE.md`](WORKSPACE.md)). Gated models need access requests before
they can be used.

## Milestone 1 (hackathon, due Oct 30 2026) and the roadmap

| Vision | Milestone 1 delivers | Roadmap |
|---|---|---|
| Choose the cancer | Breast cancer, with the comparison above | Further cancers |
| Multimodal profile | 5 data layers on TCGA-BRCA (copy number, RNA, methylation, protein, clinical); missing layers handled by masking | Pathology slides, radiology, labs, clinical notes via pretrained encoders |
| Orchestration | Nemotron case agent on Nebius Token Factory calling our models, CIViC and Tavily as tools | More specialized models, each added when it measurably helps |
| Observed vs inferred vs hypothesis | Every statement in the case note labeled; observed driver mutations (open GDC data) next to model inferences | Inferred mutation status from other layers with calibrated uncertainty |
| Longitudinal file | Real timelines from MSK-CHORD for evaluation (local only, aggregate results); a labeled synthetic timeline patient in the demo | Real contributed timelines, imaging over time, ctDNA |
| Progression prediction | Risk of progression or death in the next 12 months, re-predicted at each new event; measured against baselines as the record grows | Trajectory and tumor-marker forecasts, resistance patterns |
| Evolutionary pathways | Not attempted | Clonal-fraction based hypotheses with repeated sequencing |
| Treatment evidence | CIViC evidence for observed drivers, for clinician review; literature via Tavily | Resistance mechanisms; evolution-informed strategies as hypotheses (part three) |
| Contributed data / federation | NVFlare FedAvg across 3 simulated hospitals on TCGA-BRCA: beats any single hospital, close to pooled training | Real institutions, privacy techniques (DP, secure aggregation) |
| Clinician workspace | Demo app: synthetic timeline patient, held-out case review, federation results | Patient list, versioned reports, test import, a workbench per test type (`WORKSPACE.md`) |
| Registry | `docs/registry.md` with license and access tier per resource | Kept current as components are added |

Measured so far (TCGA-BRCA, overall survival, leave one hospital out, 5 seeds): FedAvg 0.693,
pooled training 0.700, one hospital alone 0.649, clinical data alone 0.702. On this endpoint the
omics do not yet add signal beyond clinical stage and age; we say so plainly.

## References
- Acar A et al. Exploiting evolutionary steering to induce collateral drug sensitivity in cancer.
  *Nat Commun* 2020. https://doi.org/10.1038/s41467-020-15596-z
- Bailey MH et al. Comprehensive characterization of cancer driver genes and mutations. *Cell*
  2018. https://doi.org/10.1016/j.cell.2018.02.060
- Bidard FC et al. Switch to fulvestrant and palbociclib versus no switch in advanced breast
  cancer with rising ESR1 mutation (PADA-1). *Lancet Oncol* 2022.
  https://doi.org/10.1016/S1470-2045(22)00555-1
- Bidard FC et al. First-line camizestrant for emerging ESR1-mutated advanced breast cancer
  (SERENA-6). *N Engl J Med* 2025. https://doi.org/10.1056/NEJMoa2502929
- Bozic I et al. Evolutionary dynamics of cancer in response to targeted combination therapy.
  *eLife* 2013. https://doi.org/10.7554/eLife.00747
- Egeblad M, Nakasone ES, Werb Z. Tumors as organs: complex tissues that interface with the entire
  organism. *Dev Cell* 2010. https://doi.org/10.1016/j.devcel.2010.05.012
- Gatenby RA et al. Eradicating metastatic cancer and the eco-evolutionary dynamics of
  Anthropocene extinctions. *Cancer Res* 2020. https://doi.org/10.1158/0008-5472.CAN-19-1941
- Gerstung M et al. The evolutionary history of 2,658 cancers. *Nature* 2020.
  https://doi.org/10.1038/s41586-019-1907-7
- Vogelstein B et al. Cancer genome landscapes. *Science* 2013.
  https://doi.org/10.1126/science.1235122
- Zhang J et al. Integrating evolutionary dynamics into treatment of metastatic
  castrate-resistant prostate cancer. *Nat Commun* 2017.
  https://doi.org/10.1038/s41467-017-01968-5
