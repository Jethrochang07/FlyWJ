import os
import logging
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# Callback data constants
CB_RUN = "log_run"
CB_GYM = "log_gym"
CB_OTHER = "log_other"

def _log_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏃 Run", callback_data=CB_RUN)],
            [InlineKeyboardButton("🏋️ Gym", callback_data=CB_GYM)],
            [InlineKeyboardButton("🧘 Other", callback_data=CB_OTHER)],
        ]
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! Your bot is working 🤖\n\n"
        "Use /log to log an activity.\n"
        "Use /summary to see what you logged (for this session)."
    )

async def log_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "What would you like to log?",
        reply_markup=_log_keyboard()
    )

async def on_log_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button clicks."""
    query = update.callback_query
    await query.answer()

    choice_map = {
        CB_RUN: "Run",
        CB_GYM: "Gym",
        CB_OTHER: "Other",
    }

    activity = choice_map.get(query.data)
    if not activity:
        await query.edit_message_text("Unknown option. Please type /log again.")
        return

    # Remember what the user selected; next text message will be treated as details
    context.user_data["pending_log_activity"] = activity

    await query.edit_message_text(
        f"✅ Selected: {activity}\n"
        f"Reply with details (e.g. `5km`, `45min`, `Leg day 60min`).",
        parse_mode="Markdown",
    )

async def on_details_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """If user previously chose an activity, this message becomes the details."""
    pending = context.user_data.get("pending_log_activity")
    if not pending:
        # Not in logging flow — ignore or you can echo/help here
        return

    details = (update.message.text or "").strip()
    if not details:
        await update.message.reply_text("Please send some details (e.g. `5km` or `45min`).")
        return

    # Clear pending state
    context.user_data.pop("pending_log_activity", None)

    # Store logs in memory for now (per user, per running process)
    logs = context.user_data.setdefault("logs", [])
    logs.append(
        {
            "activity": pending,
            "details": details,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )

    await update.message.reply_text(
        f"📌 Logged: {pending} — {details}\n"
        f"Type /log to add another, or /summary to see your logs."
    )

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logs = context.user_data.get("logs", [])
    if not logs:
        await update.message.reply_text("No logs yet. Type /log to start.")
        return

    lines = []
    for i, item in enumerate(logs[-10:], start=1):
        lines.append(f"{i}. {item['activity']}: {item['details']}")

    await update.message.reply_text("🧾 Your recent logs:\n" + "\n".join(lines))

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable not set")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("log", log_cmd))
    app.add_handler(CommandHandler("summary", summary))

    app.add_handler(CallbackQueryHandler(on_log_choice, pattern=f"^{CB_RUN}|{CB_GYM}|{CB_OTHER}$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_details_message))

    print("✅ Bot is running.")
    app.run_polling()

if __name__ == "__main__":
    main()
