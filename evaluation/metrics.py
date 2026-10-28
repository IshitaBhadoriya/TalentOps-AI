"""Pure metric helpers (no model/DB needed) so they can be unit-tested."""
from __future__ import annotations

from typing import Iterable

HAS = {"explicit", "paraphrase"}


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"precision": p, "recall": r, "f1": f}


def pair_metrics(records: Iterable[dict], lenient: bool) -> dict:
    """records: dicts with 'state' (explicit/paraphrase/distractor/absent) and 'status' (matched/partial/insufficient).
    Predicted positive: strict = matched only; lenient = matched or partial."""
    tp = fp = fn = tn = 0
    by_state: dict[str, list[int]] = {}
    for r in records:
        pos = r["status"] == "matched" or (lenient and r["status"] == "partial")
        truth = r["state"] in HAS
        tp += truth and pos
        fp += (not truth) and pos
        fn += truth and not pos
        tn += (not truth) and not pos
        by_state.setdefault(r["state"], []).append(int(pos))
    out = prf(tp, fp, fn)
    n = tp + fp + fn + tn
    out.update(accuracy=(tp + tn) / n if n else None, n=n, tp=tp, fp=fp, fn=fn, tn=tn)
    # share of pairs of each kind predicted positive: recall for explicit/paraphrase, false-positive rate otherwise
    out["flagged_rate_by_state"] = {k: round(sum(v) / len(v), 3) for k, v in by_state.items()}
    return out


def ground_truth_score(required_states: list[str], preferred_states: list[str]) -> float | None:
    """Same weighting as the matcher (0.8 / 0.2) but with true labels (1 = has skill, no partial credit)."""
    def cov(states):
        return sum(s in HAS for s in states) / len(states) if states else None
    rc, pc = cov(required_states), cov(preferred_states)
    if rc is not None and pc is not None:
        return 100 * (0.8 * rc + 0.2 * pc)
    if rc is not None or pc is not None:
        return 100 * (rc if rc is not None else pc)
    return None


def spearman(a: list[float], b: list[float]) -> float | None:
    from scipy.stats import spearmanr

    if len(a) < 3 or len(set(a)) < 2 or len(set(b)) < 2:
        return None
    return float(spearmanr(a, b).statistic)
