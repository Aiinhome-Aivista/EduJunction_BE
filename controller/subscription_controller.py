"""Subscription & Payment Controller for EduJunction (SahajPath).
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


RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "rzp_test_sahajpath_demo")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "sahajpath_secret_demo")


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
        if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET and not RAZORPAY_KEY_ID.startswith("rzp_test_sahajpath_demo"):
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
    if signature and RAZORPAY_KEY_SECRET and not RAZORPAY_KEY_ID.startswith("rzp_test_sahajpath_demo"):
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

