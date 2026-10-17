# Running on Nebius AI Cloud

Researched 2026-10-16 from docs.nebius.com. Check the docs if a flag has changed.

**Optional — not in the submission plan.** Since 2026-10-17 our only Nebius usage is Token
Factory on the free hackathon credits (see `docs/decisions.md`). Keep this for later.

## One-time
1. Install the CLI and create a profile (opens a browser login):
   `curl -sSL https://artifacts.nebius.cloud/cli/install.sh | bash` then `nebius profile create --profile muffle --endpoint api.nebius.cloud --federation-endpoint auth.nebius.com --parent-id <PROJECT_ID>` (browser login)
2. Find your subnet: `nebius vpc subnet list --format jsonpath='{.items[0].metadata.id}'`
3. Build and push the image to a registry Nebius can pull from (Nebius Container Registry or
   GHCR): `docker build --platform linux/amd64 -t <registry>/muffle:latest . && docker push ...`
   (Apple Silicon builds arm64 by default — `--platform linux/amd64` is required.)

## FL training as a Serverless Job (counts as "runs on Nebius AI Cloud")
```bash
nebius ai job create \
  --name muffle-fl \
  --image <registry>/muffle:latest \
  --container-command "bash" \
  --args "-c 'make fl VENV=/usr GPU=0 ROUNDS=30'" \
  --platform gpu-l40s-a --preset 1gpu-8vcpu-32gb \
  --volume 's3://<bucket>:/app/data:rw:<profile>' \
  --disk-size 100Gi --timeout 2h \
  --subnet-id $SUBNET_ID
nebius ai job logs <job_ID> --follow
nebius ai job cancel <job_ID>     # stop billing early
```
The VM is billed only while the job runs and is removed when it completes. Volumes persist —
delete buckets/filesystems you no longer need.

## Interactive GPU VM (when debugging)
Platform `gpu-h100-sxm`, preset `1gpu-16vcpu-200gb`, image family `ubuntu24.04-cuda13.0`.
See the Compute quickstart. **Stop VMs when you're done** — idle GPUs burn credits.

## Token Factory (Nemotron)
OpenAI-compatible base URL `https://api.tokenfactory.nebius.com/v1`, key in `NEBIUS_API_KEY`.
List available NVIDIA model ids: `python -m muffle.report.nemotron --list-models`, then set
`NEMOTRON_MODEL` in `.env`.
