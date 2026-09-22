"""EduJunction backend entry point.

app.py defines all API route endpoints explicitly with @app.route
and delegates execution directly to their respective controller functions.
"""
from flask import jsonify, send_from_directory
import time

from flask import Flask, g, request
from flask_cors import CORS

from controller import (
    admin_controller,
    auth_controller,
    communication_controller,
    exam_controller,
    gamification_controller,
    health_controller,
    leaderboard_controller,
    parent_controller,
    runbook_controller,
    student_controller,
    teacher_controller,
    upload_file_controller,
    chat_controller,
    blog_controller,
    notification_controller,
    curriculum_controller,
    mock_test_controller,
    subscription_controller,
    llm_config_controller,
)
from middleware.dbContext import register_db_teardown
from middleware.errorMiddleware import register_error_handlers
from middleware.rateLimitMiddleware import rate_limit
from utils.config import config
from utils.logger import log_request


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    CORS(app)

    register_error_handlers(app)
    register_db_teardown(app)

    # ------------------------------------------------------------
    # Request Hooks
    # ------------------------------------------------------------
    @app.before_request
    def _before():
        g._start_time = time.time()
        if request.path != "/api/v1/health":
            rate_limit()

    @app.route("/", methods=["GET"])
    def health():
        return jsonify({
        "status": "UP",
        "message": "API is running"
    })

    @app.after_request
    def _after(response):
        duration_ms = (time.time() - getattr(g, "_start_time", time.time())) * 1000
        status_code = response.status_code
        status_tag = f"[{status_code} OK]" if status_code < 400 else f"[{status_code} ERR]"
        print(f">> [HTTP {request.method}] {request.path} -> {status_tag} ({duration_ms:.1f}ms)", flush=True)
        log_request(
            request.method,
            request.path,
            response.status_code,
            duration_ms,
            getattr(g, "current_user_id", None),
        )
        # Secure headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    # ============================================================
    # 1. Health Endpoints
    # ============================================================
    @app.route("/api/v1/health", methods=["GET"])
    def api_health():
        return health_controller.health()

    # ============================================================
    # 2. Authentication & Roles Endpoints
    # ============================================================
    @app.route("/api/v1/auth/register", methods=["POST"])
    def api_auth_register():
        return auth_controller.register()

    @app.route("/api/v1/auth/login", methods=["POST"])
    def api_auth_login():
        return auth_controller.login()

    @app.route("/api/v1/auth/google", methods=["POST"])
    def api_auth_google():
        return auth_controller.google_auth()

    @app.route("/api/v1/auth/verify", methods=["GET"])
    def api_auth_verify():
        return auth_controller.verify_session()

    @app.route("/api/v1/auth/menu-permissions", methods=["GET"])
    def api_auth_menu_permissions():
        return auth_controller.get_menu_permissions()

    @app.route("/api/v1/auth/roles", methods=["GET"])
    def api_auth_roles():
        return auth_controller.get_registration_roles()

    @app.route("/api/v1/auth/check-username", methods=["GET"])
    def api_auth_check_username():
        return auth_controller.check_username()

    @app.route("/api/v1/auth/child-login", methods=["POST"])
    def api_auth_child_login():
        return auth_controller.child_login()

    @app.route("/api/v1/auth/refresh", methods=["POST"])
    def api_auth_refresh():
        return auth_controller.refresh()

    @app.route("/api/v1/auth/logout", methods=["POST"])
    def api_auth_logout():
        return auth_controller.logout()

    @app.route("/api/v1/auth/reset-password", methods=["POST"])
    def api_auth_reset_password():
        return auth_controller.reset_password()

    # ============================================================
    # 2.5 Master Data Endpoints
    # ============================================================
    @app.route("/api/v1/master/board_class_dropdown", methods=["GET"])
    def api_master_board_class_dropdown():
        return parent_controller.get_child_registration_options()

    # ============================================================
    # 3. Parent Endpoints
    # ============================================================
    @app.route("/api/v1/parent/dashboard", methods=["GET"])
    @app.route("/api/v1/parents/dashboard", methods=["GET"])
    def api_parent_dashboard():
        return parent_controller.get_dashboard()

    @app.route("/api/v1/parents/me", methods=["GET"])
    def api_parent_get_me():
        return parent_controller.get_me()

    @app.route("/api/v1/parents/me/children", methods=["GET"])
    def api_parent_list_children():
        return parent_controller.list_children()

    @app.route("/api/v1/parents/add-child", methods=["POST"])
    @app.route("/api/v1/parents/me/children", methods=["POST"])
    def api_parent_add_child():
        return parent_controller.add_child()

    @app.route("/api/v1/parents/me/children/<student_id>", methods=["PUT"])
    def api_parent_update_child(student_id):
        return parent_controller.update_child(student_id)

    @app.route("/api/v1/parents/me/children/<student_id>", methods=["DELETE"])
    def api_parent_delete_child(student_id):
        return parent_controller.delete_child(student_id)

    @app.route("/api/v1/parents/me/children/<student_id>/overview", methods=["GET"])
    def api_parent_child_overview(student_id):
        return parent_controller.child_overview(student_id)

    @app.route("/api/v1/parents/me/children/<student_id>/learning-path", methods=["GET"])
    def api_parent_child_learning_path(student_id):
        return parent_controller.child_learning_path(student_id)

    @app.route("/api/v1/parents/schedule-exam", methods=["POST"])
    def api_parent_schedule_exam():
        return parent_controller.schedule_exam()

    @app.route("/api/v1/parents/scheduled-exams", methods=["GET"])
    def api_parent_list_scheduled_exams():
        return parent_controller.list_scheduled_exams()

    @app.route("/api/v1/parents/scheduled-exams/<scheduled_exam_id>", methods=["DELETE"])
    def api_parent_delete_scheduled_exam(scheduled_exam_id):
        return parent_controller.delete_scheduled_exam(scheduled_exam_id)

    @app.route("/api/v1/parents/student-activity-log", methods=["GET"])
    def api_parent_student_activity_log():
        return parent_controller.get_student_activity_log()

    @app.route("/api/v1/students/activity-log", methods=["GET"])
    def api_student_activity_log():
        return parent_controller.get_student_activity_log()

    # ============================================================
    # 3.5 Notification Endpoints
    # ============================================================
    @app.route("/api/v1/notifications", methods=["GET"])
    def api_get_notifications():
        return notification_controller.get_notifications()

    @app.route("/api/v1/notifications/<notification_id>/read", methods=["PATCH"])
    def api_mark_notification_read(notification_id):
        return notification_controller.mark_as_read(notification_id)

    @app.route("/api/v1/notifications/read-all", methods=["POST"])
    def api_mark_all_notifications_read():
        return notification_controller.mark_all_as_read()

    # ============================================================
    # 4. Student Endpoints
    # ============================================================
    @app.route("/api/v1/student/dashboard", methods=["GET"])
    @app.route("/api/v1/students/dashboard", methods=["GET"])
    def api_student_dashboard():
        return student_controller.get_dashboard()

    @app.route("/api/v1/students/assigned-exams", methods=["GET"])
    def api_student_assigned_exams():
        return student_controller.get_assigned_exams()


    @app.route("/api/v1/students/me", methods=["GET"])
    def api_student_get_me():
        return student_controller.get_me()

    @app.route("/api/v1/students/me/overview", methods=["GET"])
    def api_student_overview():
        return student_controller.my_overview()

    @app.route("/api/v1/students/me/learning-path", methods=["GET"])
    def api_student_learning_path():
        return student_controller.my_learning_path()

    # ============================================================
    # 5. Teacher Endpoints
    # ============================================================
    @app.route("/api/v1/teachers/me/students", methods=["GET"])
    def api_teacher_my_students():
        return teacher_controller.my_students()

    @app.route("/api/v1/teachers/me/students/<student_id>/performance", methods=["GET"])
    def api_teacher_student_performance(student_id):
        return teacher_controller.student_performance(student_id)

    @app.route("/api/v1/teachers/me/students/<student_id>/mastery", methods=["GET"])
    def api_teacher_student_mastery(student_id):
        return teacher_controller.student_mastery(student_id)

    @app.route("/api/v1/teachers/me/students/<student_id>/diagnostics", methods=["GET"])
    def api_teacher_student_diagnostics(student_id):
        return teacher_controller.student_diagnostics(student_id)

    # ============================================================
    # 6. Exam Endpoints
    # ============================================================
    @app.route("/api/v1/exams/generate", methods=["POST"])
    def api_exam_generate():
        return exam_controller.generate_exam()

    @app.route("/api/v1/exams/quick-test", methods=["POST", "GET"])
    def api_exam_quick_test():
        return exam_controller.generate_quick_test()

    @app.route("/api/v1/exams/<exam_id>/submit", methods=["POST"])
    def api_exam_submit(exam_id):
        return exam_controller.submit_exam(exam_id)

    # ============================================================
    # 7. Gamification & Leaderboard Endpoints
    # ============================================================
    @app.route("/api/v1/gamification/badges", methods=["GET"])
    def api_gamification_list_badges():
        return gamification_controller.list_badges()

    @app.route("/api/v1/gamification/award-xp", methods=["POST"])
    def api_gamification_award_xp():
        return gamification_controller.award_xp_route()

    @app.route("/api/v1/leaderboard", methods=["GET"])
    def api_leaderboard():
        return leaderboard_controller.leaderboard()


    # ============================================================
    # 9. Communication & PTC Endpoints
    # ============================================================
    @app.route("/api/v1/teachers", methods=["GET"])
    def api_communication_list_teachers():
        return communication_controller.list_teachers()

    @app.route("/api/v1/conversations", methods=["GET"])
    def api_communication_list_conversations():
        return communication_controller.list_conversations()

    @app.route("/api/v1/conversations/<conversation_id>", methods=["GET"])
    def api_communication_get_conversation(conversation_id):
        return communication_controller.get_conversation(conversation_id)

    @app.route("/api/v1/conversations", methods=["POST"])
    def api_communication_create_conversation():
        return communication_controller.create_or_get_conversation()

    @app.route("/api/v1/conversations/<conversation_id>/messages", methods=["POST"])
    def api_communication_send_message(conversation_id):
        return communication_controller.send_message(conversation_id)

    @app.route("/api/v1/messages/<message_id>/read", methods=["PUT"])
    def api_communication_mark_message_read(message_id):
        return communication_controller.mark_message_read(message_id)

    @app.route("/api/v1/dossiers", methods=["POST"])
    def api_communication_create_dossier():
        return communication_controller.create_dossier()

    @app.route("/api/v1/dossiers", methods=["GET"])
    def api_communication_list_dossiers():
        return communication_controller.list_dossiers()

    @app.route("/api/v1/dossiers/public/<share_token>", methods=["GET"])
    def api_communication_get_public_dossier(share_token):
        return communication_controller.get_public_dossier(share_token)

    @app.route("/api/v1/dossiers/<dossier_id>", methods=["DELETE"])
    def api_communication_delete_dossier(dossier_id):
        return communication_controller.delete_dossier(dossier_id)

    @app.route("/api/v1/dossiers/preview/<student_id>", methods=["GET"])
    def api_communication_preview_student_dossier(student_id):
        return communication_controller.preview_student_dossier(student_id)

    @app.route("/api/v1/ptm/schedule", methods=["POST"])
    def api_communication_schedule_ptm():
        return communication_controller.schedule_ptm()

    @app.route("/api/v1/ptm/schedules", methods=["GET"])
    def api_communication_list_ptm_schedules():
        return communication_controller.list_ptm_schedules()

    # ============================================================
    # 10. Runbook Endpoints
    # ============================================================
    @app.route("/api/v1/runbooks", methods=["GET"])
    def api_runbook_list():
        return runbook_controller.list_runbooks()

    @app.route("/api/v1/runbooks/<runbook_id>", methods=["GET"])
    def api_runbook_get(runbook_id):
        return runbook_controller.get_runbook(runbook_id)

    @app.route("/api/v1/runbooks", methods=["POST"])
    def api_runbook_create():
        return runbook_controller.create_runbook()

    @app.route("/api/v1/runbooks/<runbook_id>", methods=["PUT"])
    def api_runbook_update(runbook_id):
        return runbook_controller.update_runbook(runbook_id)

    @app.route("/api/v1/runbooks/<runbook_id>", methods=["DELETE"])
    def api_runbook_delete(runbook_id):
        return runbook_controller.delete_runbook(runbook_id)

    # ============================================================
    # 11. Admin Endpoints
    # ============================================================
    @app.route("/api/v1/admin/login", methods=["POST"])
    def api_admin_login():
        return auth_controller.admin_login()

    @app.route("/api/v1/admin/reset-password", methods=["POST"])
    def api_admin_reset_password():
        return auth_controller.admin_reset_password()

    @app.route("/api/v1/admin/statistics", methods=["GET"])
    def api_admin_statistics():
        return admin_controller.statistics()

    @app.route("/api/v1/admin/dashboard", methods=["GET"])
    def api_admin_dashboard():
        return admin_controller.admin_dashboard()

    @app.route("/api/v1/admin/users", methods=["GET"])
    def api_admin_list_users():
        return admin_controller.list_users()

    @app.route("/api/v1/admin/users/<int:user_id>", methods=["PUT"])
    def api_admin_update_user(user_id):
        return admin_controller.update_user(user_id)

    @app.route("/api/v1/admin/users/<int:user_id>", methods=["DELETE"])
    def api_admin_delete_user(user_id):
        return admin_controller.delete_user(user_id)

    @app.route("/api/v1/admin/students", methods=["GET"])
    def api_admin_list_students():
        return admin_controller.list_students()

    @app.route("/api/v1/admin/audit-logs", methods=["GET"])
    def api_admin_list_audit_logs():
        return admin_controller.list_audit_logs()

    # ============================================================
    # 11.5 Curriculum & Question Bank Endpoints
    # ============================================================
    @app.route("/api/v1/admin/curriculum/tree", methods=["GET"])
    def api_admin_curriculum_tree():
        return curriculum_controller.get_curriculum_tree()

    @app.route("/api/v1/admin/questions", methods=["GET"])
    def api_admin_list_questions():
        return curriculum_controller.list_questions()

    @app.route("/api/v1/admin/questions", methods=["POST"])
    def api_admin_create_question():
        return curriculum_controller.create_question()

    @app.route("/api/v1/admin/questions/<int:question_id>", methods=["PUT"])
    def api_admin_update_question(question_id):
        return curriculum_controller.update_question(question_id)

    @app.route("/api/v1/admin/questions/<int:question_id>", methods=["DELETE"])
    def api_admin_delete_question(question_id):
        return curriculum_controller.delete_question(question_id)

    @app.route("/api/v1/admin/questions/bulk-upload", methods=["POST"])
    def api_admin_bulk_upload_questions():
        return curriculum_controller.bulk_upload_questions()

    @app.route("/api/v1/admin/questions/bulk-upload-stream", methods=["POST"])
    def api_admin_bulk_upload_questions_stream():
        return curriculum_controller.bulk_upload_questions_stream()

    @app.route("/api/v1/admin/questions/upload-history", methods=["GET"])
    def api_admin_get_question_upload_history():
        return curriculum_controller.get_upload_history()

    @app.route("/api/v1/admin/rag/status", methods=["GET"])
    def api_admin_rag_status():
        return upload_file_controller.get_rag_status()

    @app.route("/api/v1/admin/rag/documents/<document_id>", methods=["DELETE"])
    def api_admin_delete_rag_document(document_id):
        return upload_file_controller.delete_rag_document(document_id)

    @app.route("/api/v1/admin/rag/generate-questions", methods=["POST"])
    def api_admin_rag_generate_questions():
        return upload_file_controller.generate_questions_from_doc_api()

    @app.route("/api/v1/admin/rag/save-questions", methods=["POST"])
    def api_admin_rag_save_questions():
        return upload_file_controller.save_generated_questions_api()

    @app.route("/api/v1/admin/rag/process-document", methods=["POST"])
    def api_admin_rag_process_document():
        return upload_file_controller.process_curriculum_document_api()

    @app.route("/api/v1/admin/rag/process-documents-batch", methods=["POST"])
    def api_admin_rag_process_documents_batch():
        return upload_file_controller.process_curriculum_documents_batch_api()

    @app.route("/api/v1/admin/rag/analyze-book", methods=["POST"])
    def api_admin_rag_analyze_book():
        return upload_file_controller.analyze_and_extract_book_api()


    # ============================================================
    # 11.8 Mock Test & Blueprint Endpoints
    # ============================================================
    @app.route("/api/v1/admin/mock-tests/blueprints", methods=["GET"])
    def api_admin_get_blueprints():
        return mock_test_controller.get_blueprints()

    @app.route("/api/v1/admin/mock-tests/blueprints/<int:blueprint_id>", methods=["PUT"])
    def api_admin_update_blueprint(blueprint_id):
        return mock_test_controller.update_blueprint(blueprint_id)

    @app.route("/api/v1/admin/mock-tests/generate", methods=["POST"])
    def api_admin_generate_mock_test():
        return mock_test_controller.generate_mock_test()

    @app.route("/api/v1/mock-tests/free/generate", methods=["POST"])
    def api_generate_free_mock_test():
        return mock_test_controller.generate_free_mock_test()

    @app.route("/api/v1/admin/mock-tests", methods=["GET"])
    def api_admin_list_mock_tests():
        return mock_test_controller.list_mock_tests()

    @app.route("/api/v1/admin/mock-tests/<test_id>/toggle-auto-assign", methods=["POST"])
    def api_admin_toggle_mock_auto_assign(test_id):
        return mock_test_controller.toggle_auto_assign(test_id)

    @app.route("/api/v1/admin/mock-tests/<test_id>/assign-bulk", methods=["POST"])
    def api_admin_bulk_assign_mock(test_id):
        return mock_test_controller.bulk_assign(test_id)

    @app.route("/api/v1/admin/mock-tests/<test_id>", methods=["DELETE"])
    def api_admin_delete_mock_test(test_id):
        return mock_test_controller.delete_mock_test(test_id)


    # ============================================================
    # 12. Chat Endpoints
    # ============================================================
    @app.route("/api/v1/chat", methods=["POST"])
    def api_chat():
        return chat_controller.chat()

    @app.route("/api/v1/chat/suggestions", methods=["GET"])
    def api_chat_suggestions():
        return chat_controller.get_chat_suggestions()

    # ============================================================
    # 13. Document & File Upload Endpoints
    # ============================================================
    @app.route("/api/v1/files/upload", methods=["POST"])
    def api_files_upload():
        return upload_file_controller.upload_file()

    @app.route("/api/v1/files/upload-image", methods=["POST"])
    def api_files_upload_image():
        return upload_file_controller.upload_blog_image()

    @app.route("/uploads/<path:filename>", methods=["GET"])
    @app.route("/edujunction/uploads/<path:filename>", methods=["GET"])
    def uploaded_file(filename):
        return send_from_directory(config.UPLOAD_DIR, filename)

    @app.route("/api/v1/files/<document_id>", methods=["GET"])
    def api_files_get_status(document_id):
        return upload_file_controller.get_document_status(document_id)

    # ============================================================
    # 13. Blog Endpoints
    # ============================================================
    @app.route("/api/v1/blogs", methods=["GET"])
    def api_blog_list():
        return blog_controller.list_blogs()

    @app.route("/api/v1/blogs/<int:blog_id>", methods=["GET"])
    def api_blog_get(blog_id):
        return blog_controller.get_blog(blog_id)

    @app.route("/api/v1/blogs", methods=["POST"])
    def api_blog_create():
        return blog_controller.create_blog()

    @app.route("/api/v1/blogs/<int:blog_id>", methods=["PUT"])
    def api_blog_update(blog_id):
        return blog_controller.update_blog(blog_id)

    @app.route("/api/v1/blogs/<int:blog_id>", methods=["DELETE"])
    def api_blog_delete(blog_id):
        return blog_controller.delete_blog(blog_id)

    @app.route("/api/v1/blogs/categories", methods=["GET"])
    def api_blog_list_categories():
        return blog_controller.list_categories()

    @app.route("/api/v1/blogs/categories", methods=["POST"])
    def api_blog_create_category():
        return blog_controller.create_category()

    @app.route("/api/v1/blogs/categories/<int:category_id>", methods=["PUT"])
    def api_blog_update_category(category_id):
        return blog_controller.update_category(category_id)

    @app.route("/api/v1/blogs/categories/<int:category_id>", methods=["DELETE"])
    def api_blog_delete_category(category_id):
        return blog_controller.delete_category(category_id)

    @app.route("/api/v1/blogs/authors", methods=["GET"])
    def api_blog_list_authors():
        return blog_controller.list_authors()

    @app.route("/api/v1/blogs/authors", methods=["POST"])
    def api_blog_create_author():
        return blog_controller.create_author()

    @app.route("/api/v1/blogs/<int:blog_id>/share", methods=["POST"])
    def api_blog_share(blog_id):
        return blog_controller.increment_blog_share(blog_id)

    # ============================================================
    # 20. Subscription & Pricing Plan Endpoints (₹300 Per Model Test)
    # ============================================================
    @app.route("/api/v1/subscription-plans/active", methods=["GET"])
    def api_subscription_get_active_plans():
        return subscription_controller.get_active_subscription_plans()

    @app.route("/api/v1/subscriptions/subject/create-order", methods=["POST"])
    def api_subscription_create_order():
        return subscription_controller.create_subject_order()

    @app.route("/api/v1/subscriptions/subject/verify", methods=["POST"])
    def api_subscription_verify():
        return subscription_controller.verify_subject_payment()

    @app.route("/api/v1/subscriptions/subject/my-subscriptions", methods=["GET"])
    def api_subscription_my_subscriptions():
        return subscription_controller.get_user_subject_subscriptions()

    @app.route("/api/v1/subscriptions/subject/<int:subscription_id>/preview-paper", methods=["GET"])
    def api_subscription_preview_paper(subscription_id):
        return subscription_controller.preview_subject_model_paper(subscription_id)

    @app.route("/api/v1/subscriptions/subject/<int:subscription_id>/evaluate-paper", methods=["POST"])
    def api_subscription_evaluate_paper(subscription_id):
        return subscription_controller.evaluate_subject_model_paper(subscription_id)

    @app.route("/api/v1/subscriptions/subject/<int:subscription_id>/download-paper", methods=["GET"])
    def api_subscription_download_paper(subscription_id):
        return subscription_controller.download_subject_model_paper(subscription_id)

    # Admin Subscription Plan Management & Payment History
    @app.route("/api/v1/admin/subscription-plans", methods=["GET"])
    def api_admin_get_subscription_plans():
        return subscription_controller.admin_get_subscription_plans()

    @app.route("/api/v1/admin/subscription-plans", methods=["POST"])
    def api_admin_create_subscription_plan():
        return subscription_controller.admin_create_subscription_plan()

    @app.route("/api/v1/admin/subscription-plans/<int:plan_id>", methods=["PUT"])
    def api_admin_update_subscription_plan(plan_id):
        return subscription_controller.admin_update_subscription_plan(plan_id)

    @app.route("/api/v1/admin/subscription-plans/<int:plan_id>", methods=["DELETE"])
    def api_admin_delete_subscription_plan(plan_id):
        return subscription_controller.admin_delete_subscription_plan(plan_id)

    @app.route("/api/v1/admin/subscription-history", methods=["GET"])
    def api_admin_get_subscription_history():
        return subscription_controller.admin_get_subscription_history()

    # ============================================================
    # 21. Admin LLM Configuration Endpoints
    # ============================================================
    @app.route("/api/v1/admin/llm-config", methods=["GET"])
    def api_admin_get_llm_configs():
        return llm_config_controller.get_llm_configs()

    @app.route("/api/v1/admin/llm-config", methods=["POST"])
    def api_admin_create_llm_config():
        return llm_config_controller.create_llm_config()

    @app.route("/api/v1/admin/llm-config/<config_id>", methods=["PUT"])
    def api_admin_update_llm_config(config_id):
        return llm_config_controller.update_llm_config(config_id)

    @app.route("/api/v1/admin/llm-config/<config_id>", methods=["DELETE"])
    def api_admin_delete_llm_config(config_id):
        return llm_config_controller.delete_llm_config(config_id)

    @app.route("/api/v1/admin/llm-config/<config_id>/activate", methods=["POST"])
    def api_admin_activate_llm_config(config_id):
        return llm_config_controller.set_active_llm_config(config_id)

    @app.route("/api/v1/admin/llm-config/<config_id>/test", methods=["POST"])
    def api_admin_test_llm_config(config_id):
        return llm_config_controller.test_llm_connection(config_id)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=(config.APP_ENV == "development"))
