from typing import Any, Optional
from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str = Field(description="Machine-readable error code")
    message: str = Field(description="Human-readable explanation of what went wrong")
    details: Optional[Any] = Field(default=None, description="Optional diagnostic details (non-sensitive)")


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class APIException(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Optional[Any] = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class NotFoundError(APIException):
    def __init__(self, message: str = "Resource not found", details: Optional[Any] = None):
        super().__init__(status_code=404, code="NOT_FOUND", message=message, details=details)


class PortalError(APIException):
    def __init__(self, message: str = "Upstream portal error", details: Optional[Any] = None):
        super().__init__(status_code=502, code="UPSTREAM_PORTAL_ERROR", message=message, details=details)


class PortalAuthenticationError(APIException):
    def __init__(self, message: str = "Portal authentication failed", details: Optional[Any] = None):
        super().__init__(status_code=502, code="PORTAL_AUTH_FAILED", message=message, details=details)


class BadRequestError(APIException):
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(status_code=400, code="BAD_REQUEST", message=message, details=details)
