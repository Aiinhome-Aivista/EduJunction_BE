import uuid
from datetime import datetime
from sqlalchemy.orm import Session

from model.models import LearningPathNode, Student
from utils.config import config
from utils.date_helper import now_ist


def recommend_difficulty_for_score(percentage: float) -> str:
    if percentage < config.MASTERY_THRESHOLD_DEVELOPING:
        return "simple"
    if percentage < config.MASTERY_THRESHOLD_PROFICIENT:
        return "medium"  # "Developing" band still practices at medium
    if percentage < config.MASTERY_THRESHOLD_ADVANCED:
        return "medium"
    return "hard"


def update_learning_path_after_submission(
    session: Session,
    student_id: int,
    subject: str,
    marks_obtained: int,
    k_graph_insights: list[dict],
):
    """Dynamically creates or updates learning path nodes based on AI diagnostic insights."""
    student = session.query(Student).filter(Student.id == student_id).first()
    board = student.target_board if student and student.target_board else "CBSE"
    class_grade = student.class_grade if student and student.class_grade else "Class 10"

    nodes = session.query(LearningPathNode).filter(LearningPathNode.student_id == student_id).all()
    matched_insight_topics = set()

    for node in nodes:
        matching_insight = next(
            (
                k for k in (k_graph_insights or [])
                if k.get("topic") and (k["topic"].lower() in node.topic.lower() or node.topic.lower() in k["topic"].lower())
            ),
            None,
        )

        if matching_insight is None and node.subject != subject:
            continue

        if matching_insight and matching_insight.get("topic"):
            matched_insight_topics.add(matching_insight["topic"].lower())

        mastery = float(matching_insight["masteryPercentage"]) if matching_insight and "masteryPercentage" in matching_insight else min(100.0, float(marks_obtained) * 10.0)

        if mastery >= 80:
            status = "mastered"
            level = "advanced_hots"
        elif mastery >= 50:
            status = "in_progress"
            level = "intermediate"
        else:
            status = "remedial_needed"
            level = "foundational"

        insight_text = (
            (matching_insight.get("insight") if matching_insight else None)
            or (matching_insight.get("recommendedReason") if matching_insight else None)
            or (
                f"Awesome work! You handled {node.topic} with fantastic confidence and accuracy. You have built a solid grasp here and are capable of tackling higher-level challenges to level up your streak!"
                if mastery >= 85
                else (
                    f"Good effort! You answered basic questions in {node.topic} nicely, but there are a few multi-step steps to polish. With a quick review, you will master it completely."
                    if mastery >= 50
                    else f"Don't worry, every champion learns by trying! You gave a great attempt, but {node.topic} has a few tricky definitions to brush up on. With a little review, you'll master this in no time."
                )
            )
        )
        action_text = (
            (matching_insight.get("recommendedAction") if matching_insight else None)
            or (
                f"Read the advanced problem-solving section in your {subject} textbook for {node.topic}, then try 3-4 challenging questions to sharpen your speed."
                if mastery >= 85
                else (
                    f"Review the key formulas and worked examples for {node.topic} in your {subject} textbook, then practice 3 multi-step problems."
                    if mastery >= 50
                    else f"Open your {subject} textbook chapter on {node.topic}, carefully read the core concept summary, and solve 2 foundational practice exercises."
                )
            )
        )

        node.mastery_percentage = max(float(node.mastery_percentage or 0), mastery)
        node.status = status
        node.level = level
        node.attempts_count = (node.attempts_count or 0) + 1
        node.last_score = marks_obtained
        node.recommended_reason = insight_text
        cfg = dict(node.practice_exam_config or {})
        cfg["recommendedAction"] = action_text
        node.practice_exam_config = cfg
        node.updated_at = now_ist()

    # If insights had topics not matched to existing nodes (or if student had no nodes yet), dynamically insert them
    if k_graph_insights:
        for insight in k_graph_insights:
            topic_name = insight.get("topic") or f"{subject} Core Topic"
            if topic_name.lower() in matched_insight_topics:
                continue

            mastery = float(insight.get("masteryPercentage", marks_obtained * 10))
            if mastery >= 85:
                status = "mastered"
                level = "advanced_hots"
            elif mastery >= 50:
                status = "in_progress"
                level = "intermediate"
            else:
                status = "remedial_needed"
                level = "foundational"

            insight_text = (
                insight.get("insight")
                or insight.get("recommendedReason")
                or (
                    f"Awesome work! You handled {topic_name} with fantastic confidence and accuracy. You have built a solid grasp here and are capable of tackling higher-level challenges to level up your streak!"
                    if mastery >= 85
                    else (
                        f"Good effort! You answered basic questions in {topic_name} nicely, but there are a few multi-step steps to polish. With a quick review, you will master it completely."
                        if mastery >= 50
                        else f"Don't worry, every champion learns by trying! You gave a great attempt, but {topic_name} has a few tricky definitions to brush up on. With a little review, you'll master this in no time."
                    )
                )
            )
            action_text = (
                insight.get("recommendedAction")
                or (
                    f"Read the advanced problem-solving section in your {subject} textbook for {topic_name}, then try 3-4 challenging questions to sharpen your speed."
                    if mastery >= 85
                    else (
                        f"Review the key formulas and worked examples for {topic_name} in your {subject} textbook, then practice 3 multi-step problems."
                        if mastery >= 50
                        else f"Open your {subject} textbook chapter on {topic_name}, carefully read the core concept summary, and solve 2 foundational practice exercises."
                    )
                )
            )

            new_node = LearningPathNode(
                id=str(uuid.uuid4()),
                student_id=student_id,
                topic=topic_name,
                chapter_name=insight.get("chapter") or f"{subject} Foundations",
                subject=subject,
                class_grade=class_grade,
                board=board,
                status=status,
                mastery_percentage=mastery,
                level=level,
                prerequisites=insight.get("prerequisites", []),
                key_concepts=insight.get("keyConcepts", []),
                common_misconceptions=insight.get("commonMisconceptions", []),
                curated_resources=insight.get("curatedResources", []),
                practice_exam_config={
                    "board": board,
                    "class": class_grade,
                    "subject": subject,
                    "chapter": insight.get("chapter") or topic_name,
                    "difficulty": recommend_difficulty_for_score(mastery),
                    "recommendedAction": action_text,
                },
                recommended_reason=insight_text,
                attempts_count=1,
                last_score=marks_obtained,
                updated_at=now_ist(),
            )
            session.add(new_node)
            matched_insight_topics.add(topic_name.lower())
    elif not nodes:
        # Fallback if no specific kGraphInsights were generated but student took an exam in this subject
        mastery = min(100.0, float(marks_obtained) * 10.0)
        status = "mastered" if mastery >= 80 else ("in_progress" if mastery >= 50 else "remedial_needed")
        level = "advanced_hots" if mastery >= 80 else ("intermediate" if mastery >= 50 else "foundational")
        fallback_node = LearningPathNode(
            id=str(uuid.uuid4()),
            student_id=student_id,
            topic=f"{subject} Mastery Track",
            chapter_name=f"{subject} Diagnostic Assessment",
            subject=subject,
            class_grade=class_grade,
            board=board,
            status=status,
            mastery_percentage=mastery,
            level=level,
            prerequisites=[],
            key_concepts=[],
            common_misconceptions=[],
            curated_resources=[],
            practice_exam_config={
                "board": board,
                "class": class_grade,
                "subject": subject,
                "difficulty": recommend_difficulty_for_score(mastery),
            },
            recommended_reason="Personalized learning trajectory initialized from your latest diagnostic exam.",
            attempts_count=1,
            last_score=marks_obtained,
            updated_at=now_ist(),
        )
        session.add(fallback_node)

    session.flush()


