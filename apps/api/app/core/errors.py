class FlowchartError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: dict[str, object] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.request_id = request_id


class ProviderError(FlowchartError):
    def __init__(self, code: str, message: str, *, details: dict[str, object] | None = None):
        super().__init__(code, message, status_code=502, details=details)


class PatchError(FlowchartError):
    pass
