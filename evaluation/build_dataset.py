"""Build a SYNTHETIC labelled evaluation set (deterministic, seeded).

Ground truth is known by construction. For every (resume, skill) pair the generator decides one state:
  explicit    - the skill (or an alias) is stated in the resume      -> label: has skill
  paraphrase  - the skill is shown through different wording, with
                none of the skill's keywords                         -> label: has skill
  distractor  - the skill name appears only as a wish/plan/no use    -> label: does NOT have skill
  absent      - nothing about the skill                              -> label: does NOT have skill

LIMITATION: the author of the matcher also wrote these resumes, so this set is easier and cleaner than real
resumes. Results show relative behaviour of methods on controlled cases; they are not real-world accuracy.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parsing import term_in_text  # noqa: E402

OUT = Path(__file__).resolve().parent / "data" / "eval_set.json"
SEED = 7

# skill -> (explicit lines, paraphrase lines, distractor line)
BANK = {
    "Python": (["Developed data processing scripts in Python for weekly reporting",
                "Built a command-line tool using Python and the standard library"],
               ["Wrote Jupyter notebooks with NumPy and pandas to clean survey data",
                "Authored automation scripts with virtual environments and pip packages"],
               "Planning to learn Python next semester; no practical experience yet."),
    "SQL": (["Wrote SQL queries with joins and aggregations for a sales dashboard",
             "Designed a normalised SQL schema for an inventory project"],
            ["Wrote joins and group-by aggregations over relational tables in a database course project",
             "Designed tables, primary keys and foreign keys for a library management system"],
            "Interested in SQL but have only watched a short intro video."),
    "Machine Learning": (["Trained a machine learning model with scikit-learn to predict customer churn",
                          "Applied ML techniques including random forests to a classification project"],
                         ["Trained a random forest classifier and tuned hyperparameters with cross-validation",
                          "Built a regression model to forecast demand and evaluated it with RMSE"],
                         "Hoping to explore machine learning in the future; not yet practised."),
    "NLP": (["Built an NLP pipeline for tokenising and classifying support tickets",
             "Applied natural language processing to extract entities from news articles"],
            ["Fine-tuned a transformer model to classify the sentiment of product reviews",
             "Built a text classification system using bag-of-words and word embeddings"],
            "Curious about NLP but have not worked on any text projects."),
    "REST APIs": (["Developed REST APIs with Flask for a student portal",
                   "Built and documented RESTful API endpoints returning JSON"],
                  ["Designed HTTP endpoints that return JSON for a mobile application",
                   "Created backend routes with GET and POST handlers and status codes"],
                  "Want to learn REST APIs; my projects so far have no backend."),
    "Docker": (["Containerised a web application with Docker for deployment",
                "Wrote Dockerfiles and used Docker Compose for local development"],
               ["Packaged services into containers for consistent deployment across machines",
                "Built container images and ran multi-service stacks for local development"],
               "Currently learning Docker; I have not used it in any project."),
    "Git": (["Used Git and GitHub for version control with pull requests",
             "Managed branches and resolved merge conflicts in Git"],
            ["Collaborated through pull requests and code reviews on a shared repository",
             "Maintained feature branches and resolved merge conflicts with teammates"],
            "Haven't used Git yet; planning to set it up."),
    "Data Analysis": (["Performed data analysis on sales records to find seasonal trends",
                       "Used data analytics to summarise survey results for a club"],
                      ["Explored datasets, cleaned missing values and visualised trends with charts",
                       "Summarised survey responses with statistics and presented insights to the club"],
                      "Would like to get into data analysis; no projects yet."),
    "Excel": (["Built Excel dashboards with pivot tables for monthly reports",
               "Used Excel formulas and macros to automate attendance sheets"],
              ["Created pivot tables and lookup formulas in spreadsheets for monthly reports",
               "Automated attendance tracking with spreadsheet formulas and macros"],
              "Know of Excel but have never used it for real work."),
    "Testing": (["Wrote unit testing suites with pytest for a backend service",
                 "Added pytest tests and measured coverage on a class project"],
                ["Wrote automated checks that verify functions before each release",
                 "Added assertions and fixtures to catch regressions in a class project"],
                "Plan to start Testing practices later; none so far."),
    "Java": (["Developed a library management system in Java using OOP",
              "Built a Java Swing desktop application for a college project"],
             ["Implemented inheritance and interfaces in a JVM-based library management project",
              "Built a desktop GUI application compiled to bytecode for the JVM"],
             "Not yet familiar with Java; planning to study it."),
    "Power BI": (["Created Power BI dashboards for sales performance",
                  "Published a Power BI report with slicers and DAX measures"],
                 ["Built interactive dashboards with slicers and calculated measures for sales performance",
                  "Published business intelligence reports with filters for managers"],
                 "Heard about Power BI but have not used it."),
}

# archetype -> probability that the candidate genuinely has each skill
ARCHETYPES = {
    "data":    {"Python": .7, "SQL": .8, "Excel": .8, "Data Analysis": .9, "Power BI": .6, "Machine Learning": .3, "Git": .4, "Testing": .1},
    "backend": {"Python": .8, "REST APIs": .9, "SQL": .8, "Git": .9, "Docker": .6, "Testing": .5, "Java": .3},
    "ml":      {"Python": .95, "Machine Learning": .9, "NLP": .7, "Git": .6, "Docker": .4, "Data Analysis": .5, "SQL": .3},
    "java":    {"Java": .9, "SQL": .7, "Git": .6, "Testing": .5, "REST APIs": .4},
    "novice":  {"Python": .3, "Git": .2, "SQL": .2, "Excel": .3},
}
JOBS = [
    {"title": "Data Analyst Intern", "required_skills": ["SQL", "Excel", "Data Analysis"], "preferred_skills": ["Power BI", "Python"]},
    {"title": "Backend Developer Intern", "required_skills": ["Python", "REST APIs", "SQL", "Git"], "preferred_skills": ["Docker", "Testing"]},
    {"title": "ML / AI Intern", "required_skills": ["Python", "Machine Learning", "NLP"], "preferred_skills": ["Docker", "Git"]},
    {"title": "Java Developer Trainee", "required_skills": ["Java", "SQL", "Git"], "preferred_skills": ["Testing"]},
]
FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Ishaan", "Tara", "Vihaan", "Nisha", "Rahul", "Sana", "Yash", "Zoya"]
LAST = ["Rao", "Khan", "Iyer", "Das", "Patel", "Gill", "Nair", "Shah", "Bose", "Menon"]
NOISE = ["Member of the college robotics club", "Organised a campus event for 200 students",
         "Volunteered at an inter-college hackathon", "Captain of the department cricket team"]


def build(n: int = 40, seed: int = SEED) -> dict:
    rng = random.Random(seed)
    resumes = []
    for idx in range(n):
        arche = rng.choice(list(ARCHETYPES))
        probs = ARCHETYPES[arche]
        first, last = rng.choice(FIRST), rng.choice(LAST)
        states, exp_lines, summary_lines, skill_list = {}, [], [], []
        for skill, (explicit, para, distract) in BANK.items():
            if rng.random() < probs.get(skill, 0.05):
                if rng.random() < 0.55:
                    states[skill] = "explicit"
                    exp_lines.append(rng.choice(explicit))
                    if rng.random() < 0.6:
                        skill_list.append(skill)
                else:
                    states[skill] = "paraphrase"
                    exp_lines.append(rng.choice(para))
            elif rng.random() < 0.12:
                states[skill] = "distractor"
                summary_lines.append(distract)
            else:
                states[skill] = "absent"
        rng.shuffle(exp_lines)
        half = len(exp_lines) // 2
        lines = [f"{first} {last}", f"{first.lower()}.{last.lower()}{idx}@example.com", ""]
        if summary_lines:
            lines += ["Summary", *summary_lines[:2], ""]
        if skill_list:
            lines += ["Skills", ", ".join(skill_list), ""]
        lines += ["Education", f"B.Tech Computer Science, Example Institute (CGPA {7 + rng.random() * 2:.1f})", ""]
        if exp_lines[:half]:
            lines += ["Experience", *exp_lines[:half], ""]
        lines += ["Projects", *(exp_lines[half:] or ["Class project report on a campus survey"]), rng.choice(NOISE)]
        resumes.append({"id": idx, "archetype": arche, "text": "\n".join(lines), "states": states})
    # self-check: labels must agree with the construction rules
    for r in resumes:
        for skill, st in r["states"].items():
            present = term_in_text(skill, r["text"])
            if st == "paraphrase" and present:
                raise AssertionError(f"paraphrase leaks keyword: resume {r['id']} {skill}")
            if st == "explicit" and not present:
                raise AssertionError(f"explicit missing keyword: resume {r['id']} {skill}")
    return {"seed": seed, "jobs": JOBS, "resumes": resumes,
            "labels": "has_skill = explicit or paraphrase; no skill = absent or distractor"}


if __name__ == "__main__":
    data = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"Wrote {len(data['resumes'])} synthetic resumes and {len(data['jobs'])} jobs to {OUT}")
