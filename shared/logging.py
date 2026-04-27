"""Structured logging setup. Real polish lands in Phase 9; this is the
minimum needed to give every cog a consistent, parseable log line."""
import logging


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logging. Idempotent: safe to call more than once."""
    root = logging.getLogger()
    if root.handlers:
        # Already configured (e.g., re-entrant import). Just adjust level.
        root.setLevel(level)
        return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    root.addHandler(handler)
    root.setLevel(level)

    # discord.py is chatty at INFO. WARNING is plenty for our purposes.
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
