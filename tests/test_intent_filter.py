from app.matching import TfidfEmbedder, is_non_evidence, match_candidate


def job(*req):
    return {"title": "T", "description": "", "required_skills": list(req), "preferred_skills": []}


def test_goal_only_mention_is_not_evidence_but_is_shown():
    res = match_candidate("Summary\nPlanning to learn Python next semester; no practical experience yet.", None,
                          job("Python"), TfidfEmbedder())
    r = res["requirements"][0]
    assert r["status"] == "insufficient" and r["evidence"] == []
    assert any("Planning to learn Python" in e for e in r["excluded_evidence"])  # visible to the recruiter


def test_real_evidence_survives_next_to_goal_line():
    text = "Projects\nBuilt a data tool in Python for weekly reports\nHoping to learn Python web frameworks later"
    r = match_candidate(text, None, job("Python"), TfidfEmbedder())["requirements"][0]
    assert r["status"] == "matched" and r["evidence"] == ["Built a data tool in Python for weekly reports"]


def test_familiar_with_is_still_evidence():
    assert not is_non_evidence("Familiar with Python and SQL")
    assert not is_non_evidence("Developed REST APIs with Flask for a student portal")


def test_filter_can_be_disabled():
    text = "Summary\nPlanning to learn Python next semester"
    r = match_candidate(text, None, job("Python"), TfidfEmbedder(), filter_non_evidence=False)["requirements"][0]
    assert r["status"] == "matched"


def test_cues():
    for line in ["Hoping to explore machine learning in the future", "Currently learning Docker; not used in any project",
                 "Heard about Power BI but have not used it", "Know of Excel but never used it for real work"]:
        assert is_non_evidence(line), line
