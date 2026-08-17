import asyncio

from ..database import SessionLocal
from ..models import DMDelivery, Rule
from ..pseudogram_client import PseudoGramClient
from .rate_limiter import rate_limiter


MAX_ATTEMPTS = 3


async def process_dm_delivery(delivery_id: str):

    for attempt in range(1, MAX_ATTEMPTS + 1):

        db = SessionLocal()

        try:
            # Find the delivery job
            delivery = (
                db.query(DMDelivery)
                .filter(DMDelivery.id == delivery_id)
                .first()
            )

            if not delivery:
                print("Delivery not found:", delivery_id)
                return

            # Don't process something already finished
            if delivery.status in ("delivered", "failed"):
                print(
                    "Skipping terminal delivery:",
                    delivery_id,
                    delivery.status
                )
                return

            # Find the rule so we know what message to send
            rule = (
                db.query(Rule)
                .filter(Rule.id == delivery.rule_id)
                .first()
            )

            if not rule:
                delivery.status = "failed"
                db.commit()

                print(
                    "Rule not found:",
                    delivery.rule_id
                )

                return

            # Mark as currently being sent
            delivery.status = "sending"
            delivery.attempts = attempt
            db.commit()

            # Respect PseudoGram's rate limit
            await rate_limiter.acquire()

            client = PseudoGramClient()

            # Send the DM
            response = await client.send_dm(
                recipient_user_id=delivery.user_id,
                message=rule.dm_message,
                comment_id=delivery.comment_id
            )

            # --------------------------------
            # SUCCESS: 200 / 202
            # --------------------------------

            if response.status_code in (200, 202):

                result = response.json()

                delivery.dm_id = result.get("dm_id")

                db.commit()

                print(
                    "DM accepted:",
                    delivery.dm_id
                )

                # No DM ID means something went wrong
                if not delivery.dm_id:

                    delivery.status = "failed"
                    db.commit()

                    print(
                        "DM accepted without dm_id"
                    )

                    return

                # Check the actual delivery status
                status_response = await client.get_dm_status(
                    delivery.dm_id
                )

                if status_response.status_code == 200:

                    status_data = status_response.json()

                    dm_status = status_data.get("status")

                    # Actually delivered
                    if dm_status == "delivered":

                        delivery.status = "delivered"
                        db.commit()

                        print(
                            "DM delivered:",
                            delivery.dm_id
                        )

                        return

                    # API says delivery failed
                    elif dm_status == "failed":

                        delivery.status = "failed"
                        db.commit()

                        print(
                            "DM delivery failed:",
                            delivery.dm_id
                        )

                        return

                    # Still queued
                    else:

                        delivery.status = "accepted"
                        db.commit()

                        print(
                            "DM still pending:",
                            delivery.dm_id,
                            dm_status
                        )
                        await reconcile_dm_delivery(
                        delivery.id
                 )
                        return

                # Couldn't check delivery status
                else:

                    delivery.status = "accepted"
                    db.commit()

                    print(
                        "Could not check delivery status:",
                        status_response.status_code
                    )

                    return

            # --------------------------------
            # RATE LIMITED: 429
            # --------------------------------

            if response.status_code == 429:

                retry_after = response.headers.get(
                    "Retry-After",
                    "1"
                )

                try:
                    wait_seconds = int(retry_after)
                except ValueError:
                    wait_seconds = 1

                delivery.status = "queued"
                db.commit()

                if attempt < MAX_ATTEMPTS:

                    print(
                        f"Rate limited. "
                        f"Waiting {wait_seconds}s before retry."
                    )

                    await asyncio.sleep(wait_seconds)

                    continue

                delivery.status = "failed"
                db.commit()

                print(
                    "DM failed after rate-limit retries:",
                    delivery.id
                )

                return

            # --------------------------------
            # SERVER ERROR: 500
            # --------------------------------

            if response.status_code == 500:

                if attempt < MAX_ATTEMPTS:

                    wait_seconds = 2 ** (attempt - 1)

                    delivery.status = "queued"
                    db.commit()

                    print(
                        f"PseudoGram 500. "
                        f"Retrying in {wait_seconds}s."
                    )

                    await asyncio.sleep(wait_seconds)

                    continue

                delivery.status = "failed"
                db.commit()

                print(
                    "DM failed after 500 retries:",
                    delivery.id
                )

                return

            # --------------------------------
            # OTHER ERRORS: 400 etc.
            # --------------------------------

            delivery.status = "failed"
            db.commit()

            print(
                "Non-retryable DM failure:",
                response.status_code
            )

            return

        finally:
            db.close()
async def reconcile_dm_delivery(delivery_id: str):

    max_checks = 5

    for check_number in range(max_checks):

        db = SessionLocal()

        try:
            delivery = (
                db.query(DMDelivery)
                .filter(DMDelivery.id == delivery_id)
                .first()
            )

            if not delivery:
                return

            if not delivery.dm_id:
                return

            if delivery.status in ("delivered", "failed"):
                return

            client = PseudoGramClient()

            response = await client.get_dm_status(
                delivery.dm_id
            )

            if response.status_code != 200:

                print(
                    "Could not reconcile DM:",
                    delivery.dm_id,
                    response.status_code
                )

            else:

                data = response.json()
                status = data.get("status")

                if status == "delivered":

                    delivery.status = "delivered"
                    db.commit()

                    print(
                        "Reconciled as delivered:",
                        delivery.dm_id
                    )

                    return

                if status == "failed":

                    delivery.status = "failed"
                    db.commit()

                    print(
                        "Reconciled as failed:",
                        delivery.dm_id
                    )

                    return

                print(
                    "DM still queued:",
                    delivery.dm_id
                )

        finally:
            db.close()

        if check_number < max_checks - 1:
            await asyncio.sleep(2)       