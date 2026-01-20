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

# =========================
# CONFIG
# =========================
# For testing: 5 minutes = 300 seconds
# For production: 3 hours = 10800 seconds
INACTIVITY_SECONDS = 300

ONBOARDING_ASK_NAME = "ask_name"

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
CB_EQ_CABLE = "gym_eq_cable"
CB_EQ_BODYWEIGHT = "gym_eq_bodyweight"

CB_GYM_CONTINUE = "gym_continue"
CB_GYM_END = "gym_end"


# =========================
# Keyboards
# =========================
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
            [InlineKeyboardButton("Cable Machine", callback_data=CB_EQ_CABLE)],
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


# =========================
# Helpers
# =========================
def _reset_flow(context: ContextTypes.DEFAULT_TYPE):
    for k in ["pending_log_activity", "gym_body_part", "gym_equipment", "gym_wizard"]:
        context.user_data.pop(k, None)


def _ensure_gym_session(context: ContextTypes.DEFAULT_TYPE):
    if "gym_session" not in context.user_data:
        context.user_data["gym_session"] = {
            "date": datetime.now().strftime("%d-%m-%Y"),
            "day": None,
            "entries": [],  # dicts: equipment, exercise, compact
        }


def _format_compact(sets: int, reps: list[int], weights: list[str]) -> str:
    # 3 x 6(60), 4(61.25), 3(62.5)
    return f"{sets} x " + ", ".join(f"{reps[i]}({weights[i]})" for i in range(sets))


def _format_workout_summary_md(user_data: dict) -> str:
    sess = user_data.get("gym_session")
    if not sess:
        return "No workout found."

    date = sess.get("date") or datetime.now().strftime("%d-%m-%Y")
    day = sess.get("day") or "Unknown"

    lines = [f"Summary of *{date}* Workout", f"Day: {day}"]

    if not sess.get("entries"):
        lines.append("(no exercises logged)")
        return "\n".join(lines)

    for e in sess["entries"]:
        lines.append(f"{e['equipment']} {e['exercise']} — {e['compact']}")

    return "\n".join(lines)


def _wizard_init(exercise: str) -> dict:
    # Option 1: set-by-set input
    return {
        "step": "ask_sets",
        "exercise": exercise.strip(),
        "sets": None,
        "reps": [],
        "weights": [],
    }


def _is_int(s: str) -> bool:
    try:
        int(s)
        return True
    except Exception:
        return False


def _parse_set_input(text: str):
    """
    Accept: '6@60', '6 @ 60', '6x60' (x treated as @)
    Returns: (reps:int, weight:str) or None
    """
    t = text.strip().lower().replace(" ", "").replace("x", "@")
    if "@" not in t:
        return None
    reps_s, weight_s = t.split("@", 1)
    if not reps_s.isdigit():
        return None
    reps = int(reps_s)
    weight = weight_s.strip()
    if reps <= 0 or reps > 200 or not weight:
        return None
    return reps, weight


# =========================
# Inactivity Timer (JobQueue)
# =========================
def _cancel_gym_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.user_data.get("gym_timeout_job")
    if job:
        try:
            job.schedule_removal()
        except Exception:
            pass
        context.user_data.pop("gym_timeout_job", None)


def _reset_gym_timeout(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    """
    Call this whenever the user does something in the Gym flow.
    Resets the inactivity timer.
    """
    _cancel_gym_timeout(context)

    job = context.application.job_queue.run_once(
        _on_gym_timeout,
        when=INACTIVITY_SECONDS,
        data={"chat_id": chat_id, "user_id": user_id},
        name=f"gym_timeout_{chat_id}_{user_id}",
    )
    context.user_data["gym_timeout_job"] = job


async def _on_gym_timeout(context: ContextTypes.DEFAULT_TYPE):
    """
    JobQueue callback after inactivity.
    Auto-ends workout if there's an active gym_session.
    """
    data = context.job.data or {}
    chat_id = data.get("chat_id")
    user_id = data.get("user_id")

    if chat_id is None or user_id is None:
        return

    user_data = context.application.user_data.get(user_id, {})
    sess = user_data.get("gym_session")
    if not sess:
        return  # no active gym workout

    summary_md = _format_workout_summary_md(user_data)

    # Clear gym state
    for k in ["gym_session", "pending_log_activity", "gym_body_part", "gym_equipment", "gym_wizard", "gym_timeout_job"]:
        user_data.pop(k, None)

    await context.bot.send_message(
        chat_id=chat_id,
        text="⏱️ No activity detected for a while, so I ended your workout automatically.\n\n" + summary_md,
        parse_mode="Markdown",
    )


# =========================
# Commands
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.get("name")
    if not name:
        context.user_data["onboarding"] = ONBOARDING_ASK_NAME
        await update.message.reply_text("👋 Hey there!\n\nWhat should I call you?")
        return

    await update.message.reply_text(f"Welcome back, {name} 💪\n\nType /log to log an activity.")


async def log_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.get("name", "")
    greeting = f"{name}, what would you like to log?" if name else "What would you like to log?"
    _reset_flow(context)
    await update.message.reply_text(greeting, reply_markup=_log_keyboard())


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = []

    sess = context.user_data.get("gym_session")
    if sess and sess.get("entries"):
        lines.append(f"🏋️ Gym ({sess.get('date')}): Day: {sess.get('day') or 'Unknown'}")
        for i, e in enumerate(sess["entries"][-10:], start=1):
            lines.append(f"{i}. {e['equipment']} {e['exercise']} — {e['compact']}")
        lines.append("")

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
    # Manual end (also cancels timer)
    if "gym_session" not in context.user_data:
        await update.message.reply_text("No active gym workout.")
        return

    _cancel_gym_timeout(context)
    msg = _format_workout_summary_md(context.user_data)

    context.user_data.pop("gym_session", None)
    _reset_flow(context)

    await update.message.reply_text(msg, parse_mode="Markdown")


# =========================
# Button handlers
# =========================
async def on_log_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    chat_id = q.message.chat_id
    user_id = q.from_user.id

    if q.data == CB_GYM:
        _ensure_gym_session(context)
        context.user_data["pending_log_activity"] = "Gym"

        # Start/reset timer when gym flow begins
        _reset_gym_timeout(context, chat_id, user_id)

        await q.edit_message_text(
            "🏋️ Gym selected.\nWhat body part are you hitting today?",
            reply_markup=_gym_bodypart_keyboard(),
        )
        return

    # Run / Other: simple text logging
    activity = {CB_RUN: "Run", CB_OTHER: "Other"}.get(q.data)
    if not activity:
        await q.edit_message_text("Unknown option. Please type /log again.")
        return

    context.user_data["pending_log_activity"] = activity
    await q.edit_message_text(
        f"✅ Selected: {activity}\nReply with details (e.g. `5km`, `45min`).",
        parse_mode="Markdown",
    )


async def on_gym_bodypart_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    chat_id = q.message.chat_id
    user_id = q.from_user.id
    _reset_gym_timeout(context, chat_id, user_id)

    body_map = {
        CB_BODY_CHEST: "Chest",
        CB_BODY_BACK: "Back",
        CB_BODY_LEGS: "Legs",
        CB_BODY_ABS: "Abs",
    }
    body = body_map.get(q.data)
    if not body:
        await q.edit_message_text("Unknown option. Type /log again.")
        return

    _ensure_gym_session(context)
    context.user_data["gym_body_part"] = body
    context.user_data["gym_session"]["day"] = body

    await q.edit_message_text(
        f"Day selected: {body}\nWhich equipment will you be using?",
        reply_markup=_gym_equipment_keyboard(),
    )


async def on_gym_equipment_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    chat_id = q.message.chat_id
    user_id = q.from_user.id
    _reset_gym_timeout(context, chat_id, user_id)

    eq_map = {
        CB_EQ_DUMBBELL: "Dumbbell",
        CB_EQ_BARBELL: "Barbell",
        CB_EQ_MACHINE: "Machine",
        CB_EQ_CABLE: "Cable",
        CB_EQ_BODYWEIGHT: "Body Weight",
    }
    equipment = eq_map.get(q.data)
    if not equipment:
        await q.edit_message_text("Unknown option. Type /log again.")
        return

    context.user_data["gym_equipment"] = equipment
    context.user_data["gym_wizard"] = {"step": "ask_exercise_name"}

    day = context.user_data.get("gym_body_part", "Unknown")
    await q.edit_message_text(
        f"Day: {day}\nEquipment: {equipment}\n\nType the exercise name (e.g. `Bench Press`, `Squat`).",
        parse_mode="Markdown",
    )


async def on_continue_end_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    chat_id = q.message.chat_id
    user_id = q.from_user.id

    if q.data == CB_GYM_CONTINUE:
        # reset timer when continuing
        _reset_gym_timeout(context, chat_id, user_id)

        sess = context.user_data.get("gym_session", {})
        day = sess.get("day") or context.user_data.get("gym_body_part") or "Unknown"
        context.user_data["gym_body_part"] = day

        # clear per-exercise wizard + equipment so user chooses again
        context.user_data.pop("gym_wizard", None)
        context.user_data.pop("gym_equipment", None)

        await q.edit_message_text(
            f"Day: {day}\nWhich equipment will you be using for the next exercise?",
            reply_markup=_gym_equipment_keyboard(),
        )
        return

    if q.data == CB_GYM_END:
        _cancel_gym_timeout(context)

        msg = _format_workout_summary_md(context.user_data)
        context.user_data.pop("gym_session", None)
        _reset_flow(context)

        await q.edit_message_text("✅ Workout ended.")
        await q.message.reply_text(msg, parse_mode="Markdown")
        return


# =========================
# Text handler
# =========================
async def on_details_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return

    # Onboarding: ask for name
    if context.user_data.get("onboarding") == ONBOARDING_ASK_NAME:
        name = text.strip()
        if len(name) < 2:
            await update.message.reply_text("That name seems a bit short 😅 Try again?")
            return

        context.user_data["name"] = name
        context.user_data.pop("onboarding", None)
        await update.message.reply_text(f"Nice to meet you, {name} 💪\n\nType /log when you're ready.")
        return

    pending = context.user_data.get("pending_log_activity")

    # Gym flow (set-by-set)
    if pending == "Gym":
        _ensure_gym_session(context)

        sess = context.user_data["gym_session"]
        if not sess.get("day") or not context.user_data.get("gym_equipment"):
            await update.message.reply_text("Please choose Day + Equipment first. Type /log and pick Gym.")
            return

        # Reset inactivity timer on any gym message
        _reset_gym_timeout(context, update.effective_chat.id, update.effective_user.id)

        wiz = context.user_data.get("gym_wizard")
        if not wiz:
            await update.message.reply_text("Please choose equipment first (via buttons). Type /log → Gym.")
            return

        step = wiz.get("step")

        # Exercise name
        if step == "ask_exercise_name":
            context.user_data["gym_wizard"] = _wizard_init(text)
            await update.message.reply_text("Number of sets?")
            return

        # Sets
        if step == "ask_sets":
            if not _is_int(text) or int(text) <= 0 or int(text) > 20:
                await update.message.reply_text("Please enter a valid number of sets (1-20).")
                return

            wiz["sets"] = int(text)
            wiz["step"] = "ask_set_line"
            await update.message.reply_text(
                "Set 1 — reps @ weight?\nExample: `6@60` or `6 @ 60` or `6x60`",
                parse_mode="Markdown",
            )
            return

        # Set lines
        if step == "ask_set_line":
            parsed = _parse_set_input(text)
            if not parsed:
                await update.message.reply_text("Use format `reps@weight` (e.g. `6@60`).", parse_mode="Markdown")
                return

            reps, weight = parsed
            wiz["reps"].append(reps)
            wiz["weights"].append(weight)

            if len(wiz["reps"]) < wiz["sets"]:
                nxt = len(wiz["reps"]) + 1
                await update.message.reply_text(f"Set {nxt} — reps @ weight?")
                return

            # Finalize exercise
            sets = wiz["sets"]
            compact = _format_compact(sets, wiz["reps"], wiz["weights"])

            sess["entries"].append(
                {
                    "equipment": context.user_data["gym_equipment"],
                    "exercise": wiz["exercise"],
                    "compact": compact,
                }
            )

            # clear wizard + equipment so next exercise chooses equipment again (as you had)
            context.user_data.pop("gym_wizard", None)
            context.user_data.pop("gym_equipment", None)

            day = sess.get("day") or "Unknown"
            await update.message.reply_text(
                f"Day: {day}\n{sess['entries'][-1]['equipment']} {sess['entries'][-1]['exercise']}\n{compact}\n\n"
                "Would you like to continue logging or end the workout?",
                reply_markup=_continue_end_keyboard(),
            )
            return

        await update.message.reply_text("I got confused in the flow. Type /log to restart.")
        return

    # Run / Other quick log
    if pending in ("Run", "Other"):
        context.user_data.pop("pending_log_activity", None)
        logs = context.user_data.setdefault("logs", [])
        logs.append({"activity": pending, "details": text, "ts": datetime.now().isoformat(timespec="seconds")})
        await update.message.reply_text(f"📌 Logged: {pending} — {text}\nType /log to add another, or /summary to see logs.")


# =========================
# Main
# =========================
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable not set")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("log", log_cmd))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("end", end_workout_cmd))

    app.add_handler(CallbackQueryHandler(on_log_choice, pattern=r"^log_(run|gym|other)$"))
    app.add_handler(CallbackQueryHandler(on_gym_bodypart_choice, pattern=r"^gym_body_"))
    app.add_handler(CallbackQueryHandler(on_gym_equipment_choice, pattern=r"^gym_eq_"))
    app.add_handler(CallbackQueryHandler(on_continue_end_choice, pattern=r"^gym_(continue|end)$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_details_message))

    logging.info("✅ Bot is running.")
    app.run_polling()


if __name__ == "__main__":
    main()
