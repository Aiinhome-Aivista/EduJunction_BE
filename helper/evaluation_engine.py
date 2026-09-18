"""Per-question and whole-exam evaluation logic.
Supports fast deterministic matching for MCQs and numerical questions,
and LLM-based proportional rubric step-marking for SAQs and subjective questions
with an intelligent keyword fallback engine."""
import re
import string
from pydantic import BaseModel, Field, ValidationError as PydanticValidationError

from model import mistral_client
from model.models import Question
from prompts import subjective_evaluation_prompt
from utils.logger import logger


class SubjectiveEvaluationItem(BaseModel):
    questionId: str
    marksAwarded: float = Field(default=0.0)
    isCorrect: bool = Field(default=False)
    matchedKeywords: list[str] = Field(default_factory=list)
    missedKeywords: list[str] = Field(default_factory=list)
    misconceptionIdentified: str | None = None
    feedback: str | None = None


class SubjectiveEvaluationResponse(BaseModel):
    evaluations: list[SubjectiveEvaluationItem] = Field(default_factory=list)


def _identify_misconception(question: Question, student_answer: str) -> str | None:
    if not student_answer or not student_answer.strip():
        return "Question skipped / incomplete attempt under time pressure."
    if question.type == "numerical":
        return "Calculation step error or unit conversion discrepancy."
    if question.type == "logical":
        return "Assertion-Reasoning logical causal link was misinterpreted."
    return "Conceptual distinction between related syllabus definitions."


def _extract_opt_letter(val: str) -> str:
    s = (val or "").strip()
    m = re.match(r"^(?:option\s+)?\(?([A-Da-d])(?:\)|\.|\:|\-|\s|$)", s, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return ""


def _to_float(value: str) -> float | None:
    cleaned = re.sub(r"[^0-9.\-]", "", value or "")
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _evaluate_mcq_or_logical(question: Question, student_ans: str, correct_ans: str) -> bool:
    student_letter = _extract_opt_letter(student_ans)
    correct_letter = _extract_opt_letter(correct_ans)

    # 1. Direct letter equality (e.g. "A" == "A")
    if student_letter and correct_letter and student_letter == correct_letter:
        return True

    # 2. Match against options array
    if question.options:
        student_matched_letter = student_letter
        correct_matched_letter = correct_letter

        for idx, opt in enumerate(question.options):
            opt_str = str(opt).strip()
            opt_let = _extract_opt_letter(opt_str) or chr(65 + idx)
            opt_body = re.sub(
                r"^(?:option\s+)?\(?[A-Da-d]\)?[\).\:\-]?\s*", "", opt_str, flags=re.IGNORECASE
            ).strip().lower()

            if not student_matched_letter:
                if student_ans.lower() == opt_body or student_ans.lower() == opt_str.lower():
                    student_matched_letter = opt_let

            if not correct_matched_letter:
                if (
                    correct_ans.lower() == opt_body
                    or correct_ans.lower() == opt_str.lower()
                    or (len(correct_ans) > 3 and correct_ans.lower() in opt_body)
                    or (len(correct_ans) > 3 and opt_body in correct_ans.lower())
                ):
                    correct_matched_letter = opt_let

        if student_matched_letter and correct_matched_letter and student_matched_letter == correct_matched_letter:
            return True

    # 3. Direct text equality
    clean_s = re.sub(r"^(?:option\s+)?\(?[A-Da-d]\)?[\).\:\-]?\s*", "", student_ans, flags=re.IGNORECASE).strip().lower()
    clean_c = re.sub(r"^(?:option\s+)?\(?[A-Da-d]\)?[\).\:\-]?\s*", "", correct_ans, flags=re.IGNORECASE).strip().lower()
    if clean_s and clean_s == clean_c:
        return True

    return False


def _fallback_subjective_evaluation(
    question: Question,
    student_ans: str,
    class_grade: str,
) -> dict:
    """Intelligent semantic and keyword matching fallback when LLM is unavailable."""
    if not student_ans or not student_ans.strip():
        return {
            "marksAwarded": 0.0,
            "isCorrect": False,
            "matchedKeywords": [],
            "missedKeywords": ["Core concept explanation"],
            "misconceptionIdentified": "Question skipped / incomplete attempt under time pressure.",
            "feedback": "You did not write an answer for this question.",
        }

    correct_ans = (question.correct_answer or "").strip()
    explanation = (question.explanation or "").strip()
    max_marks = float(question.marks or 2.0)

    # Stopwords to filter out
    stopwords = {
        "a", "an", "the", "is", "are", "was", "were", "in", "on", "at", "of", "to", "for",
        "and", "or", "by", "with", "from", "it", "that", "this", "which", "be", "as", "into"
    }

    def tokenize(text: str) -> set[str]:
        cleaned = text.lower().translate(str.maketrans("", "", string.punctuation))
        tokens = set(cleaned.split())
        return {t for t in tokens if len(t) > 2 and t not in stopwords}

    student_tokens = tokenize(student_ans)
    target_tokens = tokenize(f"{correct_ans} {explanation}")
    matched = student_tokens.intersection(target_tokens)
    missed = target_tokens.difference(student_tokens)

    matched_list = sorted(list(matched))[:5]
    missed_list = sorted(list(missed))[:5]

    overlap_ratio = len(matched) / max(len(target_tokens), 1)
    cg_lower = (class_grade or "").lower()

    if any(k in cg_lower for k in ["class 1", "class 2", "class 3", "class 4", "primary"]):
        if overlap_ratio >= 0.25 or any(m in student_ans.lower() for m in target_tokens):
            marks = max_marks
            feedback = "Wonderful effort! You clearly understood the main concept."
        elif overlap_ratio > 0.1:
            marks = round(max_marks * 0.75, 1)
            feedback = "Good attempt! You got parts of the answer right."
        else:
            marks = 0.0
            feedback = "Review the model answer to strengthen this topic."
    elif any(k in cg_lower for k in ["class 11", "class 12", "senior", "isc", "neet", "iit"]):
        if overlap_ratio >= 0.65:
            marks = max_marks
            feedback = "Comprehensive and accurate answer using proper terminology."
        elif overlap_ratio >= 0.40:
            marks = round(max_marks * 0.75, 1)
            feedback = "Substantial understanding shown; minor technical depth missing."
        elif overlap_ratio >= 0.20:
            marks = round(max_marks * 0.50, 1)
            feedback = "Partial credit awarded for identifying the initial concept."
        else:
            marks = 0.0
            feedback = "Essential scientific/mathematical keywords and steps were missing."
    else:  # Class 5 - 10
        if overlap_ratio >= 0.50:
            marks = max_marks
            feedback = "Excellent answer! Core concepts and key points are well captured."
        elif overlap_ratio >= 0.30:
            marks = round(max_marks * 0.75, 1)
            feedback = "Great attempt! You covered the main concept with slight omissions."
        elif overlap_ratio >= 0.15:
            marks = round(max_marks * 0.50, 1)
            feedback = "Partial credit awarded for key terms. Add more details next time."
        elif len(matched) >= 1:
            marks = round(max_marks * 0.25, 1)
            feedback = "Relevant keyword spotted, but needs a more complete explanation."
        else:
            marks = 0.0
            feedback = "Incorrect or incomplete explanation."

    is_correct = marks >= (max_marks * 0.5)
    misconception = None if is_correct else _identify_misconception(question, student_ans)

    return {
        "marksAwarded": float(marks),
        "isCorrect": is_correct,
        "matchedKeywords": matched_list,
        "missedKeywords": missed_list,
        "misconceptionIdentified": misconception,
        "feedback": feedback,
    }


def evaluate_exam(
    questions: list[Question],
    answers: dict[str, str],
    board: str = "CBSE",
    class_grade: str = "Class 10",
    subject: str = "General",
) -> tuple[list[dict], float]:
    """Evaluates all exam questions with hybrid deterministic + LLM proportional grading."""
    evaluations_dict: dict[str, dict] = {}
    subjective_items_to_llm: list[dict] = []
    subjective_questions_map: dict[str, Question] = {}

    # Step 1: Separate deterministic (MCQ / Numerical) from subjective questions (SAQ / Objective)
    for question in sorted(questions, key=lambda q: q.question_number):
        student_ans = (answers.get(question.id, "") or "").strip()
        correct_ans = (question.correct_answer or "").strip()
        q_type = str(question.type or "mcq").lower()

        if q_type in ("mcq", "logical"):
            is_correct = _evaluate_mcq_or_logical(question, student_ans, correct_ans)
            marks_awarded = float(question.marks or 1.0) if is_correct else 0.0
            evaluations_dict[question.id] = {
                "questionId": question.id,
                "questionNumber": question.question_number,
                "type": question.type,
                "questionText": question.question_text,
                "options": question.options,
                "studentAnswer": student_ans or "(Not Answered)",
                "correctAnswer": correct_ans,
                "isCorrect": is_correct,
                "marksAwarded": marks_awarded,
                "questionMarks": float(question.marks or 1.0),
                "explanation": question.explanation,
                "misconceptionIdentified": None if is_correct else _identify_misconception(question, student_ans),
                "referenceLinks": question.reference_links or [],
                "topic": question.topic,
                "matchedKeywords": [],
                "missedKeywords": [],
                "feedback": "Correct option selected." if is_correct else (
                    "Question skipped." if not student_ans else "Incorrect option selected."
                ),
            }

        elif q_type == "numerical":
            num_student = _to_float(student_ans)
            num_correct = _to_float(correct_ans)
            if num_student is not None and num_correct is not None:
                is_correct = abs(num_student - num_correct) < 0.05
            else:
                is_correct = student_ans.lower() == correct_ans.lower()

            marks_awarded = float(question.marks or 1.0) if is_correct else 0.0
            evaluations_dict[question.id] = {
                "questionId": question.id,
                "questionNumber": question.question_number,
                "type": question.type,
                "questionText": question.question_text,
                "options": question.options,
                "studentAnswer": student_ans or "(Not Answered)",
                "correctAnswer": correct_ans,
                "isCorrect": is_correct,
                "marksAwarded": marks_awarded,
                "questionMarks": float(question.marks or 1.0),
                "explanation": question.explanation,
                "misconceptionIdentified": None if is_correct else _identify_misconception(question, student_ans),
                "referenceLinks": question.reference_links or [],
                "topic": question.topic,
                "matchedKeywords": [],
                "missedKeywords": [],
                "feedback": "Accurate numerical calculation." if is_correct else (
                    "Calculation or unit error." if student_ans else "Question skipped."
                ),
            }

        else:
            # Subjective / SAQ / Objective
            if not student_ans:
                # Skipped SAQ
                evaluations_dict[question.id] = {
                    "questionId": question.id,
                    "questionNumber": question.question_number,
                    "type": question.type,
                    "questionText": question.question_text,
                    "options": question.options,
                    "studentAnswer": "(Not Answered)",
                    "correctAnswer": correct_ans,
                    "isCorrect": False,
                    "marksAwarded": 0.0,
                    "questionMarks": float(question.marks or 2.0),
                    "explanation": question.explanation,
                    "misconceptionIdentified": "Question skipped / incomplete attempt under time pressure.",
                    "referenceLinks": question.reference_links or [],
                    "topic": question.topic,
                    "matchedKeywords": [],
                    "missedKeywords": ["Complete answer skipped"],
                    "feedback": "You did not answer this question.",
                }
            else:
                subjective_items_to_llm.append({
                    "questionId": question.id,
                    "questionText": question.question_text,
                    "correctAnswer": correct_ans,
                    "explanation": question.explanation,
                    "questionMarks": float(question.marks or 2.0),
                    "studentAnswer": student_ans,
                    "topic": question.topic,
                })
                subjective_questions_map[question.id] = question

    # Step 2: Batch LLM subjective evaluation for attempted SAQs
    if subjective_items_to_llm:
        llm_evaluated = False
        if mistral_client.is_configured():
            try:
                user_prompt = subjective_evaluation_prompt.build_subjective_eval_prompt(
                    board=board,
                    class_grade=class_grade,
                    subject=subject,
                    items_to_evaluate=subjective_items_to_llm,
                )
                raw_response = mistral_client.generate_json(
                    subjective_evaluation_prompt.SYSTEM_PROMPT, user_prompt
                )
                validated = SubjectiveEvaluationResponse.model_validate(raw_response)

                for ev in validated.evaluations:
                    q = subjective_questions_map.get(ev.questionId)
                    if q:
                        q_max = float(q.marks or 2.0)
                        awarded = max(0.0, min(q_max, float(ev.marksAwarded)))
                        is_corr = awarded >= (q_max * 0.5)

                        evaluations_dict[q.id] = {
                            "questionId": q.id,
                            "questionNumber": q.question_number,
                            "type": q.type,
                            "questionText": q.question_text,
                            "options": q.options,
                            "studentAnswer": (answers.get(q.id, "") or "").strip(),
                            "correctAnswer": (q.correct_answer or "").strip(),
                            "isCorrect": is_corr,
                            "marksAwarded": awarded,
                            "questionMarks": q_max,
                            "explanation": q.explanation,
                            "misconceptionIdentified": ev.misconceptionIdentified if not is_corr else None,
                            "referenceLinks": q.reference_links or [],
                            "topic": q.topic,
                            "matchedKeywords": ev.matchedKeywords or [],
                            "missedKeywords": ev.missedKeywords or [],
                            "feedback": ev.feedback or (
                                "Good conceptual grasp." if is_corr else "Review key concepts for this topic."
                            ),
                        }
                llm_evaluated = True
            except (mistral_client.MistralUnavailableError, PydanticValidationError, Exception) as exc:
                logger.warning(f"LLM subjective evaluation failed, using fallback engine: {exc}")

        # Fallback for any subjective questions not evaluated by LLM
        for item in subjective_items_to_llm:
            q_id = item["questionId"]
            if q_id not in evaluations_dict:
                q = subjective_questions_map[q_id]
                fallback_res = _fallback_subjective_evaluation(
                    q, item["studentAnswer"], class_grade
                )
                evaluations_dict[q_id] = {
                    "questionId": q.id,
                    "questionNumber": q.question_number,
                    "type": q.type,
                    "questionText": q.question_text,
                    "options": q.options,
                    "studentAnswer": item["studentAnswer"],
                    "correctAnswer": (q.correct_answer or "").strip(),
                    "isCorrect": fallback_res["isCorrect"],
                    "marksAwarded": fallback_res["marksAwarded"],
                    "questionMarks": float(q.marks or 2.0),
                    "explanation": q.explanation,
                    "misconceptionIdentified": fallback_res["misconceptionIdentified"],
                    "referenceLinks": q.reference_links or [],
                    "topic": q.topic,
                    "matchedKeywords": fallback_res["matchedKeywords"],
                    "missedKeywords": fallback_res["missedKeywords"],
                    "feedback": fallback_res["feedback"],
                }

    # Step 3: Assemble ordered evaluations and calculate total marks obtained
    final_evaluations = []
    total_marks_obtained = 0.0
    for question in sorted(questions, key=lambda q: q.question_number):
        ev = evaluations_dict.get(question.id)
        if ev:
            final_evaluations.append(ev)
            total_marks_obtained += ev["marksAwarded"]

    return final_evaluations, round(total_marks_obtained, 2)

