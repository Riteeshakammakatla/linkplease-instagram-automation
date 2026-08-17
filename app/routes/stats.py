from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import DMDelivery, StatCounter


router = APIRouter()


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


@router.get("/stats")
def get_stats(
    db: Session = Depends(get_db)
):

    sent = (
        db.query(func.count(DMDelivery.id))
        .filter(
            DMDelivery.status == "delivered"
        )
        .scalar()
    )

    failed = (
        db.query(func.count(DMDelivery.id))
        .filter(
            DMDelivery.status == "failed"
        )
        .scalar()
    )

    queued = (
        db.query(func.count(DMDelivery.id))
        .filter(
            DMDelivery.status.in_(
                ["queued", "sending", "accepted"]
            )
        )
        .scalar()
    )

    counter = (
        db.query(StatCounter)
        .filter(
            StatCounter.id == "global"
        )
        .first()
    )

    duplicates_blocked = (
        counter.duplicates_blocked
        if counter
        else 0
    )

    return {
        "sent": sent,
        "failed": failed,
        "queued": queued,
        "duplicates_blocked": duplicates_blocked
    }