import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_FOLDER_ID = os.getenv("GOOGLE_FOLDER_ID")

CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "client_secret.json")
TOKEN_FILE = os.getenv("TOKEN_FILE", "token.json")

# On a server, set GOOGLE_TOKEN_JSON env var with the contents of token.json
# so you don't need to copy the file manually.
GOOGLE_TOKEN_JSON = os.getenv("GOOGLE_TOKEN_JSON")

GROUP_PREFIX = "MoM - "

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]
