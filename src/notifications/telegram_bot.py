"""Phase 2 — Telegram bot (long polling; no webhook or public URL needed)."""
import logging
import os
import sys

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters,
)

from src import db, store
from src import profile as profile_rules
from src import sources
from src.notifications import cards, formatting, onboarding

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("opportunity-bot")

FELLOWSHIP_TYPES = {
    "fellowship", "scholarship", "research_program", "summer_program",
    "visiting_student_program", "exchange_program",
}


def require_token():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        logger.error(
            "TELEGRAM_BOT_TOKEN is not set. Add it to .env, then run: "
            "docker compose up -d --build telegram-bot"
        )
        sys.exit(1)
    return token


def is_internship(opp):
    return "intern" in str(opp.get("type") or "").lower() or \
        "intern" in str(opp.get("category") or "").lower() or \
        "intern" in str(opp.get("title") or "").lower()


def is_fellowship(opp):
    opp_type = str(opp.get("type") or "").lower()
    text = f"{opp_type} {opp.get('title')}".lower()
    if opp_type in FELLOWSHIP_TYPES:
        return True
    return "fellow" in text or "scholar" in text


LIST_PAGE_SIZE = 10


async def _send_items(update: Update, items, kind=None):
    items = list(items)
    if not items:
        await update.effective_chat.send_message(
            formatting.empty_state(kind), parse_mode="HTML"
        )
        return
    total = len(items)
    for offset in range(0, total, LIST_PAGE_SIZE):
        page = items[offset:offset + LIST_PAGE_SIZE]
        text = formatting.opportunities_to_text(
            page, limit=LIST_PAGE_SIZE, offset=offset, total=total
        )
        await update.effective_chat.send_message(text, parse_mode="HTML")


def _keyboard(opp_id, saved=False):
    rows = [
        [InlineKeyboardButton(text, callback_data=data) for text, data in row]
        for row in cards.buttons(opp_id, saved=saved)
    ]
    return InlineKeyboardMarkup(rows)


async def _send_card(chat_id, opp):
    saved = bool(opp.get("saved"))
    await chat_id.send_message(
        formatting.opportunity_to_text(opp),
        parse_mode="HTML",
        reply_markup=_keyboard(opp["id"], saved=saved),
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    db.set_user_chat_id(chat_id)
    logger.info("Chat registered: %s (%s)", chat_id, user.username if user else "?")
    profile = store.load_profile(chat_id)
    if not onboarding.is_profile_complete(profile):
        await update.effective_chat.send_message(
            "Welcome! Let's set up your profile so I can match "
            "opportunities to you.\n\n" + onboarding.begin(chat_id),
            parse_mode="HTML",
        )
        return
    await update.effective_chat.send_message(formatting.start_text(), parse_mode="HTML")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(formatting.help_text(), parse_mode="HTML")


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    profile = store.load_profile(update.effective_chat.id)
    await update.effective_chat.send_message(formatting.profile_to_text(profile), parse_mode="HTML")


async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(
        "Let's update your profile.\n\n" + onboarding.begin(update.effective_chat.id),
        parse_mode="HTML",
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    reply, finished = onboarding.handle_answer(chat_id, update.message.text)
    if reply is None:
        return
    await update.message.reply_text(reply, parse_mode="HTML")
    if finished:
        for opp in onboarding.top_opportunities():
            await _send_card(update.effective_chat, opp)


async def cmd_reset_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    profile = store.reset_profile(chat_id)
    if profile is None:
        await update.effective_chat.send_message("⚠️ No default profile found in config/profile.json")
        return
    await update.effective_chat.send_message(
        f"🔄 Profile reset to defaults\n\n{formatting.profile_to_text(profile)}",
        parse_mode="HTML",
    )


async def cmd_opportunities(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_items(update, store.load_opportunities())


async def cmd_internships(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_items(update, [o for o in store.load_opportunities() if is_internship(o)], "internship")


async def cmd_fellowships(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_items(update, [o for o in store.load_opportunities() if is_fellowship(o)], "fellowship")


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = sorted(
        (o for o in store.load_opportunities() if o.get("match_score") is not None),
        key=lambda o: o["match_score"],
        reverse=True,
    )[:5]
    if not items:
        await _send_items(update, items)
        return
    for opp in items:
        await _send_card(update.effective_chat, opp)


async def cmd_urgent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    urgent = []
    for opp in store.load_opportunities():
        days = formatting.deadline_days_left(opp.get("deadline"))
        if days is not None and 0 <= days <= 14:
            urgent.append(opp)
    urgent = sorted(urgent, key=lambda o: o.get("deadline") or "")
    if not urgent:
        await _send_items(update, urgent, "urgent")
        return
    for opp in urgent:
        await _send_card(update.effective_chat, opp)


async def cmd_saved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    saved = [o for o in store.load_opportunities() if o.get("saved")]
    if not saved:
        await _send_items(update, saved)
        return
    for opp in saved:
        await _send_card(update.effective_chat, opp)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src import webhook
    await update.effective_chat.send_message(
        formatting.stats_text(webhook.stats_payload()), parse_mode="HTML"
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    decoded = cards.decode(query.data)
    if not decoded:
        return
    action, opp_id = decoded
    opp = db.get_opportunity(opp_id)
    if not opp:
        await query.message.reply_text("⚠️ That opportunity no longer exists.")
        return
    if action == cards.SAVE:
        saved = db.toggle_saved(opp_id)
        if saved is None:
            return
        await query.edit_message_reply_markup(
            reply_markup=_keyboard(opp_id, saved=saved)
        )
    elif action == cards.DETAILS:
        await query.message.reply_text(
            formatting.opportunity_to_text(opp), parse_mode="HTML"
        )
    elif action == cards.APPLY:
        url = cards.apply_url(opp)
        if not url:
            await query.message.reply_text("⚠️ No application link recorded.")
        else:
            await query.message.reply_text(
                f"🔗 <a href=\"{formatting.esc(url)}\">Open application</a> "
                f"({formatting.esc(url)})",
                parse_mode="HTML",
            )


def main():
    token = require_token()
    db.init_db()
    store.load_profile()
    sources.sync_sources()
    app = Application.builder().token(token).build()
    handlers = [
        ("start", cmd_start),
        ("help", cmd_help),
        ("profile", cmd_profile),
        ("update", cmd_update),
        ("reset_profile", cmd_reset_profile),
        ("opportunities", cmd_opportunities),
        ("internships", cmd_internships),
        ("fellowships", cmd_fellowships),
        ("top", cmd_top),
        ("urgent", cmd_urgent),
        ("saved", cmd_saved),
        ("stats", cmd_stats),
    ]
    for command, handler in handlers:
        app.add_handler(CommandHandler(command, handler))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    logger.info("Opportunity Bot is polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()