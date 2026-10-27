"""Langfuse tracing helpers.

Langfuse's ``@observe`` SDK integration sends spans directly to Langfuse. A local
OpenTelemetry ConsoleSpanExporter does not export to Langfuse and can replace a
host application's tracer provider, so tracing here uses the Langfuse SDK only.
"""
import os
from dotenv import load_dotenv

load_dotenv()

try:
    from langfuse import observe as _langfuse_observe, get_client as _langfuse_get_client
except ImportError as exc:  # Give a useful message if dependencies were not installed.
    raise ImportError("Langfuse tracing requires the 'langfuse' package.") from exc


def _is_langfuse_enabled() -> bool:
    """Return whether Langfuse observability should be active."""
    raw = str(os.getenv("LANGFUSE_ENABLED", "true")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def observe(*args, **kwargs):
    """No-op decorator when Langfuse is disabled; Langfuse observe otherwise."""
    if not _is_langfuse_enabled():
        if args and callable(args[0]) and len(args) == 1 and not kwargs:
            return args[0]

        def decorator(func):
            """Return the original function without adding tracing when disabled."""
            return func

        return decorator
    return _langfuse_observe(*args, **kwargs)


def get_client():
    """Return Langfuse client accessor for compatibility with existing imports/tests."""
    return _langfuse_get_client()


# -------------------------------
# Langfuse Utilities
# -------------------------------
def flush_langfuse():
    """
    Flush Langfuse traces to ensure all pending traces are sent.
    
    This should be called during application shutdown to ensure
    all traces are properly exported.
    """
    if not _is_langfuse_enabled():
        return

    try:
        get_client().flush()
    except Exception:
        pass  # Silently fail if client is not configured


# -------------------------------
# Exports
# -------------------------------
# Re-export observe decorator for convenience
__all__ = ["observe", "get_client", "flush_langfuse"]


