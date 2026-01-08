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

# Gym flow: body parts
CB_BODY_CHEST = "gym_body_chest"
CB_BODY_BACK = "gym_body_back"
CB_BODY_LEGS = "gym_body_legs"
CB_BODY_ABS = "gym_body_abs"

# Gym flow: equipment
CB_EQ_DUMBBELL = "gym_eq_dumbbell"
CB_EQ_BARBELL = "gym_eq_barbell"
CB_EQ_MACHINE = "gym_eq_machine"
CB_EQ_BODYWEIGHT = "gym_eq_bodyweight"


def _log_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏃 Run", callback_data=CB_RUN)],
            [InlineKeyboardButton("🏋️ Gym", callback_data=CB_GYM)],
            [InlineKeyboardButton("🧘 Other", callback_data=CB_OTHER)],
        ]
    )


def _gym_bodypart_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Chest", callback_data=CB_BODY_CHEST)],
            [InlineKeyboardButton("Back", callback_data=CB_BODY_BACK)],
            [InlineKeyboardButton("Legs", callback_data=CB_BODY_LEGS)],
            [InlineKeyboardButton("Abs", callback_data=CB_BODY_ABS)],
        ]
    )


def _gym_equipment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Dumbbell", callback_data=CB_EQ_DUMBBELL)],
            [InlineKeyboardButton("Barbell", callback_data=CB_EQ_BARBELL)],
            [InlineKeyboardButton("Machine", callback_data=CB_EQ_MACHINE)],
            [InlineKeyboardButton("Body Weight", callback_data=CB_EQ_BODYWEIGHT)],
        ]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! I am your one stop fitness logging buddy!🤖\n\n"
        "Use /log to log an activity.\n"
        "Use /summary to see what you logged (for this session)."
    )


async def log_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Clear any half-finished flow
    context.user_data.pop("pending_log_activity", None)
    context.user_data.pop("gym_body_part", None)
    context.user_data.pop("gym_equipment", None)

    await update.message.reply_text(
        "What would you like to log?",
        reply_markup=_log_keyboard()
    )


async def on_log_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles top-level log choice buttons (Run / Gym / Other)."""
    query = update.callback_query
    await query.answer()

    if query.data == CB_GYM:
        # Start Gym flow: ask body part first
        context.user_data["pending_log_activity"] = "Gym"
        await query.edit_message_text(
            "🏋️ Gym selected.\nWhat body part are you hitting today?",
            reply_markup=_gym_bodypart_keyboard(),
        )
        return

    # Run / Other -> go straight to free text details
    choice_map = {
        CB_RUN: "Run",
        CB_OTHER: "Other",
    }
    activity = choice_map.get(query.data)
    if not activity:
        await query.edit_message_text("Unknown option. Please type /log again.")
        return

    context.user_data["pending_log_activity"] = activity
    await query.edit_message_text(
        f"✅ Selected: {activity}\n"
        f"Reply with details (e.g. `5km`, `45min`, `Leg day 60min`).",
        parse_mode="Markdown",
    )


async def on_gym_bodypart_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles gym body part buttons."""
    query = update.callback_query
    await query.answer()

    body_map = {
        CB_BODY_CHEST: "Chest",
        CB_BODY_BACK: "Back",
        CB_BODY_LEGS: "Legs",
        CB_BODY_ABS: "Abs",
    }
    body_part = body_map.get(query.data)
    if not body_part:
        await query.edit_message_text("Unknown option. Please type /log again.")
        return

    context.user_data["gym_body_part"] = body_part

    await query.edit_message_text(
        f"✅ Body part: {body_part}\nWhich equipment will you be using?",
        reply_markup=_gym_equipment_keyboard(),
    )


async def on_gym_equipment_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles gym equipment buttons; then ask for details."""
    query = update.callback_query
    await query.answer()

    eq_map = {
        CB_EQ_DUMBBELL: "Dumbbell",
        CB_EQ_BARBELL: "Barbell",
        CB_EQ_MACHINE: "Machine",
        CB_EQ_BODYWEIGHT: "Body Weight",
    }
    equipment = eq_map.get(query.data)
    if not equipment:
        await query.edit_message_text("Unknown option. Please type /log again.")
        return

    context.user_data["gym_equipment"] = equipment

    body_part = context.user_data.get("gym_body_part", "Unknown")
    await query.edit_message_text(
        f"✅ Gym setup:\n- Body part: {body_part}\n- Equipment: {equipment}\n\n"
        "Now reply with details (e.g. `Bench 3x8 @ 60kg`, `Squat 5x5`, `Plank 3x60s`)."
    )


async def on_details_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """If user previously chose an activity, this message becomes the details."""
    pending = context.user_data.get("pending_log_activity")
    if not pending:
        return

    details = (update.message.text or "").strip()
    if not details:
        await update.message.reply_text("Please send some details (e.g. `5km` or `45min`).")
        return

    # Build a richer detail line for Gym
    if pending == "Gym":
        body_part = context.user_data.get("gym_body_part", "")
        equipment = context.user_data.get("gym_equipment", "")

        # Ensure Gym flow was completed
        if not body_part or not equipment:
            await update.message.reply_text(
                "For Gym logs, please select a body part and equipment first.\nType /log and choose Gym."
            )
            return

        final_details = f"{body_part} | {equipment} | {details}"
    else:
        final_details = details

    # Clear pending state
    context.user_data.pop("pending_log_activity", None)
    context.user_data.pop("gym_body_part", None)
    context.user_data.pop("gym_equipment", None)

    # Store logs in memory for now (per user, per running process)
    logs = context.user_data.setdefault("logs", [])
    logs.append(
        {
            "activity": pending,
            "details": final_details,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )

    await update.message.reply_text(
        f"📌 Logged: {pending} — {final_details}\n"
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

    # Button handlers
    app.add_handler(CallbackQueryHandler(on_log_choice, pattern=r"^log_(run|gym|other)$"))
    app.add_handler(CallbackQueryHandler(on_gym_bodypart_choice, pattern=r"^gym_body_"))
    app.add_handler(CallbackQueryHandler(on_gym_equipment_choice, pattern=r"^gym_eq_"))

    # Text details handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_details_message))

    print("✅ Bot is running.")
    app.run_polling()


if __name__ == "__main__":
    main()
