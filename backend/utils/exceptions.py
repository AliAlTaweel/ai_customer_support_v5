"""Custom exception classes for the application."""

from typing import Any, Optional


class ApplicationError(Exception):
    """Base exception for all application errors."""

    def __init__(self, message: str, code: str = "INTERNAL_ERROR", status_code: int = 500, details: Optional[Any] = None):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details
        super().__init__(self.message)


class ValidationError(ApplicationError):
    """Raised when input validation fails."""

    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, code="VALIDATION_ERROR", status_code=400, details=details)


class AuthenticationError(ApplicationError):
    """Raised when authentication fails."""

    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, code="AUTH_ERROR", status_code=401, details=details)


class AuthorizationError(ApplicationError):
    """Raised when authorization fails."""

    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, code="FORBIDDEN", status_code=403, details=details)


class ResourceNotFoundError(ApplicationError):
    """Raised when a resource is not found."""

    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, code="NOT_FOUND", status_code=404, details=details)
