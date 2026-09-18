from flask import jsonify, request, g
from sqlalchemy import text

from middleware.authMiddleware import token_required
from helper.chat_engine import generate_chat_response
from database.dbConnection import get_session
from utils.logger import logger

@token_required
def chat():
    """
    POST /api/v1/chat
    Request Body:
    {
      "messages": [{"role": "user", "content": "..."}],
      "student_id": "optional_id"
    }
    """
    try:
        user_id = g.current_user_id
        if not user_id:
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        data = request.json or {}
        messages = data.get("messages", [])
        student_id = data.get("student_id")

        if not messages:
            return jsonify({"success": False, "message": "No messages provided"}), 400

        user_role = getattr(g, "current_user_role", "PARENT")
        last_user_query = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_query = msg.get("content", "").strip()
                break

        student_context = None
        target_student_id = student_id

        with get_session() as session:
            # 1. Check if user is a student
            is_student_user = session.execute(
                text("SELECT id FROM students WHERE id = :uid"),
                {"uid": user_id}
            ).scalar()
            if is_student_user:
                target_student_id = user_id
                user_role = "STUDENT"
            else:
                # 2. Parent flow: check all linked children
                linked_children = session.execute(
                    text("""
                        SELECT s.id, u.name, s.class_grade, s.target_board, s.average_score
                        FROM students s
                        JOIN users u ON s.id = u.id
                        WHERE s.parent_id = :parent_id
                    """),
                    {"parent_id": user_id}
                ).mappings().all()

                if linked_children:
                    # Check if query specifically mentions a child's name (e.g. "Sanjay" or "Aarav")
                    query_lower = last_user_query.lower()
                    matched_child = None
                    for child in linked_children:
                        c_name = (child.get("name") or "").lower().strip()
                        c_first = c_name.split()[0] if c_name else ""
                        if (c_first and c_first in query_lower) or (c_name and c_name in query_lower):
                            matched_child = child
                            break
                    
                    if matched_child:
                        target_student_id = matched_child["id"]
                    elif not target_student_id:
                        target_student_id = linked_children[0]["id"]

            if target_student_id:
                result = session.execute(
                    text("""
                        SELECT u.name, s.class_grade, s.target_board, s.average_score
                        FROM users u 
                        JOIN students s ON u.id = s.id 
                        WHERE u.id = :student_id
                    """),
                    {"student_id": target_student_id}
                ).mappings().first()

                if result:
                    # Query weak topics (mastery < 75%)
                    weak_rows = session.execute(
                        text("""
                            SELECT topic FROM mastery 
                            WHERE student_id = :student_id AND mastery_score < 75
                            ORDER BY mastery_score ASC LIMIT 5
                        """),
                        {"student_id": target_student_id}
                    ).fetchall()
                    weak_topics = [r[0] for r in weak_rows]

                    # Query recent exam marks
                    recent_subs = session.execute(
                        text("""
                            SELECT marks_obtained FROM exam_submissions 
                            WHERE student_id = :student_id
                            ORDER BY submitted_at DESC LIMIT 3
                        """),
                        {"student_id": target_student_id}
                    ).fetchall()
                    recent_scores = [r[0] for r in recent_subs]

                    student_context = {
                        "id": target_student_id,
                        "name": result.get("name", "Student"),
                        "classGrade": result.get("class_grade", "Class 10"),
                        "targetBoard": result.get("target_board", "CBSE"),
                        "averageScore": float(result.get("average_score", 0)) if result.get("average_score") is not None else 0,
                        "weakTopics": weak_topics,
                        "recentScores": recent_scores
                    }

        response_text = generate_chat_response(messages, student_context, user_role=user_role)

        return jsonify({
            "success": True,
            "response": response_text
        })

    except Exception as e:
        logger.error(f"Chat Controller Error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Failed to process chat"}), 500


@token_required
def get_chat_suggestions():
    """
    GET /api/v1/chat/suggestions
    Returns 4 dynamic, context-aware suggested questions for the authenticated user.
    """
    import random
    try:
        user_id = g.current_user_id
        if not user_id:
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        with get_session() as session:
            # 1. Check if user is a student
            student_row = session.execute(
                text("""
                    SELECT s.id, u.name, s.class_grade, s.target_board, s.average_score
                    FROM students s
                    JOIN users u ON s.id = u.id
                    WHERE s.id = :uid
                """),
                {"uid": user_id}
            ).mappings().first()

            if student_row:
                # Student Persona
                student_id = student_row["id"]
                grade = student_row.get("class_grade") or "Class 10"
                board = student_row.get("target_board") or "CBSE"

                # Weak topics from mastery
                weak_rows = session.execute(
                    text("""
                        SELECT topic, mastery_score FROM mastery
                        WHERE student_id = :sid AND mastery_score < 80
                        ORDER BY mastery_score ASC LIMIT 6
                    """),
                    {"sid": student_id}
                ).mappings().all()

                # Recent exam submissions
                recent_exams = session.execute(
                    text("""
                        SELECT es.marks_obtained, e.title, e.subject, es.total_marks
                        FROM exam_submissions es
                        JOIN exams e ON es.exam_id = e.id
                        WHERE es.student_id = :sid
                        ORDER BY es.submitted_at DESC LIMIT 4
                    """),
                    {"sid": student_id}
                ).mappings().all()

                question_pool = []

                # Weak topic questions
                for w in weak_rows:
                    t = w.get("topic")
                    if t:
                        question_pool.append(f"Explain {t} in simple terms with an example.")
                        question_pool.append(f"Give me 2 practice problems on {t}.")
                        question_pool.append(f"How can I master {t} before my next test?")

                # Recent exam questions
                for ex in recent_exams:
                    subj = ex.get("subject") or "Mathematics"
                    marks = ex.get("marks_obtained")
                    total = ex.get("total_marks") or 10
                    title = ex.get("title") or subj
                    if marks is not None:
                        question_pool.append(f"I scored {marks}/{total} in {title}. How can I improve next time?")
                        question_pool.append(f"Where did I likely lose marks in {subj}?")

                # General boosters
                question_pool.extend([
                    f"How do I level up my {grade} overall score to 90%+?",
                    f"What is the best way to earn badges and keep my streak alive?",
                    f"Can you explain a difficult concept in simple words?",
                    f"Give me 3 smart tips to solve diagnostic math questions faster!",
                    f"What should I practice today for {board} curriculum?",
                    f"Can you create a 5-minute quick revision checklist for me?"
                ])

                random.shuffle(question_pool)
                seen = set()
                final_questions = []
                for q in question_pool:
                    if q not in seen:
                        seen.add(q)
                        final_questions.append(q)
                    if len(final_questions) >= 4:
                        break

                return jsonify({
                    "success": True,
                    "role": "STUDENT",
                    "suggestions": final_questions
                })

            else:
                # Parent Persona: query all linked children
                linked_children = session.execute(
                    text("""
                        SELECT s.id, u.name, s.class_grade, s.target_board, s.average_score
                        FROM students s
                        JOIN users u ON s.id = u.id
                        WHERE s.parent_id = :parent_id
                    """),
                    {"parent_id": user_id}
                ).mappings().all()

                if not linked_children:
                    return jsonify({
                        "success": True,
                        "role": "PARENT",
                        "suggestions": [
                            "How do I get started with SahajPath?",
                            "How can I add and track my child's learning journey?",
                            "What is the best way to build a daily study routine?",
                            "How do 10-Mark diagnostic assessments work?"
                        ]
                    })

                question_pool = []
                for child in linked_children:
                    cid = child["id"]
                    cname = (child.get("name") or "Student").split()[0]
                    cgrade = child.get("class_grade") or "Class 10"

                    # Weak topics for this child
                    weak_rows = session.execute(
                        text("""
                            SELECT topic FROM mastery
                            WHERE student_id = :sid AND mastery_score < 80
                            ORDER BY mastery_score ASC LIMIT 4
                        """),
                        {"sid": cid}
                    ).fetchall()
                    child_weak = [r[0] for r in weak_rows if r[0]]

                    # Recent exam for this child
                    recent_exam = session.execute(
                        text("""
                            SELECT es.marks_obtained, e.title, e.subject, es.total_marks
                            FROM exam_submissions es
                            JOIN exams e ON es.exam_id = e.id
                            WHERE es.student_id = :sid
                            ORDER BY es.submitted_at DESC LIMIT 2
                        """),
                        {"sid": cid}
                    ).mappings().all()

                    question_pool.append(f"How is {cname} progressing overall in {cgrade}?")

                    if child_weak:
                        for topic in child_weak[:2]:
                            question_pool.append(f"How can I help {cname} improve in {topic} at home?")
                            question_pool.append(f"Why is {cname} finding {topic} challenging?")
                    else:
                        question_pool.append(f"What advanced topics should {cname} practice next?")

                    if recent_exam:
                        for ex in recent_exam:
                            sub_name = ex.get("subject") or ex.get("title") or "recent test"
                            marks = ex.get("marks_obtained")
                            total = ex.get("total_marks") or 10
                            question_pool.append(f"Can you explain {cname}'s {marks}/{total} result in {sub_name}?")

                    question_pool.append(f"How can I help {cname} build a daily home study routine?")

                random.shuffle(question_pool)
                seen = set()
                final_questions = []
                for q in question_pool:
                    if q not in seen:
                        seen.add(q)
                        final_questions.append(q)
                    if len(final_questions) >= 4:
                        break

                return jsonify({
                    "success": True,
                    "role": "PARENT",
                    "suggestions": final_questions
                })

    except Exception as e:
        logger.error(f"Error fetching suggestions: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Failed to fetch suggestions"}), 500

