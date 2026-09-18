class AppError(Exception):
    """Raised anywhere in controller/helper code; caught centrally in app.py's
    error handler and turned into the standard {success:false, error:{...}} shape.
    Never lets a raw Python traceback reach the client."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found", code: str = "NOT_FOUND"):
        super().__init__(code, message, 404)


class ForbiddenError(AppError):
    def __init__(self, message: str = "You do not have access to this resource", code: str = "FORBIDDEN"):
        super().__init__(code, message, 403)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Authentication required", code: str = "UNAUTHORIZED"):
        super().__init__(code, message, 401)


class ValidationError(AppError):
    def __init__(self, message: str = "Invalid input", code: str = "VALIDATION_ERROR"):
        super().__init__(code, message, 422)


class QuotaExceededError(AppError):
    def __init__(self, message: str = "Daily exam quota exceeded", code: str = "QUOTA_EXCEEDED"):
        super().__init__(code, message, 429)
