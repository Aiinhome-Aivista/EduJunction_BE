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
import re
from datetime import datetime, timedelta
from flask import request, g
import requests
from sqlalchemy import and_, or_, desc, func

from database.dbConnection import get_session
from middleware.authMiddleware import token_required
from middleware.roleMiddleware import assert_owns_student
from model.models import SubscriptionPlan, UserSubscription, User, Student, BoardMaster
from utils.date_helper import now_ist
from utils.errors import AppError, NotFoundError, ValidationError, ForbiddenError
from utils.logger import logger
from utils.response import success
from helper.model_paper_diagnostic_engine import generate_model_paper_diagnostic


RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "rzp_test_edujunction_demo")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "edujunction_secret_demo")


def get_razorpay_credentials():
    key_id = (os.getenv("RAZORPAY_KEY_ID") or RAZORPAY_KEY_ID or "").strip().strip('"').strip("'")
    key_secret = (os.getenv("RAZORPAY_KEY_SECRET") or RAZORPAY_KEY_SECRET or "").strip().strip('"').strip("'")
    return key_id, key_secret

def init_subscription_columns():
    """Ensures extended columns exist in user_subscriptions table."""
    try:
        with get_session() as session:
            from sqlalchemy import text
            for col_def in [
                "ALTER TABLE user_subscriptions ADD COLUMN score_obtained DECIMAL(10,2) NULL",
                "ALTER TABLE user_subscriptions ADD COLUMN total_marks DECIMAL(10,2) DEFAULT 80.00",
                "ALTER TABLE user_subscriptions ADD COLUMN accuracy_percentage DECIMAL(5,2) NULL",
                "ALTER TABLE user_subscriptions ADD COLUMN submitted_at DATETIME NULL",
                "ALTER TABLE user_subscriptions ADD COLUMN evaluation_data_json LONGTEXT NULL",
            ]:
                try:
                    session.execute(text(col_def))
                    session.commit()
                except Exception:
                    session.rollback()
    except Exception as e:
        logger.warning(f"init_subscription_columns check: {e}")

init_subscription_columns()


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
    student_id = payload.get("studentId") or payload.get("student_id")
    plan_id = payload.get("planId")
    quantity = max(1, min(10, int(payload.get("quantity", 1))))

    if not board or not class_grade or not subject:
        raise ValidationError("Board, Class Grade, and Subject are required")

    with get_session() as session:
        user_id = g.current_user_id
        role = getattr(g, "current_user_role", "").upper()

        target_student = None
        if role == "PARENT":
            if student_id:
                target_student = assert_owns_student(session, student_id, user_id)
            else:
                # Fallback to first registered child if not explicitly passed
                target_student = session.query(Student).filter(Student.parent_id == user_id).first()
                if target_student:
                    student_id = target_student.id
        elif role == "STUDENT":
            target_student = session.query(Student).filter(Student.id == user_id).first()
            if target_student:
                student_id = target_student.id

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

        # Generate Razorpay Order ID
        razorpay_key_id, razorpay_key_secret = get_razorpay_credentials()
        order_id = f"order_{uuid.uuid4().hex[:14]}"
        if razorpay_key_id and razorpay_key_secret and not ("demo" in razorpay_key_id.lower()):
            try:
                auth = (razorpay_key_id, razorpay_key_secret)
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
                            "student_id": str(student_id) if student_id else "",
                        }
                    },
                    timeout=10
                )
                if res.status_code == 200:
                    rz_data = res.json()
                    order_id = rz_data.get("id", order_id)
                else:
                    logger.error(f"Razorpay order creation failed: HTTP {res.status_code} - {res.text}")
            except Exception as e:
                logger.warning(f"Razorpay API call failed, falling back to local order ID: {e}")

        # Record pending purchase in user_subscriptions
        subscription = UserSubscription(
            user_id=user_id,
            student_id=student_id,
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
            "keyId": razorpay_key_id,
            "subscriptionId": subscription.id,
            "studentId": student_id,
            "studentName": target_student.user.name if (target_student and target_student.user) else "",
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
    student_id = payload.get("studentId") or payload.get("student_id")
    quantity = max(1, min(10, int(payload.get("quantity", 1))))

    user_id = g.current_user_id
    role = getattr(g, "current_user_role", "").upper()

    # Verify signature if live credentials present
    razorpay_key_id, razorpay_key_secret = get_razorpay_credentials()
    if signature and razorpay_key_secret and not ("demo" in razorpay_key_id.lower()):
        try:
            msg = f"{order_id}|{payment_id}".encode("utf-8")
            generated_signature = hmac.new(
                razorpay_key_secret.encode("utf-8"),
                msg,
                hashlib.sha256
            ).hexdigest()

            if generated_signature != signature:
                raise ValidationError("Payment signature verification failed")
        except ValidationError:
            raise
        except Exception as e:
            logger.warning(f"Signature check exception: {e}")

    with get_session() as session:
        # Resolve target student if not passed
        if not student_id:
            if role == "PARENT":
                first_child = session.query(Student).filter(Student.parent_id == user_id).first()
                if first_child:
                    student_id = first_child.id
            elif role == "STUDENT":
                stu = session.query(Student).filter(Student.id == user_id).first()
                if stu:
                    student_id = stu.id

        # Check existing active count for this subject to assign distinct Set numbers
        existing_count = session.query(UserSubscription).filter(
            or_(UserSubscription.user_id == user_id, UserSubscription.student_id == student_id),
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
        if pending_sub:
            if pending_sub.student_id and not student_id:
                student_id = pending_sub.student_id
            if pending_sub.model_test_id and pending_sub.model_test_id.startswith("QTY_"):
                try:
                    quantity = int(pending_sub.model_test_id.replace("QTY_", ""))
                except Exception:
                    pass

        created_subscriptions = []

        # Activate the initial pending sub as Set 1 (or existing_count + 1)
        start_set = existing_count + 1
        if pending_sub:
            pending_sub.student_id = student_id or pending_sub.student_id
            pending_sub.razorpay_payment_id = payment_id
            pending_sub.razorpay_signature = signature or "verified_checkout"
            pending_sub.status = "ACTIVE"
            pending_sub.amount_paid = 300.00
            pending_sub.model_test_id = f"{board}_{class_grade}_{subject}_SET_{start_set}".replace(" ", "_")
            created_subscriptions.append(pending_sub)
        else:
            first_sub = UserSubscription(
                user_id=user_id,
                student_id=student_id,
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
                student_id=student_id,
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

        # Dispatch notification to student if student_id is set
        if student_id:
            try:
                from controller.notification_controller import create_notification
                stu = session.get(Student, student_id)
                sets_str = f"{quantity} set{'s' if quantity > 1 else ''}"
                first_sub_id = created_subscriptions[0].id if created_subscriptions else None
                
                create_notification(
                    session=session,
                    user_id=student_id,
                    sender_id=user_id,
                    notif_type="MODEL_EXAM_ASSIGNED",
                    title=f"🎯 New 2027 Model Paper: {subject} ({board} {class_grade})",
                    message=f"Your parent has unlocked {sets_str} of 80-Mark Board Exam Specimen Model Question Paper for {board} {class_grade} {subject}. You can now start the exam!",
                    action_url=f"/model-exam/{first_sub_id}" if first_sub_id else "/pricing",
                    metadata_json={
                        "subject": subject,
                        "board": board,
                        "classGrade": class_grade,
                        "quantity": quantity,
                        "subscriptionId": first_sub_id,
                        "status": "UNATTEMPTED",
                        "type": "MODEL_EXAM"
                    }
                )
            except Exception as notif_err:
                logger.warning(f"Failed to create student notification on subject subscription: {notif_err}")

        session.commit()

        return success({
            "success": True,
            "quantity": quantity,
            "message": f"Payment successful! {quantity} Full-Length Model Test Paper set{'s' if quantity > 1 else ''} for {board} {class_grade} {subject} are now unlocked.",
            "unlockedSets": [s.model_test_id for s in created_subscriptions]
        })


@token_required
def get_user_subject_subscriptions():
    """Returns active model test subscriptions for the logged-in user or student."""
    user_id = g.current_user_id
    role = getattr(g, "current_user_role", "").upper()
    req_student_id = request.args.get("studentId") or request.args.get("student_id")

    with get_session() as session:
        if role == "STUDENT":
            # Student login: strictly sees papers assigned to this student:
            # 1. Unlocked by Parent specifically assigned to this student (student_id == stu_id)
            # 2. Unlocked by Student themselves (user_id == user_id)
            stu = session.query(Student).filter(Student.id == user_id).first()
            stu_id = stu.id if stu else user_id

            subs = session.query(UserSubscription).filter(
                or_(
                    UserSubscription.student_id == stu_id,
                    and_(UserSubscription.user_id == user_id, UserSubscription.student_id == None),
                    and_(UserSubscription.user_id == user_id, UserSubscription.student_id == stu_id)
                ),
                UserSubscription.status == "ACTIVE"
            ).order_by(UserSubscription.id.desc()).all()
        else:
            # Parent login: ONLY sees papers purchased by this parent (user_id == current_parent_user_id)
            if req_student_id:
                try:
                    s_id_int = int(req_student_id)
                    subs = session.query(UserSubscription).filter(
                        UserSubscription.user_id == user_id,
                        UserSubscription.student_id == s_id_int,
                        UserSubscription.status == "ACTIVE"
                    ).order_by(UserSubscription.id.desc()).all()
                except Exception:
                    subs = session.query(UserSubscription).filter(
                        UserSubscription.user_id == user_id,
                        UserSubscription.status == "ACTIVE"
                    ).order_by(UserSubscription.id.desc()).all()
            else:
                # All papers unlocked by this parent
                subs = session.query(UserSubscription).filter(
                    UserSubscription.user_id == user_id,
                    UserSubscription.status == "ACTIVE"
                ).order_by(UserSubscription.id.desc()).all()

        results = []
        for s in subs:
            student_name = "Assigned Child"
            student_class = s.class_grade
            student_avatar = ""
            if s.student:
                student_name = s.student.user.name if (s.student.user and s.student.user.name) else f"Student #{s.student.id}"
                student_class = s.student.class_grade or s.class_grade
                student_avatar = (s.student.avatar if hasattr(s.student, 'avatar') else '') or ''
            elif s.user and s.user.name:
                student_name = s.user.name

            # Determine who unlocked this paper
            payer_user = s.user
            payer_role = "PARENT"
            payer_name = "Parent"
            if payer_user:
                payer_name = payer_user.name or "Parent"
                if payer_user.role:
                    payer_role = getattr(payer_user.role, 'name', 'PARENT').upper()

            # Is it unlocked by the student themselves or by the parent?
            is_self = (s.student_id == s.user_id and payer_role == "STUDENT") or (payer_role == "STUDENT") or (s.user_id == user_id and role == "STUDENT")
            unlocked_by = "SELF" if is_self else "PARENT"
            unlocked_by_name = payer_name if not is_self else (student_name or "Me")

            results.append({
                "id": s.id,
                "studentId": s.student_id,
                "studentName": student_name,
                "studentClass": student_class,
                "studentAvatar": student_avatar,
                "board": s.board,
                "classGrade": s.class_grade,
                "subject": s.subject,
                "modelTestId": s.model_test_id,
                "amount": float(s.amount_paid) if s.amount_paid else 300.00,
                "razorpayOrderId": s.razorpay_order_id,
                "razorpayPaymentId": s.razorpay_payment_id,
                "status": s.status,
                "examStatus": s.exam_status or "UNATTEMPTED",
                "scoreObtained": float(s.score_obtained) if s.score_obtained is not None else None,
                "totalMarks": float(s.total_marks) if s.total_marks is not None else 80.00,
                "accuracyPercentage": float(s.accuracy_percentage) if s.accuracy_percentage is not None else None,
                "submittedAt": s.submitted_at.isoformat() if s.submitted_at else None,
                "createdAt": s.created_at.isoformat() if s.created_at else None,
                "unlockedBy": unlocked_by,
                "unlockedByName": unlocked_by_name,
                "unlockedByRole": payer_role,
                "buyerUserId": s.user_id,
            })

        return success({"subscriptions": results})


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
    from sqlalchemy.orm import aliased

    search = request.args.get("search", "").strip()
    board = request.args.get("board", "").strip()
    class_grade = request.args.get("classGrade", "").strip()
    subject = request.args.get("subject", "").strip()
    status = request.args.get("status", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    limit = min(100, max(1, int(request.args.get("limit", 20))))

    with get_session() as session:
        ParentUser = aliased(User)
        StudentUser = aliased(User)

        query = session.query(UserSubscription, ParentUser, StudentUser, Student).outerjoin(
            ParentUser, UserSubscription.user_id == ParentUser.id
        ).outerjoin(
            Student, UserSubscription.student_id == Student.id
        ).outerjoin(
            StudentUser, Student.id == StudentUser.id
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
                    ParentUser.name.ilike(search_pattern),
                    ParentUser.email.ilike(search_pattern),
                    StudentUser.name.ilike(search_pattern),
                    StudentUser.username.ilike(search_pattern),
                    UserSubscription.razorpay_order_id.ilike(search_pattern),
                    UserSubscription.razorpay_payment_id.ilike(search_pattern),
                    UserSubscription.subject.ilike(search_pattern),
                )
            )

        total_count = query.count()
        results = query.order_by(UserSubscription.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

        transactions = []
        for sub, parent_user, student_user, student in results:
            student_display_name = student_user.name if student_user else (parent_user.name if parent_user else "Student")
            transactions.append({
                "id": sub.id,
                "userId": sub.user_id,
                "parentName": parent_user.name if parent_user else "N/A",
                "parentEmail": parent_user.email if parent_user else "N/A",
                "studentId": sub.student_id,
                "studentName": student_display_name,
                "board": sub.board,
                "classGrade": sub.class_grade,
                "subject": sub.subject,
                "amountPaid": float(sub.amount_paid) if sub.amount_paid is not None else 0.0,
                "currency": sub.currency,
                "razorpayOrderId": sub.razorpay_order_id,
                "razorpayPaymentId": sub.razorpay_payment_id,
                "status": sub.status,
                "createdAt": sub.created_at.isoformat() if sub.created_at else None,
            })

        # Active boards for dynamic dropdown
        try:
            active_boards = [
                b.board_name for b in session.query(BoardMaster).filter(BoardMaster.is_active == True).order_by(BoardMaster.id).all()
            ]
        except Exception:
            active_boards = ["CBSE", "ICSE", "ISC", "WBBSE"]

        # Global metrics across all subscriptions
        total_orders = session.query(func.count(UserSubscription.id)).scalar() or 0
        active_papers = session.query(func.count(UserSubscription.id)).filter(UserSubscription.status == "ACTIVE").scalar() or 0
        pending_papers = session.query(func.count(UserSubscription.id)).filter(UserSubscription.status == "PENDING").scalar() or 0

        realized_revenue = session.query(func.coalesce(func.sum(UserSubscription.amount_paid), 0)).filter(UserSubscription.status == "ACTIVE").scalar() or 0
        pending_revenue = session.query(func.coalesce(func.sum(UserSubscription.amount_paid), 0)).filter(UserSubscription.status == "PENDING").scalar() or 0

        return success({
            "transactions": transactions,
            "total": total_count,
            "page": page,
            "limit": limit,
            "totalPages": (total_count + limit - 1) // limit,
            "metrics": {
                "totalOrders": total_orders,
                "activePapers": active_papers,
                "pendingPapers": pending_papers,
                "realizedRevenue": float(realized_revenue),
                "pendingRevenue": float(pending_revenue)
            },
            "boards": active_boards
        })


def _get_board_section_blueprint(board: str, s_idx: int, sec_name: str, questions: list) -> dict:
    """Returns official target max marks and target question count for CBSE, ICSE, ISC."""
    b_clean = (board or "").upper().strip()
    q_len = len(questions) if questions else 0

    if b_clean == "ICSE":
        # ICSE: 2 Sections (40M + 40M = 80M)
        if s_idx == 0 or "SECTION A" in sec_name.upper():
            return {
                "targetMaxMarks": 40.0,
                "targetQuestions": min(25, q_len) if q_len > 0 else 25,
                "choiceNote": "Compulsory (Attempt all questions)"
            }
        else:
            return {
                "targetMaxMarks": 40.0,
                "targetQuestions": min(4, q_len) if q_len > 0 else 4,
                "choiceNote": f"Attempt any 4 of {q_len or 7} Questions (10 Marks each)"
            }

    elif b_clean == "ISC":
        # ISC: 3 Sections (16M + 32M + 32M = 80M)
        if s_idx == 0 or "SECTION A" in sec_name.upper():
            return {
                "targetMaxMarks": 16.0,
                "targetQuestions": min(16, q_len) if q_len > 0 else 16,
                "choiceNote": "Compulsory (16 Objective Questions × 1 Mark)"
            }
        elif s_idx == 1 or "SECTION B" in sec_name.upper():
            return {
                "targetMaxMarks": 32.0,
                "targetQuestions": min(8, q_len) if q_len > 0 else 8,
                "choiceNote": "Attempt all 8 Questions (4 Marks each)"
            }
        else:
            return {
                "targetMaxMarks": 32.0,
                "targetQuestions": min(4, q_len) if q_len > 0 else 4,
                "choiceNote": "Attempt all 4 Questions (8 Marks each)"
            }

    else:
        # CBSE: 5 Sections (20M + 10M + 18M + 20M + 12M = 80M)
        if s_idx == 0 or "SECTION A" in sec_name.upper():
            return {
                "targetMaxMarks": 20.0,
                "targetQuestions": min(20, q_len) if q_len > 0 else 20,
                "choiceNote": "20 Compulsory Questions × 1 Mark"
            }
        elif s_idx == 1 or "SECTION B" in sec_name.upper():
            return {
                "targetMaxMarks": 10.0,
                "targetQuestions": min(5, q_len) if q_len > 0 else 5,
                "choiceNote": f"Attempt any 5 of {q_len or 7} Questions (2 Marks each)"
            }
        elif s_idx == 2 or "SECTION C" in sec_name.upper():
            return {
                "targetMaxMarks": 18.0,
                "targetQuestions": min(6, q_len) if q_len > 0 else 6,
                "choiceNote": f"Attempt any 6 of {q_len or 8} Questions (3 Marks each)"
            }
        elif s_idx == 3 or "SECTION D" in sec_name.upper():
            return {
                "targetMaxMarks": 20.0,
                "targetQuestions": min(4, q_len) if q_len > 0 else 4,
                "choiceNote": f"Attempt any 4 of {q_len or 6} Questions (5 Marks each)"
            }
        else:
            return {
                "targetMaxMarks": 12.0,
                "targetQuestions": min(3, q_len) if q_len > 0 else 3,
                "choiceNote": f"Attempt any 3 of {q_len or 5} Questions (4 Marks each)"
            }


def _normalize_paper_sections(paper_data: dict, include_answers: bool = False) -> list:
    """Normalizes sections into a standard list format.
    If include_answers is False, strips correct_answer and explanation.
    """
    sections = []
    global_num = 1
    board_val = paper_data.get("board", "CBSE")

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

            sec_name = sec_title.split("—")[0].strip() if "—" in sec_title else sec_title.split("(")[0].strip()
            bp = _get_board_section_blueprint(board_val, s_idx, sec_name, questions)

            sections.append({
                "id": f"sec_{s_idx}",
                "name": sec_name,
                "title": sec_title,
                "type": sec_type,
                "targetMaxMarks": bp["targetMaxMarks"],
                "targetQuestions": bp["targetQuestions"],
                "totalQuestions": len(questions),
                "choiceNote": bp.get("choiceNote", ""),
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

        bp_a = _get_board_section_blueprint("ICSE", 0, "SECTION A", sec_a_questions)
        sections.append({
            "id": "sec_0",
            "name": "SECTION A",
            "title": sec_a_raw.get("title", "SECTION A (40 Marks) — Compulsory"),
            "type": "mixed",
            "targetMaxMarks": bp_a["targetMaxMarks"],
            "targetQuestions": bp_a["targetQuestions"],
            "totalQuestions": len(sec_a_questions),
            "choiceNote": bp_a.get("choiceNote", ""),
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

        bp_b = _get_board_section_blueprint("ICSE", 1, "SECTION B", sec_b_questions)
        sections.append({
            "id": "sec_1",
            "name": "SECTION B",
            "title": sec_b_raw.get("title", "SECTION B (40 Marks)"),
            "type": "long",
            "targetMaxMarks": bp_b["targetMaxMarks"],
            "targetQuestions": bp_b["targetQuestions"],
            "totalQuestions": len(sec_b_questions),
            "choiceNote": bp_b.get("choiceNote", ""),
            "questions": sec_b_questions
        })

    return sections


def _evaluate_single_subjective(student_ans: str, correct_ans: str, explanation: str, max_marks: float) -> dict:
    import re
    s_clean = (student_ans or "").strip().lower()
    trivial_set = {
        "na", "n/a", "none", "no", "nil", "blank", "skip", "skipped",
        "don't know", "dont know", "not attempted", "not answered",
        "left", "left blank", "-", "--", ".", "..", "...", "?", "??", "???"
    }
    if not s_clean or s_clean in trivial_set:
        return {
            "marksAwarded": 0.0,
            "isCorrect": False,
            "feedback": "Question not attempted / left blank.",
            "matchedKeywords": [],
            "missedKeywords": ["Core concept explanation and steps"]
        }

    stopwords = {
        "a", "an", "the", "is", "are", "was", "were", "in", "on", "at", "of", "to", "for",
        "and", "or", "by", "with", "from", "it", "that", "this", "which", "be", "as", "into",
        "has", "have", "had", "will", "shall", "can", "could", "would", "should", "not", "but"
    }
    def tokenize(text: str) -> set:
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
        return {t for t in cleaned.split() if len(t) > 2 and t not in stopwords}

    student_tokens = tokenize(student_ans)
    target_tokens = tokenize(f"{correct_ans} {explanation}")
    matched = student_tokens.intersection(target_tokens)
    missed = target_tokens.difference(student_tokens)

    overlap_ratio = len(matched) / max(len(target_tokens), 1)
    matched_count = len(matched)

    if not student_tokens or matched_count == 0:
        marks = 0.0
        feedback = "Answer does not match the key scientific/mathematical concepts and required steps."
    elif overlap_ratio >= 0.35 and matched_count >= 5:
        marks = max_marks
        feedback = "Outstanding response! Accurate conceptual understanding, terminology, and clear steps."
    elif (overlap_ratio >= 0.20 and matched_count >= 3) or matched_count >= 4:
        marks = round(max_marks * 0.75, 1)
        feedback = "Good answer! Covers core concepts with minor omissions in steps or terminology."
    elif (overlap_ratio >= 0.10 and matched_count >= 2) or matched_count >= 2:
        marks = round(max_marks * 0.50, 1)
        feedback = "Partial credit awarded for identifying relevant principles and basic definitions."
    elif matched_count >= 1:
        marks = round(max_marks * 0.25, 1)
        feedback = "Attempted with minimal relevant keywords. Lacks complete explanation and derivation steps."
    else:
        marks = 0.0
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

    # Helper function to extract option letter ('A', 'B', 'C', 'D') from string
    def extract_letter(text: str) -> str:
        if not text:
            return ""
        # Match "Option A", "(A)", "A.", "A)", "A - ", or standalone "A"
        m = re.match(r"^(?:option\s+)?\(?([A-Da-d])(?:\)|\.|\:|\-|\s|$)", text.strip(), re.IGNORECASE)
        if m:
            return m.group(1).upper()
        if len(text.strip()) == 1 and text.strip().upper() in ("A", "B", "C", "D"):
            return text.strip().upper()
        return ""

    student_letter = extract_letter(student_clean)
    correct_letter = extract_letter(correct_clean)
    if not correct_letter:
        correct_letter = "A"

    if not student_clean:
        return {
            "marksAwarded": 0.0,
            "isCorrect": False,
            "feedback": f"Not attempted. The correct option is ({correct_letter}).",
        }

    is_correct = False

    if student_letter:
        # Strict option letter comparison
        is_correct = (student_letter == correct_letter)
    else:
        # Student entered full text rather than an option letter
        def clean_opt_text(s: str) -> str:
            s = re.sub(r"^(?:option\s+)?\(?[A-Da-d]\)?[\.\:\-\s]*", "", s.strip(), flags=re.IGNORECASE)
            return re.sub(r"[^a-zA-Z0-9]", "", s).lower()

        student_norm = clean_opt_text(student_clean)
        matched_student_letter = ""

        if options and len(student_norm) >= 3:
            for idx, opt in enumerate(options):
                opt_str = str(opt).strip()
                opt_norm = clean_opt_text(opt_str)
                if opt_norm and (student_norm == opt_norm or (len(student_norm) > 10 and (student_norm in opt_norm or opt_norm in student_norm))):
                    matched_student_letter = chr(65 + idx)
                    break

        if matched_student_letter:
            is_correct = (matched_student_letter == correct_letter)
        else:
            is_correct = (student_clean.lower() == correct_clean.lower())

    marks_awarded = float(marks) if is_correct else 0.0
    return {
        "marksAwarded": marks_awarded,
        "isCorrect": is_correct,
        "feedback": "Correct option selected!" if is_correct else f"Incorrect. The correct option is ({correct_letter}).",
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
        is_allowed = (sub.user_id == user_id or sub.student_id == user_id or role in ("ADMIN", "SUPERADMIN", "SUPER_ADMIN"))
        if not is_allowed and sub.student_id:
            stu = session.get(Student, sub.student_id)
            if stu and stu.parent_id == user_id:
                is_allowed = True
        if not is_allowed:
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
            set_number=set_num,
            session=session
        )

        is_view_mode = (
            (request.args.get("mode") in ("view", "review"))
            or (role == "PARENT" and sub.user_id == user_id and sub.student_id != user_id)
            or (sub.exam_status == "COMPLETED")
        )

        # Standardized sections: include answers/solutions if exam is completed or opened in review/view mode
        sections_data = _normalize_paper_sections(raw_paper, include_answers=bool(is_view_mode or sub.exam_status == "COMPLETED"))

        # If student starts test and status is UNATTEMPTED, update to IN_PROGRESS
        if not is_view_mode and (sub.exam_status is None or sub.exam_status in ("UNATTEMPTED", "")):
            sub.exam_status = "IN_PROGRESS"
            session.commit()

        eval_result = None
        if sub.exam_status == "COMPLETED":
            if getattr(sub, "evaluation_data_json", None):
                try:
                    eval_result = json.loads(sub.evaluation_data_json)
                except Exception as parse_err:
                    logger.warning(f"Failed to parse evaluation_data_json for sub #{sub.id}: {parse_err}")
                    eval_result = None

            if not eval_result:
                evaluated_sections_breakdown = []
                all_eval_items = []
                total_target_questions = 0
                total_available_questions = 0

                for s_idx, sec in enumerate(sections_data):
                    sec_questions = sec.get("questions", [])
                    sec_name = sec.get("name", f"SECTION {chr(65 + s_idx)}")
                    bp = _get_board_section_blueprint(sub.board, s_idx, sec_name, sec_questions)

                    sec_max = bp["targetMaxMarks"]
                    sec_target_q = bp["targetQuestions"]
                    total_target_questions += sec_target_q
                    total_available_questions += len(sec_questions)

                    for q in sec_questions:
                        all_eval_items.append({
                            "key": q.get("key"),
                            "num": q.get("num", 1),
                            "sectionName": sec_name,
                            "sectionTitle": sec.get("title"),
                            "question": q.get("question"),
                            "type": q.get("type", "saq"),
                            "options": q.get("options"),
                            "marksAwarded": 0.0,
                            "maxMarks": q.get("marks", 1),
                            "isCorrect": False,
                            "studentAnswer": "",
                            "correctAnswer": q.get("correct_answer", ""),
                            "explanation": q.get("explanation", ""),
                            "feedback": "Not Attempted / Left Blank",
                        })

                    evaluated_sections_breakdown.append({
                        "id": sec.get("id") or f"sec_{s_idx}",
                        "name": sec_name,
                        "title": sec.get("title") or sec_name,
                        "type": sec.get("type", "saq"),
                        "marksObtained": 0.0,
                        "maxMarks": round(sec_max, 1),
                        "targetQuestions": sec_target_q,
                        "totalQuestions": len(sec_questions),
                        "percentage": 0.0,
                        "attempted": 0,
                        "correct": 0,
                        "choiceNote": bp.get("choiceNote", ""),
                        "questions": sec_questions,
                    })

                max_marks_val = float(raw_paper.get("max_marks", 80))
                eval_result = {
                    "subscriptionId": sub.id,
                    "board": sub.board,
                    "classGrade": sub.class_grade,
                    "subject": sub.subject,
                    "setNumber": set_num,
                    "totalMarksObtained": 0.0,
                    "maxMarks": max_marks_val,
                    "accuracyPercentage": 0.0,
                    "grade": "Needs Improvement (D)",
                    "timeSpentSeconds": 0,
                    "summary": {
                        "totalQuestions": total_available_questions,
                        "targetQuestions": total_target_questions,
                        "attemptedCount": 0,
                        "correctCount": 0,
                        "partialCount": 0,
                        "incorrectCount": total_available_questions,
                    },
                    "sectionBreakdown": evaluated_sections_breakdown,
                    "questionEvaluations": all_eval_items,
                }

        return success({
            "subscriptionId": sub.id,
            "board": sub.board,
            "classGrade": sub.class_grade,
            "subject": sub.subject,
            "setNumber": set_num,
            "status": sub.status,
            "examStatus": sub.exam_status or "UNATTEMPTED",
            "scoreObtained": sub.score_obtained,
            "totalMarks": sub.total_marks or raw_paper.get("max_marks", 80),
            "accuracyPercentage": sub.accuracy_percentage,
            "timeAllowed": raw_paper.get("time_allowed", "3 Hours (180 Minutes)"),
            "maxMarks": raw_paper.get("max_marks", 80),
            "instructions": raw_paper.get("instructions", []),
            "sections": sections_data,
            "evaluationResult": eval_result,
        })


@token_required
def evaluate_subject_model_paper(subscription_id: int):
    """Evaluates student's submitted model paper answers, calculates marks, and returns full scorecard."""
    from helper.model_paper_document_generator import get_model_paper_questions

    user_id = g.current_user_id
    body = request.get_json(silent=True)
    if not body and request.data:
        try:
            body = json.loads(request.data.decode("utf-8"))
        except Exception:
            body = {}
    if not body:
        body = {}

    student_answers = body.get("answers", {})  # e.g. {"s0_q0": "A", "s1_q0": "Text..."}
    time_spent = body.get("timeSpentSeconds", 0)

    with get_session() as session:
        sub = session.get(UserSubscription, subscription_id)
        if not sub:
            raise NotFoundError(f"Subscription #{subscription_id} not found")

        if sub.status != "ACTIVE":
            raise ForbiddenError("This model question paper is not active.")

        role = getattr(g, "current_user_role", "").upper()
        is_allowed = (sub.user_id == user_id or sub.student_id == user_id or role in ("ADMIN", "SUPERADMIN", "SUPER_ADMIN"))
        if not is_allowed and sub.student_id:
            stu = session.get(Student, sub.student_id)
            if stu and stu.parent_id == user_id:
                is_allowed = True
        if not is_allowed:
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
            set_number=set_num,
            session=session
        )

        full_sections = _normalize_paper_sections(raw_paper, include_answers=True)

        total_marks_obtained = 0.0
        max_marks_total = float(raw_paper.get("max_marks", 80))
        total_questions_count = 0
        total_target_questions_count = 0
        attempted_count = 0
        correct_count = 0
        partial_count = 0
        incorrect_count = 0

        evaluated_sections = []
        all_evaluations = []

        for s_idx, sec in enumerate(full_sections):
            sec_name = sec.get("name", f"SECTION {chr(65 + s_idx)}")
            sec_questions = sec.get("questions", [])
            bp = _get_board_section_blueprint(sub.board, s_idx, sec_name, sec_questions)

            sec_target_max = bp["targetMaxMarks"]
            sec_target_q = bp["targetQuestions"]
            total_target_questions_count += sec_target_q

            sec_marks_raw = 0.0
            sec_attempted = 0
            sec_correct = 0
            sec_questions_eval = []

            for q in sec_questions:
                q_key = q.get("key")
                q_type = q.get("type", "saq").lower()
                q_max_marks = float(q.get("marks", 1))
                total_questions_count += 1

                # Find student answer by key or by stringified question number
                s_ans = student_answers.get(q_key, "")
                if not s_ans and str(q.get("num")) in student_answers:
                    s_ans = student_answers.get(str(q.get("num")), "")

                is_attempted = bool(str(s_ans).strip())
                if is_attempted:
                    attempted_count += 1
                    sec_attempted += 1

                is_mcq_type = (
                    q_type == "mcq"
                    or "mcq" in q_type
                    or q_type in ("assertion_reason", "assertion-reason", "ar", "assertion")
                    or bool(q.get("options"))
                )

                if is_mcq_type:
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
                sec_marks_raw += marks_awarded

                if marks_awarded >= q_max_marks:
                    correct_count += 1
                    sec_correct += 1
                elif marks_awarded > 0:
                    partial_count += 1
                else:
                    incorrect_count += 1

                # Extract clean concept topic from question metadata or bold concept tags
                q_text = q.get("question") or ""
                q_topic = q.get("topic") or q.get("case_title")
                if not q_topic and q_text:
                    bold_matches = re.findall(r"<b>(.*?)</b>", q_text)
                    for bm in bold_matches:
                        bm_clean = bm.strip()
                        if len(bm_clean) >= 3 and not any(bm_clean.startswith(p) for p in ("Assertion", "Reason", "Q", "Note", "Case", "Section", "OR")):
                            q_topic = bm_clean
                            break
                if not q_topic:
                    q_topic = f"{sec_name}: {sub.subject} Concepts"

                eval_item = {
                    "key": q_key,
                    "num": q.get("num"),
                    "sectionName": sec_name,
                    "sectionTitle": sec.get("title"),
                    "topic": q_topic,
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

            # Cap section marks to blueprint target max marks
            sec_marks_final = min(sec_marks_raw, sec_target_max)
            total_marks_obtained += sec_marks_final

            evaluated_sections.append({
                "id": sec.get("id") or f"sec_{s_idx}",
                "name": sec_name,
                "title": sec.get("title") or sec_name,
                "type": sec.get("type", "saq"),
                "marksObtained": round(sec_marks_final, 1),
                "maxMarks": round(sec_target_max, 1),
                "targetQuestions": sec_target_q,
                "totalQuestions": len(sec_questions),
                "percentage": round((sec_marks_final / max(sec_target_max, 1)) * 100, 1),
                "attempted": sec_attempted,
                "correct": sec_correct,
                "choiceNote": bp.get("choiceNote", ""),
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

        eval_result_payload = {
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
                "targetQuestions": total_target_questions_count,
                "attemptedCount": attempted_count,
                "correctCount": correct_count,
                "partialCount": partial_count,
                "incorrectCount": incorrect_count
            },
            "sectionBreakdown": evaluated_sections,
            "questionEvaluations": all_evaluations
        }

        # Update subscription status, score metrics and full evaluation payload
        sub.exam_status = "COMPLETED"
        sub.score_obtained = round(total_marks_obtained, 1)
        sub.total_marks = max_marks_total
        sub.accuracy_percentage = accuracy_pct
        sub.submitted_at = now_ist()
        sub.evaluation_data_json = json.dumps(eval_result_payload)
        session.commit()

        # Automatic PDF Report Generation & Parent Email Dispatch
        parent_email = None
        student_name = "Student"
        if sub.student:
            if sub.student.user and sub.student.user.name:
                student_name = sub.student.user.name
            if sub.student.parent and sub.student.parent.user and sub.student.parent.user.email:
                parent_email = sub.student.parent.user.email
            elif sub.student.user and sub.student.user.email:
                parent_email = sub.student.user.email
        if not parent_email and sub.user and sub.user.email:
            parent_email = sub.user.email

        if parent_email:
            try:
                from helper.pdf_report_generator import generate_exam_report_pdf
                from controller.email_controller import send_student_exam_report_email

                sub_date_str = sub.submitted_at.strftime("%d %b %Y, %I:%M %p") if sub.submitted_at else "Today"
                
                # Format evaluations for PDF report generator
                formatted_evals = []
                for ev in all_evaluations:
                    formatted_evals.append({
                        "questionId": ev.get("key"),
                        "questionNumber": ev.get("num", 1),
                        "type": ev.get("type", "saq"),
                        "questionText": ev.get("question", ""),
                        "studentAnswer": ev.get("studentAnswer", "(Not Answered)"),
                        "correctAnswer": ev.get("correctAnswer", ""),
                        "isCorrect": ev.get("isCorrect", False),
                        "marksAwarded": ev.get("marksAwarded", 0.0),
                        "questionMarks": ev.get("maxMarks", 1.0),
                        "feedback": ev.get("feedback", ""),
                        "topic": ev.get("topic") or ev.get("sectionTitle") or sub.subject,
                        "sectionName": ev.get("sectionName") or "Section",
                    })

                analysis_dict = generate_model_paper_diagnostic(
                    student_name=student_name,
                    board=sub.board,
                    class_grade=sub.class_grade,
                    subject=sub.subject,
                    set_num=set_num,
                    marks_obtained=total_marks_obtained,
                    max_marks=max_marks_total,
                    time_spent_seconds=time_spent,
                    evaluations=formatted_evals,
                    section_breakdown=evaluated_sections,
                    total_allowed_mins=180,
                )

                pdf_bytes = generate_exam_report_pdf(
                    student_name=student_name,
                    board=sub.board,
                    class_grade=sub.class_grade,
                    subject=sub.subject,
                    exam_title=f"{sub.board} {sub.class_grade} {sub.subject} 2027 Model Paper (Set {set_num})",
                    exam_date=sub_date_str,
                    marks_obtained=total_marks_obtained,
                    total_marks=max_marks_total,
                    accuracy_percentage=accuracy_pct,
                    time_taken_seconds=time_spent,
                    evaluations=formatted_evals,
                    analysis=analysis_dict,
                )

                send_student_exam_report_email(
                    to_email=parent_email,
                    student_name=student_name,
                    board=sub.board,
                    class_grade=sub.class_grade,
                    subject_name=sub.subject,
                    exam_title=f"{sub.board} {sub.class_grade} {sub.subject} 2027 Model Paper (Set {set_num})",
                    exam_date=sub_date_str,
                    marks_obtained=total_marks_obtained,
                    total_marks=max_marks_total,
                    accuracy_percentage=accuracy_pct,
                    pdf_bytes=pdf_bytes,
                )
            except Exception as email_err:
                logger.warning(f"Failed to generate/email model paper PDF report: {email_err}")

        return success(eval_result_payload)


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
        is_allowed = (sub.user_id == user_id or sub.student_id == user_id or role in ("ADMIN", "SUPERADMIN", "SUPER_ADMIN"))
        if not is_allowed and sub.student_id:
            stu = session.get(Student, sub.student_id)
            if stu and stu.parent_id == user_id:
                is_allowed = True
        if not is_allowed:
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
            set_number=set_num,
            session=session
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

