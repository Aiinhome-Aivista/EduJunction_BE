"""Model Question Paper Document Generator for EduJunction.
Generates authentic 2027 Board Specimen Question Papers in PDF (ReportLab) and Word (DOCX) formats
customized for CBSE, ICSE, and ISC examination standards, markings, and instructions.
"""
import io
import re
from datetime import datetime
from typing import Dict, Any, List

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
)

import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

from helper.fallback_exam_bank import KIDS_QUESTION_BANKS
FALLBACK_QUESTIONS_BY_SUBJECT = KIDS_QUESTION_BANKS
from utils.logger import logger


def _get_subject_questions(subject: str) -> List[dict]:
    """Finds questions from available banks matching the subject."""
    subj_clean = subject.lower().strip()
    matched_key = None
    for k in FALLBACK_QUESTIONS_BY_SUBJECT.keys():
        if k in subj_clean or subj_clean in k:
            matched_key = k
            break

    if matched_key and FALLBACK_QUESTIONS_BY_SUBJECT.get(matched_key):
        return list(FALLBACK_QUESTIONS_BY_SUBJECT[matched_key])
    return []


def _synthesize_curriculum_mcq(num: int, subject: str, board: str) -> dict:
    topics = {
        "mathematics": ["Quadratic Equations", "Coordinate Geometry", "Trigonometric Identities", "Surface Areas & Volumes", "Arithmetic Progressions", "Probability Theory", "Linear Inequations", "Matrix Transformations"],
        "physics": ["Ohm's Law & Circuit Analysis", "Refraction through Prisms", "Electromagnetic Induction", "Calorimetry & Specific Heat", "Radioactivity & Nuclear Decay", "Sound Wave Harmonics", "Force & Work-Energy Theorem"],
        "chemistry": ["Periodic Properties & Trends", "Chemical Bonding & Hybridization", "Mole Concept & Stoichiometry", "Electrolysis & Faraday's Laws", "Organic Functional Groups & Isomerism", "Acids, Bases and Salts Equilibrium"],
        "biology": ["Photosynthesis Light Reactions", "Mendelian Genetics & Inheritance", "Transpiration & Osmotic Balance", "Endocrine Hormonal Regulation", "Nervous Reflex Arc Coordination", "Circulatory Cardiac Cycle"],
        "social science": ["Nationalism in India & Europe", "Resources and Sustainable Development", "Power Sharing & Federalism", "Money and Credit Systems", "Globalization & Indian Economy", "Manufacturing Industries & Lifelines"],
        "social studies": ["Democratic Politics & Governance", "Contemporary India Geo-Resources", "Economic Development Metrics", "Modern World History & Industrialization"],
        "history": ["Nationalist Movements & Treaties", "The First World War & League of Nations", "Union Executive & Judiciary Governance", "Decolonization & Non-Aligned Movement"],
        "geography": ["Topographical Map Interpretations", "Monsoon Climate & Precipitation Dynamics", "Soil and Water Conservation", "Mineral & Energy Distribution in India"],
        "economics": ["National Income Accounting", "Monetary Policy & Central Banking", "Aggregate Demand & Multiplier", "Balance of Payments & Forex Equilibrium"],
        "accountancy": ["Partnership Goodwill & Reconstitution", "Accounting for Share Capital", "Cash Flow Analysis & Liquidity", "Financial Statement Ratio Modeling"],
        "business studies": ["Principles & Functions of Management", "Financial Markets & Capital Structure", "Marketing Management & 4Ps Mix", "Consumer Protection Act & Rights"],
        "commercial studies": ["Commercial Organizations & Ownership", "Banking Operations & E-Commerce", "Advertising & Brand Management", "Logistics & Supply Chain Fundamentals"],
        "computer applications": ["Object-Oriented Programming Constructs", "Class as the Basis of all Computation", "User-Defined Methods & Encapsulation", "Arrays & String Tokenization Operations"],
        "computer science": ["Object Oriented Encapsulation", "Iterative Loops & Array Traversals", "Function Recursion & Call Stack", "Time Complexity Analysis", "Exception Handling Architecture", "Data Structure Queue/Stack"],
        "english": ["Reading Comprehension Inference", "Sentence Transformation & Voice", "Contextual Vocabulary & Idioms", "Prepositional Collocations", "Narrative Cohesion"],
    }
    sub_key = subject.lower()
    matched_topic_list = topics.get("mathematics")
    for k, v in topics.items():
        if k in sub_key:
            matched_topic_list = v
            break

    topic = matched_topic_list[(num - 1) % len(matched_topic_list)]
    return {
        "question": f"In the context of <b>{topic}</b> in standard {subject}, which of the following statements is mathematically and conceptually correct?",
        "options": [
            f"A) The parameter varies proportionally under fundamental {topic} equilibrium laws",
            f"B) The value remains invariant regardless of boundary transformations",
            f"C) The resultant demonstrates inverse quadratic decay under specified constraints",
            f"D) The rate of change is strictly zero at the initial transition point"
        ],
        "correct_answer": "A",
        "explanation": f"Under standard fundamental principles of {topic}, option A accurately reflects the governing relationship whereas other choices contradict boundary equilibrium.",
        "marks": 1
    }


def _synthesize_assertion_reason(num: int, subject: str) -> dict:
    return {
        "question": f"<b>Assertion (A):</b> Under standard conditions in {subject}, dynamic equilibrium is established when opposing rates become strictly equal.<br/>"
                    f"<b>Reason (R):</b> Energy conservation requires continuous cyclic redistribution within a closed physical system.",
        "options": [
            "A) Both (A) and (R) are true and (R) is the correct explanation of (A)",
            "B) Both (A) and (R) are true but (R) is NOT the correct explanation of (A)",
            "C) (A) is true but (R) is false",
            "D) (A) is false but (R) is true"
        ],
        "correct_answer": "A",
        "explanation": "Both Assertion and Reason are true scientific statements, and Reason provides the correct direct underlying physical/conceptual justification.",
        "marks": 1
    }


def _synthesize_saq(num: int, subject: str, marks: int = 2) -> dict:
    prompts = [
        f"State the fundamental law governing {subject} systems and express its mathematical relationship with standard units.",
        f"Explain two critical factors that influence the equilibrium state in {subject} and provide one practical application.",
        f"Distinguish between ideal and non-ideal behaviors in {subject} analysis using a neat comparative table.",
        f"Write down the step-by-step procedure to determine the unknown coefficient in a standard {subject} experiment.",
        f"Justify why energy dissipation occurs during non-conservative transformations in {subject} modeling.",
    ]
    model_answers = [
        f"Fundamental law states that in any {subject} system under steady state, the rate of change is directly proportional to applied gradient. Mathematical formulation: Formula with standard SI units and boundary constraints.",
        f"Two critical factors: (1) Ambient temperature and pressure gradients altering internal resistance, (2) Active concentration/flux density. Practical application: Standard calibration in precision instruments.",
        f"Ideal systems follow theoretical linearity without internal losses; Non-ideal systems exhibit hysteresis, frictional damping, and thermal dissipation at higher operating ranges.",
        f"Procedure: (1) Set up standardized test apparatus. (2) Record baseline parameters. (3) Measure response across incremental test points. (4) Plot linear slope and compute coefficient = ΔY / ΔX.",
        f"Energy dissipation arises because non-conservative forces (friction, thermal resistance, radiation) convert usable mechanical/electrical energy into irreversible thermal losses.",
    ]
    idx = (num - 1) % len(prompts)
    return {
        "question": prompts[idx],
        "correct_answer": model_answers[idx],
        "explanation": f"Marking Rubric [{marks} Marks]: 1 Mark for stating core concept/definition with SI units; 1 Mark for complete supporting points/steps.",
        "marks": marks
    }


def _synthesize_long(num: int, subject: str, marks: int = 5) -> dict:
    prompts = [
        f"(a) State the governing principle of {subject} and derive the generalized analytical equation from first principles.<br/>(b) A standardized system operates under test conditions. Calculate the maximum theoretical yield and justify your deduction. [3 + 2 = 5 Marks]",
        f"(a) Explain the construction, working principle, and mathematical efficiency model in {subject} with a clear diagram.<br/>(b) State two potential sources of experimental error and propose corrective calibrations. [3 + 2 = 5 Marks]",
        f"(a) Prove that the sum of dynamic parameters remains constant throughout harmonic oscillations in {subject}.<br/>(b) Solve for the steady-state value when external excitation matches the resonant threshold. [3 + 2 = 5 Marks]",
        f"(a) Compare the theoretical derivation with empirical observations in {subject} systems.<br/>(b) Formulate the boundary equations and deduce the limiting value as parameters approach infinity. [3 + 2 = 5 Marks]",
    ]
    model_answers = [
        f"Part (a): State the principle and show step-by-step analytical derivation with boundary conditions. Part (b): Stepwise numerical calculation: Formula, substitution, final numerical result with proper SI units.",
        f"Part (a): Labeled schematic diagram, structural components, working stages, and derivation of efficiency = (Useful Output / Total Input) × 100%. Part (b): Instrumental zero-error and ambient fluctuations; corrective calibration protocols.",
        f"Part (a): Kinetic + Potential parameters = Constant total energy derivation. Part (b): Resonant amplitude and steady-state solution at excitation frequency ω0.",
        f"Part (a): Analytical vs empirical comparison points. Part (b): Limiting asymptotic formulation as t -> infinity.",
    ]
    idx = (num - 1) % len(prompts)
    return {
        "question": prompts[idx],
        "correct_answer": model_answers[idx],
        "explanation": f"Marking Rubric [{marks} Marks]: 3 Marks for comprehensive theoretical derivation and schematic diagram; 2 Marks for numerical/analytical justification.",
        "marks": marks
    }


def _synthesize_case(num: int, subject: str, marks: int = 4) -> dict:
    return {
        "case_title": f"Case Study {num} — Industrial & Experimental Investigation in {subject}",
        "case_text": f"A dedicated research facility analyzed the response behavior of a modern {subject} test apparatus. "
                     f"During controlled trials at baseline parameters, real-time telemetry recorded a stable linear relationship before transition to saturation. "
                     f"Subsequent stress testing revealed that external thermal and structural factors introduce a second-order variance of 4.2% across sample batches.",
        "question": f"(i) Identify the independent and dependent variables in the investigation described above. [1 Mark]<br/>"
                    f"(ii) State the physical or mathematical significance of the observed transition threshold. [1 Mark]<br/>"
                    f"(iii) Calculate the expected output variance when operational load is increased by 25% under nominal baseline conditions. [2 Marks]",
        "correct_answer": "(i) Independent variable: Controlled input load/parameters; Dependent variable: System response telemetry. (ii) Transition threshold marks the linearity limit beyond which saturation occurs. (iii) Applying 25% load increment: Output variance = 4.2% × 1.25 = 5.25%.",
        "explanation": f"Marking Rubric [{marks} Marks]: (i) 1 Mark for correct variable identification; (ii) 1 Mark for conceptual threshold significance; (iii) 2 Marks for step-by-step variance calculation.",
        "marks": marks
    }


from sqlalchemy import text
import json


def _fetch_model_paper_questions_from_db(
    session,
    board: str,
    class_grade: str,
    subject: str,
    set_number: int = 1,
) -> Dict[str, List[dict]]:
    """Fetches questions from question_master grouped into mark pools (1M, 2M, 3M, 4M, 5M, 8M)."""
    if not session:
        return {}

    clean_board = (board or "").strip()
    clean_class = (class_grade or "").strip()
    clean_subj = (subject or "").strip()

    try:
        sql = text("""
            SELECT 
                q.id AS question_id,
                q.question AS question_text,
                q.options,
                q.correct_answer,
                q.explanation,
                q.marks,
                COALESCE(qt.question_type_name, 'MCQ') AS question_type,
                COALESCE(dl.difficulty_level_name, 'medium') AS difficulty,
                s.subject_name,
                ch.chapter_name,
                t.topic_name,
                b.board_name,
                c.class_name
            FROM question_master q
            JOIN topic_master t ON q.topic_id = t.id
            JOIN chapter_master ch ON t.chapter_id = ch.id
            JOIN subject_master s ON ch.subject_id = s.id
            JOIN board_master b ON s.board_id = b.id
            JOIN class_master c ON s.class_id = c.id
            JOIN question_type_master qt ON q.question_type_id = qt.id
            LEFT JOIN difficulty_level_master dl ON q.difficulty_level_id = dl.id
            WHERE q.is_active = 1
              AND (
                  :board = ''
                  OR LOWER(TRIM(b.board_name)) = LOWER(TRIM(:board))
                  OR LOWER(b.board_name) LIKE CONCAT('%', LOWER(:board), '%')
                  OR LOWER(:board) LIKE CONCAT('%', LOWER(b.board_name), '%')
              )
              AND (
                  :class_grade = ''
                  OR LOWER(TRIM(c.class_name)) = LOWER(TRIM(:class_grade))
                  OR LOWER(TRIM(REPLACE(c.class_name, 'Class ', ''))) = LOWER(TRIM(REPLACE(:class_grade, 'Class ', '')))
                  OR LOWER(c.class_name) LIKE CONCAT('%', LOWER(:class_grade), '%')
              )
              AND (
                  :subject = ''
                  OR LOWER(TRIM(s.subject_name)) = LOWER(TRIM(:subject))
                  OR LOWER(s.subject_name) LIKE CONCAT('%', LOWER(:subject), '%')
                  OR LOWER(:subject) LIKE CONCAT('%', LOWER(s.subject_name), '%')
              )
            ORDER BY q.id ASC
        """)

        params = {
            "board": clean_board,
            "class_grade": clean_class,
            "subject": clean_subj,
        }

        rows = session.execute(sql, params).mappings().fetchall()
        if not rows:
            return {}

        pools: Dict[str, List[dict]] = {
            "1m": [],
            "2m": [],
            "3m": [],
            "4m": [],
            "5m": [],
            "8m": [],
        }

        for r in rows:
            raw_options = r.get("options")
            options_list = None
            if raw_options:
                if isinstance(raw_options, list):
                    options_list = raw_options
                elif isinstance(raw_options, str):
                    try:
                        parsed = json.loads(raw_options)
                        if isinstance(parsed, list):
                            options_list = parsed
                        elif isinstance(parsed, dict):
                            options_list = [f"{k}) {v}" for k, v in parsed.items()]
                    except Exception:
                        options_list = [opt.strip() for opt in raw_options.split("|") if opt.strip()]

            q_type = str(r.get("question_type") or "MCQ").upper()
            marks = int(r.get("marks") or 1)

            q_obj = {
                "question": r.get("question_text", ""),
                "options": options_list,
                "correct_answer": str(r.get("correct_answer", "A")),
                "explanation": r.get("explanation") or "Derived from standard curriculum concepts.",
                "marks": marks,
                "type": q_type.lower(),
                "topic": r.get("topic_name") or r.get("chapter_name") or clean_subj,
            }

            if marks == 1 or "MCQ" in q_type or "OBJECTIVE" in q_type or "ASSERTION" in q_type:
                q_obj["marks"] = 1
                pools["1m"].append(q_obj)
            elif marks == 2 or ("SAQ" in q_type and marks <= 2):
                q_obj["marks"] = 2
                pools["2m"].append(q_obj)
            elif marks == 3:
                q_obj["marks"] = 3
                pools["3m"].append(q_obj)
            elif marks == 4 or "CASE" in q_type:
                q_obj["marks"] = 4
                q_obj["case_title"] = f"Case Analysis: {q_obj['topic']}"
                q_obj["case_text"] = f"Contextual study on {q_obj['topic']} under standard {clean_subj} principles."
                pools["4m"].append(q_obj)
            elif marks == 5 or "LONG" in q_type:
                q_obj["marks"] = 5
                pools["5m"].append(q_obj)
            elif marks >= 8 or "EVALUATIVE" in q_type:
                q_obj["marks"] = 8
                pools["8m"].append(q_obj)
            else:
                pools["2m"].append(q_obj)

        # Rotate pools by offset for distinct question sets
        offset = max(0, (set_number - 1))
        for k in pools:
            if pools[k]:
                n = len(pools[k])
                shift = (offset * 3) % n
                pools[k] = pools[k][shift:] + pools[k][:shift]

        return pools
    except Exception as e:
        logger.warning(f"Failed to fetch model paper questions from DB: {e}")
        return {}


# ─────────────────────────────────────────────────────────────
# Board-Specific Blueprint Assemblers
# ─────────────────────────────────────────────────────────────

def assemble_cbse_paper(class_grade: str, subject: str, set_number: int, session=None) -> Dict[str, Any]:
    """CBSE 80-Mark Official 5-Section Specimen Blueprint (38 Questions, 3 Hours)."""
    db_pools = _fetch_model_paper_questions_from_db(session, "CBSE", class_grade, subject, set_number)

    # Section A: 18 MCQs + 2 Assertion-Reason = 20 Marks
    db_1m = list(db_pools.get("1m", []))
    sec_a = []
    if db_1m:
        sec_a.extend(db_1m[:20])

    if len(sec_a) < 20:
        needed = 20 - len(sec_a)
        for i in range(1, needed - 1 if needed >= 2 else needed + 1):
            sec_a.append(_synthesize_curriculum_mcq(i + len(sec_a) + (set_number - 1) * 3, subject, "CBSE"))
        if len(sec_a) < 19:
            sec_a.append(_synthesize_assertion_reason(1 + (set_number - 1), subject))
        if len(sec_a) < 20:
            sec_a.append(_synthesize_assertion_reason(2 + (set_number - 1), subject))

    # Section B: 5 Required + 2 Extra Choice Questions = 7 Questions Total (2M each)
    db_2m = list(db_pools.get("2m", []))
    sec_b = []
    if db_2m:
        sec_b.extend(db_2m[:7])
    if len(sec_b) < 7:
        needed_b = 7 - len(sec_b)
        sec_b.extend([_synthesize_saq(i + len(sec_b) + (set_number - 1), subject, 2) for i in range(1, needed_b + 1)])

    # Section C: 6 Required + 2 Extra Choice Questions = 8 Questions Total (3M each)
    db_3m = list(db_pools.get("3m", []))
    sec_c = []
    if db_3m:
        sec_c.extend(db_3m[:8])
    if len(sec_c) < 8:
        needed_c = 8 - len(sec_c)
        sec_c.extend([_synthesize_saq(i + len(sec_c) + 5 + (set_number - 1), subject, 3) for i in range(1, needed_c + 1)])

    # Section D: 4 Required + 2 Extra Choice Questions = 6 Questions Total (5M each)
    db_5m = list(db_pools.get("5m", []))
    sec_d = []
    if db_5m:
        sec_d.extend(db_5m[:6])
    if len(sec_d) < 6:
        needed_d = 6 - len(sec_d)
        sec_d.extend([_synthesize_long(i + len(sec_d) + (set_number - 1), subject, 5) for i in range(1, needed_d + 1)])

    # Section E: 3 Required + 2 Extra Choice Questions = 5 Questions Total (4M each)
    db_4m = list(db_pools.get("4m", []))
    sec_e = []
    if db_4m:
        sec_e.extend(db_4m[:5])
    if len(sec_e) < 5:
        needed_e = 5 - len(sec_e)
        sec_e.extend([_synthesize_case(i + len(sec_e) + (set_number - 1), subject, 4) for i in range(1, needed_e + 1)])

    total_q = len(sec_a) + len(sec_b) + len(sec_c) + len(sec_d) + len(sec_e)
    db_count = min(len(db_1m), 20) + min(len(db_2m), 7) + min(len(db_3m), 8) + min(len(db_5m), 6) + min(len(db_4m), 5)
    fallback_count = max(0, total_q - db_count)

    if db_count >= total_q:
        source_label = "DATABASE (question_master)"
        source_type = "database"
    elif db_count == 0:
        source_label = "FALLBACK_CURRICULUM_BANK (fallback_exam_bank.py)"
        source_type = "fallback"
    else:
        source_label = f"HYBRID ({db_count} from Database + {fallback_count} from Fallback)"
        source_type = "hybrid"

    print("\n" + "=" * 78)
    print("[*] [MODEL QUESTION PAPER GENERATION LOG]")
    print(f">> Target    : CBSE | {class_grade} | {subject} (Set {set_number})")
    print(f">> Blueprint : CBSE 80-Mark Official 5-Section Specimen Blueprint")
    print(f">> SOURCE    : >>> {source_label} <<<")
    print(f">> Questions : {total_q} Total ({db_count} DB, {fallback_count} Fallback)")
    print(f">> Marks     : 80 Marks Total | Time: 3 Hours (180 Minutes)")
    print("=" * 78 + "\n")

    return {
        "board": "CBSE",
        "board_header": "CENTRAL BOARD OF SECONDARY EDUCATION",
        "exam_title": f"ALL INDIA SECONDARY / SENIOR SCHOOL EXAMINATION 2027",
        "paper_subtitle": f"SPECIMEN MODEL QUESTION PAPER — {class_grade.upper()} • SET {set_number}",
        "subject": subject,
        "class_grade": class_grade,
        "set_number": set_number,
        "time_allowed": "3 Hours (180 Minutes)",
        "max_marks": 80,
        "source": source_type,
        "source_label": source_label,
        "db_question_count": db_count,
        "fallback_question_count": fallback_count,
        "instructions": [
            "1. This question paper contains 46 questions in 5 Sections: A, B, C, D and E.",
            "2. Section A comprises 20 Multiple Choice Questions (MCQs) of 1 mark each (Compulsory).",
            "3. Section B comprises 7 Very Short Answer questions (2 marks each) — Attempt any 5.",
            "4. Section C comprises 8 Short Answer questions (3 marks each) — Attempt any 6.",
            "5. Section D comprises 6 Long Answer questions (5 marks each) — Attempt any 4.",
            "6. Section E comprises 5 Source/Case-Based integrated units (4 marks each) — Attempt any 3.",
            "7. Sections B through E contain 2 extra choice questions each for student selection flexibility.",
            "8. Use of calculators is not permitted."
        ],
        "sections": [
            {"title": "SECTION A — Multiple Choice & Assertion-Reason (20 Compulsory Questions × 1 Mark)", "questions": sec_a, "type": "mcq"},
            {"title": "SECTION B — Very Short Answer Type Questions (Attempt any 5 out of 7 Questions × 2 Marks)", "questions": sec_b, "type": "saq"},
            {"title": "SECTION C — Short Answer Type Questions (Attempt any 6 out of 8 Questions × 3 Marks)", "questions": sec_c, "type": "saq"},
            {"title": "SECTION D — Long Answer Type Questions (Attempt any 4 out of 6 Questions × 5 Marks)", "questions": sec_d, "type": "long"},
            {"title": "SECTION E — Case-Based Integrated Assessment (Attempt any 3 out of 5 Questions × 4 Marks)", "questions": sec_e, "type": "case"},
        ]
    }


def assemble_icse_paper(class_grade: str, subject: str, set_number: int, session=None) -> Dict[str, Any]:
    """ICSE 80-Mark Official 2-Section Specimen Blueprint (2.5 Hours + 15 Mins Reading)."""
    db_pools = _fetch_model_paper_questions_from_db(session, "ICSE", class_grade, subject, set_number)

    # Section A (Compulsory - 40 Marks)
    # Question 1: 15 MCQs (15 Marks)
    db_1m = list(db_pools.get("1m", []))
    q1_mcqs = []
    if db_1m:
        q1_mcqs.extend(db_1m[:15])
    if len(q1_mcqs) < 15:
        needed_1 = 15 - len(q1_mcqs)
        q1_mcqs.extend([_synthesize_curriculum_mcq(i + len(q1_mcqs) + (set_number - 1) * 2, subject, "ICSE") for i in range(1, needed_1 + 1)])

    # Question 2: Descriptive subparts (i) to (v) (15 Marks, 3M each)
    db_3m = list(db_pools.get("3m", []))
    q2_parts = []
    if db_3m:
        q2_parts.extend(db_3m[:5])
    if len(q2_parts) < 5:
        needed_2 = 5 - len(q2_parts)
        q2_parts.extend([_synthesize_saq(i + len(q2_parts) + (set_number - 1), subject, 3) for i in range(1, needed_2 + 1)])

    # Question 3: Structured subparts (i) to (v) (10 Marks, 2M each)
    db_2m = list(db_pools.get("2m", []))
    q3_parts = []
    if db_2m:
        q3_parts.extend(db_2m[:5])
    if len(q3_parts) < 5:
        needed_3 = 5 - len(q3_parts)
        q3_parts.extend([_synthesize_saq(i + len(q3_parts) + 5 + (set_number - 1), subject, 2) for i in range(1, needed_3 + 1)])

    # Section B (Attempt any 4 questions out of 7 - 40 Marks)
    # Questions 4 to 10: each carries 10 Marks (broken into parts (a)[3M], (b)[3M], (c)[4M])
    sec_b_questions = []
    for q_idx in range(4, 11):
        sec_b_questions.append({
            "question_num": q_idx,
            "parts": [
                {"label": "(a)", "text": f"Define the principle of {subject} equilibrium and state two governing conditions. [3 Marks]", "marks": 3},
                {"label": "(b)", "text": f"Calculate the unknown circuit/system parameter under steady state conditions shown below. [3 Marks]", "marks": 3},
                {"label": "(c)", "text": f"Derive the fundamental relation in {subject} and draw a neat labeled diagram. [4 Marks]", "marks": 4},
            ],
            "total_marks": 10
        })

    total_q = len(q1_mcqs) + len(q2_parts) + len(q3_parts) + len(sec_b_questions)
    db_count = min(len(db_1m), 15) + min(len(db_3m), 5) + min(len(db_2m), 5)
    fallback_count = max(0, total_q - db_count)

    if db_count >= total_q:
        source_label = "DATABASE (question_master)"
        source_type = "database"
    elif db_count == 0:
        source_label = "FALLBACK_CURRICULUM_BANK (fallback_exam_bank.py)"
        source_type = "fallback"
    else:
        source_label = f"HYBRID ({db_count} from Database + {fallback_count} from Fallback)"
        source_type = "hybrid"

    print("\n" + "=" * 78)
    print("[*] [MODEL QUESTION PAPER GENERATION LOG]")
    print(f">> Target    : ICSE | {class_grade} | {subject} (Set {set_number})")
    print(f">> Blueprint : ICSE 80-Mark Official 2-Section Specimen Blueprint")
    print(f">> SOURCE    : >>> {source_label} <<<")
    print(f">> Questions : {total_q} Total ({db_count} DB, {fallback_count} Fallback)")
    print(f">> Marks     : 80 Marks Total | Time: 2.5 Hours (150 Minutes)")
    print("=" * 78 + "\n")

    return {
        "board": "ICSE",
        "board_header": "COUNCIL FOR THE INDIAN SCHOOL CERTIFICATE EXAMINATIONS, NEW DELHI",
        "exam_title": "INDIAN CERTIFICATE OF SECONDARY EDUCATION EXAMINATION (ICSE) 2027",
        "paper_subtitle": f"SPECIMEN QUESTION PAPER — {class_grade.upper()} • {subject.upper()} (SET {set_number})",
        "subject": subject,
        "class_grade": class_grade,
        "set_number": set_number,
        "time_allowed": "2.5 Hours (150 Minutes)",
        "max_marks": 80,
        "source": source_type,
        "source_label": source_label,
        "db_question_count": db_count,
        "fallback_question_count": fallback_count,
        "instructions": [
            "1. Answers to this Paper must be written on the paper provided separately.",
            "2. You will not be allowed to write during the first 15 minutes. This time is to be spent in reading the question paper.",
            "3. The time given at the head of this Paper is the time allowed for writing the answers.",
            "4. Section A is compulsory. Attempt all questions from Section A.",
            "5. Attempt any four questions from Section B.",
            "6. The intended marks for questions or parts of questions are given in brackets [ ]."
        ],
        "icse_section_a": {
            "title": "SECTION A (40 Marks) — Compulsory (Attempt all questions)",
            "q1": q1_mcqs,  # 15 Marks
            "q2": q2_parts, # 15 Marks
            "q3": q3_parts, # 10 Marks
        },
        "icse_section_b": {
            "title": "SECTION B (40 Marks) — Attempt any FOUR questions from this Section",
            "questions": sec_b_questions  # 7 questions, 10 Marks each
        }
    }


def assemble_isc_paper(class_grade: str, subject: str, set_number: int, session=None) -> Dict[str, Any]:
    """ISC Class 11/12 80-Mark Specimen Blueprint (3 Sections, 3 Hours)."""
    db_pools = _fetch_model_paper_questions_from_db(session, "ISC", class_grade, subject, set_number)

    # Section A: 16 Compulsory Objective / MCQs (16 Marks)
    db_1m = list(db_pools.get("1m", []))
    sec_a = []
    if db_1m:
        sec_a.extend(db_1m[:16])
    if len(sec_a) < 16:
        needed_1 = 16 - len(sec_a)
        sec_a.extend([_synthesize_curriculum_mcq(i + len(sec_a) + (set_number - 1) * 2, subject, "ISC") for i in range(1, needed_1 + 1)])

    # Section B: 8 Short / Numerical Questions of 4 Marks each = 32 Marks
    db_4m = list(db_pools.get("4m", []))
    sec_b = []
    if db_4m:
        sec_b.extend(db_4m[:8])
    if len(sec_b) < 8:
        needed_b = 8 - len(sec_b)
        for i in range(1, needed_b + 1):
            sec_b.append({
                "question": f"<b>(a)</b> Evaluate the analytical response in {subject} and formulate the system equations.<br/>"
                            f"<b>(b)</b> Compute the steady state coefficient when boundary values reach threshold. [2 + 2 = 4 Marks]",
                "marks": 4
            })

    # Section C: 4 Evaluative / Derivation Questions of 8 Marks each = 32 Marks
    db_8m = list(db_pools.get("8m", []))
    sec_c = []
    if db_8m:
        sec_c.extend(db_8m[:4])
    if len(sec_c) < 4:
        needed_c = 4 - len(sec_c)
        for i in range(1, needed_c + 1):
            sec_c.append({
                "question": f"<b>(a)</b> Derive the comprehensive governing equation in {subject} from fundamental physical laws. Draw a neat schematic diagram. [4 Marks]<br/>"
                            f"<b>(b)</b> An operational system exhibits non-linear damping of 3.8%. Calculate the maximum power dissipation and justify the convergence criteria. [4 Marks]",
                "marks": 8
            })

    total_q = len(sec_a) + len(sec_b) + len(sec_c)
    db_count = min(len(db_1m), 16) + min(len(db_4m), 8) + min(len(db_8m), 4)
    fallback_count = max(0, total_q - db_count)

    if db_count >= total_q:
        source_label = "DATABASE (question_master)"
        source_type = "database"
    elif db_count == 0:
        source_label = "FALLBACK_CURRICULUM_BANK (fallback_exam_bank.py)"
        source_type = "fallback"
    else:
        source_label = f"HYBRID ({db_count} from Database + {fallback_count} from Fallback)"
        source_type = "hybrid"

    print("\n" + "=" * 78)
    print("[*] [MODEL QUESTION PAPER GENERATION LOG]")
    print(f">> Target    : ISC | {class_grade} | {subject} (Set {set_number})")
    print(f">> Blueprint : ISC 80-Mark Official 3-Section Specimen Blueprint")
    print(f">> SOURCE    : >>> {source_label} <<<")
    print(f">> Questions : {total_q} Total ({db_count} DB, {fallback_count} Fallback)")
    print(f">> Marks     : 80 Marks Total | Time: 3 Hours (180 Minutes)")
    print("=" * 78 + "\n")

    return {
        "board": "ISC",
        "board_header": "COUNCIL FOR THE INDIAN SCHOOL CERTIFICATE EXAMINATIONS, NEW DELHI",
        "exam_title": "INDIAN SCHOOL CERTIFICATE EXAMINATION (ISC - CLASS XII) 2027",
        "paper_subtitle": f"SPECIMEN QUESTION PAPER — {class_grade.upper()} • {subject.upper()} (SET {set_number})",
        "subject": subject,
        "class_grade": class_grade,
        "set_number": set_number,
        "time_allowed": "3 Hours (180 Minutes)",
        "max_marks": 80,
        "source": source_type,
        "source_label": source_label,
        "db_question_count": db_count,
        "fallback_question_count": fallback_count,
        "instructions": [
            "1. Answer all questions in Section A, Section B and Section C.",
            "2. Section A consists of 16 objective / multiple-choice subparts carrying 1 mark each.",
            "3. Section B consists of 8 short answer questions carrying 4 marks each.",
            "4. Section C consists of 4 long evaluative questions carrying 8 marks each.",
            "5. Internal choices have been provided in two questions each in Section B and Section C.",
            "6. All working, including rough work, must be shown on the same answer sheet alongside the relevant question.",
            "7. Mathematical tables and non-programmable calculators may be used if permitted."
        ],
        "sections": [
            {"title": "SECTION A (16 Marks) — Compulsory (16 Objective Questions × 1 Mark)", "questions": sec_a, "type": "mcq"},
            {"title": "SECTION B (32 Marks) — Short Answer & Analytical Questions (8 Questions × 4 Marks)", "questions": sec_b, "type": "saq"},
            {"title": "SECTION C (32 Marks) — Evaluative & Long Answer Questions (4 Questions × 8 Marks)", "questions": sec_c, "type": "long"},
        ]
    }


def get_model_paper_questions(
    board: str,
    class_grade: str,
    subject: str,
    set_number: int = 1,
    session=None,
) -> Dict[str, Any]:
    """Dispatches to board-specific assembler (CBSE, ICSE, ISC) with optional database session."""
    board_clean = board.upper().strip()
    if board_clean == "ICSE":
        return assemble_icse_paper(class_grade, subject, set_number, session=session)
    elif board_clean == "ISC":
        return assemble_isc_paper(class_grade, subject, set_number, session=session)
    else:
        return assemble_cbse_paper(class_grade, subject, set_number, session=session)


# ─────────────────────────────────────────────────────────────
# ReportLab PDF Generator (Authentic Board Layout)
# ─────────────────────────────────────────────────────────────

def generate_model_paper_pdf(paper_data: Dict[str, Any]) -> bytes:
    """Renders the Model Question Paper into a clean, official PDF using ReportLab."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    header_title_style = ParagraphStyle(
        "BoardTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=13,
        alignment=1,  # Center
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=2,
    )
    header_sub_style = ParagraphStyle(
        "BoardSub",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        alignment=1,
        textColor=colors.HexColor("#b45309"),
        spaceAfter=4,
    )
    instruction_title = ParagraphStyle(
        "InstTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=2,
    )
    instruction_body = ParagraphStyle(
        "InstBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10.5,
        textColor=colors.HexColor("#334155"),
    )
    sec_heading_style = ParagraphStyle(
        "SecHead",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=6,
        spaceAfter=4,
    )
    q_text_style = ParagraphStyle(
        "QText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#1e293b"),
    )
    q_num_style = ParagraphStyle(
        "QNum",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        textColor=colors.HexColor("#0f172a"),
    )
    q_marks_style = ParagraphStyle(
        "QMarks",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        alignment=2,  # Right
        textColor=colors.HexColor("#475569"),
    )
    opt_style = ParagraphStyle(
        "QOpt",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#334155"),
    )

    story = []

    # Board Header
    story.append(Paragraph(paper_data.get("board_header", "CENTRAL BOARD OF SECONDARY EDUCATION"), header_title_style))
    story.append(Paragraph(paper_data.get("exam_title", "EXAMINATION 2027"), header_sub_style))
    story.append(Paragraph(paper_data.get("paper_subtitle", "SPECIMEN QUESTION PAPER"), header_sub_style))

    # Info Strip Table
    info_data = [
        [
            Paragraph(f"<b>Subject:</b> {paper_data.get('subject', 'Mathematics')}", instruction_body),
            Paragraph(f"<b>Time Allowed:</b> {paper_data.get('time_allowed', '3 Hours')}", instruction_body),
            Paragraph(f"<b>Maximum Marks:</b> {paper_data.get('max_marks', 80)}", instruction_body),
        ]
    ]
    info_table = Table(info_data, colWidths=[200, 200, 140])
    info_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("PADDING", (0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )
    story.append(info_table)
    story.append(Spacer(1, 4))

    # General Instructions Box
    inst_lines = paper_data.get("instructions", [])
    inst_html = "<br/>".join(inst_lines)
    inst_content = [
        Paragraph("<b>General Instructions:</b>", instruction_title),
        Paragraph(inst_html, instruction_body),
    ]
    inst_table = Table([[inst_content]], colWidths=[540])
    inst_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffbeb")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#fde68a")),
            ("PADDING", (0, 0), (-1, -1), 5),
        ])
    )
    story.append(inst_table)
    story.append(Spacer(1, 6))

    # Render Board-Specific Content
    board = paper_data.get("board", "CBSE")

    if board == "ICSE":
        # Render ICSE Layout
        sec_a = paper_data.get("icse_section_a", {})
        story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#94a3b8"), spaceBefore=4, spaceAfter=4))
        story.append(Paragraph(sec_a.get("title", "SECTION A (40 Marks)"), sec_heading_style))
        story.append(Spacer(1, 3))

        # Question 1 (15 MCQs)
        story.append(Paragraph("<b>Question 1 (15 Multiple Choice Questions × 1 Mark = 15 Marks)</b>", instruction_title))
        for idx, mcq in enumerate(sec_a.get("q1", [])):
            sub_num_p = Paragraph(f"<b>({idx + 1})</b>", q_num_style)
            q_text_p = Paragraph(mcq.get("question", ""), q_text_style)
            q_marks_p = Paragraph("[1]", q_marks_style)

            q_table = Table([[sub_num_p, q_text_p, q_marks_p]], colWidths=[24, 480, 36])
            q_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 1)]))
            story.append(q_table)

            if mcq.get("options"):
                opts = mcq["options"]
                opt_rows = []
                for o_idx in range(0, len(opts), 2):
                    c1 = Paragraph(opts[o_idx], opt_style) if o_idx < len(opts) else Paragraph("", opt_style)
                    c2 = Paragraph(opts[o_idx + 1], opt_style) if o_idx + 1 < len(opts) else Paragraph("", opt_style)
                    opt_rows.append([Paragraph("", opt_style), c1, c2])
                opt_table = Table(opt_rows, colWidths=[24, 256, 260])
                opt_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 1)]))
                story.append(opt_table)
            story.append(Spacer(1, 3))

        # Question 2 (5 subparts, 15M)
        story.append(Spacer(1, 4))
        story.append(Paragraph("<b>Question 2 (5 Sub-questions × 3 Marks = 15 Marks)</b>", instruction_title))
        roman = ["(i)", "(ii)", "(iii)", "(iv)", "(v)"]
        for idx, sq in enumerate(sec_a.get("q2", [])):
            q_table = Table([[Paragraph(f"<b>{roman[idx]}</b>", q_num_style), Paragraph(sq.get("question", ""), q_text_style), Paragraph("[3]", q_marks_style)]], colWidths=[24, 480, 36])
            q_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 1)]))
            story.append(q_table)
            story.append(Spacer(1, 3))

        # Question 3 (5 subparts, 10M)
        story.append(Spacer(1, 4))
        story.append(Paragraph("<b>Question 3 (5 Sub-questions × 2 Marks = 10 Marks)</b>", instruction_title))
        for idx, sq in enumerate(sec_a.get("q3", [])):
            q_table = Table([[Paragraph(f"<b>{roman[idx]}</b>", q_num_style), Paragraph(sq.get("question", ""), q_text_style), Paragraph("[2]", q_marks_style)]], colWidths=[24, 480, 36])
            q_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 1)]))
            story.append(q_table)
            story.append(Spacer(1, 3))

        # Section B (Attempt any 4 questions out of 7 - 40 Marks)
        sec_b = paper_data.get("icse_section_b", {})
        story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#94a3b8"), spaceBefore=6, spaceAfter=4))
        story.append(Paragraph(sec_b.get("title", "SECTION B (40 Marks)"), sec_heading_style))
        story.append(Spacer(1, 3))

        for b_q in sec_b.get("questions", []):
            q_hdr = Table([[Paragraph(f"<b>Question {b_q['question_num']}</b>", instruction_title), Paragraph(f"[{b_q.get('total_marks', 10)} Marks]", q_marks_style)]], colWidths=[480, 60])
            q_hdr.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 1)]))
            story.append(q_hdr)

            for part in b_q.get("parts", []):
                p_table = Table([[Paragraph(f"<b>{part['label']}</b>", q_num_style), Paragraph(part["text"], q_text_style), Paragraph(f"[{part['marks']}]", q_marks_style)]], colWidths=[24, 480, 36])
                p_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 1)]))
                story.append(p_table)
                story.append(Spacer(1, 2))
            story.append(Spacer(1, 4))

    else:
        # Render CBSE / ISC Sections
        q_global_counter = 1
        for sec in paper_data.get("sections", []):
            story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#94a3b8"), spaceBefore=5, spaceAfter=4))
            story.append(Paragraph(sec.get("title", ""), sec_heading_style))
            story.append(Spacer(1, 3))

            is_mcq = sec.get("type") == "mcq"
            is_case = sec.get("type") == "case"

            for q in sec.get("questions", []):
                q_num_p = Paragraph(f"<b>Q{q_global_counter}.</b>", q_num_style)
                q_text_raw = q.get("question", "")
                if is_case and q.get("case_text"):
                    q_text_raw = f"<b>{q.get('case_title', '')}</b><br/><i>{q.get('case_text')}</i><br/><br/><b>Questions:</b><br/>{q_text_raw}"

                q_text_p = Paragraph(q_text_raw, q_text_style)
                q_marks_p = Paragraph(f"[{q.get('marks', 1)}]", q_marks_style)

                q_table = Table([[q_num_p, q_text_p, q_marks_p]], colWidths=[26, 478, 36])
                q_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 1)]))
                story.append(q_table)

                if is_mcq and q.get("options"):
                    opts = q["options"]
                    opt_rows = []
                    for idx in range(0, len(opts), 2):
                        col1 = Paragraph(opts[idx], opt_style) if idx < len(opts) else Paragraph("", opt_style)
                        col2 = Paragraph(opts[idx + 1], opt_style) if idx + 1 < len(opts) else Paragraph("", opt_style)
                        opt_rows.append([Paragraph("", opt_style), col1, col2])

                    opt_table = Table(opt_rows, colWidths=[26, 254, 260])
                    opt_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 1)]))
                    story.append(opt_table)

                story.append(Spacer(1, 3))
                q_global_counter += 1

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# ─────────────────────────────────────────────────────────────
# python-docx Word Document Generator (Authentic Board Layout)
# ─────────────────────────────────────────────────────────────

def generate_model_paper_docx(paper_data: Dict[str, Any]) -> bytes:
    """Renders the Model Question Paper into an editable Word (.docx) document."""
    doc = docx.Document()

    # Page Margins
    for s in doc.sections:
        s.top_margin = Inches(0.5)
        s.bottom_margin = Inches(0.5)
        s.left_margin = Inches(0.5)
        s.right_margin = Inches(0.5)

    # Title
    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_t = p_title.add_run(paper_data.get("board_header", "CENTRAL BOARD OF SECONDARY EDUCATION"))
    run_t.bold = True
    run_t.font.size = Pt(13)
    run_t.font.color.rgb = RGBColor(15, 23, 42)

    # Subtitle
    p_sub = doc.add_paragraph()
    p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_s = p_sub.add_run(f"{paper_data.get('exam_title', 'EXAMINATION 2027')}\n{paper_data.get('paper_subtitle', 'SPECIMEN QUESTION PAPER')}")
    run_s.bold = True
    run_s.font.size = Pt(10)
    run_s.font.color.rgb = RGBColor(180, 83, 9)

    # Info Table
    info_table = doc.add_table(rows=1, cols=3)
    info_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    row = info_table.rows[0]
    row.cells[0].paragraphs[0].text = f"Subject: {paper_data.get('subject', 'Mathematics')}"
    row.cells[1].paragraphs[0].text = f"Time Allowed: {paper_data.get('time_allowed', '3 Hours')}"
    row.cells[2].paragraphs[0].text = f"Maximum Marks: {paper_data.get('max_marks', 80)}"
    for c in row.cells:
        for p in c.paragraphs:
            p.runs[0].bold = True
            p.runs[0].font.size = Pt(9)

    doc.add_paragraph()

    # General Instructions
    p_inst_title = doc.add_paragraph()
    r_it = p_inst_title.add_run("General Instructions:")
    r_it.bold = True
    r_it.font.size = Pt(9.5)

    for it in paper_data.get("instructions", []):
        p_it = doc.add_paragraph(it, style="List Bullet")
        p_it.paragraph_format.space_after = Pt(1)
        if p_it.runs:
            p_it.runs[0].font.size = Pt(8.5)

    doc.add_paragraph()

    board = paper_data.get("board", "CBSE")

    if board == "ICSE":
        # ICSE Section A
        sec_a = paper_data.get("icse_section_a", {})
        p_sa = doc.add_paragraph()
        r_sa = p_sa.add_run(f"━━━ {sec_a.get('title', 'SECTION A (40 Marks)')} ━━━")
        r_sa.bold = True
        r_sa.font.size = Pt(10.5)

        # Q1 MCQs
        p_q1 = doc.add_paragraph()
        r_q1 = p_q1.add_run("Question 1 (15 Multiple Choice Questions × 1 Mark = 15 Marks)")
        r_q1.bold = True
        r_q1.font.size = Pt(9.5)

        for idx, mcq in enumerate(sec_a.get("q1", [])):
            clean_q = re.sub(r"<[^>]+>", "", mcq.get("question", ""))
            p_m = doc.add_paragraph()
            r_mn = p_m.add_run(f"({idx + 1}) {clean_q} ")
            r_mn.font.size = Pt(9)
            r_mm = p_m.add_run("[1 Mark]")
            r_mm.bold = True
            r_mm.font.size = Pt(8.5)
            r_mm.font.color.rgb = RGBColor(100, 116, 139)

            if mcq.get("options"):
                for opt in mcq["options"]:
                    p_opt = doc.add_paragraph(f"    {opt}")
                    p_opt.paragraph_format.space_after = Pt(0.5)
                    p_opt.runs[0].font.size = Pt(8.5)

        # Q2 Descriptive
        p_q2 = doc.add_paragraph()
        r_q2 = p_q2.add_run("Question 2 (5 Sub-questions × 3 Marks = 15 Marks)")
        r_q2.bold = True
        r_q2.font.size = Pt(9.5)
        roman = ["(i)", "(ii)", "(iii)", "(iv)", "(v)"]
        for idx, sq in enumerate(sec_a.get("q2", [])):
            clean_sq = re.sub(r"<[^>]+>", "", sq.get("question", ""))
            p_s = doc.add_paragraph(f"{roman[idx]} {clean_sq} [3 Marks]")
            p_s.runs[0].font.size = Pt(9)

        # Q3 Structured
        p_q3 = doc.add_paragraph()
        r_q3 = p_q3.add_run("Question 3 (5 Sub-questions × 2 Marks = 10 Marks)")
        r_q3.bold = True
        r_q3.font.size = Pt(9.5)
        for idx, sq in enumerate(sec_a.get("q3", [])):
            clean_sq = re.sub(r"<[^>]+>", "", sq.get("question", ""))
            p_s = doc.add_paragraph(f"{roman[idx]} {clean_sq} [2 Marks]")
            p_s.runs[0].font.size = Pt(9)

        # ICSE Section B
        sec_b = paper_data.get("icse_section_b", {})
        p_sb = doc.add_paragraph()
        r_sb = p_sb.add_run(f"\n━━━ {sec_b.get('title', 'SECTION B (40 Marks)')} ━━━")
        r_sb.bold = True
        r_sb.font.size = Pt(10.5)

        for b_q in sec_b.get("questions", []):
            p_bq = doc.add_paragraph()
            r_bq = p_bq.add_run(f"Question {b_q['question_num']} [{b_q.get('total_marks', 10)} Marks]")
            r_bq.bold = True
            r_bq.font.size = Pt(9.5)

            for part in b_q.get("parts", []):
                clean_pt = re.sub(r"<[^>]+>", "", part.get("text", ""))
                p_pt = doc.add_paragraph(f"    {part['label']} {clean_pt}")
                p_pt.runs[0].font.size = Pt(9)

    else:
        # CBSE / ISC Sections
        q_counter = 1
        for sec in paper_data.get("sections", []):
            p_sh = doc.add_paragraph()
            r_sh = p_sh.add_run(f"━━━ {sec.get('title', '')} ━━━")
            r_sh.bold = True
            r_sh.font.size = Pt(10)

            is_mcq = sec.get("type") == "mcq"
            is_case = sec.get("type") == "case"

            for q in sec.get("questions", []):
                if is_case and q.get("case_text"):
                    p_case = doc.add_paragraph(f"Case Context: {q.get('case_text')}")
                    p_case.runs[0].italic = True
                    p_case.runs[0].font.size = Pt(8.5)

                clean_q = re.sub(r"<[^>]+>", "", q.get("question", ""))
                p_q = doc.add_paragraph()
                r_qn = p_q.add_run(f"Q{q_counter}. {clean_q} ")
                r_qn.font.size = Pt(9)
                r_qm = p_q.add_run(f"[{q.get('marks', 1)} Marks]")
                r_qm.bold = True
                r_qm.font.size = Pt(8.5)
                r_qm.font.color.rgb = RGBColor(100, 116, 139)

                if is_mcq and q.get("options"):
                    for opt in q["options"]:
                        p_opt = doc.add_paragraph(f"    {opt}")
                        p_opt.paragraph_format.space_after = Pt(0.5)
                        p_opt.runs[0].font.size = Pt(8.5)

                p_q.paragraph_format.space_after = Pt(3)
                q_counter += 1

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
