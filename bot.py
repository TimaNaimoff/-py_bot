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
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL', '').strip()
if not RENDER_URL:
    raise ValueError("Переменная RENDER_EXTERNAL_URL не установлена!")

WEBHOOK_URL = f"{RENDER_URL}/{TOKEN}"


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
                word TEXT ,
                description TEXT ,
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
    markup.add("Получить вопрос", "Рейтинги", "Статистика", "Обновить")
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



@bot.message_handler(commands=['start'])
def start(message):
    welcome_text = (
        "Привет, человек! 🤖✨\n\n"
        "Я — твой помощник в изучении слов и развитии знаний! 📚💡\n"
        "Вот что надо знать , чтобы мы сработались:\n\n"
        "🔹 /question — получить случайный вопрос. Проверь свои знания!\n"
        "🔹 /stats — посмотреть свою статистику и уровень.\n"
        "🔹 /global_rating — увидеть топ игроков! 🏆\n"
        "🔹 /clean — очистить чат и перезапустить бота.\n\n"
        "🎯 Отвечай на вопросы, зарабатывай очки и прокачивай уровень! 🏅\n"
        "Напиши /question, чтобы начать! 🚀\n"
    )
    bot.send_message(message.chat.id, welcome_text)
    send_main_menu(message.chat.id)
    logging.info(f"Пользователь {message.chat.id} начал работу с ботом.")
    logger.handlers[0].flush()  # Принудительная запись в ло
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


user_sessions = {}  # Храним текущие вопросы для каждого чата

@bot.message_handler(commands=['question'])
def send_question(message):
    chat_id = message.chat.id  # Теперь учитываем и групповые чаты
    username = message.from_user.username or message.from_user.first_name
    question_data = get_random_question()
    
    if question_data:
        word, description, difficulty = question_data
        emoji = get_difficulty_emoji(difficulty)
        start_time = time.time()
        
        user_sessions[chat_id] = {
            "correct_answer": word.lower(),
            "difficulty": difficulty,
            "start_time": start_time
        }
        
        bot.send_message(chat_id, f"**{difficulty} - lvl** {emoji} {description}", parse_mode="Markdown")
        log_event(chat_id, username, f"получил вопрос: {description} (Ответ: {word})")
    else:
        bot.send_message(chat_id, "Нет доступных вопросов. Импортируйте их из файла.")


@bot.message_handler(func=lambda message: message.chat.id in user_sessions and not is_button(message.text))
def check_answer(message):
    chat_id = message.chat.id
    username = message.from_user.username or message.from_user.first_name
    session = user_sessions.get(chat_id)

    if not session:
        return
    
    correct_answer = session["correct_answer"]
    difficulty = session["difficulty"]
    elapsed_time = int(time.time() - session["start_time"])
    user_answer = message.text.strip().lower()

    log_event(chat_id, username, f"ответил на вопрос: {user_answer} за {elapsed_time} сек (Правильный: {correct_answer})")
    
    if user_answer == correct_answer:
        update_user_stats(message.from_user.id, username, difficulty, elapsed_time)
        bot.send_message(chat_id, f"✅ {username}, верно! ({difficulty} балл.)\nСлово: {correct_answer}")
        del user_sessions[chat_id]  # Удаляем сессию после правильного ответа
    else:
        bot.send_message(chat_id, f"❌ {username}, неверно. Попробуйте ещё раз!")




@bot.message_handler(commands=['global_rating'])
def leaderboard(message):
    with sqlite3.connect("quiz.db") as conn:
        results = conn.execute(
            "SELECT user_id, username, score FROM leaderboard ORDER BY score DESC LIMIT 10"
        ).fetchall()
    
    if results:
        text = "🏆 *Топ игроков:*\n\n"
        for idx, (user_id, username, score) in enumerate(results):
            level = get_level(score)
            emoji = LEVEL_EMOJIS.get(level, "❓")
            user_link = f"[{username}](tg://user?id={user_id})"
            text += f"{idx+1}. {user_link} ({level} - lvl {emoji}) {score} очк.\n"
    else:
        text = "❌ *Рейтинг пока пуст!*"
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown")
    logging.info(f"Пользователь {message.chat.id} запросил таблицу лидеров.")


    

@bot.message_handler(commands=['clean'])
def clean(message):
    bot.send_message(message.chat.id, "🔄 Перезапуск...")
    bot.send_message(message.chat.id, "\u200b")  # Отправляем невидимое сообщение (очистка)
    start(message)
    logging.info(f"Пользователь {message.chat.id} перезапустил бота.")
    
@bot.message_handler(commands=['stats', 'global_rating', 'clean'])
def handle_commands(message):
    command = message.text.strip().lower()
    if command == '/stats':
        send_stats(message)
    elif command == '/global_rating':
        leaderboard(message)
    elif command == '/clean':
        clean(message)
@bot.message_handler(func=lambda message: is_button(message.text))
def handle_buttons(message):
    chat_id = message.chat.id
    if message.text == "Получить вопрос":
        send_question(message)
    elif message.text == "Рейтинги":
        leaderboard(message)
    elif message.text == "Статистика":
        send_stats(message)
    elif message.text == "Обновить":
        clean(message)
def is_button(text):
    return text in ["Получить вопрос", "Рейтинги", "Статистика", "Обновить"]

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
    try:
        json_str = request.get_data().decode("utf-8")
        #logging.info(f"Webhook received: {json_str}")  # Проверяем, доходят ли запросы
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
    except Exception as e:
        logging.error(f"Ошибка в вебхуке: {e}")
    return "OK", 200, {"Content-Type": "text/plain"}

@app.route("/", methods=["GET"])
def home():
    return "Бот работает!", 200  # Это
if __name__ == "__main__":
    init_db()
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)  # Устанавливаем вебхук без задержки
    port = int(os.environ.get("PORT", 5000))  # Render передаст нужный порт
    app.run(host="0.0.0.0", port=port)


