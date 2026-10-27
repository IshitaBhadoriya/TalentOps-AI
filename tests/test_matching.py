import pytest

from app.matching import SentenceTransformerEmbedder, TfidfEmbedder, match_candidate, segment_resume

TEXT = """Skills
Python, SQL, Docker
Projects
Built REST APIs in Python and stored results in SQL databases
Built an ETL data pipeline for monthly sales reports
"""


def job(req, pref=(), **kw):
    return {"title": "T", "description": kw.get("description", ""), "required_skills": list(req),
            "preferred_skills": list(pref), "min_experience_years": kw.get("min_exp")}


def by_req(res):
    return {r["requirement"]: r for r in res["requirements"]}


def test_keyword_match_has_supporting_evidence():
    res = match_candidate(TEXT, None, job(["Python", "SQL"]), TfidfEmbedder())
    r = by_req(res)["Python"]
    assert r["status"] == "matched" and r["match_type"] == "keyword"
    assert any("Python" in e for e in r["evidence"])


def test_alias_matching():
    res = match_candidate("Projects\nWorked on REST endpoints with sklearn models", None,
                          job(["scikit-learn"]), TfidfEmbedder())
    assert by_req(res)["scikit-learn"]["status"] == "matched"


def test_java_does_not_match_javascript():
    res = match_candidate("Skills\nJavaScript and TypeScript development", None, job(["Java"]), TfidfEmbedder())
    assert by_req(res)["Java"]["status"] != "matched"


def test_partial_semantic_match():
    res = match_candidate(TEXT, None, job(["data pipelines"]), TfidfEmbedder())
    r = by_req(res)["data pipelines"]
    assert r["status"] == "partial" and r["match_type"] == "semantic" and r["evidence"]


def test_missing_evidence_is_insufficient_not_rejection():
    res = match_candidate(TEXT, None, job(["Kubernetes"]), TfidfEmbedder())
    r = by_req(res)["Kubernetes"]
    assert r["status"] == "insufficient" and r["evidence"] == []
    assert res["score"] == 0.0
    assert "reject" not in str(res).lower().replace("does not prove", "")  # no rejection concept
    assert "not a probability" in res["disclaimer"] and "Missing evidence" in res["disclaimer"]


def test_score_calculation_required_and_preferred():
    # required: Python, SQL both matched (1.0); preferred: Docker matched, Kubernetes missing (0.5)
    res = match_candidate(TEXT, None, job(["Python", "SQL"], ["Docker", "Kubernetes"]), TfidfEmbedder())
    assert res["required_coverage"] == 1.0 and res["preferred_coverage"] == 0.5
    assert res["score"] == pytest.approx(90.0)
    assert res["meets_all_required"] is True
    assert res["counts"] == {"matched": 3, "partial": 0, "insufficient": 1}
    assert "0.8" in res["score_explanation"]


def test_score_required_only_and_partial_half_credit():
    res = match_candidate(TEXT, None, job(["Python", "data pipelines"]), TfidfEmbedder())
    assert res["score"] == pytest.approx(75.0)  # (1 + 0.5) / 2
    assert res["meets_all_required"] is False


def test_no_requirements_gives_no_score():
    assert match_candidate(TEXT, None, job([]), TfidfEmbedder())["score"] is None


def test_experience_check_states():
    t = TfidfEmbedder()
    assert match_candidate(TEXT, None, job(["Python"], min_exp=2), t)["experience_check"]["status"] == "insufficient evidence"
    assert match_candidate(TEXT, 3, job(["Python"], min_exp=2), t)["experience_check"]["status"].startswith("meets")
    assert match_candidate(TEXT, 1, job(["Python"], min_exp=2), t)["experience_check"]["status"].startswith("below")
    assert match_candidate(TEXT, None, job(["Python"]), t)["experience_check"]["status"] == "not specified"


def test_score_ignores_name_and_contact_details():
    a = match_candidate("Aarav Sharma\na@example.com\n" + TEXT, None, job(["Python", "SQL"]), TfidfEmbedder())
    b = match_candidate("Emily Johnson\nb@example.com\n" + TEXT, None, job(["Python", "SQL"]), TfidfEmbedder())
    assert a["score"] == b["score"]


def test_segmenting_skips_headings_and_short_lines():
    segs = segment_resume("Skills\nPython, SQL\nx\nEducation\nB.Tech in Computer Science")
    assert "Skills" not in segs and "Education" not in segs and "x" not in segs


def test_empty_resume_does_not_crash():
    res = match_candidate("", None, job(["Python"]), TfidfEmbedder())
    assert by_req(res)["Python"]["status"] == "insufficient"


def test_embedding_backend_if_model_available():
    """Runs only if sentence-transformers AND the model are present locally; otherwise skipped."""
    try:
        emb = SentenceTransformerEmbedder("all-MiniLM-L6-v2")
    except Exception as exc:
        pytest.skip(f"embedding model unavailable: {type(exc).__name__}")
    sims = emb.similarity(["Experience with machine learning"], ["Trained neural network classifiers", "Cooked pasta"])
    assert sims[0][0] > sims[0][1]
