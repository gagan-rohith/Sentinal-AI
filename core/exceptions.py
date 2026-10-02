class SentinelError(Exception):
    # status_code and code are used by the API error handler.
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(SentinelError):
    status_code = 404
    code = "not_found"


class DuplicateIncidentError(SentinelError):
    status_code = 409
    code = "duplicate_incident"


class MissingIncidentDataError(SentinelError):
    status_code = 422
    code = "missing_incident_data"


class AuthenticationError(SentinelError):
    status_code = 401
    code = "unauthenticated"


class UnauthorizedActionError(SentinelError):
    status_code = 403
    code = "forbidden"


class ApprovalRequiredError(SentinelError):
    status_code = 409
    code = "approval_required"


class InvalidStateError(SentinelError):
    status_code = 409
    code = "invalid_state"


class SearchUnavailableError(SentinelError):
    status_code = 503
    code = "search_unavailable"


class LLMUnavailableError(SentinelError):
    status_code = 503
    code = "llm_unavailable"


class CriticUnavailableError(SentinelError):
    status_code = 503
    code = "critic_unavailable"


class ToolTimeoutError(SentinelError):
    status_code = 504
    code = "tool_timeout"


class MalformedToolResponseError(SentinelError):
    status_code = 502
    code = "malformed_tool_response"


class ToolNotFoundError(NotFoundError):
    code = "tool_not_found"


class ToolInputError(SentinelError):
    status_code = 422
    code = "invalid_tool_input"


class RetryLimitExceededError(SentinelError):
    status_code = 500
    code = "retry_limit_exceeded"
