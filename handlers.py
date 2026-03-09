import logging

from telegram import ReactionTypeEmoji, Update
from telegram.ext import ContextTypes

from config import GROUP_PREFIX
from google_docs_service import (
    get_services,
    find_or_create_doc,
    append_to_doc,
    find_doc,
    get_doc_link,
)

logger = logging.getLogger(__name__)

docs_service, drive_service = get_services()


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle every text message in MoM groups: append to Google Doc and react."""
    if not update.message or not update.message.text or not update.message.text.strip():
        return

    sender = update.message.from_user
    chat = update.effective_chat

    logger.info(
        "MESSAGE RECEIVED | chat: '%s' (id: %s) | from: %s | text: '%s'",
        getattr(chat, "title", "DM"),
        chat.id if chat else "?",
        sender.username or sender.first_name if sender else "unknown",
        update.message.text[:80],
    )

    if sender and sender.is_bot:
        logger.info("Skipping — message is from a bot")
        return

    if not chat or not chat.title or not chat.title.startswith(GROUP_PREFIX):
        logger.info(
            "Skipping — chat title '%s' does not start with '%s'",
            getattr(chat, "title", None),
            GROUP_PREFIX,
        )
        return

    client_name = chat.title[len(GROUP_PREFIX) :]
    message_text = update.message.text.strip()
    timestamp = update.message.date

    for attempt in range(2):
        try:
            doc_id = find_or_create_doc(docs_service, drive_service, client_name)
            append_to_doc(docs_service, doc_id, message_text, timestamp)
            logger.info("APPENDED to doc for '%s': %s", client_name, message_text[:60])
            break
        except RuntimeError:
            if attempt == 0:
                logger.warning("Doc was deleted — retrying with fresh doc for '%s'", client_name)
                continue
            logger.exception("FAILED to append note for '%s' after retry", client_name)
            return
        except Exception:
            logger.exception("FAILED to append note for '%s'", client_name)
            return

    try:
        await update.message.set_reaction([ReactionTypeEmoji("👍")])
    except Exception:
        logger.warning("Could not set reaction (may not be supported in this chat)")


async def on_doc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /doc command: reply with the Google Doc link for this client."""
    if not update.message:
        return

    chat = update.effective_chat
    if not chat or not chat.title or not chat.title.startswith(GROUP_PREFIX):
        await update.message.reply_text("This command only works in MoM groups.")
        return

    client_name = chat.title[len(GROUP_PREFIX) :]
    doc_id = find_doc(drive_service, client_name)

    if doc_id is None:
        await update.message.reply_text(
            f"No document found for {client_name}. Send a message first!"
        )
        return

    link = get_doc_link(doc_id)
    await update.message.reply_text(f"MoM for {client_name}:\n{link}")
