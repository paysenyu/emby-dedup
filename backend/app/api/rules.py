"""Rules API router."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.rules import RulesPayload, RulesResponse
from app.services.rules_service import load_rules, save_rules

router = APIRouter(tags=["rules"])


@router.get("/rules", response_model=RulesResponse)
def get_rules(db: Session = Depends(get_db)) -> RulesResponse:
    """Return current rule configuration."""
    return load_rules(db)


@router.put("/rules", response_model=RulesResponse)
def put_rules(payload: RulesPayload, db: Session = Depends(get_db)) -> RulesResponse:
    """Persist new rule configuration."""
    return save_rules(db, payload)
