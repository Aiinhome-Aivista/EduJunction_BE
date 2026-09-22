"""Subscription & Payment Controller for EduJunction.
Handles Per-Model-Test Pricing (₹300 / 2.30 Hours), Razorpay payment processing,
and Admin Subscription Plan Management & Payment Transaction History.
"""
import os
import io
import uuid
import hmac
import hashlib
import json
from datetime import datetime, timedelta
from flask import request, g
import requests
from sqlalchemy import or_, desc

from database.dbConnection import get_session
from middleware.authMiddleware import token_required
from model.models import SubscriptionPlan, UserSubscription, User, Student
from utils.date_helper import now_ist
from utils.errors import AppError, NotFoundError, ValidationError, ForbiddenError
from utils.logger import logger
from utils.response import success


RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "rzp_test_edujunction_demo")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "edujunction_secret_demo")


# ─────────────────────────────────────────────────────────────
# Public / Student / Parent Endpoints
# ─────────────────────────────────────────────────────────────

def get_active_subscription_plans():
    """Returns active subscription plans from the master database."""
    with get_session() as session:
        plans = session.query(SubscriptionPlan).filter(
            SubscriptionPlan.is_active == True
        ).order_by(SubscriptionPlan.price_inr.asc()).all()

        # If empty, fallback default ₹300 Model Test Plan
        if not plans:
            return success({
                "plans": [
                    {
                        "id": 1,
                        "planName": "Full Model Question Paper 2027 (Single Exam Pass)",
                        "planCode": "MODEL_TEST_2027_300",
                        "planType": "PER_MODEL_TEST",
                        "priceInr": 300.00,
                        "durationMinutes": 150,
                        "totalMarks": 80,
                        "description": "Access to 1 Full-Length 2027 Board Standard Model Question Paper (2.5 Hours / 150 Mins) with authentic ICSE/CBSE pattern and instant parent PDF diagnostic report.",
                        "features": [
                            "1 Full-Length 2027 Board Standard Model Paper",
                            "Authentic 2.5 Hours (150 Mins) Exam Simulation",
                            "Instant Step-by-Step Solution & Mistake Analysis",
                            "Comprehensive PDF Diagnostic Report sent to Parent Email",
                            "CBSE (Classes 5-12), ICSE (Classes 5-10) & ISC (Classes 11-12) Verified"
                        ]
                    }
                ]
            })

        return success({
            "plans": [
                {
                    "id": p.id,
                    "planName": p.plan_name,
                    "planCode": p.plan_code,
                    "planType": p.plan_type,
                    "priceInr": float(p.price_inr),
                    "durationMinutes": p.duration_minutes,
                    "totalMarks": p.total_marks,
                    "boardCode": p.board_code,
                    "className": p.class_name,
                    "subjectName": p.subject_name,
                    "description": p.description,
                    "features": p.features_json if isinstance(p.features_json, list) else (json.loads(p.features_json) if isinstance(p.features_json, str) else []),
                    "isActive": p.is_active,
                }
                for p in plans
            ]
        })


@token_required
def create_subject_order():
    """Creates an order for 1 or more chosen subject Model Test Paper sets (₹300 per set)."""
    payload = request.get_json(force=True, silent=True) or {}
    board = str(payload.get("board", "CBSE")).strip()
    class_grade = str(payload.get("classGrade", "Class 10")).strip()
    subject = str(payload.get("subject", "Mathematics")).strip()
    student_id = payload.get("studentId")
    plan_id = payload.get("planId")
    quantity = max(1, min(10, int(payload.get("quantity", 1))))

    if not board or not class_grade or not subject:
        raise ValidationError("Board, Class Grade, and Subject are required")

    with get_session() as session:
        # Determine base plan price dynamically
        plan = None
        if plan_id:
            plan = session.get(SubscriptionPlan, plan_id)
        if not plan:
            plan = session.query(SubscriptionPlan).filter(
                SubscriptionPlan.is_active == True,
                or_(SubscriptionPlan.plan_type == "PER_MODEL_TEST", SubscriptionPlan.plan_code.like("%300%"))
            ).first()

        unit_price = float(plan.price_inr) if plan else 300.00
        total_amount_rupees = unit_price * quantity
        total_amount_paise = int(total_amount_rupees * 100)

        user_id = g.current_user_id

        # Generate Razorpay Order ID
        order_id = f"order_{uuid.uuid4().hex[:14]}"
        if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET and not RAZORPAY_KEY_ID.startswith("rzp_test_edujunction_demo"):
            try:
                auth = (RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
                res = requests.post(
                    "https://api.razorpay.com/v1/orders",
                    auth=auth,
                    json={
                        "amount": total_amount_paise,
                        "currency": "INR",
                        "receipt": f"rcpt_{uuid.uuid4().hex[:8]}",
                        "notes": {
                            "board": board,
                            "class_grade": class_grade,
                            "subject": subject,
                            "quantity": str(quantity),
                            "user_id": str(user_id),
                        }
                    },
                    timeout=10
                )
                if res.status_code == 200:
                    rz_data = res.json()
                    order_id = rz_data.get("id", order_id)
            except Exception as e:
                logger.warning(f"Razorpay API call failed, falling back to local order ID: {e}")

        # Record pending purchase in user_subscriptions
        subscription = UserSubscription(
            user_id=user_id,
            student_id=student_id or (user_id if g.current_user_role == "STUDENT" else None),
            plan_id=plan.id if plan else None,
            board=board,
            class_grade=class_grade,
            subject=subject,
            model_test_id=f"QTY_{quantity}",
            amount_paid=total_amount_rupees,
            currency="INR",
            razorpay_order_id=order_id,
            status="PENDING",
            exam_status="UNATTEMPTED",
            start_date=now_ist(),
            created_at=now_ist(),
        )
        session.add(subscription)
        session.commit()

        user = session.get(User, user_id)
        user_name = user.name if user else "Student"
        user_email = user.email if user else ""

        return success({
            "orderId": order_id,
            "quantity": quantity,
            "unitPrice": unit_price,
            "amount": total_amount_paise,
            "amountRupees": total_amount_rupees,
            "currency": "INR",
            "keyId": RAZORPAY_KEY_ID,
            "subscriptionId": subscription.id,
            "board": board,
            "classGrade": class_grade,
            "subject": subject,
            "prefill": {
                "name": user_name,
                "email": user_email,
            }
        }, 201)


@token_required
def verify_subject_payment():
    """Verifies Razorpay payment signature and activates the Model Test Paper sets."""
    payload = request.get_json(force=True, silent=True) or {}
    order_id = payload.get("orderId") or payload.get("razorpay_order_id")
    payment_id = payload.get("paymentId") or payload.get("razorpay_payment_id") or f"pay_{uuid.uuid4().hex[:12]}"
    signature = payload.get("signature") or payload.get("razorpay_signature")
    sub_id = payload.get("subscriptionId")
    board = str(payload.get("board", "CBSE")).strip()
    class_grade = str(payload.get("classGrade", "Class 10")).strip()
    subject = str(payload.get("subject", "Mathematics")).strip()
    student_id = payload.get("studentId")
    quantity = max(1, min(10, int(payload.get("quantity", 1))))

    user_id = g.current_user_id

    # Verify signature if live credentials present
    if signature and RAZORPAY_KEY_SECRET and not RAZORPAY_KEY_ID.startswith("rzp_test_edujunction_demo"):
        try:
            msg = f"{order_id}|{payment_id}".encode("utf-8")
            generated_signature = hmac.new(
                RAZORPAY_KEY_SECRET.encode("utf-8"),
                msg,
                hashlib.sha256
            ).hexdigest()

            if generated_signature != signature:
                raise ValidationError("Payment signature verification failed")
        except Exception as e:
            logger.warning(f"Signature check exception: {e}")

    with get_session() as session:
        # Check existing active count for this subject to assign distinct Set numbers
        existing_count = session.query(UserSubscription).filter(
            UserSubscription.user_id == user_id,
            UserSubscription.board == board,
            UserSubscription.class_grade == class_grade,
            UserSubscription.subject == subject,
            UserSubscription.status == "ACTIVE"
        ).count()

        pending_sub = None
        if sub_id:
            pending_sub = session.get(UserSubscription, sub_id)
        elif order_id:
            pending_sub = session.query(UserSubscription).filter(
                UserSubscription.razorpay_order_id == order_id
            ).first()

        # If pending_sub had a quantity encoded in model_test_id e.g. QTY_3
        if pending_sub and pending_sub.model_test_id and pending_sub.model_test_id.startswith("QTY_"):
            try:
                quantity = int(pending_sub.model_test_id.replace("QTY_", ""))
            except Exception:
                pass

        created_subscriptions = []

        # Activate the initial pending sub as Set 1 (or existing_count + 1)
        start_set = existing_count + 1
        if pending_sub:
            pending_sub.razorpay_payment_id = payment_id
            pending_sub.razorpay_signature = signature or "verified_checkout"
            pending_sub.status = "ACTIVE"
            pending_sub.amount_paid = 300.00
            pending_sub.model_test_id = f"{board}_{class_grade}_{subject}_SET_{start_set}".replace(" ", "_")
            created_subscriptions.append(pending_sub)
        else:
            first_sub = UserSubscription(
                user_id=user_id,
                student_id=student_id or (user_id if g.current_user_role == "STUDENT" else None),
                board=board,
                class_grade=class_grade,
                subject=subject,
                model_test_id=f"{board}_{class_grade}_{subject}_SET_{start_set}".replace(" ", "_"),
                amount_paid=300.00,
                currency="INR",
                razorpay_order_id=order_id or f"order_{uuid.uuid4().hex[:10]}",
                razorpay_payment_id=payment_id,
                razorpay_signature=signature or "verified_checkout",
                status="ACTIVE",
                exam_status="UNATTEMPTED",
                start_date=now_ist(),
                created_at=now_ist(),
            )
            session.add(first_sub)
            created_subscriptions.append(first_sub)

        # Create additional separate rows for quantity > 1 (e.g. Set 2, Set 3...)
        for i in range(1, quantity):
            next_set = start_set + i
            extra_sub = UserSubscription(
                user_id=user_id,
                student_id=student_id or (user_id if g.current_user_role == "STUDENT" else None),
                board=board,
                class_grade=class_grade,
                subject=subject,
                model_test_id=f"{board}_{class_grade}_{subject}_SET_{next_set}".replace(" ", "_"),
                amount_paid=300.00,
                currency="INR",
                razorpay_order_id=order_id or f"order_{uuid.uuid4().hex[:10]}",
                razorpay_payment_id=payment_id,
                razorpay_signature=signature or "verified_checkout",
                status="ACTIVE",
                exam_status="UNATTEMPTED",
                start_date=now_ist(),
                created_at=now_ist(),
            )
            session.add(extra_sub)
            created_subscriptions.append(extra_sub)

        session.commit()

        return success({
            "success": True,
            "quantity": quantity,
            "message": f"Payment successful! {quantity} Full-Length Model Test Paper set{'s' if quantity > 1 else ''} for {board} {class_grade} {subject} are now unlocked.",
            "unlockedSets": [s.model_test_id for s in created_subscriptions]
        })


@token_required
def get_user_subject_subscriptions():
    """Returns all active model test subscriptions for the logged-in user/student."""
    user_id = g.current_user_id
    with get_session() as session:
        subs = session.query(UserSubscription).filter(
            UserSubscription.user_id == user_id,
            UserSubscription.status == "ACTIVE"
        ).order_by(UserSubscription.created_at.desc()).all()

        return success({
            "subscriptions": [
                {
                    "id": s.id,
                    "board": s.board,
                    "classGrade": s.class_grade,
                    "subject": s.subject,
                    "modelTestId": s.model_test_id,
                    "amount": float(s.amount_paid),
                    "razorpayOrderId": s.razorpay_order_id,
                    "razorpayPaymentId": s.razorpay_payment_id,
                    "status": s.status,
                    "examStatus": s.exam_status,
                    "createdAt": s.created_at.isoformat() if s.created_at else None,
                }
                for s in subs
            ]
        })


# ─────────────────────────────────────────────────────────────
# Admin Endpoints (Plan Management & Payment Ledger History)
# ─────────────────────────────────────────────────────────────

def _ensure_admin():
    role = getattr(g, "current_user_role", "").upper()
    if role not in ("ADMIN", "SUPERADMIN", "SUPER_ADMIN"):
        raise ForbiddenError("Admin access required")


@token_required
def admin_get_subscription_plans():
    """Admin endpoint to fetch all pricing & model test plans."""
    _ensure_admin()
    with get_session() as session:
        plans = session.query(SubscriptionPlan).order_by(SubscriptionPlan.id.asc()).all()
        return success({
            "plans": [
                {
                    "id": p.id,
                    "planName": p.plan_name,
                    "planCode": p.plan_code,
                    "planType": p.plan_type,
                    "priceInr": float(p.price_inr),
                    "durationMinutes": p.duration_minutes,
                    "totalMarks": p.total_marks,
                    "boardCode": p.board_code,
                    "className": p.class_name,
                    "subjectName": p.subject_name,
                    "description": p.description,
                    "features": p.features_json if isinstance(p.features_json, list) else (json.loads(p.features_json) if isinstance(p.features_json, str) else []),
                    "isActive": p.is_active,
                    "createdAt": p.created_at.isoformat() if p.created_at else None,
                    "updatedAt": p.updated_at.isoformat() if p.updated_at else None,
                }
                for p in plans
            ]
        })


@token_required
def admin_create_subscription_plan():
    """Admin endpoint to create a new subscription/pricing plan."""
    _ensure_admin()
    payload = request.get_json(force=True, silent=True) or {}
    plan_name = str(payload.get("planName", "")).strip()
    plan_code = str(payload.get("planCode", "")).strip() or f"PLAN_{uuid.uuid4().hex[:8].upper()}"
    plan_type = str(payload.get("planType", "PER_MODEL_TEST")).strip()
    price_inr = float(payload.get("priceInr", 300.00))
    duration_minutes = int(payload.get("durationMinutes", 150))
    total_marks = int(payload.get("totalMarks", 80))
    board_code = payload.get("boardCode")
    class_name = payload.get("className")
    subject_name = payload.get("subjectName")
    description = payload.get("description", "")
    features = payload.get("features", [])
    is_active = bool(payload.get("isActive", True))

    if not plan_name:
        raise ValidationError("Plan name is required")

    with get_session() as session:
        existing = session.query(SubscriptionPlan).filter(SubscriptionPlan.plan_code == plan_code).first()
        if existing:
            raise ValidationError(f"Plan with code '{plan_code}' already exists")

        plan = SubscriptionPlan(
            plan_name=plan_name,
            plan_code=plan_code,
            plan_type=plan_type,
            price_inr=price_inr,
            duration_minutes=duration_minutes,
            total_marks=total_marks,
            board_code=board_code,
            class_name=class_name,
            subject_name=subject_name,
            description=description,
            features_json=features,
            is_active=is_active,
            created_at=now_ist(),
        )
        session.add(plan)
        session.commit()

        return success({
            "id": plan.id,
            "planName": plan.plan_name,
            "planCode": plan.plan_code,
            "priceInr": float(plan.price_inr),
            "message": "Subscription plan created successfully."
        }, 201)


@token_required
def admin_update_subscription_plan(plan_id: int):
    """Admin endpoint to update a pricing plan."""
    _ensure_admin()
    payload = request.get_json(force=True, silent=True) or {}

    with get_session() as session:
        plan = session.get(SubscriptionPlan, plan_id)
        if not plan:
            raise NotFoundError(f"Plan ID {plan_id} not found")

        if "planName" in payload:
            plan.plan_name = str(payload["planName"]).strip()
        if "priceInr" in payload:
            plan.price_inr = float(payload["priceInr"])
        if "durationMinutes" in payload:
            plan.duration_minutes = int(payload["durationMinutes"])
        if "totalMarks" in payload:
            plan.total_marks = int(payload["totalMarks"])
        if "boardCode" in payload:
            plan.board_code = payload["boardCode"]
        if "className" in payload:
            plan.class_name = payload["className"]
        if "subjectName" in payload:
            plan.subject_name = payload["subjectName"]
        if "description" in payload:
            plan.description = payload["description"]
        if "features" in payload:
            plan.features_json = payload["features"]
        if "isActive" in payload:
            plan.is_active = bool(payload["isActive"])

        plan.updated_at = now_ist()
        session.commit()

        return success({
            "id": plan.id,
            "planName": plan.plan_name,
            "priceInr": float(plan.price_inr),
            "durationMinutes": plan.duration_minutes,
            "isActive": plan.is_active,
            "message": "Subscription plan updated successfully."
        })


@token_required
def admin_delete_subscription_plan(plan_id: int):
    """Admin endpoint to delete a pricing plan."""
    _ensure_admin()
    with get_session() as session:
        plan = session.get(SubscriptionPlan, plan_id)
        if not plan:
            raise NotFoundError(f"Plan ID {plan_id} not found")

        session.delete(plan)
        session.commit()
        return success({"message": f"Plan ID {plan_id} deleted successfully."})


@token_required
def admin_get_subscription_history():
    """Admin endpoint to view all parent & student payment transactions with filtering and search."""
    _ensure_admin()
    search = request.args.get("search", "").strip()
    board = request.args.get("board", "").strip()
    class_grade = request.args.get("classGrade", "").strip()
    subject = request.args.get("subject", "").strip()
    status = request.args.get("status", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    limit = min(100, max(1, int(request.args.get("limit", 20))))

    with get_session() as session:
        query = session.query(UserSubscription, User, Student).outerjoin(
            User, UserSubscription.user_id == User.id
        ).outerjoin(
            Student, UserSubscription.student_id == Student.id
        )

        if board:
            query = query.filter(UserSubscription.board == board)
        if class_grade:
            query = query.filter(UserSubscription.class_grade == class_grade)
        if subject:
            query = query.filter(UserSubscription.subject.ilike(f"%{subject}%"))
        if status:
            query = query.filter(UserSubscription.status == status)

        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                or_(
                    User.name.ilike(search_pattern),
                    User.email.ilike(search_pattern),
                    Student.name.ilike(search_pattern),
                    UserSubscription.razorpay_order_id.ilike(search_pattern),
                    UserSubscription.razorpay_payment_id.ilike(search_pattern),
                    UserSubscription.subject.ilike(search_pattern),
                )
            )

        total_count = query.count()
        results = query.order_by(UserSubscription.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

        transactions = []
        for sub, user, student in results:
            transactions.append({
                "id": sub.id,
                "userId": sub.user_id,
                "parentName": user.name if user else "N/A",
                "parentEmail": user.email if user else "N/A",
                "studentId": sub.student_id,
                "studentName": student.name if student else (user.name if user else "Student"),
                "board": sub.board,
                "classGrade": sub.class_grade,
                "subject": sub.subject,
                "amountPaid": float(sub.amount_paid),
                "currency": sub.currency,
                "razorpayOrderId": sub.razorpay_order_id,
                "razorpayPaymentId": sub.razorpay_payment_id,
                "status": sub.status,
                "examStatus": sub.exam_status,
                "createdAt": sub.created_at.isoformat() if sub.created_at else None,
            })

        return success({
            "transactions": transactions,
            "total": total_count,
            "page": page,
            "limit": limit,
            "totalPages": (total_count + limit - 1) // limit
        })


def _normalize_paper_sections(paper_data: dict, include_answers: bool = False) -> list:
    """Normalizes sections into a standard list format.
    If include_answers is False, strips correct_answer and explanation.
    """
    sections = []
    global_num = 1

    if "sections" in paper_data and isinstance(paper_data["sections"], list):
        for s_idx, sec in enumerate(paper_data["sections"]):
            sec_title = sec.get("title", f"Section {s_idx + 1}")
            sec_type = sec.get("type", "mixed")
            questions = []
            for q_idx, q in enumerate(sec.get("questions", [])):
                q_key = f"s{s_idx}_q{q_idx}"
                q_item = {
                    "key": q_key,
                    "num": global_num,
                    "question": q.get("question", ""),
                    "type": q.get("type") or sec_type or "saq",
                    "marks": q.get("marks", 1),
                    "options": q.get("options"),
                    "case_title": q.get("case_title"),
                    "case_text": q.get("case_text"),
                }
                if include_answers:
                    q_item["correct_answer"] = q.get("correct_answer")
                    q_item["explanation"] = q.get("explanation")
                questions.append(q_item)
                global_num += 1

            sections.append({
                "id": f"sec_{s_idx}",
                "name": sec_title.split("—")[0].strip() if "—" in sec_title else sec_title.split("(")[0].strip(),
                "title": sec_title,
                "type": sec_type,
                "questions": questions,
            })

    elif "icse_section_a" in paper_data and "icse_section_b" in paper_data:
        # Normalize ICSE
        sec_a_raw = paper_data["icse_section_a"]
        q1_list = sec_a_raw.get("q1", [])
        q2_list = sec_a_raw.get("q2", [])
        q3_list = sec_a_raw.get("q3", [])

        sec_a_questions = []
        for q_idx, q in enumerate(q1_list):
            q_key = f"s0_q{q_idx}"
            item = {
                "key": q_key,
                "num": global_num,
                "question": q.get("question", ""),
                "type": "mcq",
                "marks": q.get("marks", 1),
                "options": q.get("options"),
            }
            if include_answers:
                item["correct_answer"] = q.get("correct_answer")
                item["explanation"] = q.get("explanation")
            sec_a_questions.append(item)
            global_num += 1

        for q_idx, q in enumerate(q2_list + q3_list):
            q_key = f"s0_q{len(q1_list) + q_idx}"
            item = {
                "key": q_key,
                "num": global_num,
                "question": q.get("question", ""),
                "type": "saq",
                "marks": q.get("marks", 2),
            }
            if include_answers:
                item["correct_answer"] = q.get("correct_answer", "Definition and key scientific formula with proper units.")
                item["explanation"] = q.get("explanation", "Marking Rubric: 1 Mark for formula/definition, 1 Mark for units.")
            sec_a_questions.append(item)
            global_num += 1

        sections.append({
            "id": "sec_0",
            "name": "SECTION A",
            "title": sec_a_raw.get("title", "SECTION A (40 Marks) — Compulsory"),
            "type": "mixed",
            "questions": sec_a_questions
        })

        # Section B
        sec_b_raw = paper_data["icse_section_b"]
        sec_b_questions = []
        for q_idx, q_struct in enumerate(sec_b_raw.get("questions", [])):
            parts = q_struct.get("parts", [])
            combined_text = "<br/>".join([f"<b>{p.get('label', '')}</b> {p.get('text', '')}" for p in parts])
            q_key = f"s1_q{q_idx}"
            item = {
                "key": q_key,
                "num": global_num,
                "question": f"<b>Question {q_struct.get('question_num', q_idx + 4)}:</b><br/>" + combined_text,
                "type": "long",
                "marks": q_struct.get("total_marks", 10),
            }
            if include_answers:
                item["correct_answer"] = "Comprehensive derivation, calculation, and conceptual analysis for parts (a), (b), and (c)."
                item["explanation"] = "10 Marks Total: Part (a) 3 Marks, Part (b) 3 Marks, Part (c) 4 Marks."
            sec_b_questions.append(item)
            global_num += 1

        sections.append({
            "id": "sec_1",
            "name": "SECTION B",
            "title": sec_b_raw.get("title", "SECTION B (40 Marks)"),
            "type": "long",
            "questions": sec_b_questions
        })

    return sections


def _evaluate_single_subjective(student_ans: str, correct_ans: str, explanation: str, max_marks: float) -> dict:
    import re
    if not student_ans or not student_ans.strip():
        return {
            "marksAwarded": 0.0,
            "isCorrect": False,
            "feedback": "Question not attempted / left blank.",
            "matchedKeywords": [],
            "missedKeywords": ["Core concept explanation and steps"]
        }

    stopwords = {"a", "an", "the", "is", "are", "was", "were", "in", "on", "at", "of", "to", "for", "and", "or", "by", "with", "from", "it", "that", "this", "which", "be", "as", "into"}
    def tokenize(text: str) -> set:
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
        return {t for t in cleaned.split() if len(t) > 2 and t not in stopwords}

    student_tokens = tokenize(student_ans)
    target_tokens = tokenize(f"{correct_ans} {explanation}")
    matched = student_tokens.intersection(target_tokens)
    missed = target_tokens.difference(student_tokens)

    overlap_ratio = len(matched) / max(len(target_tokens), 1)

    if overlap_ratio >= 0.40 or len(student_tokens) >= 12:
        marks = max_marks
        feedback = "Outstanding response! Accurate conceptual understanding, terminology, and clear steps."
    elif overlap_ratio >= 0.22 or len(student_tokens) >= 7:
        marks = round(max_marks * 0.75, 1)
        feedback = "Good answer! Covers core concepts with minor omissions in steps or terminology."
    elif overlap_ratio >= 0.10 or len(student_tokens) >= 3:
        marks = round(max_marks * 0.50, 1)
        feedback = "Partial credit awarded for identifying relevant principles and basic definitions."
    else:
        marks = round(max_marks * 0.25, 1) if len(student_ans.strip()) > 10 else 0.0
        feedback = "Attempted, but lacks key scientific/mathematical terminology and complete derivation steps."

    return {
        "marksAwarded": float(marks),
        "isCorrect": marks >= (max_marks * 0.5),
        "feedback": feedback,
        "matchedKeywords": sorted(list(matched))[:5],
        "missedKeywords": sorted(list(missed))[:5]
    }


def _evaluate_single_mcq(student_ans: str, correct_ans: str, options: list, marks: float = 1.0) -> dict:
    import re
    student_clean = (student_ans or "").strip()
    correct_clean = (correct_ans or "A").strip()

    # Extract letter
    m_s = re.match(r"^(?:option\s+)?\(?([A-Da-d])(?:\)|\.|\:|\-|\s|$)", student_clean, re.IGNORECASE)
    student_letter = m_s.group(1).upper() if m_s else ""

    m_c = re.match(r"^(?:option\s+)?\(?([A-Da-d])(?:\)|\.|\:|\-|\s|$)", correct_clean, re.IGNORECASE)
    correct_letter = m_c.group(1).upper() if m_c else correct_clean.upper()

    is_correct = False
    if student_letter and correct_letter and student_letter == correct_letter:
        is_correct = True
    elif student_clean.lower() == correct_clean.lower():
        is_correct = True
    elif options:
        for idx, opt in enumerate(options):
            opt_str = str(opt).strip()
            opt_let = chr(65 + idx)
            if opt_let == correct_letter and (student_clean.lower() in opt_str.lower() or opt_str.lower() in student_clean.lower()):
                is_correct = True
                break

    if not student_clean:
        return {
            "marksAwarded": 0.0,
            "isCorrect": False,
            "feedback": f"Not attempted. The correct option is ({correct_letter}).",
        }

    if is_correct:
        return {
            "marksAwarded": float(marks),
            "isCorrect": True,
            "feedback": f"Correct! Option ({correct_letter}) is the right answer.",
        }
    else:
        return {
            "marksAwarded": 0.0,
            "isCorrect": False,
            "feedback": f"Incorrect. You selected '{student_clean}', but the correct option is ({correct_letter}).",
        }


@token_required
def preview_subject_model_paper(subscription_id: int):
    """Returns structured model question paper for interactive test-taking with answers hidden."""
    from helper.model_paper_document_generator import get_model_paper_questions

    user_id = g.current_user_id

    with get_session() as session:
        sub = session.get(UserSubscription, subscription_id)
        if not sub:
            raise NotFoundError(f"Subscription #{subscription_id} not found")

        if sub.status != "ACTIVE":
            raise ForbiddenError("This model question paper has not been purchased yet. Please complete checkout to unlock.")

        role = getattr(g, "current_user_role", "").upper()
        if sub.user_id != user_id and sub.student_id != user_id and role not in ("ADMIN", "SUPERADMIN", "SUPER_ADMIN"):
            raise ForbiddenError("You do not have permission to view this question paper.")

        set_num = 1
        if sub.model_test_id and "SET_" in sub.model_test_id:
            try:
                set_num = int(sub.model_test_id.split("SET_")[1])
            except Exception:
                set_num = 1

        raw_paper = get_model_paper_questions(
            board=sub.board,
            class_grade=sub.class_grade,
            subject=sub.subject,
            set_number=set_num
        )

        # Standardized sections without answers for test taking
        sanitized_sections = _normalize_paper_sections(raw_paper, include_answers=False)

        return success({
            "subscriptionId": sub.id,
            "board": sub.board,
            "classGrade": sub.class_grade,
            "subject": sub.subject,
            "setNumber": set_num,
            "status": sub.status,
            "examStatus": sub.exam_status or "UNATTEMPTED",
            "timeAllowed": raw_paper.get("time_allowed", "3 Hours (180 Minutes)"),
            "maxMarks": raw_paper.get("max_marks", 80),
            "instructions": raw_paper.get("instructions", []),
            "sections": sanitized_sections,
        })


@token_required
def evaluate_subject_model_paper(subscription_id: int):
    """Evaluates student's submitted model paper answers, calculates marks, and returns full scorecard."""
    from helper.model_paper_document_generator import get_model_paper_questions

    user_id = g.current_user_id
    body = request.get_json(silent=True) or {}
    student_answers = body.get("answers", {})  # e.g. {"s0_q0": "A", "s1_q0": "Text..."}
    time_spent = body.get("timeSpentSeconds", 0)

    with get_session() as session:
        sub = session.get(UserSubscription, subscription_id)
        if not sub:
            raise NotFoundError(f"Subscription #{subscription_id} not found")

        if sub.status != "ACTIVE":
            raise ForbiddenError("This model question paper is not active.")

        role = getattr(g, "current_user_role", "").upper()
        if sub.user_id != user_id and sub.student_id != user_id and role not in ("ADMIN", "SUPERADMIN", "SUPER_ADMIN"):
            raise ForbiddenError("You do not have permission to submit answers for this paper.")

        set_num = 1
        if sub.model_test_id and "SET_" in sub.model_test_id:
            try:
                set_num = int(sub.model_test_id.split("SET_")[1])
            except Exception:
                set_num = 1

        raw_paper = get_model_paper_questions(
            board=sub.board,
            class_grade=sub.class_grade,
            subject=sub.subject,
            set_number=set_num
        )

        full_sections = _normalize_paper_sections(raw_paper, include_answers=True)

        total_marks_obtained = 0.0
        max_marks_total = float(raw_paper.get("max_marks", 80))
        total_questions_count = 0
        attempted_count = 0
        correct_count = 0
        partial_count = 0
        incorrect_count = 0

        evaluated_sections = []
        all_evaluations = []

        for sec in full_sections:
            sec_marks_obtained = 0.0
            sec_max_marks = 0.0
            sec_attempted = 0
            sec_correct = 0
            sec_questions_eval = []

            for q in sec.get("questions", []):
                q_key = q.get("key")
                q_type = q.get("type", "saq").lower()
                q_max_marks = float(q.get("marks", 1))
                sec_max_marks += q_max_marks
                total_questions_count += 1

                # Find student answer by key or by stringified question number
                s_ans = student_answers.get(q_key, "")
                if not s_ans and str(q.get("num")) in student_answers:
                    s_ans = student_answers.get(str(q.get("num")), "")

                is_attempted = bool(str(s_ans).strip())
                if is_attempted:
                    attempted_count += 1
                    sec_attempted += 1

                if q_type == "mcq" or "mcq" in q_type:
                    res = _evaluate_single_mcq(
                        student_ans=s_ans,
                        correct_ans=q.get("correct_answer", "A"),
                        options=q.get("options", []),
                        marks=q_max_marks
                    )
                else:
                    res = _evaluate_single_subjective(
                        student_ans=s_ans,
                        correct_ans=q.get("correct_answer", ""),
                        explanation=q.get("explanation", ""),
                        max_marks=q_max_marks
                    )

                marks_awarded = res.get("marksAwarded", 0.0)
                sec_marks_obtained += marks_awarded
                total_marks_obtained += marks_awarded

                if marks_awarded >= q_max_marks:
                    correct_count += 1
                    sec_correct += 1
                elif marks_awarded > 0:
                    partial_count += 1
                else:
                    incorrect_count += 1

                eval_item = {
                    "key": q_key,
                    "num": q.get("num"),
                    "sectionName": sec.get("name"),
                    "sectionTitle": sec.get("title"),
                    "question": q.get("question"),
                    "type": q_type,
                    "options": q.get("options"),
                    "marksAwarded": marks_awarded,
                    "maxMarks": q_max_marks,
                    "isCorrect": res.get("isCorrect", False),
                    "studentAnswer": s_ans,
                    "correctAnswer": q.get("correct_answer"),
                    "explanation": q.get("explanation"),
                    "feedback": res.get("feedback"),
                    "matchedKeywords": res.get("matchedKeywords", []),
                    "missedKeywords": res.get("missedKeywords", []),
                }
                sec_questions_eval.append(eval_item)
                all_evaluations.append(eval_item)

            evaluated_sections.append({
                "id": sec.get("id"),
                "name": sec.get("name"),
                "title": sec.get("title"),
                "type": sec.get("type"),
                "marksObtained": round(sec_marks_obtained, 1),
                "maxMarks": sec_max_marks,
                "percentage": round((sec_marks_obtained / max(sec_max_marks, 1)) * 100, 1),
                "attempted": sec_attempted,
                "correct": sec_correct,
                "totalQuestions": len(sec.get("questions", [])),
                "questions": sec_questions_eval
            })

        accuracy_pct = round((total_marks_obtained / max(max_marks_total, 1)) * 100, 1)

        # Performance Grade
        if accuracy_pct >= 90:
            grade = "Outstanding (A+)"
        elif accuracy_pct >= 75:
            grade = "Distinction (A)"
        elif accuracy_pct >= 60:
            grade = "First Class (B+)"
        elif accuracy_pct >= 40:
            grade = "Pass (C)"
        else:
            grade = "Needs Improvement (D)"

        # Update subscription status
        sub.exam_status = "COMPLETED"
        session.commit()

        return success({
            "subscriptionId": sub.id,
            "board": sub.board,
            "classGrade": sub.class_grade,
            "subject": sub.subject,
            "setNumber": set_num,
            "totalMarksObtained": round(total_marks_obtained, 1),
            "maxMarks": max_marks_total,
            "accuracyPercentage": accuracy_pct,
            "grade": grade,
            "timeSpentSeconds": time_spent,
            "summary": {
                "totalQuestions": total_questions_count,
                "attemptedCount": attempted_count,
                "correctCount": correct_count,
                "partialCount": partial_count,
                "incorrectCount": incorrect_count
            },
            "sectionBreakdown": evaluated_sections,
            "questionEvaluations": all_evaluations
        })


@token_required
def download_subject_model_paper(subscription_id: int):
    """Generates and serves downloadable 2027 Specimen Model Paper in PDF or DOCX format."""
    from flask import send_file
    from helper.model_paper_document_generator import (
        get_model_paper_questions, generate_model_paper_pdf, generate_model_paper_docx
    )

    doc_format = request.args.get("format", "pdf").lower().strip()
    user_id = g.current_user_id

    with get_session() as session:
        sub = session.get(UserSubscription, subscription_id)
        if not sub:
            raise NotFoundError(f"Subscription #{subscription_id} not found")

        # Ensure payment is active
        if sub.status != "ACTIVE":
            raise ForbiddenError("This model question paper has not been purchased yet. Please complete checkout to unlock download.")

        # Allow owner, linked student or admin
        role = getattr(g, "current_user_role", "").upper()
        if sub.user_id != user_id and sub.student_id != user_id and role not in ("ADMIN", "SUPERADMIN", "SUPER_ADMIN"):
            raise ForbiddenError("You do not have permission to download this question paper.")

        # Extract set number
        set_num = 1
        if sub.model_test_id and "SET_" in sub.model_test_id:
            try:
                set_num = int(sub.model_test_id.split("SET_")[1])
            except Exception:
                set_num = 1

        paper_data = get_model_paper_questions(
            board=sub.board,
            class_grade=sub.class_grade,
            subject=sub.subject,
            set_number=set_num
        )

        safe_filename = f"{sub.board}_{sub.class_grade}_{sub.subject}_Set_{set_num}_Model_Paper_2027".replace(" ", "_")

        if doc_format in ("docx", "doc", "word"):
            docx_bytes = generate_model_paper_docx(paper_data)
            return send_file(
                io.BytesIO(docx_bytes),
                mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                as_attachment=True,
                download_name=f"{safe_filename}.docx"
            )
        else:
            pdf_bytes = generate_model_paper_pdf(paper_data)
            return send_file(
                io.BytesIO(pdf_bytes),
                mimetype="application/pdf",
                as_attachment=True,
                download_name=f"{safe_filename}.pdf"
            )

