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

# ---------- Callback data ----------
CB_RUN = "log_run"
CB_GYM = "log_gym"
CB_OTHER = "log_other"

CB_BODY_CHEST = "gym_body_chest"
CB_BODY_BACK = "gym_body_back"
CB_BODY_LEGS = "gym_body_legs"
CB_BODY_ABS = "gym_body_abs"

CB_EQ_DUMBBELL = "gym_eq_dumbbell"
CB_EQ_BARBELL = "gym_eq_barbell"
CB_EQ_MACHINE = "gym_eq_machine"
CB_EQ_BODYWEIGHT = "gym_eq_bodyweight"

CB_YES = "yn_yes"
CB_NO = "yn_no"

CB_GYM_CONTINUE = "gym_continue"
CB_GYM_END = "gym_end"


# ---------- Keyboards ----------
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


def _yes_no_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Yes", callback_data=CB_YES), InlineKeyboardButton("No", callback_data=CB_NO)]]
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


# ---------- Helpers ----------
def _reset_flow(context: ContextTypes.DEFAULT_TYPE):
    for k in [
        "pending_log_activity",
        "gym_body_part",
        "gym_equipment",
        "gym_wizard",
    ]:
        context.user_data.pop(k, None)


def _ensure_gym_session(context: ContextTypes.DEFAULT_TYPE):
    if "gym_session" not in context.user_data:
        context.user_data["gym_session"] = {
            "date": datetime.now().strftime("%d-%m-%Y"),
            "day": None,
            "entries": [],  # each entry is a dict with equipment, exercise, sets, reps[], weights[], compact
        }


def _format_compact(sets: int, reps: list[int], weights: list[str]) -> str:
    """
    3 x 6(60), 5(60), 5(60)
    3 x 6(60), 4(61.25), 3(62.5)
    """
    parts = []
    for i in range(sets):
        parts.append(f"{reps[i]}({weights[i]})")
    return f"{sets} x " + ", ".join(parts)


def _format_workout_summary_md(context: ContextTypes.DEFAULT_TYPE) -> str:
    sess = context.user_data.get("gym_session")
    if not sess:
        return "No workout found."

    date = sess.get("date") or datetime.now().strftime("%d-%m-%Y")
    day = sess.get("day") or "Unknown"

    lines = [f"Summary of *{date}* Workout", f"Day: {day}"]
    if not sess["entries"]:
        lines.append("(no exercises logged)")
        return "\n".join(lines)

    for e in sess["entries"]:
        lines.append(f"{e['equipment']} {e['exercise']} — {e['compact']}")

    return "\n".join(lines)


def _wizard_init(exercise: str):
    # gym_wizard state machine
    return {
        "step": "ask_sets",              # next expected input
        "exercise": exercise.strip(),
        "sets": None,
        "reps_same": None,
        "weights_same": None,
        "reps": [],
        "weights": [],
        "current_index": 0,              # for per-set prompting (0-based)
        "temp_reps_all": None,
        "temp_weight_all": None,
    }


def _is_int(s: str) -> bool:
    try:
        int(s)
        return True
    except Exception:
        return False


# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! I am your one stop fitness logging buddy! 🤖\n\n"
        "Type /log to log an activity."
    )


async def log_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _reset_flow(context)
    await update.message.reply_text("What would you like to log?", reply_markup=_log_keyboard())


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # session summary for non-gym (legacy) + gym entries preview
    lines = []

    # Gym session preview
    sess = context.user_data.get("gym_session")
    if sess and sess.get("entries"):
        lines.append(f"🏋️ Gym ({sess.get('date')}): Day: {sess.get('day') or 'Unknown'}")
        for i, e in enumerate(sess["entries"][-10:], start=1):
            lines.append(f"{i}. {e['equipment']} {e['exercise']} — {e['compact']}")
        lines.append("")

    # Legacy logs
    logs = context.user_data.get("logs", [])
    if logs:
        lines.append("🧾 Other logs:")
        for i, item in enumerate(logs[-10:], start=1):
            lines.append(f"{i}. {item['activity']}: {item['details']}")

    if not lines:
        await update.message.reply_text("No logs yet. Type /log to start.")
        return

    await update.message.reply_text("\n".join(lines))


async def end_workout_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "gym_session" not in context.user_data:
        await update.message.reply_text("No active gym workout.")
        return

    msg = _format_workout_summary_md(context)
    context.user_data.pop("gym_session", None)
    _reset_flow(context)
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

    activity = {CB_RUN: "Run", CB_OTHER: "Other"}.get(query.data)
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

    _ensure_gym_session(context)
    context.user_data["gym_body_part"] = body_part
    context.user_data["gym_session"]["day"] = body_part

    await query.edit_message_text(
        f"Day selected: {body_part}\nWhich equipment will you be using?",
        reply_markup=_gym_equipment_keyboard(),
    )


async def on_gym_equipment_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    day = context.user_data.get("gym_body_part", "Unknown")
    await query.edit_message_text(
        f"Day: {day}\nEquipment: {equipment}\n\n"
        "Type the exercise name (e.g. `Bench Press`, `Squat`).",
        parse_mode="Markdown",
    )

    # Prepare wizard to accept exercise name as next text
    context.user_data["gym_wizard"] = {"step": "ask_exercise_name"}


async def on_yes_no_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles Yes/No clicks for:
    - reps same?
    - weights same?
    """
    query = update.callback_query
    await query.answer()

    wiz = context.user_data.get("gym_wizard")
    if not wiz:
        await query.edit_message_text("No active logging flow. Type /log to start.")
        return

    yn = True if query.data == CB_YES else False

    # reps same question
    if wiz.get("step") == "ask_reps_same":
        wiz["reps_same"] = yn
        if yn:
            wiz["step"] = "ask_reps_all"
            await query.edit_message_text("Number of reps (same for all sets)?")
        else:
            wiz["step"] = "ask_reps_set"
            wiz["current_index"] = 0
            await query.edit_message_text("Number of reps for set 1?")
        return

    # weights same question
    if wiz.get("step") == "ask_weights_same":
        wiz["weights_same"] = yn
        if yn:
            wiz["step"] = "ask_weight_all"
            await query.edit_message_text("Weight used for ALL sets? (e.g. `60`, `61.25`, `135lb`)")
        else:
            wiz["step"] = "ask_weight_set"
            wiz["current_index"] = 0
            await query.edit_message_text("Weight used for set 1? (e.g. `60`, `61.25`, `135lb`)")
        return

    await query.edit_message_text("Unexpected selection. Type /log to restart.")


async def on_continue_end_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == CB_GYM_CONTINUE:
        # Ask equipment again for next exercise
        sess = context.user_data.get("gym_session", {})
        day = sess.get("day") or context.user_data.get("gym_body_part") or "Unknown"
        context.user_data["gym_body_part"] = day
        context.user_data.pop("gym_wizard", None)
        context.user_data.pop("gym_equipment", None)

        await query.edit_message_text(
            f"Day: {day}\nWhich equipment will you be using for the next exercise?",
            reply_markup=_gym_equipment_keyboard(),
        )
        return

    if query.data == CB_GYM_END:
        msg = _format_workout_summary_md(context)
        context.user_data.pop("gym_session", None)
        _reset_flow(context)

        await query.edit_message_text("✅ Workout ended.")
        await query.message.reply_text(msg, parse_mode="Markdown")
        return


# ---------- Text handler ----------
async def on_details_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending = context.user_data.get("pending_log_activity")
    text = (update.message.text or "").strip()
    if not text:
        return

    # ----- Gym wizard flow -----
    if pending == "Gym":
        _ensure_gym_session(context)
        sess = context.user_data["gym_session"]
        day = sess.get("day")
        equipment = context.user_data.get("gym_equipment")

        if not day or not equipment:
            await update.message.reply_text("Please choose Day + Equipment first. Type /log and pick Gym.")
            return

        wiz = context.user_data.get("gym_wizard")

        # If wizard not started, require user to choose equipment (we start it after equipment selection)
        if not wiz:
            await update.message.reply_text("Please choose equipment first (via buttons). Type /log → Gym.")
            return

        step = wiz.get("step")

        # Step: exercise name
        if step == "ask_exercise_name":
            exercise = text
            context.user_data["gym_wizard"] = _wizard_init(exercise)
            await update.message.reply_text("Number of sets?")
            return

        # Step: sets
        if step == "ask_sets":
            if not _is_int(text) or int(text) <= 0 or int(text) > 20:
                await update.message.reply_text("Please enter a valid number of sets (1-20).")
                return
            wiz["sets"] = int(text)
            wiz["step"] = "ask_reps_same"
            await update.message.reply_text("Are reps the same for all sets?", reply_markup=_yes_no_keyboard())
            return

        # Step: reps all
        if step == "ask_reps_all":
            if not _is_int(text) or int(text) <= 0 or int(text) > 100:
                await update.message.reply_text("Please enter a valid reps number (1-100).")
                return
            reps_all = int(text)
            wiz["reps"] = [reps_all] * wiz["sets"]
            wiz["step"] = "ask_weights_same"
            await update.message.reply_text("Is weight used the same for all sets?", reply_markup=_yes_no_keyboard())
            return

        # Step: reps per set
        if step == "ask_reps_set":
            if not _is_int(text) or int(text) <= 0 or int(text) > 100:
                await update.message.reply_text("Please enter a valid reps number (1-100).")
                return
            wiz["reps"].append(int(text))
            idx = len(wiz["reps"])
            if idx < wiz["sets"]:
                await update.message.reply_text(f"Number of reps for set {idx + 1}?")
                return
            wiz["step"] = "ask_weights_same"
            await update.message.reply_text("Is weight used the same for all sets?", reply_markup=_yes_no_keyboard())
            return

        # Step: weight all
        if step == "ask_weight_all":
            # keep weight as text (supports kg/lb)
            w = text
            wiz["weights"] = [w] * wiz["sets"]
            await _finalize_gym_entry(update, context)
            return

        # Step: weight per set
        if step == "ask_weight_set":
            wiz["weights"].append(text)
            idx = len(wiz["weights"])
            if idx < wiz["sets"]:
                await update.message.reply_text(f"Weight used for set {idx + 1}?")
                return
            await _finalize_gym_entry(update, context)
            return

        await update.message.reply_text("I got confused in the flow. Type /log to restart.")
        return

    # ----- Run / Other (legacy) -----
    if pending:
        activity = pending
        context.user_data.pop("pending_log_activity", None)
        logs = context.user_data.setdefault("logs", [])
        logs.append({"activity": activity, "details": text, "ts": datetime.now().isoformat(timespec="seconds")})
        await update.message.reply_text(
            f"📌 Logged: {activity} — {text}\nType /log to add another, or /summary to see your logs."
        )


async def _finalize_gym_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Create compact format:
      3 x 6(60), 5(60), 5(60)
      3 x 6(60), 4(61.25), 3(62.5)
    Save it into gym_session entries and prompt Continue/End.
    """
    sess = context.user_data["gym_session"]
    equipment = context.user_data.get("gym_equipment")
    wiz = context.user_data.get("gym_wizard")

    sets = wiz["sets"]
    reps = wiz["reps"]
    weights = wiz["weights"]
    exercise = wiz["exercise"]

    compact = _format_compact(sets, reps, weights)

    sess["entries"].append(
        {
            "equipment": equipment,
            "exercise": exercise,
            "sets": sets,
            "reps": reps,
            "weights": weights,
            "compact": compact,
        }
    )

    # Clear wizard (keep day + allow continue)
    context.user_data.pop("gym_wizard", None)
    context.user_data.pop("gym_equipment", None)

    # Show the clean format you asked for
    day = sess.get("day") or "Unknown"
    await update.message.reply_text(
        f"Day: {day}\n{equipment} {exercise}\n{compact}\n\n"
        "Would you like to continue logging or end the workout?",
        reply_markup=_continue_end_keyboard(),
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
    app.add_handler(CommandHandler("end", end_workout_cmd))  # optional manual end

    app.add_handler(CallbackQueryHandler(on_log_choice, pattern=r"^log_(run|gym|other)$"))
    app.add_handler(CallbackQueryHandler(on_gym_bodypart_choice, pattern=r"^gym_body_"))
    app.add_handler(CallbackQueryHandler(on_gym_equipment_choice, pattern=r"^gym_eq_"))
    app.add_handler(CallbackQueryHandler(on_yes_no_choice, pattern=r"^yn_(yes|no)$"))
    app.add_handler(CallbackQueryHandler(on_continue_end_choice, pattern=r"^gym_(continue|end)$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_details_message))

    logging.info("✅ Bot is running.")
    app.run_polling()


if __name__ == "__main__":
    main()
