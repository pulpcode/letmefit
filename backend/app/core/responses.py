from fastapi import Request


def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "req_unknown")


def success_response(data: dict, request: Request) -> dict:
    return {
        "data": data,
        "request_id": get_request_id(request),
    }
