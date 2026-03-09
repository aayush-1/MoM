from __future__ import annotations

import json
import os
import logging
from datetime import datetime
from typing import Dict, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import SCOPES, CREDENTIALS_FILE, TOKEN_FILE, GOOGLE_FOLDER_ID, GOOGLE_TOKEN_JSON

logger = logging.getLogger(__name__)

_doc_cache: Dict[str, str] = {}


def get_credentials():
    """Authenticate via OAuth. Supports token from file or GOOGLE_TOKEN_JSON env var."""
    creds = None

    if GOOGLE_TOKEN_JSON:
        creds = Credentials.from_authorized_user_info(json.loads(GOOGLE_TOKEN_JSON), SCOPES)
    elif os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                logger.exception("Token refresh failed")
                creds = None
        if not creds:
            if GOOGLE_TOKEN_JSON:
                raise SystemExit(
                    "Google token from GOOGLE_TOKEN_JSON is invalid and cannot be "
                    "refreshed. Re-generate token.json locally and update the env var."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return creds


def get_services():
    """Build and return Google Docs + Drive API service objects."""
    creds = get_credentials()
    docs_service = build("docs", "v1", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)
    return docs_service, drive_service


def _extract_text(body_content):
    """Pull plain text from a Google Docs body content structure."""
    text = ""
    for element in body_content:
        if "paragraph" in element:
            for run in element["paragraph"].get("elements", []):
                if "textRun" in run:
                    text += run["textRun"]["content"]
    return text


def find_doc(drive_service, client_name: str) -> Optional[str]:
    """Find an existing MoM doc for a client in the shared Drive folder."""
    if client_name in _doc_cache:
        return _doc_cache[client_name]

    doc_name = f"MoM - {client_name}"
    logger.info("Cache miss — searching Drive for doc '%s'", doc_name)
    safe_name = doc_name.replace("'", "\\'")
    query = (
        f"name = '{safe_name}' "
        f"and '{GOOGLE_FOLDER_ID}' in parents "
        f"and mimeType = 'application/vnd.google-apps.document' "
        f"and trashed = false"
    )
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])

    if files:
        _doc_cache[client_name] = files[0]["id"]
        return files[0]["id"]
    return None


def create_doc(docs_service, drive_service, client_name: str) -> str:
    """Create a new MoM Google Doc for a client in the shared Drive folder."""
    doc_name = f"MoM - {client_name}"
    file_metadata = {
        "name": doc_name,
        "mimeType": "application/vnd.google-apps.document",
        "parents": [GOOGLE_FOLDER_ID],
    }
    file = drive_service.files().create(body=file_metadata, fields="id").execute()
    doc_id = file["id"]

    title = f"Minutes of Meeting — {client_name}"
    requests = [
        {
            "insertText": {
                "location": {"index": 1},
                "text": title + "\n",
            }
        },
        {
            "updateParagraphStyle": {
                "range": {"startIndex": 1, "endIndex": 1 + len(title) + 1},
                "paragraphStyle": {"namedStyleType": "HEADING_1"},
                "fields": "namedStyleType",
            }
        },
    ]
    docs_service.documents().batchUpdate(
        documentId=doc_id, body={"requests": requests}
    ).execute()

    _doc_cache[client_name] = doc_id
    logger.info("Created new doc '%s' (id: %s)", doc_name, doc_id)
    return doc_id


def find_or_create_doc(docs_service, drive_service, client_name: str) -> str:
    """Return the doc ID for a client, creating the doc if it doesn't exist."""
    doc_id = find_doc(drive_service, client_name)
    if doc_id is None:
        doc_id = create_doc(docs_service, drive_service, client_name)
    return doc_id


def _invalidate_cache(doc_id: str):
    """Remove a doc_id from cache (e.g. when the doc was deleted externally)."""
    for key, val in list(_doc_cache.items()):
        if val == doc_id:
            del _doc_cache[key]
            logger.warning("Evicted stale cache entry for '%s'", key)
            break


def append_to_doc(docs_service, doc_id: str, message: str, timestamp: datetime):
    """Append a timestamped message to the doc, adding a date heading if needed."""
    from googleapiclient.errors import HttpError

    try:
        doc = docs_service.documents().get(documentId=doc_id).execute()
    except HttpError as e:
        if e.resp.status == 404:
            _invalidate_cache(doc_id)
            raise RuntimeError(
                f"Doc {doc_id} not found (deleted?). Cache cleared — retry will create a new one."
            )
        raise

    body_content = doc.get("body", {}).get("content", [])
    end_index = body_content[-1]["endIndex"]
    full_text = _extract_text(body_content)

    date_str = timestamp.strftime("%d %B %Y")
    date_heading = f"--- {date_str} ---"

    text_to_insert = ""
    if date_heading not in full_text:
        logger.info("NEW DAY — adding heading '%s'", date_heading)
        text_to_insert += f"\n{date_heading}\n"

    text_to_insert += f"  • {message}\n"

    requests = [
        {
            "insertText": {
                "location": {"index": end_index - 1},
                "text": text_to_insert,
            }
        }
    ]
    docs_service.documents().batchUpdate(
        documentId=doc_id, body={"requests": requests}
    ).execute()


def get_doc_link(doc_id: str) -> str:
    return f"https://docs.google.com/document/d/{doc_id}/edit"


def append_image_to_doc(
    docs_service,
    doc_id: str,
    image_url: str,
    caption: str,
    timestamp: datetime,
    image_width_pt: float = 150,
    image_height_pt: float = 112,
):
    """Append an inline image (with optional caption) as a bullet point to the doc."""
    from googleapiclient.errors import HttpError

    try:
        doc = docs_service.documents().get(documentId=doc_id).execute()
    except HttpError as e:
        if e.resp.status == 404:
            _invalidate_cache(doc_id)
            raise RuntimeError(
                f"Doc {doc_id} not found (deleted?). Cache cleared — retry will create a new one."
            )
        raise

    body_content = doc.get("body", {}).get("content", [])
    end_index = body_content[-1]["endIndex"]
    full_text = _extract_text(body_content)

    date_str = timestamp.strftime("%d %B %Y")
    date_heading = f"--- {date_str} ---"

    requests = []
    insert_index = end_index - 1

    date_text = ""
    if date_heading not in full_text:
        logger.info("NEW DAY — adding heading '%s'", date_heading)
        date_text = f"\n{date_heading}\n"

    bullet_prefix = "  • "
    text_before_image = date_text + bullet_prefix

    requests.append(
        {
            "insertText": {
                "location": {"index": insert_index},
                "text": text_before_image,
            }
        }
    )

    image_insert_index = insert_index + len(text_before_image)
    requests.append(
        {
            "insertInlineImage": {
                "location": {"index": image_insert_index},
                "uri": image_url,
                "objectSize": {
                    "width": {"magnitude": image_width_pt, "unit": "PT"},
                    "height": {"magnitude": image_height_pt, "unit": "PT"},
                },
            }
        }
    )

    # Inline image occupies exactly 1 index in the document model
    after_image_index = image_insert_index + 1
    suffix = f" {caption}\n" if caption else "\n"
    requests.append(
        {
            "insertText": {
                "location": {"index": after_image_index},
                "text": suffix,
            }
        }
    )

    docs_service.documents().batchUpdate(
        documentId=doc_id, body={"requests": requests}
    ).execute()
