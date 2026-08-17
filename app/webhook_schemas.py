from pydantic import BaseModel, Field
from typing import Optional


class User(BaseModel):
    user_id: str
    username: str


class CommentData(BaseModel):
    comment_id: str
    post_id: Optional[str] = None
    text: Optional[str] = None
    from_: Optional[User] = Field(default=None, alias="from")


class WebhookEvent(BaseModel):
    event_id: str
    event_type: str
    sent_at: str
    data: CommentData