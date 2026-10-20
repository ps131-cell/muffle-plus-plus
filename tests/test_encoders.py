"""The encoder table in scripts/slide_spike.py: every entry is complete, CC BY-NC-ND models never
write into the repository, and a gated model without a token stops with one line."""

import importlib.util
import json
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("slide_spike", ROOT / "scripts" / "slide_spike.py")
spike = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spike)

LOADERS = {"hf_auto", "hf_clip", "timm", "timm_file", "tf_savedmodel", "conch"}
POOLS = {"cls+mean", "clip_proj", "pooler", "pooled", "output_0", "conch_image"}


@pytest.mark.parametrize("name", list(spike.ENCODERS))
def test_every_encoder_is_complete(name):
    spec = spike.ENCODERS[name]
    assert spec["license"] and spec["gate"]
    assert spec["loader"] in LOADERS and spec["pool"] in POOLS
    assert spec["size"] in (224, 448)
    assert len(spec["mean"]) == 3 and len(spec["std"]) == 3 and min(spec["std"]) > 0
    assert spec["params_m"] > 0 and spec["dim"] > 0
    assert isinstance(spec["local_only"], bool)
    if spec.get("remote_code"):  # repo code runs on load: pinned to a reviewed revision
        assert len(spec["revision"]) == 40
    if spec["loader"] == "timm_file":
        assert spec["arch"]


def test_nc_nd_models_are_local_only():
    nc_nd = {n for n, s in spike.ENCODERS.items() if "NC-ND" in s["license"]}
    assert nc_nd == spike.LOCAL_ONLY
    assert {"MahmoodLab/UNI2-h", "MahmoodLab/CONCH"} <= spike.LOCAL_ONLY


def test_local_only_result_refuses_the_app_folder(tmp_path):
    (tmp_path / "timing.json").write_text(json.dumps({"model": "MahmoodLab/UNI2-h"}))
    out = ROOT / "app" / "workbenches" / "uni2_example_test"
    with pytest.raises(SystemExit, match="local only"):
        spike.cmd_result(Namespace(work=tmp_path, slide="S", out=out))
    assert not out.exists()


def test_local_only_guard_covers_the_whole_repository(tmp_path):
    for path in (ROOT / "app", ROOT / "outputs" / "runs", ROOT):
        with pytest.raises(SystemExit):
            spike.guard_local("MahmoodLab/CONCH", path)
    spike.guard_local("MahmoodLab/CONCH", tmp_path)                   # outside: allowed
    spike.guard_local("wisdomik/QuiltNet-B-32", ROOT / "app" / "x")   # open model: allowed


def test_gated_model_without_token_stops_with_one_line(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "")
    monkeypatch.delenv("HF_TOKEN")
    with pytest.raises(SystemExit) as e:
        spike.require_access("histai/hibou-b", env_file=tmp_path / "missing.env")
    msg = str(e.value)
    assert "\n" not in msg
    assert "https://huggingface.co/histai/hibou-b" in msg and "HF_TOKEN" in msg


def test_token_from_env_file_is_used_and_never_printed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HF_TOKEN", "")
    monkeypatch.delenv("HF_TOKEN")
    env = tmp_path / ".env"
    env.write_text("HF_TOKEN=hf_test_not_a_real_token\n")
    spike.require_access("bioptimus/H-optimus-0", env_file=env)  # no exit
    out = capsys.readouterr()
    assert "hf_test_not_a_real_token" not in out.out + out.err


def test_open_model_needs_no_token_and_unknown_model_stops(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "")
    monkeypatch.delenv("HF_TOKEN")
    spike.require_access("kaiko-ai/midnight", env_file=tmp_path / "missing.env")
    with pytest.raises(SystemExit, match="Unknown encoder"):
        spike.require_access("someone/else", env_file=tmp_path / "missing.env")


def test_compare_table_fills_measured_rows_and_lists_pending_commands(tmp_path):
    run = tmp_path / "QuiltNet-B-32"
    run.mkdir()
    (run / "timing.json").write_text(json.dumps(
        {"model": "wisdomik/QuiltNet-B-32", "device": "cpu", "threads": 2,
         "load_1min_start": 0.7, "tiles_per_s_median": 5.0}))
    per = {c: {"recall": 0.9} for c in spike.HEAD_CLASSES}
    (run / "head_metrics.json").write_text(json.dumps(
        {"accuracy": 0.877, "balanced_accuracy": 0.854, "per_class": per}))
    table = spike.compare_table(tmp_path)
    quilt = next(line for line in table.splitlines() if "QuiltNet" in line)
    assert "0.877 (0.854)" in quilt and "| 50 |" in quilt  # 15,000 tiles at 5/s = 50 min
    assert "HF_TOKEN=… python scripts/slide_spike.py embed" in table
    assert "--model histai/hibou-L" in table
    assert "--model wisdomik/QuiltNet-B-32 &&" not in table
