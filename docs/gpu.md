# GPU run: every encoder on a Nebius AI Cloud GPU, in one sitting

Runbook for `scripts/slide_spike.py embed` (the encoder comparison, then whole slides) on a
rented NVIDIA GPU. Written 2026-10-20 from docs.nebius.com and nebius.com/prices; check them if a
flag has changed. Do the click-throughs in [`model_access.md`](model_access.md) first: a model you
cannot download is skipped with a one-line message.

**Before you start: money.** The hackathon event code covers Token Factory; whether your credits
also cover AI Cloud compute (Nebius Builders Program or other) shows on the billing page of the
Nebius console. Check it, and **delete the VM at the end** (step 7): an idle GPU bills by the hour.
This spending is outside `budget.py`, which caps Token Factory calls only.

## What it costs and how long it takes

On-demand prices (nebius.com/prices, 2026-10-20): **L40S with Intel CPU from $1.55 per GPU-hour**
(platform `gpu-l40s-a`, region `eu-north1`), H100 $4.50, H200 $5.40. One L40S is enough; take it.

Estimated seconds per encoder for one 15,000-tile slide on one L40S, from per-tile cost (survey
section 1) and an assumed ~100 TFLOP/s sustained in fp16. **Arithmetic, not measured**; the run
below writes the measured tiles/s into each `timing.json`:

| Encoder | Class | GFLOP per tile | Est. tiles/s | Est. min per 15k-tile slide |
|---|---|---|---|---|
| Path Foundation, GigaPath-Flash | ViT-S | ~9 | thousands (disk-bound) | < 1 |
| QuiltNet-B-32 | ViT-B/32 | ~9 | thousands | < 1 |
| Hibou-B | ViT-B/14 | ~35 | ~2,800 | < 1 |
| CONCH | ViT-B/16 at 448 px | ~150 | ~650 | ~0.5 |
| Hibou-L | ViT-L | ~120 | ~800 | ~0.3 |
| Virchow, UNI2-h | ViT-H | ~330 | ~300 | ~1 |
| Midnight-12k, H-optimus-0 | ViT-g | ~590 | ~170 | ~1.5 |

The comparison on the spike's 2,214 tiles is seconds per model; downloading the weights (up to
~4.5 GB each for the ViT-g models) dominates. Plan **about 2 hours of VM time (~$3 on an L40S)**
for setup, all ten encoders and a few whole slides.

## 1. One-time CLI setup (on the WSL side)

As in [`NEBIUS.md`](NEBIUS.md): install the CLI and create a profile in a project in `eu-north1`
(the L40S region), then find the subnet:

```bash
curl -sSL https://artifacts.nebius.cloud/cli/install.sh | bash
nebius profile create --profile muffle --endpoint api.nebius.cloud --federation-endpoint auth.nebius.com --parent-id <PROJECT_ID>
export SUBNET_ID=$(nebius vpc subnet list --format jsonpath='{.items[0].metadata.id}')
```

## 2. Create the VM

```bash
export USER_DATA=$(jq -Rrs '.' <<EOF
#cloud-config
users:
  - name: muffle
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - $(cat ~/.ssh/id_ed25519.pub)
EOF
)
nebius compute instance create \
  --name muffle-encoders \
  --resources-platform gpu-l40s-a \
  --resources-preset 1gpu-8vcpu-32gb \
  --boot-disk-managed-disk-name muffle-encoders-boot \
  --boot-disk-managed-disk-type network_ssd \
  --boot-disk-managed-disk-size-gibibytes 200 \
  --boot-disk-managed-disk-source-image-family-image-family ubuntu24.04-cuda13.0 \
  --boot-disk-attach-mode READ_WRITE \
  --cloud-init-user-data "$USER_DATA" \
  --network-interfaces '[{"name": "eth0", "ip_address": {}, "public_ip_address": {}, "subnet_id": "'$SUBNET_ID'"}]'
```

`ubuntu24.04-cuda13.0` is the image Nebius recommends for `gpu-l40s-a` (drivers and CUDA
included). No `~/.ssh/id_ed25519.pub`? Make one with `ssh-keygen -t ed25519`. Read the public IP
in the console (Compute → the VM) and set `VM=muffle@<public IP>`.

## 3. Python on the VM

```bash
ssh $VM 'nvidia-smi && sudo apt-get update -q && sudo apt-get install -yq python3-venv rsync && python3 -m venv ~/venv && ~/venv/bin/pip install -q torch torchvision "transformers>=5" timm huggingface_hub python-dotenv numpy pandas scipy pyyaml scikit-learn scikit-image'
```

The default Linux `torch` wheel from PyPI is built with CUDA and runs on the image's driver. For
Path Foundation add `tensorflow[and-cuda]`; for CONCH add
`git+https://github.com/Mahmoodlab/CONCH.git` (both with `~/venv/bin/pip install`).

## 4. Copy code, tiles and the token

```bash
rsync -az --exclude .venv --exclude data --exclude outputs --exclude .env ~/muffle-plus-plus/ $VM:~/muffle-plus-plus/
rsync -az ~/muffle-encoders/work/ $VM:~/muffle-encoders/work/          # 356 MB of spike tiles
grep '^HF_TOKEN=' ~/muffle-plus-plus/.env | ssh $VM 'cat > ~/muffle-plus-plus/.env'   # token only, never printed
```

Whole slides: when the whole-slide pipeline has written `WORK/<slide>/tiles_rgb.npy` and
`tiles.csv` for them, copy that folder the same way (a 15k-tile slide is ~2.3 GB of tiles).

## 5. Run every encoder

```bash
ssh $VM 'cd ~/muffle-plus-plus && for M in wisdomik/QuiltNet-B-32 prov-gigapath/prov-gigapath-flash google/path-foundation histai/hibou-b histai/hibou-L kaiko-ai/midnight bioptimus/H-optimus-0 paige-ai/Virchow MahmoodLab/UNI2-h MahmoodLab/CONCH; do R=~/muffle-encoders/runs/${M##*/}; ~/venv/bin/python scripts/slide_spike.py embed --tiles ~/muffle-encoders/work --work $R --model $M --device auto --batch 64 && ~/venv/bin/python scripts/slide_spike.py train --work $R --test TCGA-C8-A26X-DX1 TCGA-C8-A26Y-DX1 TCGA-EW-A1OV-DX1 > $R/train.log; done; ~/venv/bin/python scripts/slide_spike.py compare --runs ~/muffle-encoders/runs --tiles ~/muffle-encoders/work' | tee ~/muffle-encoders/compare_gpu.md
```

`--device auto` picks CUDA and runs in fp16 autocast, as the cards recommend. A model without
access prints its one-line message and the loop moves on. For whole slides, run `embed` with
`--tiles` pointing at the whole-slide folder and `--work` at a new run folder.

## 6. Copy results back

```bash
for M in QuiltNet-B-32 prov-gigapath-flash path-foundation hibou-b hibou-L midnight H-optimus-0 Virchow; do rsync -azL --include '*/' --include 'embeddings.npy' --include '*.json' --include 'tiles.csv' --include '*.png' --exclude '*' $VM:~/muffle-encoders/runs/$M/ ~/muffle-encoders/runs/$M/; done
for M in UNI2-h CONCH; do rsync -az --include '*/' --include 'timing.json' --include 'head_metrics.json' --exclude '*' $VM:~/muffle-encoders/runs/$M/ ~/muffle-encoders/runs/$M/; done
```

`-L` copies the linked tile tables as files (the pixel stacks stay behind), so `train` and
`result` work on these folders in WSL. The second line is the local-only rule: for the CC BY-NC-ND models only the aggregate numbers
come back; their embeddings and heads are deleted with the VM. Then refresh the table in
[`encoders.md`](encoders.md) with `python scripts/slide_spike.py compare --runs ~/muffle-encoders/runs`.

## 7. Delete the VM (stops billing)

```bash
nebius compute instance delete --id $(nebius compute instance get-by-name --name muffle-encoders --format jsonpath='{.metadata.id}')
nebius compute disk delete --id $(nebius compute disk get-by-name --name muffle-encoders-boot --format jsonpath='{.metadata.id}')
```

Check the console shows neither the VM nor the disk.
