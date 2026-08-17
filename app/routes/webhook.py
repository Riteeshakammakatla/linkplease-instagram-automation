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

LAST_WEBHOOK_DEBUG = {}


@router.get("/debug-last-webhook")
def get_debug_last_webhook():
    return LAST_WEBHOOK_DEBUG


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


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
    # 3. CALCULATE EXPECTED SIGNATURE
    # -----------------------------------------

    api_key_raw = PSEUDOGRAM_API_KEY or ""
    api_key_clean = api_key_raw.strip()

    expected_hash = hmac.new(
        api_key_raw.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    expected_signature = f"sha256={expected_hash}"

    expected_hash_clean = hmac.new(
        api_key_clean.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    expected_signature_clean = f"sha256={expected_hash_clean}"

    # Safe key fingerprints
    key_hash_raw = hashlib.sha256(api_key_raw.encode()).hexdigest()[:8]
    key_hash_clean = hashlib.sha256(api_key_clean.encode()).hexdigest()[:8]

    global LAST_WEBHOOK_DEBUG
    LAST_WEBHOOK_DEBUG = {
        "headers": dict(request.headers),
        "received_signature": received_signature,
        "expected_signature": expected_signature,
        "expected_signature_clean": expected_signature_clean,
        "raw_body_len": len(body),
        "raw_body_str": body.decode("utf-8", errors="replace"),
        "key_raw_len": len(api_key_raw),
        "key_clean_len": len(api_key_clean),
        "key_hash_raw": key_hash_raw,
        "key_hash_clean": key_hash_clean,
    }

    # Debug logs for Render
    print("=== DEBUG WEBHOOK START ===", flush=True)
    print(f"DEBUG: headers={dict(request.headers)}", flush=True)
    print(f"DEBUG: received_signature={received_signature!r}", flush=True)
    print(f"DEBUG: expected_signature={expected_signature!r}", flush=True)
    print(f"DEBUG: expected_signature_clean={expected_signature_clean!r}", flush=True)
    print(f"DEBUG: raw_body_len={len(body)}", flush=True)
    print(f"DEBUG: raw_body_sample={body[:100]!r}", flush=True)
    print(f"DEBUG: key_raw_len={len(api_key_raw)}, key_clean_len={len(api_key_clean)}", flush=True)
    print(f"DEBUG: key_hash_raw={key_hash_raw}, key_hash_clean={key_hash_clean}", flush=True)
    print("=== DEBUG WEBHOOK END ===", flush=True)

    # -----------------------------------------
    # 4. COMPARE SIGNATURES SAFELY
    # -----------------------------------------

    if not hmac.compare_digest(
        received_signature,
        expected_signature
    ):
        print("Invalid webhook signature", flush=True)

        raise HTTPException(
            status_code=401,
            detail=f"Invalid webhook signature. Recv: {received_signature}, Exp: {expected_signature}, ExpClean: {expected_signature_clean}"
        )

    print("Webhook signature verified", flush=True)

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