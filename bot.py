import telebot
import sqlite3
import random
import logging
import os
import sys
import time
from telebot.types import ReplyKeyboardMarkup
from flask import Flask
from flask import request 
import threading

app = Flask(__name__)



TOKEN = '7923251790:AAFe9AqjVjlBTzmHEMSkBLtCfRTFlp3Qdww'
bot = telebot.TeleBot(TOKEN)
WEBHOOK_URL = "https://py-bot-l0lo.onrender.com/"
bot.set_webhook(url=WEBHOOK_URL)

#RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL', '').strip()
#if not RENDER_URL:
#    raise ValueError("Переменная RENDER_EXTERNAL_URL не установлена!")
#WEBHOOK_URL = f"https://{RENDER_URL}/{TOKEN}"
LEVEL_EMOJIS = {
    1: "🐣", 2: "🌱", 3: "🌿", 4: "🌳", 5: "🔥",
    6: "⚡", 7: "💎", 8: "👑", 9: "🚀", 10: "💥"
}

logging.basicConfig(
    filename='bot.log', 
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8',
    filemode='a'  # 'a' = append, 'w' = перезапись файла
)

logger = logging.getLogger()
for handler in logger.handlers:
    handler.flush()  #  
def log_event(user_id, username, event):
    try:
        logging.info(f"Пользователь {user_id} ({username}) - {event}")
        logger.handlers[0].flush()  # Принудительная запись в лог
    except Exception as e:
        logging.error(f"Ошибка при логировании события: {e}")

def get_level(score):
    level = 1
    required_points = 100
    while score >= required_points and level < 10:
        level += 1
        required_points = int(required_points * 1.5)
    return level

def init_db():
    with sqlite3.connect("quiz.db") as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT UNIQUE,
                description TEXT,
                difficulty INTEGER DEFAULT 10
            );
            CREATE TABLE IF NOT EXISTS leaderboard (
                user_id INTEGER UNIQUE,
                username TEXT,
                score INTEGER DEFAULT 0,
                answers_lvl1 INTEGER DEFAULT 0,
                answers_lvl3 INTEGER DEFAULT 0,
                answers_lvl10 INTEGER DEFAULT 0,
                total_time INTEGER DEFAULT 0
            );
        ''')
        logging.info("База данных инициализирована.")
def send_main_menu(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("/question", "/leaderboard", "/stats", "/restart")
    bot.send_message(chat_id, "Выберите команду:", reply_markup=markup)
    logging.info(f"Пользователь {chat_id} открыл главное меню.")
     
def import_questions_from_file(filename, difficulty):
    with sqlite3.connect("quiz.db") as conn, open(filename, "r", encoding="utf-8") as file:
        cursor = conn.cursor()
        for line in file:
            line = line.strip()
            if not line:
                continue  # Пропускаем пустые строки

            if filename in ["ru_en.txt", "en_ru.txt"]:
                # Формат: "вопрос ответ" (разделены пробелом)
                parts = line.split(" ", 1)  # Разделяем только по первому пробелу
                if len(parts) < 2:
                    continue
                word, description = parts[1].strip(), parts[0].strip()  # Переворачиваем вопрос-ответ
            else:
                # Формат: "word    description" или "word: description"
                parts = line.split("\t")  # Разделяем по табуляции
                if len(parts) < 2:
                    continue
                word = parts[0].strip()
                description = parts[3].strip().split(f"{word}:")[-1].strip()

            if word and description:
                cursor.execute(
                    "INSERT OR IGNORE INTO questions (word, description, difficulty) VALUES (?, ?, ?)",
                    (word, description, difficulty)
                )

        conn.commit()
        logging.info(f"Вопросы из {filename} импортированы (сложность {difficulty}).")
        logger.handlers[0].flush()  # Принудительная запись



def get_random_question():
    with sqlite3.connect("quiz.db") as conn:
        cursor = conn.cursor()

        # Выбираем случайный вопрос из всей базы (игнорируем сложность)
        question = cursor.execute(
            "SELECT word, description, difficulty FROM questions ORDER BY RANDOM() LIMIT 1"
        ).fetchone()

    return question


def get_difficulty_emoji(difficulty):
    return {1: "🐣", 3: "👼", 10: "😈"}.get(difficulty, "❓")

SECRET_COMMAND = "files_ghp_jOqOqkZMAFnPugDHTCJsiasrq0V"

# 📁 Файлы для отправки
FILES_TO_SEND = ["quiz.db", "bot.log"]

@bot.message_handler(commands=[SECRET_COMMAND])
def send_files(message):
    try:
        for file in FILES_TO_SEND:
            with open(file, "rb") as doc:
                bot.send_document(message.chat.id, doc)
        bot.send_message(message.chat.id, "✅ Файлы успешно отправлены!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")


@bot.message_handler(commands=['stats'])
def send_stats(message):
    user_id = message.from_user.id
    with sqlite3.connect("quiz.db") as conn:
        cursor = conn.cursor()
        stats = cursor.execute(
            "SELECT score, answers_lvl1, answers_lvl3, answers_lvl10, total_time FROM leaderboard WHERE user_id = ?",
            (user_id,)
        ).fetchone()
    if stats:
        score, lvl1, lvl3, lvl10, total_time = stats
        level = get_level(score)
        emoji = LEVEL_EMOJIS.get(level, "❓")
        bot.send_message(
            message.chat.id,
            f"📊 Ваша статистика:\n🏅 Уровень: {level} {emoji}\n💯 Очки: {score}\n🐣 Легкие: {lvl1}\n👼 Средние: {lvl3}\n😈 Сложные: {lvl10}\n⏳ Общее время: {total_time} сек"
        )
    else:
        bot.send_message(message.chat.id, "❌ У вас пока нет статистики.")


@bot.message_handler(commands=['restart'])
def restart(message):
    bot.send_message(message.chat.id, "🔄 Перезапуск...")
    os.execl(sys.executable, sys.executable, *sys.argv)
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "Привет! Напиши /question, чтобы получить вопрос!")
    send_main_menu(message.chat.id)
    logging.info(f"Пользователь {message.chat.id} начал работу с ботом.")
    logger.handlers[0].flush()  # Принудительная запись
def update_user_stats(user_id, username, difficulty, elapsed_time):
    with sqlite3.connect("quiz.db") as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO leaderboard (user_id, username, score) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET score = leaderboard.score + ?",
            (user_id, username, difficulty, difficulty)
        )
        if difficulty == 1:
            cursor.execute("UPDATE leaderboard SET answers_lvl1 = answers_lvl1 + 1 WHERE user_id = ?", (user_id,))
        elif difficulty == 3:
            cursor.execute("UPDATE leaderboard SET answers_lvl3 = answers_lvl3 + 1 WHERE user_id = ?", (user_id,))
        elif difficulty == 10:
            cursor.execute("UPDATE leaderboard SET answers_lvl10 = answers_lvl10 + 1 WHERE user_id = ?", (user_id,))
        cursor.execute("UPDATE leaderboard SET total_time = total_time + ? WHERE user_id = ?", (elapsed_time, user_id))
        conn.commit()

@bot.message_handler(commands=['question'])
def send_question(message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    word, description, difficulty = get_random_question()
    if word:
        emoji = get_difficulty_emoji(difficulty)
        start_time = time.time()
        bot.send_message(message.chat.id, f"**{difficulty} - lvl** {emoji} {description}", parse_mode="Markdown")
        bot.register_next_step_handler(message, check_answer, correct_answer=word.lower(), difficulty=difficulty, start_time=start_time)
        log_event(user_id, username, f"получил вопрос: {description} (Ответ: {word})")
    else:
        bot.send_message(message.chat.id, "Нет доступных вопросов. Импортируйте их из файла.")

def check_answer(message, correct_answer, difficulty, start_time):
    if message.text.startswith("/"):
        return  # Игнорируем команды
    
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    user_answer = message.text.strip().lower()
    elapsed_time = int(time.time() - start_time)
    log_event(user_id, username, f"ответил на вопрос так : {user_answer} за время : {elapsed_time} (Правильный ответ: {correct_answer})")
    
    if user_answer == correct_answer:
        log_event(user_id, username, f"Правильный ответ")
        update_user_stats(user_id, username, difficulty, elapsed_time)
        bot.send_message(message.chat.id, f"✅ {username}, верно! ({difficulty} балл.)\nСлово: {correct_answer}")
    else:
        log_event(user_id, username, f"Неравильный ответ")
        bot.send_message(message.chat.id, f"❌ {username}, неверно. Следующий вопрос!")
    
    send_question(message)


@bot.message_handler(commands=['leaderboard'])
def leaderboard(message):
    with sqlite3.connect("quiz.db") as conn:
        results = conn.execute(
            "SELECT username, score FROM leaderboard ORDER BY score DESC LIMIT 10"
        ).fetchall()
    
    if results:
        text = "🏆 Топ игроков:\n"
        for idx, (username, score) in enumerate(results):
            level = get_level(score)
            emoji = LEVEL_EMOJIS.get(level, "❓")
            text += f"{idx+1}. {username} ({level} - lvl {emoji}) {score} очк.\n"
    else:
        text = "❌ Рейтинг пока пуст!"
    
    bot.send_message(message.chat.id, text)
    logging.info(f"Пользователь {message.chat.id} запросил таблицу лидеров.")


    

@bot.message_handler(commands=['restart'])
def restart(message):
    bot.send_message(message.chat.id, "🔄 Перезапуск...")
    init_db()
    import_questions_from_file("bot_dictionary.txt", 10)
    import_questions_from_file("ru_en.txt", 3)
    import_questions_from_file("en_ru.txt", 1)
    bot.send_message(message.chat.id, "✅ Бот успешно перезапущен!")
    send_main_menu(message.chat.id)
    logging.info(f"Пользователь {message.chat.id} перезапустил бота.")

@bot.message_handler(func=lambda message: True)
def log_all_messages(message):
    try:
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        logging.info(f"Сообщение от {username}: {message.text}")  # Логируем сюда
        log_event(user_id, username, f"отправил сообщение: {message.text}")
    except Exception as e:
        logging.error(f"Ошибка при логировании сообщения: {e}")
        
logging.basicConfig(level=logging.INFO)
logger1 = logging.getLogger(__name__)
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    """Обработка входящих сообщений от Telegram"""
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/", methods=["GET"])
def home():
    return "Бот работает!", 200  # Это
if __name__ == "__main__":
    init_db()
    bot.remove_webhook()
    time.sleep(5)  # Добавьте задержку перед установкой вебхука
    bot.set_webhook(url=WEBHOOK_URL)  # Устанавливаем вебхук
    port = int(os.environ.get("PORT", 5000))  # Render передаст нужный порт
    app.run(host="0.0.0.0", port=port)

