import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import anthropic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ALLOWED_CHAT_ID = int(os.environ.get("ALLOWED_CHAT_ID", "247237959"))
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_DB_ID = os.environ.get("NOTION_DB_ID", "d4ca7d7f780f4ce7a51ee7e8cda134a5")

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

notion = None
if NOTION_TOKEN:
    from notion_client import Client as NotionClient
    notion = NotionClient(auth=NOTION_TOKEN)

conversation_history = []

SYSTEM_PROMPT = """Your name is Sun. You are Derrick's personal AI advisor — direct, sharp, never sycophantic.

Rules:
- Never start with agreement. First sentence must challenge, expose a gap, or ask a pointed question.
- Rate confidence: [Certain] = hard evidence, [Likely] = strong inference, [Guessing] = filling gaps.
- Never say: "great question", "absolutely", "definitely", "that makes sense", "you're right".
- Give uncomfortable truths first. Lead with what Derrick probably doesn't want to hear.
- Hold your position under pushback unless genuinely new information is given.
- Keep responses concise — this is Telegram, not an essay.

Context about Derrick:
- Singapore real estate strategist. Brand: Property Roadmap Strategist (4 pillars: Buy Right, Sell Right, Time Right, Finance Right).
- Uses KND frameworks for property analysis (7 Factors, D&S Matrix, Price Gap, Harmonisation, Price Matrix, Capital Appreciation, Density, NL vs Resale, SWAP).
- Running a 12-month marketing engagement with Growcast.
- Never mention commission or agent fees in any content."""


async def is_authorized(update: Update) -> bool:
    return update.effective_chat.id == ALLOWED_CHAT_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update):
        return
    await update.message.reply_text(
        "Thousand Sunny is ready.\n\nChat freely, or use:\n/todo add <task>\n/todo list\n/todo done <number>\n/todo delete <number>\n/clear — reset conversation"
    )


async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update):
        return
    global conversation_history
    conversation_history = []
    await update.message.reply_text("Conversation cleared.")


async def todo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage:\n/todo add <task>\n/todo list\n/todo done <number>\n/todo delete <number>"
        )
        return

    cmd = args[0].lower()

    if not notion:
        await update.message.reply_text("Notion not connected yet. Add NOTION_TOKEN to env vars.")
        return

    if cmd == "add":
        task = " ".join(args[1:])
        if not task:
            await update.message.reply_text("What's the task?")
            return
        notion.pages.create(
            parent={"database_id": NOTION_DB_ID},
            properties={
                "Task": {"title": [{"text": {"content": task}}]},
                "Status": {"select": {"name": "To Do"}},
            },
        )
        await update.message.reply_text(f"Added: {task}")

    elif cmd == "list":
        results = notion.databases.query(
            database_id=NOTION_DB_ID,
            filter={"property": "Status", "select": {"does_not_equal": "Done"}},
            sorts=[{"timestamp": "created_time", "direction": "ascending"}],
        )
        pages = results["results"]
        if not pages:
            await update.message.reply_text("No pending tasks.")
            return
        lines = []
        for i, page in enumerate(pages, 1):
            title = page["properties"]["Task"]["title"]
            task_text = title[0]["text"]["content"] if title else "Untitled"
            status_obj = page["properties"]["Status"]["select"]
            status = status_obj["name"] if status_obj else "To Do"
            lines.append(f"{i}. [{status}] {task_text}")
        await update.message.reply_text("\n".join(lines))

    elif cmd in ("done", "delete"):
        try:
            num = int(args[1]) - 1
        except (IndexError, ValueError):
            await update.message.reply_text(f"Usage: /todo {cmd} <number>")
            return
        results = notion.databases.query(
            database_id=NOTION_DB_ID,
            filter={"property": "Status", "select": {"does_not_equal": "Done"}},
            sorts=[{"timestamp": "created_time", "direction": "ascending"}],
        )
        pages = results["results"]
        if num < 0 or num >= len(pages):
            await update.message.reply_text("Invalid number. Use /todo list to see tasks.")
            return
        page = pages[num]
        notion.pages.update(page["id"], properties={"Status": {"select": {"name": "Done"}}})
        title = page["properties"]["Task"]["title"]
        task_text = title[0]["text"]["content"] if title else "Untitled"
        await update.message.reply_text(f"Done: {task_text}")

    else:
        await update.message.reply_text("Unknown command. Use add, list, done, or delete.")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update):
        return

    global conversation_history
    user_message = update.message.text
    conversation_history.append({"role": "user", "content": user_message})

    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]

    await context.bot.send_chat_action(update.effective_chat.id, "typing")

    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=conversation_history,
    )

    reply = response.content[0].text
    conversation_history.append({"role": "assistant", "content": reply})

    await update.message.reply_text(reply)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear_history))
    app.add_handler(CommandHandler("todo", todo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    logger.info("Thousand Sunny bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
