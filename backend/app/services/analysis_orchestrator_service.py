"""Single-flight orchestration for analysis runs."""

from __future__ import annotations

import logging
from threading import Lock

from sqlalchemy.orm import Session

from app.schemas.analysis import AnalysisRunResponse
from app.services.analysis_service import run_analysis

logger = logging.getLogger(__name__)

_ANALYSIS_EXEC_LOCK = Lock()
_ANALYSIS_STATE_LOCK = Lock()
_ANALYSIS_PENDING_REQUEST = False


def run_analysis_singleflight(db: Session) -> AnalysisRunResponse:
    global _ANALYSIS_PENDING_REQUEST
    if not _ANALYSIS_EXEC_LOCK.acquire(blocking=False):
        with _ANALYSIS_STATE_LOCK:
            _ANALYSIS_PENDING_REQUEST = True
        logger.info("Analysis run request merged into pending single-flight slot.")
        return AnalysisRunResponse(status="queued", groups=0, items=0)

    try:
        result = run_analysis(db)
        while True:
            with _ANALYSIS_STATE_LOCK:
                if not _ANALYSIS_PENDING_REQUEST:
                    break
                _ANALYSIS_PENDING_REQUEST = False
            logger.info("Analysis single-flight draining pending request.")
            result = run_analysis(db)
        return result
    finally:
        _ANALYSIS_EXEC_LOCK.release()
