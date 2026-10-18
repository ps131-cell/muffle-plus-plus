# Calibration and fairness checks (TCGA-BRCA, overall survival)

`make calibration-tcga` (`python -m muffle.calibration`). Every patient is scored by a model
trained **without their hospital**: each of the 3 FL clients is held out in turn, the model
trains on the other two hospitals' training splits, and predicts all of the held-out
hospital's patients. Survival curves use the Breslow baseline of each fold's training
patients. Seed 0; 1,064 patients, 148 deaths.

## Takeaways
- **Calibrated within ~2 percentage points.** Predicted 3-year death risk per risk quintile
  is close to the Kaplan-Meier observed rate (mean absolute error 0.019–0.027). All models
  over-predict a little for the lowest-risk 40% of patients.
- **Ranking is the useful output, not absolute probabilities.** Brier scores beat the
  "no model" Kaplan-Meier reference only slightly (integrated 0.095–0.098 vs 0.101) at a 14%
  death rate. The demo and the case agent should keep talking in percentiles and risk groups
  (as `predict_risk` already does), not "X% chance of death".
- **Discrimination fades with horizon** (AUC ~0.69–0.77 at 2 years → ~0.61–0.65 at 5 years).
- **Weaker slices:** patients under 50 (C 0.62–0.67 vs 0.71–0.75 for ages 50–64), and within
  stage II (~0.60): much of the ranking comes from stage itself. FedAvg-residual's 0.43 within
  stage I rests on 15 deaths; treat slices with ≤ 15 deaths as noise.
- **Order of models** matches the leave-one-site-out results: clinical-only ≥ residual >
  FedAvg-residual on discrimination; the residual models are slightly better calibrated.

Caveats: one seed; slices are small; the Breslow baseline is computed centrally here (in a
federation it can come from per-site binned risk-set sums).

## Tables (seed 0)
### Discrimination and error (all patients, cross-site)
| metric | clinical | residual | fedavg_residual |
|---|---|---|---|
| C-index (site-stratified) | 0.703 | 0.693 | 0.671 |
| AUC at 2y | 0.766 | 0.723 | 0.688 |
| AUC at 3y | 0.697 | 0.688 | 0.663 |
| AUC at 5y | 0.652 | 0.643 | 0.611 |
| Brier at 2y (KM ref 0.047) | 0.045 | 0.045 | 0.046 |
| Brier at 3y (KM ref 0.093) | 0.088 | 0.088 | 0.090 |
| Brier at 5y (KM ref 0.147) | 0.141 | 0.138 | 0.143 |
| Integrated Brier (KM ref 0.101) | 0.096 | 0.095 | 0.098 |
| Calibration error at 3y (mean abs, quintiles) | 0.027 | 0.019 | 0.021 |

### C-index by age (n, deaths)
| slice | clinical | residual | fedavg_residual |
|---|---|---|---|
| 50-64 (n=449, 51) | 0.750 | 0.737 | 0.713 |
| <50 (n=292, 38) | 0.622 | 0.627 | 0.673 |
| >=65 (n=323, 59) | 0.668 | 0.637 | 0.641 |

### C-index by stage (n, deaths)
| slice | clinical | residual | fedavg_residual |
|---|---|---|---|
| I (n=180, 15) | 0.695 | 0.662 | 0.427 |
| II (n=601, 65) | 0.612 | 0.599 | 0.599 |
| III-IV (n=260, 58) | 0.623 | 0.659 | 0.614 |
| unknown (n=23, 10) | 0.439 | 0.585 | 0.659 |

### C-index by hospital (n, deaths)
| slice | clinical | residual | fedavg_residual |
|---|---|---|---|
| site-1 (n=355, 68) | 0.680 | 0.701 | 0.647 |
| site-2 (n=355, 56) | 0.678 | 0.656 | 0.670 |
| site-3 (n=354, 24) | 0.791 | 0.731 | 0.725 |

### Calibration at 3 years: clinical (predicted vs observed death risk)
| risk quintile | n | deaths | predicted | observed (KM) |
|---|---|---|---|---|
| 1 | 213 | 21 | 0.071 | 0.044 |
| 2 | 213 | 19 | 0.084 | 0.037 |
| 3 | 211 | 26 | 0.097 | 0.093 |
| 4 | 214 | 26 | 0.135 | 0.111 |
| 5 | 213 | 56 | 0.212 | 0.243 |

### Calibration at 3 years: residual (predicted vs observed death risk)
| risk quintile | n | deaths | predicted | observed (KM) |
|---|---|---|---|---|
| 1 | 213 | 11 | 0.056 | 0.030 |
| 2 | 213 | 28 | 0.078 | 0.070 |
| 3 | 212 | 28 | 0.101 | 0.110 |
| 4 | 213 | 28 | 0.140 | 0.086 |
| 5 | 213 | 53 | 0.235 | 0.235 |

### Calibration at 3 years: fedavg_residual (predicted vs observed death risk)
| risk quintile | n | deaths | predicted | observed (KM) |
|---|---|---|---|---|
| 1 | 213 | 14 | 0.074 | 0.044 |
| 2 | 213 | 21 | 0.094 | 0.050 |
| 3 | 212 | 31 | 0.112 | 0.100 |
| 4 | 213 | 35 | 0.137 | 0.132 |
| 5 | 213 | 47 | 0.182 | 0.197 |
