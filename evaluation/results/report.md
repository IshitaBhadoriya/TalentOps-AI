# Evaluation report (synthetic labelled set)

- Resumes: 40 synthetic (dev 20 / test 20), jobs: 4, seed 7
- Unit of evaluation: one (resume, job requirement) pair. Truth: skill present (explicit or paraphrased) vs not (absent or only a wish/plan).
- Threshold chosen on DEV (best lenient F1), numbers below are on TEST.
- **Caveat:** resumes and matcher were written by the same author; this is a controlled comparison, not real-world accuracy.
- 'Strict' = only keyword-matched counts as found; 'Lenient' = matched or partial counts as found.

> MiniLM backend NOT evaluated in this run (ModuleNotFoundError: model/library unavailable).

| Method | Thr. | Mode | Precision | Recall | F1 | Spearman (score vs truth) |
|---|---|---|---|---|---|---|
| Keyword/alias only (baseline) (no intent filter) | 2.0 | strict | 0.89 | 0.60 | 0.71 | 0.66 |
| Keyword/alias only (baseline) (no intent filter) | 2.0 | lenient | 0.89 | 0.60 | 0.71 | 0.66 |
| Keyword/alias only (baseline) + intent filter | 2.0 | strict | 1.00 | 0.60 | 0.75 | 0.73 |
| Keyword/alias only (baseline) + intent filter | 2.0 | lenient | 1.00 | 0.60 | 0.75 | 0.73 |
| TF-IDF (keyword-weighted fallback) + intent filter | 0.15 | strict | 1.00 | 0.60 | 0.75 | 0.73 |
| TF-IDF (keyword-weighted fallback) + intent filter | 0.15 | lenient | 1.00 | 0.60 | 0.75 | 0.73 |

## Share of requirement pairs flagged as 'found', by true state (lenient, TEST)
Explicit/paraphrase rows are recall (higher is better); distractor/absent rows are false-positive rates (lower is better).

| Method | explicit | paraphrase | distractor | absent |
|---|---|---|---|---|
| Keyword/alias only (baseline) (no intent filter) | 1.0 | 0.0 | 0.737 | 0.0 |
| Keyword/alias only (baseline) + intent filter | 1.0 | 0.0 | 0.0 | 0.0 |
| TF-IDF (keyword-weighted fallback) + intent filter | 1.0 | 0.0 | 0.0 | 0.0 |

## 'Meets all required skills' flag (strict keyword rule, TEST)

| Method | Precision | Recall | F1 |
|---|---|---|---|
| Keyword/alias only (baseline) (no intent filter) | 0.67 | 0.13 | 0.22 |
| Keyword/alias only (baseline) + intent filter | 1.00 | 0.13 | 0.24 |
| TF-IDF (keyword-weighted fallback) + intent filter | 1.00 | 0.13 | 0.24 |

## Threshold sensitivity on DEV (lenient F1)

| Method | threshold -> F1 |
|---|---|
| Keyword/alias only (baseline) (no intent filter) | 2.0: 0.63 |
| Keyword/alias only (baseline) + intent filter | 2.0: 0.71 |
| TF-IDF (keyword-weighted fallback) + intent filter | 0.1: 0.71, 0.15: 0.71, 0.2: 0.71, 0.3: 0.71, 0.4: 0.71 |

## How to read this

- Keyword matching is precise on explicit mentions but cannot see paraphrases (recall on the paraphrase column).
- Semantic similarity can recover paraphrases but may also flag unrelated text; compare the distractor/absent columns.
- Without the intent filter, keyword matching treats 'planning to learn X' as evidence (distractor column). The filter is a hand-written cue list; the distractor sentences in this set were written by the same author, so its gain here is optimistic and real resumes will phrase intent differently.
- Small sample: differences of a few points are not statistically meaningful.
