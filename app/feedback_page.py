"""The Feedback page (docs/feedback.md; docs/VISION.md part four, learning from clinicians): every
review mark of this browser session as a ledger with filters, the share of findings marked
disagree per model or rule (the signal a future training round would use), the disagreed
findings as a queue that opens each one in its patient file, a summary per reviewer, the ledger's
download and upload, what happens with the marks today, and the roadmap.

Nothing on this page trains or changes a model: marks stay in the browser session and in the
files the clinician downloads. The shell calls ``render(files, build, open_finding, patients)``:
the patient files (id -> ``PatientFile``), the app build (a code digest), a callback that opens
a finding in its file (pid, opens, focus) and the Patients page to switch to.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from muffle import feedback, workspace
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.workbench.grammar import chip, esc
from workbenches._page import line_and_action

GOTO = "feedback-goto"  # set by "Open": switch to the Patients page on the next run
KIND = {"synthetic": "synthetic (written by hand)", "TCGA-BRCA": "TCGA-BRCA public case"}


def tags(text: str) -> str:
    return " ".join(chip(e) for e in (OBSERVED, INFERENCE, HYPOTHESIS) if e in text)


def render(files: dict, build: str, open_finding, patients) -> None:
    if st.session_state.pop(GOTO, False):
        st.switch_page(patients)
    reviews = st.session_state.setdefault("reviews", {})
    records = feedback.ledger(reviews, files, build)
    st.title("Feedback")
    st.markdown(
        "Every review mark made in this browser session, as a ledger you can filter, download "
        "and load again. The share of findings marked **disagree**, per model or rule, is the "
        "signal a future training round would use. Nothing here trains or changes a model.")
    st.caption(workspace.DISCLAIMER)
    today()
    if not records:
        st.info("No marks yet. Mark a finding in a patient file (**Review** next to it, or **m** "
                "in the report's attention queue); it appears here.", icon="🗳️")
    else:
        bad = feedback.disagreed(records)
        with st.container(horizontal=True):
            st.metric("Marks", len(records), width="content")
            st.metric("Patients", len({x["patient"] for x in records}), width="content")
            st.metric("Reviewers", len({x["reviewer"] for x in records}), width="content")
            st.metric("Disagreed", len(bad), width="content")
        ledger_table(records)
        signal(records)
        queue(bad, files, open_finding)
        per_reviewer(records)
    transfer(records, files)
    roadmap(records)


def today() -> None:
    with st.container(border=True):
        st.markdown(f"**What happens with your marks today** {chip(workspace.IMPLEMENTED)}")
        st.markdown(
            "- They stay in this browser session: closing the tab ends them, and nothing is "
            "stored on the server or sent anywhere.\n"
            "- They go into the files you download: each report export (Review marks and "
            "Feedback sections) and the ledger below (JSON lines), which you can load again "
            "into a later session.\n"
            "- They change nothing: no model, rule, cutoff or alert is re-trained, re-calibrated "
            "or switched off by a mark. A mark is a clinician's judgment on one finding, not a "
            "measured error rate.")


def ledger_table(records: list[dict]) -> None:
    st.subheader("Ledger")
    f = st.columns(4)
    pick = {}
    for col, (field, label) in zip(f, (("patient", "Patient"), ("kind", "Finding kind"),
                                       ("mark", "Mark"), ("reviewer", "Reviewer")), strict=True):
        pick[field] = col.multiselect(label, sorted({x[field] for x in records}),
                                      key=f"feedback-{field}", placeholder="Any",
                                      format_func=lambda v: v or "no initials")
    shown = [x for x in records if all(not v or x[k] in v for k, v in pick.items())]
    st.dataframe(pd.DataFrame([{
        "When": x["at"], "Patient": x["patient"], "Patient kind": KIND.get(x["patient_kind"],
                                                                          x["patient_kind"]),
        "Finding kind": x["kind"], "Finding": x["finding"], "Mark": x["mark"],
        "Reviewer": x["reviewer"] or "no initials", "Model or rule": x["method"],
        "Version": x["method_version"], "Evidence": x["evidence"]} for x in shown],
        columns=["When", "Patient", "Patient kind", "Finding kind", "Finding", "Mark",
                 "Reviewer", "Model or rule", "Version", "Evidence"]),
        hide_index=True, width="stretch", column_config={
            "Model or rule": st.column_config.TextColumn(
                help="Derived from the finding's kind; its card is on Methods and validation"),
            "Evidence": st.column_config.TextColumn(
                help="Observed, model inference or hypothesis, as the finding is labeled")})
    st.caption(f"{len(shown)} of {len(records)} marks, newest first. SYNTHETIC-001 is a "
               "synthetic patient written by hand; the TCGA cases are public TCGA-BRCA patients "
               "assigned to simulated hospitals.")


def signal(records: list[dict]) -> None:
    st.subheader("Disagreement per model or rule")
    by = st.segmented_control("Group by", ["Model or rule", "Finding kind"],
                              default="Model or rule", key="feedback-by", required=True)
    field = "method" if by == "Model or rule" else "kind"
    groups = feedback.rates(records, field)
    table = pd.DataFrame([{
        by: g[field], "Reviewed": g["n"], "Agree": g["agree"], "Disagree": g["disagree"],
        "Second look": g["second look"], "Reviewed only": g["reviewed"],
        "Disagreed": g["rate"], "95% interval": f"{g['low']:.0%}–{g['high']:.0%}"}
        for g in groups])
    bars = alt.Chart(table).encode(y=alt.Y(f"{by}:N", sort=None, title=None))
    chart = (bars.mark_bar(color="#c0392b").encode(
        x=alt.X("Disagreed:Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%"),
                title="share of reviewed findings marked disagree"),
        tooltip=[by, "Reviewed", "Disagree", "Second look", "95% interval"])
        + alt.Chart(pd.DataFrame([{by: g[field], "low": g["low"], "high": g["high"]}
                                  for g in groups])).mark_rule(color="#555").encode(
            y=alt.Y(f"{by}:N", sort=None), x="low:Q", x2="high:Q"))
    st.altair_chart(chart.properties(height=max(80, 28 * len(groups))), width="stretch")
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        "Disagreed": st.column_config.NumberColumn(format="percent")})
    st.caption(
        "Every mark counts as a reviewed finding; the share is disagree / reviewed, with its 95% "
        "Wilson interval (the gray line): a few marks say little, and the interval says how "
        "little. These are this session's marks, not a validation of any model; each model and "
        "rule keeps its measured numbers on Methods and validation, where its card now shows "
        "these counts.")


def queue(bad: list[dict], files: dict, open_finding) -> None:
    st.subheader(f"Findings you disagreed with · {len(bad)}")
    if not bad:
        st.caption("None marked disagree.")
        return
    for n, x in enumerate(bad):
        pf = files.get(x["patient"])
        where = feedback.target(pf, x["key"]) if pf else None
        line, act = line_and_action()
        line.markdown(f"**{esc(x['finding'])}** {tags(x['evidence'])}  \n"
                      f"{x['patient']} · {x['kind']} · {x['method']} · "
                      f"{x['reviewer'] or 'no initials'}, {x['at']}")
        act.button("Open", key=f"feedback-open-{n}", disabled=where is None,
                   help="Opens the finding in its patient file" if where else
                   "This finding is not in the file as loaded (an import from another session?)",
                   on_click=_open, args=(open_finding, x["patient"], *(where or ((), None))))
    st.caption("Open lands on the finding's test or view in its patient file, as the report's "
               "attention queue does.")


def _open(open_finding, pid: str, opens: tuple, focus: dict | None) -> None:
    open_finding(pid, opens, focus)
    st.session_state[GOTO] = True


def per_reviewer(records: list[dict]) -> None:
    st.subheader("Per reviewer")
    st.dataframe(pd.DataFrame([{
        "Reviewer": r["reviewer"], "Marks": r["n"], "Agree": r["agree"],
        "Disagree": r["disagree"], "Second look": r["second look"],
        "Reviewed only": r["reviewed"], "Patients": r["patients"], "First": r["first"],
        "Last": r["last"]} for r in feedback.reviewers(records)]),
        hide_index=True, width="stretch")
    st.caption("Initials as typed in the sidebar; nothing checks who typed them.")


def transfer(records: list[dict], files: dict) -> None:
    st.subheader("Download and load the ledger")
    st.download_button(
        "Download the feedback ledger (JSON lines)", feedback.export(records),
        file_name="muffle_feedback.jsonl", mime="application/x-ndjson",
        disabled=not records,
        help=f"One record per mark, schema {feedback.SCHEMA} (docs/feedback.md): the finding as "
             "its card shows it, the model or rule behind it, its version and inputs, the mark, "
             "the reviewer and time. No patient data beyond what the finding card shows.")
    up = st.file_uploader("Load a downloaded ledger into this session", type=["jsonl", "json"],
                          key="feedback-upload",
                          help="Read in this browser session only; nothing is stored on the "
                               "server.")
    if up is None:
        return
    loaded, rejected = feedback.load(up.getvalue(), files)
    st.markdown(f"**{len(loaded)}** mark{'s' if len(loaded) != 1 else ''} can be added"
                + (f"; {len(rejected)} line{'s' if len(rejected) != 1 else ''} rejected"
                   if rejected else "") + ".")
    if rejected:
        with st.expander("Rejected lines and why"):
            st.markdown("\n".join(f"- {r}" for r in rejected[:50]))
    st.button("Add these marks to this session", key="feedback-add", disabled=not loaded,
              on_click=_add, args=(loaded,),
              help="For a finding marked both here and in the file, the later mark wins.")
    if "feedback-added" in st.session_state:  # once, after "Add"
        added, replaced = st.session_state.pop("feedback-added")
        st.success(f"Added {added} mark{'s' if added != 1 else ''}, replaced {replaced} older "
                   "one" + ("s" if replaced != 1 else "") + ".")


def _add(loaded: dict) -> None:
    merged, added, replaced = feedback.merge(st.session_state.reviews, loaded)
    st.session_state.reviews.clear()
    st.session_state.reviews.update(merged)
    st.session_state["feedback-added"] = (added, replaced)


def roadmap(records: list[dict]) -> None:
    bad = feedback.disagreed(records)
    placeholder = sorted({x["method"] for x in bad if "placeholder" in x["method_version"]})
    tiles = sum(x["kind"] == "slide" for x in bad)
    with st.container(border=True):
        st.markdown(f"**What a training round would do with them** {chip(workspace.PLANNED)}")
        st.caption(f"Roadmap, {feedback.ROADMAP}. Storing a mark, updating a research dataset "
                   "and retraining a model are different steps, and a mark never becomes "
                   "training data by itself (docs/VISION.md, part four).")
        st.markdown(
            "- **Re-calibrate placeholder cutoffs** against the findings clinicians disagreed "
            "with, then validate the new cutoffs on held-out patients before any is used"
            + (f" (disagreed this session: {', '.join(placeholder)})" if placeholder else "")
            + ".\n"
            "- **Retrain the slide tissue head** with disagreed tiles as new labels, once a "
            "pathologist confirms them" + (f" ({tiles} tile{'s' if tiles != 1 else ''} "
                                           "disagreed this session)" if tiles else "") + ".\n"
            "- **Federated rounds across sites**: each hospital keeps its marks and data and "
            "sends only model updates, as the survival model is trained today across simulated "
            "hospitals with NVIDIA FLARE (Methods and validation). Real sites need consent, "
            "ethics approval and data agreements first.")
