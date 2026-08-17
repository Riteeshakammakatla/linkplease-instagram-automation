import base64
import hashlib
import hmac
import json

from fastapi import APIRouter, BackgroundTasks, Depends, Request, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..config import PSEUDOGRAM_API_KEY
from ..models import ProcessedEvent, StatCounter, Rule, DMDelivery
from ..database import SessionLocal
from ..webhook_schemas import WebhookEvent
from ..services.comment_service import (
    find_matching_rules,
    create_dm_delivery,
)
from ..services.dm_service import process_dm_delivery


router = APIRouter()


@router.get("/debug/state")
def debug_state():
    """Temporary diagnostic endpoint to inspect DB state on Render."""
    db = SessionLocal()
    try:
        rules = db.query(Rule).all()
        deliveries = db.query(DMDelivery).all()
        events = db.query(ProcessedEvent).count()
        counter = db.query(StatCounter).filter(StatCounter.id == "global").first()
        return {
            "rules": [{"id": r.id, "keyword": r.keyword} for r in rules],
            "total_processed_events": events,
            "deliveries": [
                {"id": d.id, "rule_id": d.rule_id, "user_id": d.user_id, "status": d.status, "dm_id": d.dm_id}
                for d in deliveries[:20]
            ],
            "total_deliveries": len(deliveries),
            "stat_counter": {
                "duplicates_blocked": counter.duplicates_blocked if counter else None
            },
            "database_url": "sqlite:///./linkplease.db"
        }
    finally:
        db.close()


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def get_candidate_secrets(api_key: str) -> list[str]:
    """
    Extract all possible candidate secrets from PSEUDOGRAM_API_KEY.
    PseudoGram API keys follow the structure: `<base64_email>.<secret_token>`
    
    Candidates tested for HMAC-SHA256 verification:
    1. Full API key string (used by manual Postman / client requests)
    2. Secret token portion after the dot (`part2`)
    3. Base64 email prefix before the dot (`part1`)
    4. Decoded user email address (`decoded_email`)
    """
    clean_key = (api_key or "").strip()
    if not clean_key:
        return []

    candidates = [clean_key]

    if "." in clean_key:
        parts = clean_key.split(".", 1)
        part1 = parts[0].strip()
        part2 = parts[1].strip()

        if part2 and part2 not in candidates:
            candidates.append(part2)

        if part1 and part1 not in candidates:
            candidates.append(part1)

        try:
            b64_str = part1 + "=" * (-len(part1) % 4)
            decoded_email = base64.b64decode(b64_str).decode("utf-8").strip()
            if decoded_email and decoded_email not in candidates:
                candidates.append(decoded_email)
        except Exception:
            pass

    return candidates


def verify_webhook_signature(received_signature: str, body: bytes, api_key: str) -> bool:
    if not received_signature or not api_key or body is None:
        return False

    clean_received = received_signature.strip()
    if clean_received.lower().startswith("sha256="):
        clean_received = clean_received[7:].strip()
    elif clean_received.lower().startswith("sha256:"):
        clean_received = clean_received[7:].strip()

    candidate_secrets = get_candidate_secrets(api_key)

    for secret in candidate_secrets:
        expected_hash = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256
        ).hexdigest()

        if hmac.compare_digest(clean_received.lower(), expected_hash.lower()):
            return True

    return False


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):

    # -----------------------------------------
    # 1. READ RAW REQUEST BODY
    # -----------------------------------------

    body = await request.body()

    # -----------------------------------------
    # 2. GET SIGNATURE FROM HEADER
    # -----------------------------------------

    received_signature = request.headers.get(
        "X-PseudoGram-Signature"
    )

    if not received_signature:
        raise HTTPException(
            status_code=401,
            detail="Missing webhook signature"
        )

    # -----------------------------------------
    # 3. VERIFY SIGNATURE SAFELY
    # -----------------------------------------

    if not verify_webhook_signature(
        received_signature=received_signature,
        body=body,
        api_key=PSEUDOGRAM_API_KEY or ""
    ):
        print("Invalid webhook signature")

        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature"
        )

    print("[DIAG] Webhook signature verified")

    # -----------------------------------------
    # 5. PARSE JSON BODY
    # -----------------------------------------

    try:
        payload = json.loads(body)

        event = WebhookEvent.model_validate(
            payload
        )

    except Exception:

        raise HTTPException(
            status_code=400,
            detail="Invalid webhook payload"
        )

    # -----------------------------------------
    # 6. EVENT DEDUPLICATION
    # -----------------------------------------

    try:

        processed_event = ProcessedEvent(
            event_id=event.event_id,
            event_type=event.event_type
        )

        db.add(processed_event)
        db.commit()

    except IntegrityError:

        db.rollback()

        print(
            "[DIAG] Duplicate event blocked:",
            event.event_id
        )

        return {
            "status": "received"
        }

    # -----------------------------------------
    # 7. ONLY PROCESS COMMENT.CREATED
    # -----------------------------------------

    if event.event_type != "comment.created":

        print(f"[DIAG] Skipping non-comment event: type={event.event_type}")
        return {
            "status": "received"
        }

    # -----------------------------------------
    # 8. VALIDATE COMMENT DATA
    # -----------------------------------------

    if not event.data.text or not event.data.from_:

        print(f"[DIAG] Skipping: text={event.data.text!r}, from={event.data.from_}")
        return {
            "status": "received"
        }

    user_id = event.data.from_.user_id
    comment_id = event.data.comment_id

    # -----------------------------------------
    # 9. FIND MATCHING RULES
    # -----------------------------------------

    all_rules = db.query(Rule).all()
    print(f"[DIAG] event_id={event.event_id}, text={event.data.text!r}, user={event.data.from_.user_id}")
    print(f"[DIAG] Total rules in DB: {len(all_rules)}, keywords: {[r.keyword for r in all_rules]}")

    matching_rules = find_matching_rules(
        event.data.text,
        db
    )
    print(f"[DIAG] Matching rules: {len(matching_rules)}, matched: {[r.keyword for r in matching_rules]}")

    # -----------------------------------------
    # 10. CREATE DM DELIVERIES
    # -----------------------------------------

    for rule in matching_rules:

        delivery, duplicate = create_dm_delivery(
            rule=rule,
            user_id=user_id,
            comment_id=comment_id,
            db=db
        )

        # -------------------------------------
        # DUPLICATE DM
        # -------------------------------------

        if duplicate:

            print(
                f"[DIAG] Duplicate DM blocked: user={user_id}, keyword={rule.keyword}"
            )

            counter = (
                db.query(StatCounter)
                .filter(
                    StatCounter.id == "global"
                )
                .first()
            )

            if not counter:
                counter = StatCounter(
                    id="global",
                    duplicates_blocked=1
                )
                db.add(counter)
            else:
                counter.duplicates_blocked += 1

            db.commit()

        # -------------------------------------
        # NEW DM
        # -------------------------------------

        else:

            print(
                f"[DIAG] DM delivery created: id={delivery.id}, user={user_id}, keyword={rule.keyword}"
            )

            background_tasks.add_task(
                process_dm_delivery,
                delivery.id
            )
            print(f"[DIAG] Background task scheduled for delivery {delivery.id}")

    # -----------------------------------------
    # 11. RETURN QUICKLY
    # -----------------------------------------

    return {
        "status": "received"
    }