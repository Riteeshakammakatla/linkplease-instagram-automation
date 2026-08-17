from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    Integer,
    UniqueConstraint,
)

from .database import Base


class Rule(Base):
    __tablename__ = "rules"

    id = Column(String, primary_key=True)
    keyword = Column(String, nullable=False)
    dm_message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class DMDelivery(Base):
    __tablename__ = "dm_deliveries"

    id = Column(String, primary_key=True)

    rule_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    comment_id = Column(String, nullable=False)

    dm_id = Column(String, nullable=True)

    status = Column(String, nullable=False, default="queued")

    attempts = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        UniqueConstraint(
            "rule_id",
            "user_id",
            name="unique_rule_user",
        ),
    )
class ProcessedEvent(Base):
    __tablename__ = "processed_events"

    event_id = Column(String, primary_key=True)
    event_type = Column(String, nullable=False)
    processed_at = Column(DateTime, default=datetime.utcnow)
class StatCounter(Base):
    __tablename__ = "stat_counters"

    id = Column(String, primary_key=True)
    duplicates_blocked = Column(
        Integer,
        nullable=False,
        default=0
    )