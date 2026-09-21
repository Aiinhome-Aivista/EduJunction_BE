import traceback
from flask import jsonify, request

from utils.config import config
from utils.errors import AppError
from utils.logger import logger


def register_error_handlers(app):
    @app.errorhandler(AppError)
    def handle_app_error(err: AppError):
        print(f"\n>> [API ERROR {err.status_code}] {request.method} {request.path} | Code: {err.code} | Message: {err.message}\n", flush=True)
        return jsonify({"success": False, "error": {"code": err.code, "message": err.message}}), err.status_code

    @app.errorhandler(404)
    def handle_404(_err):
        print(f"\n>> [404 NOT FOUND] {request.method} {request.path}\n", flush=True)
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Endpoint not found"}}), 404

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        print(f"\n=======================================================", flush=True)
        print(f">> [500 SERVER ERROR] {request.method} {request.path}", flush=True)
        print(f">> Exception: {type(err).__name__}: {err}", flush=True)
        traceback.print_exc()
        print(f"=======================================================\n", flush=True)
        logger.error(f"Unhandled exception: {type(err).__name__}: {err}", exc_info=True)
        message = str(err) if config.APP_ENV == "development" else "An internal error occurred"
        return jsonify({"success": False, "error": {"code": "INTERNAL_ERROR", "message": message}}), 500

