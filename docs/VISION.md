# Vision: a multimodal, longitudinal cancer intelligence platform

MuFFLe++ is the first milestone of a larger idea: an AI-powered cancer **research and clinical
decision-support** platform for one carefully chosen cancer type. It brings together specialized
models, biomedical datasets and each patient's data over time into one continuously updated
understanding of that patient's disease. It is research support for qualified clinicians and
researchers, never a diagnosis or a prescription.

The milestone we build for the hackathon is smaller and rigorously evaluated. The table at the
end maps each part of the vision to what milestone 1 delivers and what stays on the roadmap.

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
~5,400 breast cancer patients).

**Connecting specialized models and datasets.** An orchestration layer coordinates pretrained
models (Hugging Face and other biomedical resources) across pathology slides, radiology, blood
and lab tests, pathology reports and clinical notes, tumor type/subtype/grade/stage, sequencing
and mutations, gene expression and other molecular data, and treatment history and outcomes. It
cross-references findings with datasets and research evidence, and accounts for data quality,
missing tests, units and the timing of each observation. The result is an evidence-linked cancer
profile that separates confirmed findings from uncertain predictions.

**Mutations and cancer biology.** A cancer is an evolving population of cells with related but
genetically distinct subpopulations; some mutations are drivers, many are passengers. The
platform distinguishes:
1. **Observed mutations**: identified directly by an appropriate molecular test.
2. **Supported molecular inferences**: alterations suggested by other measurements, with the
   uncertainty stated.
3. **Evolutionary hypotheses**: possible mutation orders or pathways inferred from molecular and
   longitudinal evidence.

It never assumes a mutation can be read from an image or a routine blood test, or that mutation
order can always be reconstructed; those conclusions need sequencing and informative samples
over time.

## Part two: longitudinal patient files and tumor evolution
**A patient timeline.** Each patient has a longitudinal file: at each timepoint whatever exists
(images, labs and tumor markers, biopsies and reports, molecular tests, stage, treatments and
their timing, observed tumor changes, response, side effects, outcomes). Each new result is
compared with the record so far; the original observations are preserved, and the system records
which conclusions changed, why, and how confident it is.

**Tracking progression and predicting change.** With each new result it looks for changes in
disease burden, progression or response, newly observed alterations, shifts in known
subpopulations where the data allow, resistance patterns, and plausible future trajectories with
their uncertainty. Every prediction is later checked against what actually happened, so
performance is measured and improved by properly validated research.

**Narrowing evolutionary pathways.** Repeated observations can make some evolutionary hypotheses
more or less plausible. New evidence can also open new ones, so the aim is to narrow uncertainty
where the evidence supports it, not to promise a small, fully predictable set of futures.

## Part three: investigating treatment strategies
For each timepoint, summarize treatment evidence for the observed subtype and molecular profile,
treatments studied in comparable patients, known resistance mechanisms for the observed
alterations, research-supported combinations worth investigating, and the uncertainties,
contraindications and missing information that need clinical review. Two questions guide it: how
can the current tumor be controlled, and how might future resistance be anticipated? Whether a
treatment prevents a given mutation or improves survival must come from scientific and clinical
evidence; the platform supports researchers and clinicians and never prescribes.

## Part four: learning from contributed data
Start with public datasets and pretrained models; later, with permissions, governance, privacy
safeguards and validation, learn from data contributed by pathologists and research institutions
(more patients, more scanners and labs, independent validation, more longitudinal records,
under-represented patterns). Storing an observation, updating a research dataset and retraining a
model are different steps, and new data never becomes training data automatically. **Federated
learning** lets institutions contribute to training without centralizing patient data; prototype
sites are labeled as simulated.

## Part five: datasets, pretrained models and architecture
Systematically survey public datasets (pathology and radiology images, clinical and longitudinal
records, genomic and transcriptomic data, data linking molecules to treatment and outcome) and
pretrained biomedical models, with license, access, compute needs and validation evidence for
each (`docs/registry.md`). A central orchestration layer coordinates the models, each with
defined inputs, outputs, limitations and evaluation criteria; components are added only when they
measurably help.

## Milestone 1 (hackathon, due Oct 30 2026) and the roadmap

| Vision | Milestone 1 delivers | Roadmap |
|---|---|---|
| Choose the cancer | Breast cancer, with the comparison above | Further cancers |
| Multimodal profile | 5 data layers on TCGA-BRCA (copy number, RNA, methylation, protein, clinical); missing layers handled by masking | Pathology slides, radiology, labs, clinical notes via pretrained encoders |
| Orchestration | Nemotron case agent on Nebius Token Factory calling our models, CIViC and Tavily as tools | More specialized models, each added when it measurably helps |
| Observed vs inferred vs hypothesis | Every statement in the case note labeled; observed driver mutations (open GDC data) next to model inferences | Inferred mutation status from other layers with calibrated uncertainty |
| Longitudinal file | Real timelines from MSK-CHORD for evaluation (local only, aggregate results); a labeled synthetic timeline patient in the demo | Real contributed timelines, imaging over time |
| Progression prediction | Risk of progression or death in the next 12 months, re-predicted at each new event; measured against baselines as the record grows | Trajectory and tumor-marker forecasts, resistance patterns |
| Evolutionary pathways | Not attempted | Clonal-fraction based hypotheses with repeated sequencing |
| Treatment evidence | CIViC evidence for observed drivers, for clinician review; literature via Tavily | Resistance mechanisms, combination strategies |
| Contributed data / federation | NVFlare FedAvg across 3 simulated hospitals on TCGA-BRCA: beats any single hospital, close to pooled training | Real institutions, privacy techniques (DP, secure aggregation) |
| Registry | `docs/registry.md` with license and access tier per resource | Kept current as components are added |

Measured so far (TCGA-BRCA, overall survival, leave one hospital out, 5 seeds): FedAvg 0.693,
pooled training 0.700, one hospital alone 0.649, clinical data alone 0.702. On this endpoint the
omics do not yet add signal beyond clinical stage and age; we say so plainly.
