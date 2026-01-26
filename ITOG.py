import sqlite3
import datetime
from typing import List, Tuple
import logging
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = 'вартр'


class TaskDB:
    def __init__(self, db_path="tasks.db"):
        self.db_path = db_path
        self._create_table()

    def _create_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    is_done BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, title)
                )
            ''')
            conn.commit()
            logger.info("Таблица 'tasks' проверена/создана.")

    def add_task(self, user_id: int, title: str) -> bool:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    'INSERT INTO tasks (user_id, title) VALUES (?, ?)',
                    (user_id, title)
                )
                conn.commit()
            logger.info(f"Задача '{title}' добавлена для пользователя {user_id}.")
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"Попытка добавить дубликат задачи '{title}' для пользователя {user_id}.")
            return False
        except Exception as e:
            logger.error(f"Ошибка при добавлении задачи '{title}' для пользователя {user_id}: {e}")
            return False

    def mark_task_done(self, user_id: int, task_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                'UPDATE tasks SET is_done = TRUE WHERE user_id = ? AND id = ?',
                (user_id, task_id)
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Задача ID:{task_id} помечена как выполненная для пользователя {user_id}.")
            return cursor.rowcount > 0

    def get_stats(self, user_id: int) -> Tuple[int, int, float]:
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute(
                'SELECT COUNT(*) FROM tasks WHERE user_id = ?',
                (user_id,)
            ).fetchone()[0]

            done = conn.execute(
                'SELECT COUNT(*) FROM tasks WHERE user_id = ? AND is_done = TRUE',
                (user_id,)
            ).fetchone()[0]

        percent = (done / total) * 100 if total > 0 else 0
        return total, done, round(percent, 1)

    def get_all_tasks(self, user_id: int) -> List[Tuple[int, str, bool]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                'SELECT id, title, is_done FROM tasks WHERE user_id = ? ORDER BY created_at',
                (user_id,)
            )
            return cursor.fetchall()

    def delete_task(self, user_id: int, task_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                'DELETE FROM tasks WHERE user_id = ? AND id = ?',
                (user_id, task_id)
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Задача ID:{task_id} удалена для пользователя {user_id}.")
            return cursor.rowcount > 0

    def clear_all_tasks(self, user_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                'DELETE FROM tasks WHERE user_id = ?',
                (user_id,)
            )
            conn.commit()

            logger.info(f"Все задачи очищены для пользователя {user_id}.")

db = TaskDB()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["📝 Список дел", "📊 Статистика"],
        ["🗑️ Очистить все дела"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "Добро пожаловать в бот для учёта выполненных дел! "
        "Напишите текст, чтобы добавить новое дело. "
        "Или выберите действие из меню:",
        reply_markup=reply_markup
    )


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "📝 Список дел":
        tasks = db.get_all_tasks(user_id)
        if not tasks:
            await update.message.reply_text("Ваш список дел пуст! Добавьте что-нибудь.")
            return

        message_text = "Ваши текущие дела:\n"
        inline_keyboard = []
        for task_id, title, is_done in tasks:
            status = "✅" if is_done else "⬜"
            message_text += f"{status} {title}\n"

            task_buttons = []
            if not is_done: 
                task_buttons.append(InlineKeyboardButton("✅ Выполнить", callback_data=f"done_task:{task_id}"))
            task_buttons.append(InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_task:{task_id}"))
            inline_keyboard.append(task_buttons)


        reply_markup = InlineKeyboardMarkup(inline_keyboard)
        await update.message.reply_text(message_text, reply_markup=reply_markup)

    elif text == "📊 Статистика":
        total, done, percent = db.get_stats(user_id)
        if total == 0:
            await update.message.reply_text("У вас пока нет дел для статистики.")
        else:
            await update.message.reply_text(
                f"Ваша статистика:\n"
                f"Всего дел: {total}\n"
                f"Выполнено: {done}\n"
                f"Процент выполнения: {percent}%"
            )

    elif text == "🗑️ Очистить все дела":
        inline_keyboard = [
            [InlineKeyboardButton("✅ Да, очистить", callback_data="confirm_clear_all")],
            [InlineKeyboardButton("❌ Нет, отмена", callback_data="cancel_clear_all")]
        ]
        reply_markup = InlineKeyboardMarkup(inline_keyboard)
        await update.message.reply_text(
            "Вы уверены, что хотите удалить ВСЕ свои дела? Это действие необратимо.",
            reply_markup=reply_markup
        )
    else:
        await add_new_task(update, context)


async def add_new_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    task_title = update.message.text.strip()

    if not task_title:
        await update.message.reply_text("Дело не может быть пустым.")
        return

    if db.add_task(user_id, task_title):
        await update.message.reply_text(f"Дело '{task_title}' добавлено!")
    else:
        await update.message.reply_text(f"Дело '{task_title}' уже есть в вашем списке.")


async def handle_inline_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    if data.startswith("done_task:"):
        task_id = int(data.split(":")[1])
        if db.mark_task_done(user_id, task_id):
            await query.edit_message_text("Дело отмечено как выполненное!")

            await handle_buttons(update, context)
        else:
            await query.edit_message_text(
                "Не удалось отметить дело как выполненное. Возможно, оно уже выполнено или удалено.")

    elif data.startswith("delete_task:"):
        task_id = int(data.split(":")[1])
        if db.delete_task(user_id, task_id):
            await query.edit_message_text("Дело удалено.")
            await handle_buttons(update, context)
        else:
            await query.edit_message_text("Не удалось удалить дело. Возможно, оно уже удалено.")

    elif data == "confirm_clear_all":
        db.clear_all_tasks(user_id)
        await query.edit_message_text("Все ваши дела были удалены!")
        await start(update, context)

    elif data == "cancel_clear_all":
        await query.edit_message_text("Очистка дел отменена.")


def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex("^(📝 Список дел|📊 Статистика|🗑️ Очистить все дела)$"),
        handle_buttons))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_new_task))
    application.add_handler(CallbackQueryHandler(handle_inline_buttons))

    application.run_polling()


if __name__ == '__main__':
    main()
