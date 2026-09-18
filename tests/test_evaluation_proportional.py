import pytest
from model.models import Question
from helper.evaluation_engine import evaluate_exam, _fallback_subjective_evaluation


def test_mcq_evaluation():
    q = Question(
        id="q1",
        question_number=1,
        type="mcq",
        question_text="What is the chemical formula for water?",
        options=["A) H2O", "B) CO2", "C) NaCl", "D) CH4"],
        correct_answer="A) H2O",
        marks=1,
        topic="Chemistry",
    )
    # Correct letter
    evals, score = evaluate_exam([q], {"q1": "A"}, board="CBSE", class_grade="Class 10")
    assert score == 1.0
    assert evals[0]["isCorrect"] is True
    assert evals[0]["marksAwarded"] == 1.0

    # Incorrect letter
    evals, score = evaluate_exam([q], {"q1": "C"}, board="CBSE", class_grade="Class 10")
    assert score == 0.0
    assert evals[0]["isCorrect"] is False


def test_subjective_proportional_evaluation_secondary():
    q = Question(
        id="q2",
        question_number=2,
        type="saq",
        question_text="Explain how photosynthesis works in green plants.",
        correct_answer="Photosynthesis is the biological process where chlorophyll in green plants converts carbon dioxide and water into glucose and oxygen using sunlight energy.",
        explanation="Chlorophyll absorbs radiant sunlight energy to synthesize glucose carbohydrate from atmospheric CO2 and soil water, releasing oxygen.",
        marks=2,
        topic="Biology",
    )

    # Partial answer containing keywords (chlorophyll, sunlight, glucose)
    student_ans = "Plants absorb sunlight energy using chlorophyll to make glucose food."
    evals, score = evaluate_exam([q], {"q2": student_ans}, board="CBSE", class_grade="Class 10")
    
    assert len(evals) == 1
    ev = evals[0]
    assert ev["marksAwarded"] > 0.0  # Partial or full credit awarded
    assert ev["questionMarks"] == 2.0
    assert ev["feedback"] is not None
    assert len(ev["matchedKeywords"]) > 0


def test_subjective_proportional_evaluation_kids_tier():
    q = Question(
        id="q3",
        question_number=1,
        type="saq",
        question_text="Why do birds have wings?",
        correct_answer="Birds have wings so that they can fly in the air and find food.",
        explanation="Wings provide aerodynamic lift enabling birds to fly, escape danger, and search for food.",
        marks=1,
        topic="Environmental Science",
    )

    # Child writes simple conceptual phrase with minor grammar
    student_ans = "to fly in sky and eat food"
    evals, score = evaluate_exam([q], {"q3": student_ans}, board="CBSE", class_grade="Class 3")
    assert evals[0]["marksAwarded"] >= 0.75  # Primary tier gives encouraging/full marks for core intuition
    assert evals[0]["isCorrect"] is True


def test_subjective_proportional_evaluation_skipped():
    q = Question(
        id="q4",
        question_number=1,
        type="saq",
        question_text="State Newton's Second Law of Motion.",
        correct_answer="The rate of change of momentum is directly proportional to the applied unbalanced force and occurs in the direction of the force (F = ma).",
        explanation="Force equals mass multiplied by acceleration: F = dp/dt = m*a.",
        marks=2,
        topic="Physics",
    )

    evals, score = evaluate_exam([q], {"q4": ""}, board="CBSE", class_grade="Class 11")
    assert score == 0.0
    assert evals[0]["isCorrect"] is False
    assert evals[0]["marksAwarded"] == 0.0
    assert "skipped" in evals[0]["feedback"].lower() or "did not" in evals[0]["feedback"].lower()
