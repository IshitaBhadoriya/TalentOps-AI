"""Explainable requirement-by-requirement matching.

For each job requirement we look for evidence in the resume in two ways:
  1. Keyword/alias evidence (exact skill term found in a resume line)  -> 'matched'
  2. Semantic evidence (similarity between the requirement and resume segments) -> 'partial'
     when similarity >= the backend's threshold, otherwise 'insufficient'.
Semantic-only evidence is deliberately capped at 'partial' so a human confirms it.

Similarity backends (same interface):
  - SentenceTransformerEmbedder: all-MiniLM-L6-v2 on CPU, cosine similarity of dense embeddings
  - TfidfEmbedder: scikit-learn TF-IDF fallback, cosine similarity of keyword-weighted vectors

Thresholds are heuristic and UNCALIBRATED. The score is a transparent coverage number, not a
probability of hiring success and not a validated predictor of job performance.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import numpy as np

from .config import settings
from .parsing import HEADING_LOOKUP, term_in_text

log = logging.getLogger("talentops.matching")

REQUIRED_WEIGHT, PREFERRED_WEIGHT = 0.8, 0.2
DISCLAIMER = (
    "This score measures how much of the stated requirements has supporting evidence in the resume text. "
    "It is not a probability of hiring success and not a validated predictor of job performance. "
    "Missing evidence does not prove the candidate lacks a skill. A human recruiter must review every result."
)


# Lines that mention a skill only as a goal, a plan, or something not used are NOT evidence of the skill.
# Hand-written heuristic (not a trained model): it will miss unusual phrasing and may occasionally exclude a
# genuine line, which is why excluded lines are always shown to the recruiter instead of being silently dropped.
NON_EVIDENCE_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r"\b(?:plan(?:s|ning)?|hop(?:e|es|ing)|want(?:s|ed)?|would like|wish(?:es)?|aim(?:s|ing)?|intend(?:s|ing)?)\s+to\b",
    r"\b(?:interested in|curious about|heard (?:of|about)|know of)\b",
    r"\b(?:not yet|never|haven'?t|have not|has not|yet to|not used|not familiar|unfamiliar|currently learning)\b",
    r"\bno\s+(?:practical |prior |real |hands-on )?(?:experience|exposure|projects)\b",
    r"\b(?:only|just)\s+(?:watched|read about|heard)\b",
]]


def is_non_evidence(segment: str) -> bool:
    return any(p.search(segment) for p in NON_EVIDENCE_PATTERNS)


def segment_resume(text: str, max_len: int = 300) -> list[str]:
    """Split resume text into evidence-sized segments (lines / sentences), skipping headings."""
    segments: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"^[\s\-\u2022\u25cf\u25aa*·>]+", "", raw).strip()
        if len(line) < 8 or line.lower().rstrip(":") in HEADING_LOOKUP:
            continue
        if len(line) <= max_len:
            segments.append(line)
        else:
            for sent in re.split(r"(?<=[.!?])\s+", line):
                if len(sent.strip()) >= 8:
                    segments.append(sent.strip()[:max_len])
    return segments


def _stem(tok: str) -> str:
    """Very light plural stripping so 'pipelines' ~ 'pipeline' (no external NLP library needed)."""
    return tok[:-1] if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss") else tok


def _tfidf_analyzer(doc: str) -> list[str]:
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

    toks = [_stem(t) for t in re.findall(r"[a-z0-9+#.]+", doc.lower()) if t not in ENGLISH_STOP_WORDS]
    toks = [t.strip(".") for t in toks if t.strip(".")]
    return toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]


class TfidfEmbedder:
    kind = "tfidf"
    name = "TF-IDF (keyword-weighted fallback)"
    partial_threshold = 0.20
    query_template = "{req}"

    def similarity(self, queries: list[str], segments: list[str]) -> np.ndarray:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        if not queries or not segments:
            return np.zeros((len(queries), len(segments)))
        try:
            vec = TfidfVectorizer(analyzer=_tfidf_analyzer, sublinear_tf=True)
            matrix = vec.fit_transform(segments + queries)
        except ValueError:  # empty vocabulary
            return np.zeros((len(queries), len(segments)))
        seg_m, q_m = matrix[: len(segments)], matrix[len(segments):]
        return cosine_similarity(q_m, seg_m)


class SentenceTransformerEmbedder:
    kind = "embedding"
    partial_threshold = 0.45
    query_template = "Experience with {req}"
    _model = None

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.name = f"{model_name} (CPU sentence embeddings)"
        if SentenceTransformerEmbedder._model is None:
            from sentence_transformers import SentenceTransformer  # heavy import, lazy

            SentenceTransformerEmbedder._model = SentenceTransformer(model_name, device="cpu")

    def similarity(self, queries: list[str], segments: list[str]) -> np.ndarray:
        if not queries or not segments:
            return np.zeros((len(queries), len(segments)))
        m = SentenceTransformerEmbedder._model
        q = m.encode(queries, normalize_embeddings=True, show_progress_bar=False)
        s = m.encode(segments, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(q) @ np.asarray(s).T  # unit vectors -> dot product == cosine


_cached = None


def get_embedder(force_reload: bool = False):
    """Return the configured similarity backend; fall back to TF-IDF in 'auto' mode."""
    global _cached
    if _cached is not None and not force_reload:
        return _cached
    mode = settings.embedding_backend
    if mode == "tfidf":
        _cached = TfidfEmbedder()
    else:
        try:
            _cached = SentenceTransformerEmbedder(settings.model_name)
        except Exception as exc:
            if mode == "embedding":
                raise
            log.warning("Embedding model unavailable (%s); using TF-IDF fallback.", exc)
            _cached = TfidfEmbedder()
    return _cached


def _status_for(term: str, requirement_sims: np.ndarray, segments: list[str], threshold: float,
                excluded: frozenset = frozenset()):
    kw_idx = [i for i, seg in enumerate(segments) if i not in excluded and term_in_text(term, seg)]
    order = np.argsort(-requirement_sims) if len(segments) else []
    if kw_idx:
        best = sorted(kw_idx, key=lambda i: -requirement_sims[i])[:2]
        return "matched", "keyword", best, float(requirement_sims[best[0]])
    if len(segments) and requirement_sims[order[0]] >= threshold:
        top = [int(i) for i in order[:2] if requirement_sims[i] >= threshold]
        return "partial", "semantic", top, float(requirement_sims[top[0]])
    top1 = float(requirement_sims[order[0]]) if len(segments) else 0.0
    return "insufficient", "none", [], top1


def match_candidate(resume_text: str, declared_years: Optional[float], job: dict, embedder=None,
                    filter_non_evidence: bool = True) -> dict:
    embedder = embedder or get_embedder()
    segments = segment_resume(resume_text)
    excluded = frozenset(i for i, seg in enumerate(segments) if filter_non_evidence and is_non_evidence(seg))
    required, preferred = job.get("required_skills", []), job.get("preferred_skills", [])
    reqs = [(r, "required") for r in required] + [(p, "preferred") for p in preferred]

    queries = [embedder.query_template.format(req=r) for r, _ in reqs]
    sims = embedder.similarity(queries, segments)
    if excluded and len(segments):
        sims = sims.copy()
        sims[:, list(excluded)] = 0.0  # goal/plan/negated lines can never be semantic evidence either

    results = []
    for i, (term, rtype) in enumerate(reqs):
        status, mtype, idxs, best = _status_for(term, sims[i] if len(segments) else np.array([]), segments,
                                                embedder.partial_threshold, excluded)
        skipped = [segments[j] for j in sorted(excluded) if term_in_text(term, segments[j])]
        results.append({
            "requirement": term, "type": rtype, "status": status, "match_type": mtype,
            "similarity": round(best, 3), "evidence": [segments[j] for j in idxs],
            "excluded_evidence": skipped,  # mentions found only as a goal/plan/negation - shown for human review
        })

    def coverage(kind: str) -> Optional[float]:
        rows = [r for r in results if r["type"] == kind]
        if not rows:
            return None
        pts = sum(1.0 if r["status"] == "matched" else 0.5 if r["status"] == "partial" else 0.0 for r in rows)
        return pts / len(rows)

    req_cov, pref_cov = coverage("required"), coverage("preferred")
    if req_cov is not None and pref_cov is not None:
        score = 100 * (REQUIRED_WEIGHT * req_cov + PREFERRED_WEIGHT * pref_cov)
    elif req_cov is not None or pref_cov is not None:
        score = 100 * (req_cov if req_cov is not None else pref_cov)
    else:
        score = None

    min_exp = job.get("min_experience_years")
    exp = {"required_years": min_exp, "declared_years": declared_years, "status": "not specified",
           "note": "No minimum experience specified for this role."}
    if min_exp is not None:
        if declared_years is None:
            exp.update(status="insufficient evidence",
                       note="Resume does not state total years of experience in a form we could read. "
                            "This does not mean the candidate lacks the experience.")
        elif declared_years >= min_exp:
            exp.update(status="meets (self-declared)", note="Based on the resume's own wording; not verified.")
        else:
            exp.update(status="below (self-declared)",
                       note="Based on the resume's own wording; recruiter should verify.")

    jd_text = (job.get("description") or "").strip()
    jd_sim = None
    if jd_text and segments:
        row = embedder.similarity([jd_text[:2000]], segments)[0]
        jd_sim = round(float(np.mean(np.sort(row)[-3:])), 3)

    n_m = sum(r["status"] == "matched" for r in results)
    n_p = sum(r["status"] == "partial" for r in results)
    n_i = len(results) - n_m - n_p
    explanation = (
        f"Score = 100 x (0.8 x required coverage + 0.2 x preferred coverage); a matched requirement counts 1, "
        f"a partial match 0.5, insufficient evidence 0. If only one group exists it carries full weight. "
        f"Result: {n_m} matched, {n_p} partial, {n_i} with insufficient evidence. "
        f"Experience and the whole-description similarity are shown for context and are NOT in the score."
    )
    return {
        "requirements": results, "required_coverage": req_cov, "preferred_coverage": pref_cov,
        "score": None if score is None else round(score, 1),
        "meets_all_required": bool(required) and all(r["status"] == "matched" for r in results if r["type"] == "required"),
        "counts": {"matched": n_m, "partial": n_p, "insufficient": n_i},
        "experience_check": exp, "description_similarity": jd_sim,
        "score_explanation": explanation, "backend": embedder.name, "backend_kind": embedder.kind,
        "disclaimer": DISCLAIMER,
    }
