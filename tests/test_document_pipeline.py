"""End-to-End Test for Curriculum Document Pipeline (5-Step Processing).
Tests textbook synthesis & old question paper ingestion into question_master.
"""
import io
import pytest
from database.dbConnection import get_session
from helper.pipeline_engine import process_curriculum_document_pipeline
from sqlalchemy import text


SAMPLE_TEXTBOOK_CONTENT = """
Chapter 12: Electricity and Circuits
Subject: Physics | Class: Class 10 | Board: CBSE

12.1 Electric Current and Potential Difference
Electric current is defined as the rate of flow of electric charge through a conductor.
Formula: I = Q / t, where I is current in Amperes (A), Q is charge in Coulombs (C), and t is time in seconds.
1 Ampere corresponds to the flow of 1 Coulomb of charge per second (6.25 x 10^18 electrons/sec).

12.2 Ohm's Law
Ohm's Law states that the current flowing through a metallic conductor is directly proportional to the potential difference across its ends, provided the physical conditions such as temperature remain constant.
Mathematical Relation: V = I * R
where V is potential difference in Volts (V), I is current in Amperes (A), and R is resistance in Ohms (Ω).

12.3 Factors Affecting Resistance:
1. Length of the conductor: R is directly proportional to l.
2. Cross-sectional area: R is inversely proportional to A.
3. Nature of material: Resistivity (rho) is an intrinsic property.
Relation: R = rho * (l / A). Unit of resistivity is Ohm-meter (Ω·m).

Sample Exercises:
Q1. A 6V battery is connected across an unknown resistor. There is a current of 2.5 mA in the circuit. Find the value of the resistance of the resistor.
Solution: R = V / I = 6V / (2.5 * 10^-3 A) = 2400 Ohms = 2.4 kΩ.
"""

SAMPLE_QUESTION_PAPER_CONTENT = """
CENTRAL BOARD OF SECONDARY EDUCATION (CBSE)
SECONDARY SCHOOL EXAMINATION - 2024
SUBJECT: SCIENCE (THEORY) - CLASS X
Time Allowed: 3 Hours | Maximum Marks: 80

SECTION A (Multiple Choice Questions - 1 Mark each)
Q1. A cylindrical conductor of length 'l' and uniform area of cross-section 'A' has resistance 'R'. Another conductor of length 2.5l and resistance 0.5R of the same material has area of cross-section:
(A) 5 A
(B) 2.5 A
(C) 0.5 A
(D) 1.25 A

Q2. When aqueous solution of potassium iodide is added to lead nitrate solution, an insoluble precipitate is formed. What is the color of this precipitate?
(A) White
(B) Yellow
(C) Black
(D) Reddish Brown

SECTION B (Short Answer Questions - 2 Marks each)
Q3. State the rule to determine the direction of magnetic field produced around a straight conductor-carrying current.
Answer: Right Hand Thumb Rule. If you hold the current-carrying straight wire in your right hand such that the thumb points in the direction of current, then the curled fingers show the direction of magnetic field lines.

SECTION C (Numerical Problems - 3 Marks each)
Q4. An electric lamp of resistance 20 Ω and a conductor of 4 Ω resistance are connected in series to a 6 V battery. Calculate:
(a) The total resistance of the circuit.
(b) The current flowing through the circuit.
"""


def test_pipeline_textbook_ingestion():
    """Tests 5-step pipeline for textbook chapter processing."""
    file_bytes = SAMPLE_TEXTBOOK_CONTENT.encode("utf-8")
    filename = "CBSE_Class10_Physics_Electricity.txt"

    with get_session() as session:
        result = process_curriculum_document_pipeline(
            session=session,
            file_bytes=file_bytes,
            filename=filename,
            board="CBSE",
            class_grade="Class 10",
            subject="Physics",
            document_type="textbook",
            question_count=4,
        )

        assert result["success"] is True
        assert result["total_extracted"] > 0
        assert "document_id" in result
        assert result["questions_inserted"] + result["questions_updated"] > 0

        # Verify insertion into question_master
        q_count = session.execute(
            text("SELECT COUNT(*) FROM question_master WHERE topic_id = :t_id"),
            {"t_id": result["topic_id"]}
        ).scalar()
        assert q_count > 0
        print(f"\n[TEST PASSED] Successfully verified {result['total_extracted']} questions in question_master!")


def test_pipeline_old_question_paper_ingestion():
    """Tests 5-step pipeline for old question paper parsing."""
    file_bytes = SAMPLE_QUESTION_PAPER_CONTENT.encode("utf-8")
    filename = "CBSE_2024_Class10_Science_PYQ.txt"

    with get_session() as session:
        result = process_curriculum_document_pipeline(
            session=session,
            file_bytes=file_bytes,
            filename=filename,
            board="CBSE",
            class_grade="Class 10",
            subject="Science",
            document_type="old_question_paper",
            question_count=4,
        )

        assert result["success"] is True
        assert result["total_extracted"] > 0
        assert len(result["questions"]) > 0
        print(f"\n[TEST PASSED] Successfully parsed {result['total_extracted']} questions from Old Question Paper!")
