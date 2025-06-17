import os
import logging
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ContextTypes,
)
import asyncio

# Load environment variables
load_dotenv()
BOT_TOKEN = os.environ.get('BOT_TOKEN')
SUPPORT_GROUP_ID = int(os.environ.get('SUPPORT_GROUP_ID'))

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)

user_sessions = {}      # user_id: {state, other info}
pending_claims = {}     # user_id: {info}
active_chats = {}       # user_id: agent_id, agent_id: user_id

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_sessions[user.id] = {"state": "welcome", "userName": user.first_name}
    keyboard = [
        [InlineKeyboardButton("📋 Yes, send screenshot", callback_data="send_screenshot")],
        [InlineKeyboardButton("❓ No, I need human help", callback_data="human_help")],
    ]
    await update.message.reply_text(
        f"Hello {user.first_name}!\n\nWould you like to send a trade screenshot for Loss Coverage?\n\nChoose an option below:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    data = query.data

    if data == "send_screenshot":
        user_sessions[user.id]["state"] = "waiting_screenshot"
        await query.edit_message_text(
            "Please send your trade screenshot now.\n\nI will save it and notify an agent to review your case within 4 hours."
        )
    elif data == "human_help":
        user_sessions[user.id]["state"] = "waiting_description"
        await query.edit_message_text(
            "You will be transferred to an agent within 4 hours.\n\nPlease describe your issue below:"
        )
    elif data.startswith("claim_"):
        target_user_id = int(data.split("_")[1])
        agent_id = user.id
        if target_user_id in active_chats:
            await query.answer("Already claimed.", show_alert=True)
            return
        active_chats[target_user_id] = agent_id
        active_chats[agent_id] = target_user_id
        pending_claims.pop(target_user_id, None)
        await query.edit_message_reply_markup(None)
        await context.bot.send_message(
            agent_id,
            f"You have claimed the request. You can now chat with the user (ID: {target_user_id})."
        )
        try:
            await context.bot.send_message(
                target_user_id,
                f"Agent {user.first_name} has joined the chat! You can now chat directly."
            )
        except Exception:
            pass

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = user_sessions.get(user.id)
    if not session or session.get("state") != "waiting_screenshot":
        await update.message.reply_text("Please use /start first.")
        return
    user_sessions[user.id]["state"] = "screenshot_received"
    pending_claims[user.id] = {
        "userName": user.first_name,
        "type": "screenshot"
    }
    keyboard = [[InlineKeyboardButton("🔥 CLAIM", callback_data=f"claim_{user.id}")]]
    await update.message.reply_text("Screenshot received! An agent will contact you within 4 hours.")
    await context.bot.send_message(
        SUPPORT_GROUP_ID,
        f"NEW SCREENSHOT CLAIM\nUser: {user.first_name} (ID: {user.id})",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    if user.id in active_chats:
        partner_id = active_chats[user.id]
        await context.bot.send_message(partner_id, f"{user.first_name}: {text}")
        return
    session = user_sessions.get(user.id)
    if session and session.get("state") == "waiting_description":
        user_sessions[user.id]["state"] = "description_received"
        pending_claims[user.id] = {
            "userName": user.first_name,
            "type": "human_help",
            "description": text
        }
        keyboard = [[InlineKeyboardButton("🔥 CLAIM", callback_data=f"claim_{user.id}")]]
        await update.message.reply_text("Agent notified! An agent will contact you within 4 hours.")
        await context.bot.send_message(
            SUPPORT_GROUP_ID,
            f"NEW HUMAN HELP REQUEST\nUser: {user.first_name} (ID: {user.id})\nIssue: {text}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    await update.message.reply_text("Please use /start to begin support.")

async def send_reminders(app):
    while True:
        await asyncio.sleep(3600)  # every hour
        for user_id in list(pending_claims.keys()):
            try:
                await app.bot.send_message(
                    user_id,
                    "Our agents are currently busy, but someone will respond to you shortly! Thank you for your patience."
                )
            except Exception:
                pass

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.job_queue.run_once(lambda *_: asyncio.create_task(send_reminders(app)), 0)
    logging.info("Bot running...")
    app.run_polling()

if __name__ == '__main__':
    main()