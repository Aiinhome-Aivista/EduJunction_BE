"""Registers a single Flask error handler that converts AppError (and any
uncaught exception) into the standard {success:false, error:{...}} envelope.
No Python traceback or exception message ever reaches the client for
unexpected errors — only for AppError subclasses we raised ourselves."""
from flask import jsonify

from utils.config import config
from utils.errors import AppError
from utils.logger import logger


def register_error_handlers(app):
    @app.errorhandler(AppError)
    def handle_app_error(err: AppError):
        return jsonify({"success": False, "error": {"code": err.code, "message": err.message}}), err.status_code

    @app.errorhandler(404)
    def handle_404(_err):
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Endpoint not found"}}), 404

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        logger.error(f"Unhandled exception: {type(err).__name__}")
        message = str(err) if config.APP_ENV == "development" else "An internal error occurred"
        return jsonify({"success": False, "error": {"code": "INTERNAL_ERROR", "message": message}}), 500
