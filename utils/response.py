"""Consistent API response envelopes with status code, message, and data objects."""
from flask import jsonify


def success(data=None, status_code: int = 200, message: str = "Operation successful", **extra):
    body = {
        "statusCode": status_code,
        "success": True,
        "message": message,
        "data": data if data is not None else {},
    }
    body.update(extra)
    return jsonify(body), status_code


def error(code: str, message: str, status_code: int = 400, details=None):
    return jsonify({
        "statusCode": status_code,
        "success": False,
        "message": message,
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
    }), status_code
