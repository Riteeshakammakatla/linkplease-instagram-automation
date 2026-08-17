from fastapi import FastAPI

from .database import Base, engine, SessionLocal
from . import models

# Create database tables
Base.metadata.create_all(bind=engine)

# Initialize the global statistics counter
db = SessionLocal()

try:
    counter = (
        db.query(models.StatCounter)
        .filter(models.StatCounter.id == "global")
        .first()
    )

    if not counter:
        counter = models.StatCounter(
            id="global",
            duplicates_blocked=0
        )

        db.add(counter)
        db.commit()

finally:
    db.close()


from .routes.rules import router as rules_router
from .routes.webhook import router as webhook_router
from .routes.stats import router as stats_router
from .pseudogram_client import PseudoGramClient


app = FastAPI(title="LinkPlease API")


# Register routes
app.include_router(rules_router)
app.include_router(webhook_router)
app.include_router(stats_router)


@app.get("/")
def root():
    return {
        "message": "LinkPlease API is running"
    }


@app.post("/test-dm")
async def test_dm():

    client = PseudoGramClient()

    response = await client.send_dm(
        recipient_user_id="usr_test_001",
        message="Test message from LinkPlease",
        comment_id="cmt_test_001"
    )

    return {
        "status_code": response.status_code,
        "response": response.json()
    }