PY      ?= python3
VENV    ?= .venv
BIN      = $(VENV)/bin
TORCH   ?= cpu          # Linux only: cpu | cu126 | cu128 (Mac always uses the default wheel)
GPU     ?=              # e.g. GPU=0 to run the FL simulator on a GPU
CLIENTS ?= 3
ROUNDS  ?= 10
FL_CKPT ?= workspaces/muffle_fedavg/server/simulate_job/app_server/FL_global_model.pt
PATIENT ?= 0

.PHONY: setup test lint synth tcga local fl fl-tcga agent-tcga compare experiment \
	experiment-tcga calibration-tcga demo demo-tcga clean-nb docker

setup:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -U pip
	@if [ "$$(uname)" = "Darwin" ]; then $(BIN)/pip install torch; \
	else $(BIN)/pip install torch --index-url https://download.pytorch.org/whl/$(strip $(TORCH)); fi
	$(BIN)/pip install -r requirements-dev.txt
	$(BIN)/pip install -e .
	$(BIN)/nbstripout --install || true

test:
	$(BIN)/pytest -q

lint:
	$(BIN)/ruff check src tests jobs scripts app

synth:
	$(BIN)/python scripts/make_synthetic.py --out data/synthetic --n-patients 900

# open-tier TCGA-BRCA -> data/tcga_brca/cohort.npz (downloads ~0.4 GB, streams ~3 GB)
tcga:
	$(BIN)/python scripts/prepare_tcga.py

local: synth
	$(BIN)/python -m muffle.train_local --data data/synthetic --config configs/default.yaml

fl: synth
	$(BIN)/python jobs/fedavg_job.py --data data/synthetic --n-clients $(strip $(CLIENTS)) \
		--rounds $(strip $(ROUNDS)) $(if $(strip $(GPU)),--gpu $(strip $(GPU)),)

# real data (after `make tcga`): clinical-anchored residual FedAvg across the 3 hospitals
# (20 anchor + 20 residual rounds, λ by federated evaluation) -> outputs/tcga_fedavg.pt
fl-tcga:
	$(BIN)/python jobs/fedavg_job.py --data data/tcga_brca --config configs/tcga_brca.yaml \
		--n-clients $(strip $(CLIENTS)) --workspace workspaces/tcga --residual \
		--save outputs/tcga_fedavg.pt

# Nemotron case agent on one TCGA patient, real gene names (offline template without a key)
agent-tcga:
	$(BIN)/python -m muffle.report.nemotron --agent --ckpt outputs/tcga_fedavg.pt \
		--data data/tcga_brca --patient $(strip $(PATIENT))

# repeated seeds: centralized vs local-only vs FedAvg (+ single-modality baselines), mean ± sd
experiment: synth
	$(BIN)/python -m muffle.experiment --data data/synthetic --n-clients $(strip $(CLIENTS)) \
		--seeds 0 1 2

# real data (after `make tcga`): hospital clients, 5 seeds, plus leave-one-site-out (~15 min)
experiment-tcga:
	$(BIN)/python -m muffle.experiment --data data/tcga_brca --config configs/tcga_brca.yaml \
		--n-clients $(strip $(CLIENTS)) --seeds 0 1 2 3 4 --loso

# cross-site calibration + fairness slices: clinical vs residual vs FedAvg-residual (~8 min)
calibration-tcga:
	$(BIN)/python -m muffle.calibration --data data/tcga_brca --config configs/tcga_brca.yaml \
		--n-clients $(strip $(CLIENTS)) --seed 0

# after `make fl`: per-site C-index table, centralized vs local-only vs the final FedAvg model
compare: synth
	$(BIN)/python -m muffle.train_local --data data/synthetic --config configs/default.yaml \
		--n-clients $(strip $(CLIENTS)) --fl-ckpt $(FL_CKPT)

demo:
	$(BIN)/streamlit run app/streamlit_app.py -- --ckpt outputs/centralized.pt --data data/synthetic

demo-tcga:
	$(BIN)/streamlit run app/streamlit_app.py -- --ckpt outputs/tcga_fedavg.pt --data data/tcga_brca

clean-nb:
	$(BIN)/nbstripout notebooks/*.ipynb

docker:
	docker build -t muffle:dev .
