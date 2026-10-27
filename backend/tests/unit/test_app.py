import asyncio

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import Response

from app import main
from graph import builder


def _request():
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/test",
            "raw_path": b"/test",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 1234),
        }
    )


def test_validation_handler_returns_safe_422():
    response = asyncio.run(
        main.handle_request_validation_error(_request(), RequestValidationError([]))
    )

    assert response.status_code == 422
    assert response.body == b'{"detail":"Please check your request and try again."}'


def test_unexpected_error_handler_returns_safe_500():
    response = asyncio.run(
        main.handle_unexpected_error(_request(), RuntimeError("private failure"))
    )

    assert response.status_code == 500
    assert b"private failure" not in response.body


def test_request_middleware_logs_successful_response():
    response = asyncio.run(
        main.log_request_processing_time(
            _request(),
            lambda request: asyncio.sleep(0, result=Response(status_code=204)),
        )
    )

    assert response.status_code == 204


def test_request_middleware_reraises_failed_request():
    async def fail(_request):
        raise RuntimeError("request failed")

    with pytest.raises(RuntimeError, match="request failed"):
        asyncio.run(main.log_request_processing_time(_request(), fail))


def test_startup_renders_graph_and_shutdown_flushes_observability(monkeypatch):
    calls = []
    monkeypatch.setattr(builder, "render_graph_image", lambda: calls.append("render"))
    monkeypatch.setattr(main, "flush_langfuse", lambda: calls.append("flush"))

    main.initialize_content_graph()
    main.flush_observability()

    assert calls == ["render", "flush"]
