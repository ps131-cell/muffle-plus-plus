PY      ?= python3
VENV    ?= .venv
BIN      = $(VENV)/bin
TORCH   ?= cpu          # Linux only: cpu | cu126 | cu128 (Mac always uses the default wheel)
GPU     ?=              # e.g. GPU=0 to run the FL simulator on a GPU
CLIENTS ?= 3
ROUNDS  ?= 10
FL_CKPT ?= workspaces/muffle_fedavg/server/simulate_job/app_server/FL_global_model.pt

.PHONY: setup test lint synth tcga local fl compare demo clean-nb docker

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
	$(BIN)/ruff check src tests jobs scripts

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

# after `make fl`: per-site C-index table, centralized vs local-only vs the final FedAvg model
compare: synth
	$(BIN)/python -m muffle.train_local --data data/synthetic --config configs/default.yaml \
		--n-clients $(strip $(CLIENTS)) --fl-ckpt $(FL_CKPT)

demo:
	$(BIN)/streamlit run app/streamlit_app.py -- --ckpt outputs/centralized.pt --data data/synthetic

clean-nb:
	$(BIN)/nbstripout notebooks/*.ipynb

docker:
	docker build -t muffle:dev .
