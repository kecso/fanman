"""HTTP helpers."""

from fastapi import HTTPException


class FanManHTTPException(HTTPException):
    def __init__(self, status_code: int, error: str, detail_msg: str) -> None:
        body = {"error": error, "detail": detail_msg, "status_code": status_code}
        super().__init__(status_code=status_code, detail=body)


def api_error(code: str, detail: str, status_code: int) -> FanManHTTPException:
    return FanManHTTPException(status_code=status_code, error=code, detail_msg=detail)
