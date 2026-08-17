import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Rule, DMDelivery


def find_matching_rules(comment_text: str, db: Session):
    rules = db.query(Rule).all()

    matching_rules = []
    text_lower = (comment_text or "").lower()

    for rule in rules:
        keyword_clean = (rule.keyword or "").strip().lower()
        if keyword_clean and keyword_clean in text_lower:
            matching_rules.append(rule)

    return matching_rules


def create_dm_delivery(
    rule: Rule,
    user_id: str,
    comment_id: str,
    db: Session
):
    delivery = DMDelivery(
        id=str(uuid.uuid4()),
        rule_id=rule.id,
        user_id=user_id,
        comment_id=comment_id,
        status="queued",
        attempts=0
    )

    try:
        db.add(delivery)
        db.commit()

        return delivery, False

    except IntegrityError:
        db.rollback()

        return None, True