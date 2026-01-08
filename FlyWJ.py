import os
import logging
from datetime import datetime

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

# Top-level log choices
CB_RUN = "log_run"
CB_GYM = "log_gym"
CB_OTHER = "log_other"

# Gym: body part
CB_BODY_CHEST = "gym_body_chest"
CB_BODY_BACK = "gym_body_back"
CB_BODY_LEGS = "gym_body_legs"
CB_BODY_ABS = "gym_body_abs"

# Gym: equipment
CB_EQ_DUMBBELL = "gym_eq_dumbbell"
CB_EQ_BARBELL = "gym_eq_barbell"
CB_EQ_MACHINE = "gym_eq_machine"
CB_EQ_BODYWEIGHT = "gym_eq_bodyweight"

# Gym: after an exercise is logged
CB_GYM_CONTINUE = "gym_continue"
CB_GYM_END = "gym_end"


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


def _continue_end_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("➕ Continue logging", callback_data=CB_GYM_CONTINUE),
                InlineKeyboardButton("✅ End workout", callback_data=CB_GYM_END),
            ]
        ]
    )


def _gym_choice_maps():
    body_map = {
        CB_BODY_CHEST: "Chest",
        CB_BODY_BACK: "Back",
        CB_BODY_LEGS: "Legs",
        CB_BODY_ABS: "Abs",
    }
    eq_map = {
        CB_EQ_DUMBBELL: "Dumbbell",
        CB_EQ_BARBELL: "Barbell",
        CB_EQ_MACHINE: "Machine",
        CB_EQ_BODYWEIGHT: "Body Weight",
    }
    return body_map, eq_map


def _reset_flow_state(context: ContextTypes.DEFAULT_TYPE):
    # flow state
    context.user_data.pop("pending_log_activity", None)
    context.user_data.pop("gym_body_part", None)
    context.user_data.pop("gym_equipment", None)


def _ensure_gym_session(context: ContextTypes.DEFAULT_TYPE):
    """
    Create a session store if it doesn't exist.
    One gym session = one "workout draft" for the user.
    """
    if "gym_session" not in context.user_data:
        context.user_data["gym_session"] = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "day": None,          # e.g. Chest
            "lines": [],          # e.g. ["Dumbbell Bench Press 3x6 @ 60kg", ...]
        }


def _format_gym_preview(context: ContextTypes.DEFAULT_TYPE) -> str:
    sess = context.user_data.get("gym_session")
    if not sess:
        return "No active workout."

    day = sess.get("day") or "Unknown"
    lines = sess.get("lines", [])
    preview_lines = "\n".join(lines) if lines else "(no exercises yet)"

    return (
        f"Day: {day}\n"
        f"{preview_lines}"
    )


def _format_gym_summary(context: ContextTypes.DEFAULT_TYPE) -> str:
    sess = context.user_data.get("gym_session")
    if not sess:
        return "No workout found."

    date = sess.get("date") or datetime.now().strftime("%d-%m-%Y")
    day = sess.get("day") or "Unknown"
    lines = sess.get("lines", [])

    body = "\n".join(lines) if lines else "(no exercises logged)"

    return (
        f"Summary of *{date}* Workout\n"
        f"Day: {day}\n"
        f"{body}"
    )


# ---------- Commands ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! I am your one stop fitness logging buddy! 🤖\n\n"
        "Type /log to log an activity."
    )


async def log_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _reset_flow_state(context)
    await update.message.reply_text(
        "What would you like to log?",
        reply_markup=_log_keyboard()
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


async def end_workout_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Optional command to end gym workout by text.
    """
    if "gym_session" not in context.user_data:
        await update.message.reply_text("No active gym workout.")
        return

    msg = _format_gym_summary(context)
    # clear session
    context.user_data.pop("gym_session", None)
    _reset_flow_state(context)
    await update.message.reply_text(msg, parse_mode="Markdown")


# ---------- Button handlers ----------

async def on_log_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == CB_GYM:
        _ensure_gym_session(context)
        context.user_data["pending_log_activity"] = "Gym"
        await query.edit_message_text(
            "🏋️ Gym selected.\nWhat body part are you hitting today?",
            reply_markup=_gym_bodypart_keyboard(),
        )
        return

    # Run / Other: simple flow (text details)
    activity = {"log_run": "Run", "log_other": "Other"}.get(query.data)
    if not activity:
        await query.edit_message_text("Unknown option. Please type /log again.")
        return

    context.user_data["pending_log_activity"] = activity
    await query.edit_message_text(
        f"✅ Selected: {activity}\nReply with details (e.g. `5km`, `45min`).",
        parse_mode="Markdown",
    )


async def on_gym_bodypart_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    body_map, _ = _gym_choice_maps()
    body_part = body_map.get(query.data)
    if not body_part:
        await query.edit_message_text("Unknown option. Please type /log again.")
        return

    _ensure_gym_session(context)
    context.user_data["gym_body_part"] = body_part
    context.user_data["gym_session"]["day"] = body_part  # set workout "Day"

    await query.edit_message_text(
        f"Day selected: {body_part}\nWhich equipment will you be using?",
        reply_markup=_gym_equipment_keyboard(),
    )


async def on_gym_equipment_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, eq_map = _gym_choice_maps()
    equipment = eq_map.get(query.data)
    if not equipment:
        await query.edit_message_text("Unknown option. Please type /log again.")
        return

    context.user_data["gym_equipment"] = equipment

    day = context.user_data.get("gym_body_part", "Unknown")
    await query.edit_message_text(
        f"Day: {day}\nEquipment: {equipment}\n\n"
        "Now type the exercise details.\n"
        "Example: `Bench Press 3 x 6 @ 60 kg`",
        parse_mode="Markdown",
    )


async def on_continue_end_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == CB_GYM_CONTINUE:
        # ask equipment again (same Day) so user can choose per exercise
        day = context.user_data.get("gym_session", {}).get("day") or context.user_data.get("gym_body_part") or "Unknown"
        context.user_data["gym_body_part"] = day
        await query.edit_message_text(
            f"Day: {day}\nWhich equipment will you be using for the next exercise?",
            reply_markup=_gym_equipment_keyboard(),
        )
        return

    if query.data == CB_GYM_END:
        msg = _format_gym_summary(context)
        # clear gym session
        context.user_data.pop("gym_session", None)
        _reset_flow_state(context)

        await query.edit_message_text("✅ Workout ended.")
        await query.message.reply_text(msg, parse_mode="Markdown")
        return


# ---------- Text handler (details) ----------

async def on_details_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending = context.user_data.get("pending_log_activity")
    if not pending:
        return

    details = (update.message.text or "").strip()
    if not details:
        await update.message.reply_text("Please type some details.")
        return

    # Gym: require day + equipment, store as session lines
    if pending == "Gym":
        sess = context.user_data.get("gym_session")
        day = sess.get("day") if sess else None
        equipment = context.user_data.get("gym_equipment")

        if not day or not equipment:
            await update.message.reply_text("Please choose Day + Equipment first. Type /log and pick Gym.")
            return

        # Build the line: "Dumbbell Bench Press 3 x 6 @ 60 kg"
        line = f"{equipment} {details}"

        # Append to session
        sess["lines"].append(line)

        # Show preview + continue/end
        preview = _format_gym_preview(context)
        await update.message.reply_text(preview)
        await update.message.reply_text(
            "Would you like to continue logging or end the workout?",
            reply_markup=_continue_end_keyboard(),
        )
        return

    # Run / Other: old behavior (single log item)
    final_details = details
    context.user_data.pop("pending_log_activity", None)

    logs = context.user_data.setdefault("logs", [])
    logs.append(
        {
            "activity": pending,
            "details": final_details,
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
    )

    await update.message.reply_text(
        f"📌 Logged: {pending} — {final_details}\n"
        "Type /log to add another, or /summary to see your logs."
    )


# ---------- Main ----------

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable not set")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("log", log_cmd))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("end", end_workout_cmd))  # optional

    app.add_handler(CallbackQueryHandler(on_log_choice, pattern=r"^log_(run|gym|other)$"))
    app.add_handler(CallbackQueryHandler(on_gym_bodypart_choice, pattern=r"^gym_body_"))
    app.add_handler(CallbackQueryHandler(on_gym_equipment_choice, pattern=r"^gym_eq_"))
    app.add_handler(CallbackQueryHandler(on_continue_end_choice, pattern=r"^gym_(continue|end)$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_details_message))

    logging.info("✅ Bot is running.")
    app.run_polling()


if __name__ == "__main__":
    main()
