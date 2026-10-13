class ToolError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        next_operation: str | None = None,
        status: int = 400,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.next_operation = next_operation
        self.status = status
