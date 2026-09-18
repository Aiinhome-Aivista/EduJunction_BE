from model.models import Student, ExamSubmission, LearningPathNode, Badge, Misconception, AuthorMaster, CategoryMaster, Blog
from utils.date_helper import to_iso_ist


def student_to_child_account(student: Student, badge_ids: list[str] | None = None) -> dict:
    return {
        "id": student.id,
        "parentId": student.parent_id,
        "name": student.user.name if student.user else "",
        "username": student.user.username if student.user else "",
        "email": student.user.email if student.user else "",
        "avatar": student.avatar,
        "classGrade": student.class_grade,
        "targetBoard": student.target_board,
        "schoolName": student.school_name,
        "schoolEmail": student.school_email,
        "dailyExamsTakenToday": student.daily_exams_taken_today,
        "lastExamDate": student.last_exam_date.isoformat() if student.last_exam_date else None,
        "totalExamsTaken": student.total_exams_taken,
        "averageScore": float(student.average_score or 0),
        "streakDays": student.streak_days,
        "createdAt": to_iso_ist(student.created_at),
        "xp": student.xp,
        "level": student.level,
        "earnedBadgeIds": badge_ids or [],
    }


def submission_to_dict(submission: ExamSubmission) -> dict:
    evaluations_list = []
    if submission.evaluations:
        for ev in submission.evaluations:
            q = ev.question if hasattr(ev, 'question') and ev.question else None
            evaluations_list.append({
                "questionId": ev.question_id,
                "questionNumber": q.question_number if q else 1,
                "type": q.type if q else "mcq",
                "questionText": q.question_text if q else "",
                "options": q.options if q else [],
                "studentAnswer": ev.student_answer,
                "correctAnswer": q.correct_answer if q else "",
                "isCorrect": ev.is_correct,
                "marksAwarded": float(ev.marks_awarded) if ev.marks_awarded is not None else 0.0,
                "questionMarks": float(q.marks) if (q and q.marks) else (float(ev.marks_awarded) if ev.marks_awarded and ev.marks_awarded > 0 else 1.0),
                "explanation": q.explanation if q else "",
                "misconceptionIdentified": ev.misconception_identified,
                "feedback": getattr(ev, 'feedback', None),
                "referenceLinks": q.reference_links if q else [],
                "topic": q.topic if q else (submission.exam.subject if submission.exam else "General"),
            })

    analysis_dict = {
        "overallBand": "Proficient",
        "masteryScorePercentage": float(submission.accuracy_percentage or 0),
        "strengths": ["Foundational problem-solving", "Conceptual recall"],
        "areasToImprove": ["Timed accuracy", "Advanced HOTS questions"],
        "kGraphInsights": [],
        "evolutionaryRoadmap": "Continue daily diagnostic sprint practice to achieve full topic mastery.",
        "encouragementNote": "Solid diagnostic performance. Focus on identified remediation areas to maximize scores.",
        "recommendedNextExam": {
            "board": submission.exam.board if submission.exam else "CBSE",
            "classGrade": submission.exam.class_grade if submission.exam else "Class 10",
            "subject": submission.exam.subject if submission.exam else "Mathematics",
            "difficulty": "medium",
            "reason": "Reinforce conceptual foundations from diagnostic insights."
        },
        "curatedStudyLinks": [],
    }

    if submission.analysis:
        a = submission.analysis
        analysis_dict = {
            "overallBand": a.overall_band,
            "masteryScorePercentage": float(a.mastery_score_percentage or submission.accuracy_percentage or 0),
            "strengths": a.strengths or ["Core understanding"],
            "areasToImprove": a.areas_to_improve or ["Targeted practice"],
            "kGraphInsights": a.k_graph_insights or [],
            "evolutionaryRoadmap": a.evolutionary_roadmap or "Follow adaptive learning path.",
            "encouragementNote": a.encouragement_note or "Great effort on completing the diagnostic exam!",
            "recommendedNextExam": a.recommended_next_exam or {
                "board": submission.exam.board if submission.exam else "CBSE",
                "classGrade": submission.exam.class_grade if submission.exam else "Class 10",
                "subject": submission.exam.subject if submission.exam else "Mathematics",
                "difficulty": "medium",
                "reason": "Adaptive progression"
            },
            "curatedStudyLinks": a.curated_study_links or [],
        }

    return {
        "id": submission.id,
        "examId": submission.exam_id,
        "studentId": submission.student_id,
        "studentName": submission.student.user.name if (submission.student and submission.student.user) else "Student",
        "examTitle": submission.exam.title if submission.exam else "10-Mark Diagnostic Exam",
        "board": submission.exam.board if submission.exam else "CBSE",
        "classGrade": submission.exam.class_grade if submission.exam else "Class 10",
        "subject": submission.exam.subject if submission.exam else "Mathematics",
        "difficulty": submission.exam.difficulty if submission.exam else "medium",
        "answers": submission.answers or {},
        "marksObtained": float(submission.marks_obtained) if submission.marks_obtained is not None else 0.0,
        "totalMarks": submission.total_marks or (5 if (submission.exam and str(submission.exam.class_grade).lower() in ('class 1', 'class 2', 'class 3', 'class 4', '1', '2', '3', '4')) else 15),
        "accuracyPercentage": float(submission.accuracy_percentage or 0),
        "timeTakenSeconds": submission.time_taken_seconds or 0,
        "submittedAt": to_iso_ist(submission.submitted_at),
        "evaluations": evaluations_list,
        "analysis": analysis_dict,
    }


def learning_path_node_to_dict(node: LearningPathNode) -> dict:
    return {
        "id": node.id,
        "topic": node.topic,
        "chapterName": node.chapter_name,
        "subject": node.subject,
        "classGrade": node.class_grade,
        "board": node.board,
        "status": node.status,
        "masteryPercentage": float(node.mastery_percentage or 0),
        "level": node.level,
        "prerequisites": node.prerequisites or [],
        "keyConcepts": node.key_concepts or [],
        "commonMisconceptions": node.common_misconceptions or [],
        "curatedResources": node.curated_resources or [],
        "practiceExamConfig": node.practice_exam_config or {},
        "recommendedReason": node.recommended_reason,
    }


def badge_to_dict(badge: Badge) -> dict:
    return {
        "id": badge.id,
        "title": badge.title,
        "description": badge.description,
        "icon": badge.icon,
        "tier": badge.tier,
        "category": badge.category,
        "xpReward": badge.xp_reward,
        "requirementText": badge.requirement_text,
    }


def runbook_to_dict(rb) -> dict:
    return {
        "id": rb.id,
        "board": rb.board,
        "classGrade": rb.class_grade,
        "subject": rb.subject,
        "chapterName": rb.chapter_name,
        "coreConcepts": rb.core_concepts,
        "keyFormulasOrRules": rb.key_formulas_or_rules,
        "commonTraps": rb.common_traps,
        "curatedReferenceUrls": rb.curated_reference_urls,
        "sampleQuestionArchetypes": rb.sample_question_archetypes,
        "difficultyCalibration": rb.difficulty_calibration,
        "status": rb.status,
        "lastUpdated": rb.updated_at.date().isoformat() if rb.updated_at else None,
    }


def misconception_to_dict(m: Misconception) -> dict:
    return {
        "id": m.id,
        "topic": m.topic,
        "description": m.description,
        "evidence": m.evidence,
        "severity": m.severity,
        "status": m.status,
    }

def blog_to_dict(blog: Blog) -> dict:
    return {
        "id": blog.id,
        "title": blog.title,
        "heading": blog.title,
        "introduction": blog.introduction or "",
        "content": blog.content or "",
        "contentPreview": (blog.introduction or blog.content or "")[:240],
        "imageUrl": blog.image_url or "",
        "image": blog.image_url or "",
        "isPinned": bool(blog.is_pinned),
        "tags": blog.tags or [],
        "metaTitle": blog.meta_title or "",
        "metaDescription": blog.meta_description or "",
        "metaKeywords": blog.meta_keywords or "",
        "canonicalUrl": blog.canonical_url or "",
        "authorId": blog.author_id,
        "author": blog.author.name if blog.author else "Admin User",
        "authorName": blog.author.name if blog.author else "Admin User",
        "categoryId": blog.category_id,
        "category": blog.category.name if blog.category else "Education",
        "status": blog.status,
        "sharesCount": blog.shares_count or 0,
        "date": blog.date.strftime("%b %d, %Y") if blog.date else None,
        "isoDate": blog.date.isoformat() if blog.date else None,
        "createdAt": blog.created_at.isoformat() if blog.created_at else None,
        "updatedAt": blog.updated_at.isoformat() if blog.updated_at else None,
    }


def category_to_dict(cat: CategoryMaster, count: int = 0) -> dict:
    return {
        "id": cat.id,
        "name": cat.name,
        "isActive": cat.is_active,
        "status": "Active" if cat.is_active else "Inactive",
        "count": count,
        "items": count,
        "createdAt": cat.created_at.isoformat() if cat.created_at else None,
        "updatedAt": cat.updated_at.isoformat() if cat.updated_at else None,
    }


def author_to_dict(author: AuthorMaster, count: int = 0) -> dict:
    return {
        "id": author.id,
        "name": author.name,
        "isActive": author.is_active,
        "count": count,
        "createdAt": author.created_at.isoformat() if author.created_at else None,
        "updatedAt": author.updated_at.isoformat() if author.updated_at else None,
    }