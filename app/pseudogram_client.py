import httpx

from .config import (
    PSEUDOGRAM_API_KEY,
    PSEUDOGRAM_BASE_URL,
)


class PseudoGramClient:

    def __init__(self):
        self.base_url = PSEUDOGRAM_BASE_URL

        self.headers = {
            "X-API-Key": PSEUDOGRAM_API_KEY
        }

    async def send_dm(
        self,
        recipient_user_id: str,
        message: str,
        comment_id: str
    ):
        url = f"{self.base_url}/v1/dm/send"

        payload = {
            "recipient_user_id": recipient_user_id,
            "message": message,
            "comment_id": comment_id
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                headers=self.headers
            )

        return response

    async def get_dm_status(self, dm_id: str):
        url = f"{self.base_url}/v1/dm/{dm_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=self.headers
            )

        return response