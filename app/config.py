import os

from dotenv import load_dotenv


load_dotenv()


PSEUDOGRAM_API_KEY = (os.getenv("PSEUDOGRAM_API_KEY") or "").strip()
PSEUDOGRAM_BASE_URL = (
    os.getenv(
        "PSEUDOGRAM_BASE_URL",
        "https://pseudogram-api.onrender.com"
    ) or ""
).strip()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./linkplease.db").strip()