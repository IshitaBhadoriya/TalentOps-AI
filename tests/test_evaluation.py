from evaluation.build_dataset import BANK, build
from evaluation.metrics import ground_truth_score, pair_metrics, prf, spearman
from app.parsing import term_in_text


def test_dataset_is_deterministic_and_labels_consistent():
    a, b = build(12, seed=3), build(12, seed=3)
    assert a == b and len(a["resumes"]) == 12
    states = {s for r in a["resumes"] for s in r["states"].values()}
    assert {"explicit", "absent"} <= states


def test_bank_rules():
    for skill, (explicit, para, distract) in BANK.items():
        assert all(term_in_text(skill, e) for e in explicit), skill
        assert not any(term_in_text(skill, p) for p in para), skill
        assert term_in_text(skill, distract), skill


def test_pair_metrics_strict_vs_lenient():
    recs = [{"state": "explicit", "status": "matched"}, {"state": "paraphrase", "status": "partial"},
            {"state": "paraphrase", "status": "insufficient"}, {"state": "distractor", "status": "matched"},
            {"state": "absent", "status": "insufficient"}]
    strict, lenient = pair_metrics(recs, False), pair_metrics(recs, True)
    assert (strict["tp"], strict["fp"], strict["fn"], strict["tn"]) == (1, 1, 2, 1)
    assert (lenient["tp"], lenient["fp"], lenient["fn"], lenient["tn"]) == (2, 1, 1, 1)
    assert lenient["flagged_rate_by_state"]["paraphrase"] == 0.5


def test_ground_truth_score_and_helpers():
    assert ground_truth_score(["explicit", "absent"], ["paraphrase"]) == 100 * (0.8 * 0.5 + 0.2 * 1.0)
    assert ground_truth_score([], []) is None
    assert prf(0, 0, 0) == {"precision": None, "recall": None, "f1": None}
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert spearman([1, 1, 1], [1, 2, 3]) is None
