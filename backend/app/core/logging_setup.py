"""Application logging configuration."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import settings

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _build_file_handler(path: Path, level: int = logging.DEBUG) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        filename=str(path),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    return handler


def _clear_handlers(logger: logging.Logger) -> None:
    for h in list(logger.handlers):
        logger.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass


def _has_handler_for_path(logger: logging.Logger, target: Path) -> bool:
    target_str = str(target)
    for h in logger.handlers:
        base = getattr(h, "baseFilename", "")
        if base and str(base) == target_str:
            return True
    return False


def init_logging(logs_dir: str | None = None, *, force: bool = False) -> Path:
    """Initialize structured file logging for webhook/delete/analysis/sync flows."""
    target_dir = Path(logs_dir or settings.logs_dir).expanduser()
    _ensure_dir(target_dir)

    root_logger = logging.getLogger()
    if force:
        _clear_handlers(root_logger)
    if not root_logger.handlers:
        root_logger.setLevel(logging.DEBUG)
        console = logging.StreamHandler()
        console.setLevel(logging.DEBUG)
        console.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        root_logger.addHandler(console)

    webhook_logger = logging.getLogger("WebhookReceiver")
    delete_logger = logging.getLogger("app.services.delete_preview_service")
    analysis_logger = logging.getLogger("app.services.analysis_service")
    sync_logger = logging.getLogger("app.services.sync_service")

    if force:
        _clear_handlers(webhook_logger)
        _clear_handlers(delete_logger)
        _clear_handlers(analysis_logger)
        _clear_handlers(sync_logger)

    webhook_logger.setLevel(logging.DEBUG)
    delete_logger.setLevel(logging.DEBUG)
    analysis_logger.setLevel(logging.DEBUG)
    sync_logger.setLevel(logging.DEBUG)

    webhook_logger.propagate = True
    delete_logger.propagate = True
    analysis_logger.propagate = True
    sync_logger.propagate = True

    webhook_path = target_dir / "dedup-webhook.log"
    delete_path = target_dir / "dedup-delete.log"
    analysis_path = target_dir / "dedup-analysis.log"
    sync_path = target_dir / "dedup-sync.log"

    if not _has_handler_for_path(webhook_logger, webhook_path):
        webhook_logger.addHandler(_build_file_handler(webhook_path))
    if not _has_handler_for_path(delete_logger, delete_path):
        delete_logger.addHandler(_build_file_handler(delete_path))
    if not _has_handler_for_path(analysis_logger, analysis_path):
        analysis_logger.addHandler(_build_file_handler(analysis_path))
    if not _has_handler_for_path(sync_logger, sync_path):
        sync_logger.addHandler(_build_file_handler(sync_path))

    root_logger.debug("Logging initialized. logs_dir=%s", str(target_dir))
    return target_dir
