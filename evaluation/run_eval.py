"""Compare keyword-only, TF-IDF and MiniLM matching on the synthetic labelled set.

Usage (from the repo root, venv active):
    python -m evaluation.build_dataset     # (re)create evaluation/data/eval_set.json
    python -m evaluation.run_eval          # writes evaluation/results/report.md + results.json

Protocol: resumes are split into DEV (even ids) and TEST (odd ids). The partial-match threshold is chosen on DEV
(best lenient F1) and then reported on TEST, so the headline numbers are not tuned on the data they are reported on.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.matching import SentenceTransformerEmbedder, TfidfEmbedder, match_candidate  # noqa: E402
from evaluation.metrics import ground_truth_score, pair_metrics, spearman  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "eval_set.json"
RESULTS = HERE / "results"


class KeywordOnly:
    """Baseline: exact keyword/alias evidence only; semantic similarity disabled."""
    kind, name, partial_threshold, query_template = "keyword", "Keyword/alias only (baseline)", 2.0, "{req}"

    def similarity(self, queries, segments):
        return np.zeros((len(queries), len(segments)))


class Cached:
    """Wrap an embedder so threshold sweeps do not re-encode the same text."""
    def __init__(self, inner):
        self.inner, self._c = inner, {}
        self.kind, self.name, self.query_template = inner.kind, inner.name, inner.query_template
        self.partial_threshold = inner.partial_threshold

    def similarity(self, queries, segments):
        key = (tuple(queries), tuple(segments))
        if key not in self._c:
            self._c[key] = self.inner.similarity(queries, segments)
        return self._c[key]


def run(embedder, threshold, resumes, jobs, use_filter=True):
    embedder.partial_threshold = threshold
    pairs, job_rows = [], []
    for job in jobs:
        for r in resumes:
            res = match_candidate(r["text"], None, {**job, "description": ""}, embedder, filter_non_evidence=use_filter)
            req_states, pref_states = [], []
            for q in res["requirements"]:
                state = r["states"][q["requirement"]]
                pairs.append({"state": state, "status": q["status"], "type": q["type"]})
                (req_states if q["type"] == "required" else pref_states).append(state)
            job_rows.append({"job": job["title"], "pred": res["score"],
                             "truth": ground_truth_score(req_states, pref_states),
                             "pred_all": res["meets_all_required"],
                             "truth_all": all(s in ("explicit", "paraphrase") for s in req_states)})
    return pairs, job_rows


def summarise(pairs, job_rows):
    out = {"strict": pair_metrics(pairs, False), "lenient": pair_metrics(pairs, True)}
    rhos = []
    for title in sorted({j["job"] for j in job_rows}):
        rows = [j for j in job_rows if j["job"] == title]
        rho = spearman([j["pred"] for j in rows], [j["truth"] for j in rows])
        if rho is not None:
            rhos.append(rho)
    out["mean_spearman_score_vs_truth"] = round(float(np.mean(rhos)), 3) if rhos else None
    tp = sum(j["pred_all"] and j["truth_all"] for j in job_rows)
    fp = sum(j["pred_all"] and not j["truth_all"] for j in job_rows)
    fn = sum((not j["pred_all"]) and j["truth_all"] for j in job_rows)
    from evaluation.metrics import prf
    out["meets_all_required"] = prf(tp, fp, fn)
    return out


def fmt(x):
    return "-" if x is None else f"{x:.2f}"


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    jobs = data["jobs"]
    dev = [r for r in data["resumes"] if r["id"] % 2 == 0]
    test = [r for r in data["resumes"] if r["id"] % 2 == 1]

    # (key, embedder, threshold grid, use intent filter)
    backends = [("keyword", Cached(KeywordOnly()), [2.0], False),
                ("keyword+filter", Cached(KeywordOnly()), [2.0], True),
                ("tfidf+filter", Cached(TfidfEmbedder()), [0.10, 0.15, 0.20, 0.30, 0.40], True)]
    note = ""
    try:
        mini = Cached(SentenceTransformerEmbedder("all-MiniLM-L6-v2"))
        backends.append(("minilm+filter", mini, [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60], True))
    except Exception as exc:
        note = f"MiniLM backend NOT evaluated in this run ({type(exc).__name__}: model/library unavailable)."
        print(note)

    results, sweeps = {}, {}
    for key, emb, grid, use_filter in backends:
        dev_scores = {}
        for t in grid:
            pairs, rows = run(emb, t, dev, jobs, use_filter)
            dev_scores[t] = summarise(pairs, rows)
        best = max(grid, key=lambda t: (dev_scores[t]["lenient"]["f1"] or 0, -t))
        pairs, rows = run(emb, best, test, jobs, use_filter)
        default_t = emb.inner.partial_threshold if not key.startswith("keyword") else 2.0
        results[key] = {"name": emb.name + (" + intent filter" if use_filter else " (no intent filter)"), "chosen_threshold_on_dev": best, "test": summarise(pairs, rows)}
        sweeps[key] = {str(t): {"lenient_f1": dev_scores[t]["lenient"]["f1"],
                                "lenient_precision": dev_scores[t]["lenient"]["precision"],
                                "lenient_recall": dev_scores[t]["lenient"]["recall"]} for t in grid}
        emb.inner.partial_threshold = default_t

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "results.json").write_text(json.dumps({"results": results, "dev_sweeps": sweeps, "note": note}, indent=1))

    L = ["# Evaluation report (synthetic labelled set)", "",
         f"- Resumes: {len(data['resumes'])} synthetic (dev {len(dev)} / test {len(test)}), jobs: {len(jobs)}, seed {data['seed']}",
         "- Unit of evaluation: one (resume, job requirement) pair. Truth: skill present (explicit or paraphrased) vs not (absent or only a wish/plan).",
         "- Threshold chosen on DEV (best lenient F1), numbers below are on TEST.",
         "- **Caveat:** resumes and matcher were written by the same author; this is a controlled comparison, not real-world accuracy.",
         "- 'Strict' = only keyword-matched counts as found; 'Lenient' = matched or partial counts as found.", ""]
    if note:
        L += [f"> {note}", ""]
    L += ["| Method | Thr. | Mode | Precision | Recall | F1 | Spearman (score vs truth) |", "|---|---|---|---|---|---|---|"]
    for key, r in results.items():
        for mode in ("strict", "lenient"):
            m = r["test"][mode]
            L.append(f"| {r['name']} | {r['chosen_threshold_on_dev']} | {mode} | {fmt(m['precision'])} | {fmt(m['recall'])} | "
                     f"{fmt(m['f1'])} | {fmt(r['test']['mean_spearman_score_vs_truth'])} |")
    L += ["", "## Share of requirement pairs flagged as 'found', by true state (lenient, TEST)",
          "Explicit/paraphrase rows are recall (higher is better); distractor/absent rows are false-positive rates (lower is better).", "",
          "| Method | explicit | paraphrase | distractor | absent |", "|---|---|---|---|---|"]
    for key, r in results.items():
        d = r["test"]["lenient"]["flagged_rate_by_state"]
        L.append(f"| {r['name']} | {d.get('explicit', '-')} | {d.get('paraphrase', '-')} | {d.get('distractor', '-')} | {d.get('absent', '-')} |")
    L += ["", "## 'Meets all required skills' flag (strict keyword rule, TEST)", "", "| Method | Precision | Recall | F1 |", "|---|---|---|---|"]
    for key, r in results.items():
        m = r["test"]["meets_all_required"]
        L.append(f"| {r['name']} | {fmt(m['precision'])} | {fmt(m['recall'])} | {fmt(m['f1'])} |")
    L += ["", "## Threshold sensitivity on DEV (lenient F1)", "", "| Method | " + " | ".join(["threshold -> F1"]) + " |", "|---|---|"]
    for key, sw in sweeps.items():
        L.append(f"| {results[key]['name']} | " + ", ".join(f"{t}: {fmt(v['lenient_f1'])}" for t, v in sw.items()) + " |")
    L += ["", "## How to read this", "",
          "- Keyword matching is precise on explicit mentions but cannot see paraphrases (recall on the paraphrase column).",
          "- Semantic similarity can recover paraphrases but may also flag unrelated text; compare the distractor/absent columns.",
          "- Without the intent filter, keyword matching treats 'planning to learn X' as evidence (distractor column). The filter is a hand-written cue list; the distractor sentences in this set were written by the same author, so its gain here is optimistic and real resumes will phrase intent differently.",
          "- Small sample: differences of a few points are not statistically meaningful."]
    (RESULTS / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
