import base64
import hashlib
import hmac
import json

from fastapi import APIRouter, BackgroundTasks, Depends, Request, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..config import PSEUDOGRAM_API_KEY
from ..models import ProcessedEvent, StatCounter
from ..database import SessionLocal
from ..webhook_schemas import WebhookEvent
from ..services.comment_service import (
    find_matching_rules,
    create_dm_delivery,
)
from ..services.dm_service import process_dm_delivery


router = APIRouter()


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def verify_webhook_signature(received_signature: str, body: bytes, api_key: str) -> bool:
    if not received_signature or not api_key:
        return False

    clean_key = api_key.strip()
    candidate_secrets = [clean_key]

    # PseudoGram API keys are structured as <base64_email>.<secret>.
    # PseudoGram simulator signs webhooks using the user email as secret.
    if "." in clean_key:
        part1 = clean_key.split(".")[0]
        try:
            b64_str = part1 + "=" * (-len(part1) % 4)
            decoded_email = base64.b64decode(b64_str).decode("utf-8")
            candidate_secrets.append(decoded_email)
            candidate_secrets.append(part1)
        except Exception:
            pass

    clean_received = received_signature.strip()
    if clean_received.lower().startswith("sha256="):
        clean_received = clean_received[7:].strip()
    elif clean_received.lower().startswith("sha256:"):
        clean_received = clean_received[7:].strip()

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

    print("Webhook signature verified")

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
            "Duplicate event blocked:",
            event.event_id
        )

        return {
            "status": "received"
        }

    # -----------------------------------------
    # 7. ONLY PROCESS COMMENT.CREATED
    # -----------------------------------------

    if event.event_type != "comment.created":

        return {
            "status": "received"
        }

    # -----------------------------------------
    # 8. VALIDATE COMMENT DATA
    # -----------------------------------------

    if not event.data.text or not event.data.from_:

        return {
            "status": "received"
        }

    user_id = event.data.from_.user_id
    comment_id = event.data.comment_id

    # -----------------------------------------
    # 9. FIND MATCHING RULES
    # -----------------------------------------

    matching_rules = find_matching_rules(
        event.data.text,
        db
    )

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
                "Duplicate blocked:",
                user_id,
                rule.keyword
            )

            counter = (
                db.query(StatCounter)
                .filter(
                    StatCounter.id == "global"
                )
                .first()
            )

            if counter:

                counter.duplicates_blocked += 1
                db.commit()

        # -------------------------------------
        # NEW DM
        # -------------------------------------

        else:

            print(
                "DM queued:",
                user_id,
                rule.keyword
            )

            background_tasks.add_task(
                process_dm_delivery,
                delivery.id
            )

    # -----------------------------------------
    # 11. RETURN QUICKLY
    # -----------------------------------------

    return {
        "status": "received"
    }