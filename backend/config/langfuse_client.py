"""Utilities for Langfuse initialization and configuration."""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

from langfuse import Langfuse
logger = logging.getLogger(__name__)


def create_langfuse_client():
    """Create a Langfuse client using configured credentials and host settings.

    Raises ``RuntimeError`` when the public or secret key is not configured.
    """
    logger.info("Initialising langfuse client")

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST")
    if not public_key or not secret_key:
        raise RuntimeError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be configured.")

    langfuse_client = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=host,
    )
    return langfuse_client
