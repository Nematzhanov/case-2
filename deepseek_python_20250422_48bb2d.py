import logging
import sqlite3
import os
import pandas as pd
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import datetime # Для получения текущей даты в названии файла

# --- Логирование, Константы, БД, Клавиатуры (БЕЗ ИЗМЕНЕНИЙ) ---
# ... (весь код до функции start без изменений) ...
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)
TELEGRAM_BOT_TOKEN = "7580331808:AAHxGMkM7ypuJAqmzwt-J1u-_XqX_R5Oepw"  # <<<=== ЗАМЕНИ НА СВОЙ ТОКЕН!
DB_NAME = "schedule_bot_v2.db"
FACULTIES = ["ИЭИС", "ИЦЭУС", "ПИ", "ИБХИ", "ИГУМ", "ИМО", "ИЮР", "ИПТ", "ПТИ"]
COURSES = ["1", "2", "3", "4", "5", "6"]
DAYS_OF_WEEK = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]
TIME_SLOTS = [f"с {h}:00 до {h+1}:00" for h in range(6, 21)]
(SELECT_FACULTY, SELECT_COURSE, SELECT_GROUP, ADD_GROUP_PROMPT,
 SELECT_DAY, SELECT_TIME, ENTER_SUBJECT, POST_SAVE_OPTIONS, EXPORT_ASK_DAY) = range(9)
(CALLBACK_FACULTY, CALLBACK_COURSE, CALLBACK_GROUP, CALLBACK_DAY, CALLBACK_TIME, CALLBACK_SUBJECT) = ("FACULTY", "COURSE", "GROUP", "DAY", "TIME", "SUBJECT")

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faculty TEXT NOT NULL,
            course INTEGER NOT NULL,
            group_name TEXT NOT NULL,
            UNIQUE(faculty, course, group_name)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schedule_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faculty TEXT NOT NULL,
            course INTEGER NOT NULL,
            group_name TEXT NOT NULL,
            day_of_week TEXT NOT NULL,
            time_slot TEXT NOT NULL,
            subject TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    logger.info(f"База данных {DB_NAME} инициализирована.")

def add_group_db(faculty: str, course: int, group_name: str) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO groups (faculty, course, group_name) VALUES (?, ?, ?)",
            (faculty, course, group_name)
        )
        conn.commit()
        logger.info(f"Добавлена группа: {faculty}, Курс {course}, {group_name}")
        return True
    except sqlite3.IntegrityError:
        logger.warning(f"Попытка добавить существующую группу: {faculty}, Курс {course}, {group_name}")
        return False
    finally:
        conn.close()

def get_groups_db(faculty: str, course: int) -> list:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT group_name FROM groups WHERE faculty = ? AND course = ? ORDER BY group_name",
        (faculty, course)
    )
    groups = [row[0] for row in cursor.fetchall()]
    conn.close()
    return groups

def save_schedule_entry_db(faculty: str, course: int, group_name: str, day: str, time_slot: str, subject: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO schedule_entries (faculty, course, group_name, day_of_week, time_slot, subject) VALUES (?, ?, ?, ?, ?, ?)",
            (faculty, course, group_name, day, time_slot, subject)
        )
        conn.commit()
        logger.info(f"Сохранена запись: {faculty}, К{course}, {group_name}, {day}, {time_slot}, {subject}")
    except Exception as e:
        logger.error(f"Ошибка сохранения записи в БД: {e}")
    finally:
        conn.close()

def get_schedule_data_db(day_filter: str = None) -> list:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    query = "SELECT faculty, course, group_name, day_of_week, time_slot, subject FROM schedule_entries"
    params = []
    if day_filter:
        query += " WHERE day_of_week = ?"
        params.append(day_filter)
    query += " ORDER BY faculty, course, group_name, day_of_week, time_slot"
    cursor.execute(query, params)
    data = cursor.fetchall()
    conn.close()
    return data

def create_reply_keyboard(buttons: list, columns: int, one_time: bool = True, add_back: bool = False, add_add_group: bool = False, custom_buttons: list = None) -> ReplyKeyboardMarkup:
    keyboard = []
    row = []
    for i, button_text in enumerate(buttons):
        row.append(button_text)
        if (i + 1) % columns == 0 or i == len(buttons) - 1:
            keyboard.append(row)
            row = []
    if add_add_group:
         keyboard.append(["➕ Добавить группу"])
    if custom_buttons:
        for btn_row in custom_buttons:
             keyboard.append(btn_row)
    if add_back:
        keyboard.append(["⬅️ Назад"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=one_time)

def create_inline_keyboard(buttons: list, columns: int) -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for i, button_text in enumerate(buttons):
        row.append(InlineKeyboardButton(button_text, callback_data=button_text))
        if (i + 1) % columns == 0 or i == len(buttons) - 1:
            keyboard.append(row)
            row = []
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    context.user_data.clear()
    logger.info(f"Пользователь {user.username} ({user.id}) запустил бота.")
    reply_markup = create_reply_keyboard(FACULTIES, columns=3)
    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n"
        "Я помогу тебе внести данные для расписания.\n\n"
        "Выберите институт/факультет:",
        reply_markup=reply_markup,
    )
    return SELECT_FACULTY

async def select_faculty(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    faculty = update.message.text
    # ---> ИЗМЕНЕНИЕ ЗДЕСЬ: Проверка внутри функции <---
    if faculty not in FACULTIES:
        await update.message.reply_text("Пожалуйста, выберите факультет из предложенных кнопок.")
        return SELECT_FACULTY

    context.user_data[CALLBACK_FACULTY] = faculty
    logger.info(f"Пользователь {update.effective_user.id} выбрал факультет: {faculty}")
    reply_markup = create_reply_keyboard(COURSES, columns=3, add_back=True)
    await update.message.reply_text("Отлично! Теперь выберите курс:", reply_markup=reply_markup)
    return SELECT_COURSE

async def select_course(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    course_text = update.message.text
    # ---> ИЗМЕНЕНИЕ ЗДЕСЬ: Проверка внутри функции <---
    if course_text not in COURSES:
         await update.message.reply_text("Пожалуйста, выберите курс из предложенных кнопок.")
         return SELECT_COURSE

    course = int(course_text)
    context.user_data[CALLBACK_COURSE] = course
    faculty = context.user_data[CALLBACK_FACULTY]
    logger.info(f"Пользователь {update.effective_user.id} выбрал курс: {course} для факультета {faculty}")
    await send_group_selection(update, context)
    return SELECT_GROUP

async def send_group_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, message_id_to_edit: int = None):
    faculty = context.user_data[CALLBACK_FACULTY]
    course = context.user_data[CALLBACK_COURSE]
    groups = get_groups_db(faculty, course)
    reply_markup_main = create_reply_keyboard([], columns=1, add_back=True, add_add_group=True)
    if groups:
        inline_markup = create_inline_keyboard(groups, columns=3)
        message_text = f"Выберите группу для {faculty}, курс {course}:"
        if message_id_to_edit:
             try:
                  await context.bot.edit_message_text(
                       chat_id=update.effective_chat.id,
                       message_id=message_id_to_edit,
                       text=message_text,
                       reply_markup=inline_markup
                  )
                  await update.message.reply_text("(Или добавьте новую / вернитесь назад)", reply_markup=reply_markup_main)
             except Exception as e:
                  logger.error(f"Не удалось отредактировать сообщение выбора группы: {e}. Отправляю новое.")
                  await update.message.reply_text(message_text, reply_markup=inline_markup)
                  await update.message.reply_text("(Или добавьте новую / вернитесь назад)", reply_markup=reply_markup_main)
        else:
             await update.message.reply_text(message_text, reply_markup=inline_markup)
             await update.message.reply_text("(Или добавьте новую / вернитесь назад)", reply_markup=reply_markup_main)
    else:
        message_text = f"Для {faculty}, курс {course} пока нет добавленных групп."
        await update.message.reply_text(message_text, reply_markup=reply_markup_main)

async def select_group_inline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    group_name = query.data
    context.user_data[CALLBACK_GROUP] = group_name
    faculty = context.user_data[CALLBACK_FACULTY]
    course = context.user_data[CALLBACK_COURSE]
    logger.info(f"Пользователь {query.from_user.id} выбрал группу: {group_name} ({faculty}, {course})")
    await query.delete_message()
    reply_markup = create_reply_keyboard(DAYS_OF_WEEK, columns=2, add_back=True)
    await query.message.reply_text(
        f"Группа: {group_name}. Выберите день недели:",
        reply_markup=reply_markup
    )
    return SELECT_DAY

async def prompt_add_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info(f"Пользователь {update.effective_user.id} нажал 'Добавить группу'.")
    # Ищем ID сообщения с inline кнопками (обычно оно перед текущим)
    # Это может быть не надежно, если между ними были другие сообщения
    try:
        context.user_data['group_select_message_id'] = update.message.message_id - 1
    except:
        context.user_data['group_select_message_id'] = None # На случай если что-то пошло не так
    await update.message.reply_text("Введите название новой группы:", reply_markup=ReplyKeyboardMarkup([["⬅️ Отмена добавления"]], resize_keyboard=True))
    return ADD_GROUP_PROMPT

async def add_group_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_group_name = update.message.text.strip()
    user = update.effective_user
    if not new_group_name or len(new_group_name) > 50:
        await update.message.reply_text("Название группы не может быть пустым или слишком длинным. Попробуйте еще раз или нажмите 'Отмена добавления'.")
        return ADD_GROUP_PROMPT
    faculty = context.user_data[CALLBACK_FACULTY]
    course = context.user_data[CALLBACK_COURSE]
    if add_group_db(faculty, course, new_group_name):
        logger.info(f"Пользователь {user.id} успешно добавил группу: {new_group_name}")
        await update.message.reply_text(f"Группа '{new_group_name}' успешно добавлена!", reply_markup=ReplyKeyboardRemove())
    else:
        logger.warning(f"Пользователь {user.id} пытался добавить существующую группу: {new_group_name}")
        await update.message.reply_text(f"Группа '{new_group_name}' уже существует для этого курса и факультета.", reply_markup=ReplyKeyboardRemove())
    message_id_to_update = context.user_data.pop('group_select_message_id', None)
    await send_group_selection(update, context, message_id_to_edit=message_id_to_update)
    return SELECT_GROUP

async def cancel_add_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info(f"Пользователь {update.effective_user.id} отменил добавление группы.")
    await update.message.reply_text("Добавление группы отменено.", reply_markup=ReplyKeyboardRemove())
    message_id_to_update = context.user_data.pop('group_select_message_id', None)
    await send_group_selection(update, context, message_id_to_edit=message_id_to_update)
    return SELECT_GROUP

async def select_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    day = update.message.text
     # ---> ИЗМЕНЕНИЕ ЗДЕСЬ: Проверка внутри функции <---
    if day not in DAYS_OF_WEEK:
         await update.message.reply_text("Пожалуйста, выберите день недели из предложенных кнопок.")
         return SELECT_DAY

    context.user_data[CALLBACK_DAY] = day
    group_name = context.user_data[CALLBACK_GROUP]
    logger.info(f"Пользователь {update.effective_user.id} выбрал день: {day} для группы {group_name}")
    reply_markup = create_reply_keyboard(TIME_SLOTS, columns=2, add_back=True)
    await update.message.reply_text(f"День: {day}. Выберите время занятия:", reply_markup=reply_markup)
    return SELECT_TIME

async def select_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    time_slot = update.message.text
     # ---> ИЗМЕНЕНИЕ ЗДЕСЬ: Проверка внутри функции <---
    if time_slot not in TIME_SLOTS:
        await update.message.reply_text("Пожалуйста, выберите время из предложенных кнопок.")
        return SELECT_TIME

    context.user_data[CALLBACK_TIME] = time_slot
    day = context.user_data[CALLBACK_DAY]
    logger.info(f"Пользователь {update.effective_user.id} выбрал время: {time_slot} ({day})")
    reply_markup = ReplyKeyboardMarkup([["⬅️ Назад"]], resize_keyboard=True)
    await update.message.reply_text(f"Время: {time_slot}. Введите название предмета:", reply_markup=reply_markup)
    return ENTER_SUBJECT

async def save_subject_and_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    subject = update.message.text.strip()
    user = update.effective_user
    if subject == "⬅️ Назад":
         logger.warning("Получена команда 'Назад' в обработчике предмета, хотя ожидался текст.")
         return await back_handler(update, context) # На всякий случай вызываем back_handler
    if not subject or len(subject) > 100:
         await update.message.reply_text("Название предмета не может быть пустым или слишком длинным. Попробуйте еще раз или нажмите 'Назад'.")
         return ENTER_SUBJECT
    context.user_data[CALLBACK_SUBJECT] = subject
    logger.info(f"Пользователь {user.id} ввел предмет: {subject}")
    faculty = context.user_data[CALLBACK_FACULTY]
    course = context.user_data[CALLBACK_COURSE]
    group_name = context.user_data[CALLBACK_GROUP]
    day = context.user_data[CALLBACK_DAY]
    time_slot = context.user_data[CALLBACK_TIME]
    save_schedule_entry_db(faculty, course, group_name, day, time_slot, subject)
    all_data_for_day = get_schedule_data_db(day_filter=day)
    group_day_entries = [entry for entry in all_data_for_day if entry[0] == faculty and entry[1] == course and entry[2] == group_name]
    hours_count = len(group_day_entries)
    warning_message = ""
    if hours_count > 6:
         warning_message = f"\n\n⚠️ *Внимание!* Для группы {group_name} в {day} уже {hours_count} записей. Проверьте соблюдение правила непрерывной учебы (>6 часов)."
    confirmation_text = (
        f"✅ Сохранено:\n"
        f"Институт/Факультет: {faculty}\n"
        f"Курс: {course}\n"
        f"Группа: {group_name}\n"
        f"День: {day}\n"
        f"Время: {time_slot}\n"
        f"Предмет: {subject}"
        f"{warning_message}"
    )
    final_options_keyboard = [
        ["➕ Добавить еще запись"], [" EЯ Выбрать другую группу"],
        ["📊 Вывести расписание дня"], ["✅ Завершить"] ]
    reply_markup = ReplyKeyboardMarkup(final_options_keyboard, resize_keyboard=True, one_time_keyboard=False)
    await update.message.reply_text(confirmation_text, reply_markup=reply_markup, parse_mode='Markdown')
    return POST_SAVE_OPTIONS

async def add_another_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    group_name = context.user_data.get(CALLBACK_GROUP, "текущая группа")
    logger.info(f"Пользователь {update.effective_user.id} решил добавить еще запись для группы {group_name}.")
    context.user_data.pop(CALLBACK_DAY, None)
    context.user_data.pop(CALLBACK_TIME, None)
    context.user_data.pop(CALLBACK_SUBJECT, None)
    reply_markup = create_reply_keyboard(DAYS_OF_WEEK, columns=2, add_back=True)
    await update.message.reply_text(
        f"Добавляем еще запись для группы {group_name}.\nВыберите день недели:",
        reply_markup=reply_markup
    )
    return SELECT_DAY

async def go_to_group_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info(f"Пользователь {update.effective_user.id} решил выбрать другую группу.")
    context.user_data.pop(CALLBACK_GROUP, None)
    context.user_data.pop(CALLBACK_DAY, None)
    context.user_data.pop(CALLBACK_TIME, None)
    context.user_data.pop(CALLBACK_SUBJECT, None)
    await send_group_selection(update, context)
    return SELECT_GROUP

async def prompt_export_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info(f"Пользователь {update.effective_user.id} запросил экспорт за день.")
    reply_markup = create_reply_keyboard(DAYS_OF_WEEK, columns=2, add_back=True) # Назад вернет к POST_SAVE_OPTIONS
    await update.message.reply_text("Выберите день недели для экспорта расписания:", reply_markup=reply_markup)
    return EXPORT_ASK_DAY

async def export_day_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    day_to_export = update.message.text
    user = update.effective_user
     # ---> ИЗМЕНЕНИЕ ЗДЕСЬ: Проверка внутри функции <---
    if day_to_export not in DAYS_OF_WEEK:
        await update.message.reply_text("Пожалуйста, выберите день из кнопок.")
        return EXPORT_ASK_DAY

    logger.info(f"Пользователь {user.id} экспортирует расписание за {day_to_export}.")
    schedule_data = get_schedule_data_db(day_filter=day_to_export)
    if not schedule_data:
        await update.message.reply_text(f"Нет записей расписания для '{day_to_export}'.")
        final_options_keyboard = [
            ["➕ Добавить еще запись"], [" EЯ Выбрать другую группу"],
            ["📊 Вывести расписание дня"], ["✅ Завершить"] ]
        reply_markup = ReplyKeyboardMarkup(final_options_keyboard, resize_keyboard=True, one_time_keyboard=False)
        await update.message.reply_text("Что делаем дальше?", reply_markup=reply_markup)
        return POST_SAVE_OPTIONS
    try:
        df = pd.DataFrame(schedule_data, columns=['Факультет', 'Курс', 'Группа', 'День', 'Время', 'Предмет'])
        df_sorted = df.sort_values(by=['Группа', 'Время']) # Сортировка по группе и времени
        current_date = datetime.datetime.now().strftime("%Y-%m-%d")
        excel_filename = f"schedule_{day_to_export}_{user.id}_{current_date}.xlsx"
        df_sorted.to_excel(excel_filename, index=False, engine='openpyxl') # Указали движок явно
        logger.info(f"Excel файл {excel_filename} создан.")
        await update.message.reply_document(
            document=open(excel_filename, 'rb'),
            filename=f"Расписание_{day_to_export}.xlsx",
            caption=f"Вот расписание для '{day_to_export}' в формате Excel."
        )
        os.remove(excel_filename)
        logger.info(f"Excel файл {excel_filename} удален.")
    except Exception as e:
        logger.error(f"Ошибка при создании или отправке Excel файла для дня {day_to_export}: {e}")
        await update.message.reply_text("Произошла ошибка при создании Excel файла. Попробуйте позже.")
    final_options_keyboard = [
        ["➕ Добавить еще запись"], [" EЯ Выбрать другую группу"],
        ["📊 Вывести расписание дня"], ["✅ Завершить"] ]
    reply_markup = ReplyKeyboardMarkup(final_options_keyboard, resize_keyboard=True, one_time_keyboard=False)
    await update.message.reply_text("Что делаем дальше?", reply_markup=reply_markup)
    return POST_SAVE_OPTIONS

async def back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    logger.info(f"Пользователь {user.id} нажал Назад.")
    current_data = context.user_data
    if CALLBACK_SUBJECT in current_data:
        del current_data[CALLBACK_SUBJECT]
        logger.debug("Возврат к выбору времени")
        reply_markup = create_reply_keyboard(TIME_SLOTS, columns=2, add_back=True)
        await update.message.reply_text(f"День: {current_data.get(CALLBACK_DAY, '?')}. Выберите время занятия:", reply_markup=reply_markup)
        return SELECT_TIME
    elif CALLBACK_TIME in current_data:
        del current_data[CALLBACK_TIME]
        logger.debug("Возврат к выбору дня")
        reply_markup = create_reply_keyboard(DAYS_OF_WEEK, columns=2, add_back=True)
        await update.message.reply_text(f"Группа: {current_data.get(CALLBACK_GROUP, '?')}. Выберите день недели:", reply_markup=reply_markup)
        return SELECT_DAY
    elif CALLBACK_DAY in current_data:
        del current_data[CALLBACK_DAY]
        logger.debug("Возврат к выбору группы")
        await send_group_selection(update, context)
        return SELECT_GROUP
    elif CALLBACK_GROUP in current_data:
        del current_data[CALLBACK_GROUP]
        current_data.pop(CALLBACK_DAY, None)
        current_data.pop(CALLBACK_TIME, None)
        current_data.pop(CALLBACK_SUBJECT, None)
        logger.debug("Возврат к выбору курса")
        reply_markup = create_reply_keyboard(COURSES, columns=3, add_back=True)
        await update.message.reply_text("Выберите курс:", reply_markup=reply_markup)
        return SELECT_COURSE
    elif CALLBACK_COURSE in current_data:
        del current_data[CALLBACK_COURSE]
        logger.debug("Возврат к выбору факультета")
        reply_markup = create_reply_keyboard(FACULTIES, columns=3)
        await update.message.reply_text("Выберите институт/факультет:", reply_markup=reply_markup)
        return SELECT_FACULTY
    elif CALLBACK_FACULTY in current_data:
        del current_data[CALLBACK_FACULTY]
        logger.debug("Возврат в начало")
        return await start(update, context)
    else:
        logger.debug("Некуда возвращаться, переход в начало")
        return await start(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    logger.info(f"Пользователь {user.id} отменил диалог командой /cancel.")
    context.user_data.clear()
    await update.message.reply_text(
        "Действие отменено. Чтобы начать заново, введите /start.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    logger.info(f"Пользователь {user.id} завершил ввод расписания.")
    context.user_data.clear()
    await update.message.reply_text(
        "Отлично! Ввод данных завершен.\nЧтобы начать заново, введите /start.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# --- Основная функция ---

def main() -> None:
    """Запускает бота."""
    init_db()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_FACULTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_faculty)], # Проверка факультета внутри
            SELECT_COURSE: [
                MessageHandler(filters.Regex("^⬅️ Назад$"), back_handler),
                # ---> ИЗМЕНЕНИЕ ЗДЕСЬ: Убран filters.In <---
                MessageHandler(filters.TEXT & ~filters.COMMAND, select_course), # Проверка курса внутри
            ],
            SELECT_GROUP: [
                MessageHandler(filters.Regex("^⬅️ Назад$"), back_handler),
                MessageHandler(filters.Regex("^➕ Добавить группу$"), prompt_add_group),
                CallbackQueryHandler(select_group_inline),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lambda update, context: update.message.reply_text("Используйте кнопки для выбора или добавления группы.")),
            ],
            ADD_GROUP_PROMPT: [
                MessageHandler(filters.Regex("^⬅️ Отмена добавления$"), cancel_add_group),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_group_handler),
            ],
            SELECT_DAY: [
                 MessageHandler(filters.Regex("^⬅️ Назад$"), back_handler),
                 # ---> ИЗМЕНЕНИЕ ЗДЕСЬ: Убран filters.In <---
                 MessageHandler(filters.TEXT & ~filters.COMMAND, select_day), # Проверка дня внутри
            ],
            SELECT_TIME: [
                 MessageHandler(filters.Regex("^⬅️ Назад$"), back_handler),
                 # ---> ИЗМЕНЕНИЕ ЗДЕСЬ: Убран filters.In <---
                 MessageHandler(filters.TEXT & ~filters.COMMAND, select_time), # Проверка времени внутри
            ],
            ENTER_SUBJECT: [
                MessageHandler(filters.Regex("^⬅️ Назад$"), back_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_subject_and_entry), # Проверка предмета внутри
            ],
            POST_SAVE_OPTIONS: [
                MessageHandler(filters.Regex("^➕ Добавить еще запись$"), add_another_entry),
                MessageHandler(filters.Regex("^ EЯ Выбрать другую группу$"), go_to_group_selection),
                MessageHandler(filters.Regex("^📊 Вывести расписание дня$"), prompt_export_day),
                MessageHandler(filters.Regex("^✅ Завершить$"), done),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lambda update, context: update.message.reply_text("Используйте предложенные кнопки.")),
            ],
             EXPORT_ASK_DAY: [
                  MessageHandler(filters.Regex("^⬅️ Назад$"), lambda update, context: POST_SAVE_OPTIONS), # Назад -> к опциям
                  # ---> ИЗМЕНЕНИЕ ЗДЕСЬ: Убран filters.In <---
                  MessageHandler(filters.TEXT & ~filters.COMMAND, export_day_schedule), # Проверка дня внутри
             ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))

    logger.info("Запуск бота (v3)...")
    application.run_polling()
    logger.info("Бот остановлен.")

if __name__ == "__main__":
    main()