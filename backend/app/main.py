"""FastAPI application entry point with basic logging."""

import logging
import os
from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from api.routes import router
from observability import flush_langfuse

log_directory = Path(__file__).resolve().parent.parent / "logs"
log_directory.mkdir(exist_ok=True)
log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_directory / "app.log", encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Autonomous Content Creator Application",
    description="A FastAPI application that utilizes LangGraph and Azure OpenAI for content creation.",
    version="1.0.0",
)


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Keep schema and validation internals out of messages shown to users."""
    logger.info("Request validation failed path=%s", request.url.path)
    return JSONResponse(
        status_code=422,
        content={"detail": "Please check your request and try again."},
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Return a safe message while retaining the full exception in server logs."""
    logger.exception("Unhandled request error path=%s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong. Please try again shortly."},
    )

# Configure additional deployed frontend origins with FRONTEND_ORIGINS as a
# comma-separated list. Local Vite defaults are included for development.
frontend_origins = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def log_request_processing_time(request: Request, call_next):
    """Log request start, completion status, and elapsed time, including failures."""
    start_time = perf_counter()
    logger.info("Request started method=%s path=%s", request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        elapsed_seconds = perf_counter() - start_time
        logger.exception(
            "Request failed method=%s path=%s elapsed_seconds=%.3f",
            request.method,
            request.url.path,
            elapsed_seconds,
        )
        raise

    elapsed_seconds = perf_counter() - start_time
    logger.info(
        "Request completed method=%s path=%s status_code=%s elapsed_seconds=%.3f",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_seconds,
    )
    return response

logger.info("FastAPI application initialized")


@app.on_event("startup")
def initialize_content_graph() -> None:
    """Compile the workflow before the first generation request arrives."""
    from graph.builder import app_graph, render_graph_image  # noqa: F401

    render_graph_image()
    logger.info("Content graph initialized")


@app.on_event("shutdown")
def flush_observability() -> None:
    """Send buffered Langfuse events before the process exits."""
    flush_langfuse()

app.include_router(router)

if __name__ == "__main__":
    logger.info("Starting FastAPI application on http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
