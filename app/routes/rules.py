import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Rule
from ..schemas import RuleCreate, RuleResponse


router = APIRouter()


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


@router.post("/rules", response_model=RuleResponse, status_code=201)
def create_rule(rule: RuleCreate, db: Session = Depends(get_db)):
    rule_id = str(uuid.uuid4())

    new_rule = Rule(
        id=rule_id,
        keyword=rule.keyword,
        dm_message=rule.dm_message
    )

    db.add(new_rule)
    db.commit()

    return {
        "rule_id": rule_id,
        "keyword": rule.keyword,
        "dm_message": rule.dm_message
    }