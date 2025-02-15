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
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton 
import threading
from gtts import gTTS
import re
import parselmouth
import speech_recognition as sr
from pydub import AudioSegment, silence
import numpy as np


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

logging.getLogger("werkzeug").setLevel(logging.WARNING)

for handler in logger.handlers:
    handler.flush()  #  
def log_event(user_id, username, event):
    try:
        logging.info(f"Пользователь {user_id} ({username}) - {event}")
        logger.handlers[0].flush()  # Принудительная запись в лог
    except Exception as e:
        logging.error(f"Ошибка при логировании события: {e}")
def contains_cyrillic(text):
    """ Проверяет, содержит ли строка кириллические символы. """
    return bool(re.search("[а-яА-Я]", text))

def speak_text(text, filename="Озвучка.mp3"):
    """ Озвучивает текст, если он не содержит кириллицы, и сохраняет в файл. """
    if not contains_cyrillic(text):
        tts = gTTS(text=text, lang="en")
        tts.save(filename)
        return filename
    return None
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
                answers_lvl7 INTEGER DEFAULT 0,
                answers_lvl10 INTEGER DEFAULT 0,
                answers_lvl15 INTEGER DEFAULT 0,
                total_time INTEGER DEFAULT 0,
                avg_percentage REAL DEFAULT 0
            );
        ''')
        logging.info("База данных инициализирована.")
def send_main_menu(chat_id):
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton("Получить вопрос", callback_data="get_question"),
        InlineKeyboardButton("Рейтинги", callback_data="leaderboard"),
        InlineKeyboardButton("Статистика", callback_data="stats"),
        InlineKeyboardButton("Обновить", callback_data="clean")
    ]
    markup.add(*buttons)
    bot.send_message(chat_id, "Список команд:", reply_markup=markup)
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
                parts = line.split("\t", 1)  # Разделяем только по первому пробелу
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
    return {1: "🐣", 3: "👼", 7: "👹" , 10: "😈" , 15: "👽"}.get(difficulty, "❓")

SECRET_COMMAND = "akj;lgbnskdgjaoivnuikZMAFnPugDHTCJsiasrq0V"

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


def send_stats(data):
    if isinstance(data, telebot.types.Message):
        user_id = data.from_user.id
        chat_id = data.chat.id
    else:  # Если это callback от кнопки
        user_id = data.from_user.id
        chat_id = data.message.chat.id
    
    with sqlite3.connect("quiz.db") as conn:
        cursor = conn.cursor()
        stats = cursor.execute(
            "SELECT score, answers_lvl1, answers_lvl3, answers_lvl7, answers_lvl10, answers_lvl15 , total_time FROM leaderboard WHERE user_id = ?",
            (user_id,)
        ).fetchone()
    
    if stats:
        score, lvl1, lvl3, lvl7 , lvl10, lvl15, total_time = stats
        level = get_level(score)
        emoji = LEVEL_EMOJIS.get(level, "❓")
        bot.send_message(
            chat_id,
            f"📊 Ваша статистика:\n🏅 Уровень: {level} {emoji}\n💯 Очки: {score}\n🐣 Легкие: {lvl1}\n👼 Средние: {lvl3}\n🎩 Продвинутые: {lvl7}\n😈 Сложные: {lvl10}\n 🛸 Инопланетные: {lvl15}\n⏳ Общее время: {total_time} сек"
        )
    else:
        bot.send_message(chat_id, "❌ У вас пока нет статистики.")



@bot.message_handler(commands=['start'])
def start(message):
    welcome_text = (
        "Привет, человек! 🤖✨\n\n"
        "Я — твой помощник в изучении слов и развитии знаний! 📚💡\n"
        "Вот что надо знать, чтобы мы сработались:\n\n"
        "Если одна из нижеперечисленных кнопок не видна или не работает, введите /start, чтобы обновить состояние бота.\n"
        "🔹 **Получить вопрос** — получить случайный вопрос. Проверь свои знания!\n"
        "🔹 **Статистика** — посмотреть свою статистику и уровень.\n"
        "🔹 **Рейтинги** — увидеть топ игроков! 🏆\n"
        "🔹 **Обновить** — перезапустить бота.\n\n"
        "🎯 Отвечай на вопросы, зарабатывай очки и прокачивай уровень! 🏅\n"
        "Выбери одну из 4 кнопок ниже, чтобы начать brainstorm! 🚀\n\n"
        "❓Типы вопросов: \n"
        "🐣  Легкие - ➊ : дается английское слово, нужно перевести на русский эквивалент. Очки за правильный ответ: ➊\n\n"
        "👼  Средние - ➌ : дается русское слово, нужно перевести на английский эквивалент. Очки за правильный ответ: ➌\n\n"
        "👹  Продвинутые - ➐ : дается английская аудиозапись с 1 словом, нужно перевести её на русский. Очки за правильный ответ: ➐\n\n"
        "😈  Сложные - ➓ : дается английское лексическое описание, нужно корректно подобрать под него слово. Очки за правильный ответ: ➓\n\n"
        "👽  Инопланетные - ⑮ : дается английское лексическое описание в виде аудиозаписи, нужно корректно подобрать под него слово. Очки за правильный ответ: ⑮ и респект от тех, кто затрудняется с listening 🎧\n\n"
    )
    bot.send_message(message.chat.id, welcome_text)
    send_main_menu(message.chat.id)
    logging.info(f"Пользователь {message.chat.id} начал работу с ботом.")
    logger.handlers[0].flush()  # Принудительная запись в лог

def update_user_stats(user_id, username, difficulty, elapsed_time):
    try:
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
            elif difficulty == 7:
                cursor.execute("UPDATE leaderboard SET answers_lvl7 = answers_lvl7 + 1 WHERE user_id = ?", (user_id,))    
            elif difficulty == 10:
                cursor.execute("UPDATE leaderboard SET answers_lvl10 = answers_lvl10 + 1 WHERE user_id = ?", (user_id,))
            elif difficulty == 15:
                cursor.execute("UPDATE leaderboard SET answers_lvl15 = answers_lvl15 + 1 WHERE user_id = ?", (user_id,))
            cursor.execute("UPDATE leaderboard SET total_time = total_time + ? WHERE user_id = ?", (elapsed_time, user_id))
            conn.commit()
    except sqlite3.Error as e:
        log_event(user_id, username, f"❌ Ошибка работы с БД: {e}")



user_sessions = {}  # Храним текущие вопросы для каждого чата
@bot.callback_query_handler(func=lambda call: call.data.startswith("play_audio_"))
def play_audio(call):
    chat_id = call.message.chat.id
    session = user_sessions.get(chat_id)

    if session and "question_text" in session:
        question_text = session["question_text"]
        tts_file = speak_text(question_text)  # Генерируем новый аудиофайл
        
        if tts_file:
            with open(tts_file, "rb") as audio:
                bot.send_audio(chat_id, audio)


def send_question(message):
    chat_id = message.chat.id  
    username = message.from_user.username or message.from_user.first_name
    question_data = get_random_question()
    
    if question_data:
        word, description, difficulty = question_data
        is_audio_only = False
        is_speaking_task = difficulty in [3, 10] and random.randint(1, 4) == 1
        
        if difficulty in [1, 10] and random.randint(1, 3) == 1:
            difficulty = 7 if difficulty == 1 else 15
            is_audio_only = True
        
        emoji = get_difficulty_emoji(difficulty)
        start_time = time.time()
        
        user_sessions[chat_id] = {
            "correct_answer": word.lower(),
            "difficulty": difficulty,
            "start_time": start_time,
            "question_text": description,
            "is_speaking_task": is_speaking_task
        }
        
        logging.info(f"[send_question] Chat {chat_id}: is_speaking_task={is_speaking_task}, is_audio_only={is_audio_only}")
        
        tts_file = speak_text(description)
        
        if tts_file and os.path.exists(tts_file):
            with open(tts_file, "rb") as audio:
                bot.send_audio(chat_id, audio)
        
        if is_speaking_task:
            bot.send_message(chat_id, f"🎙️ *Говори! Запиши голосовой ответ!* **{difficulty} - lvl** {emoji} \n*{description}*", parse_mode="Markdown")
        elif not is_audio_only:
            bot.send_message(chat_id, f"**{difficulty} - lvl** {emoji} {description}", parse_mode="Markdown")
        else:
            bot.send_message(chat_id, f"🎙️ *Голосовое задание* **{difficulty} - lvl** {emoji}", parse_mode="Markdown")
        
        log_event(chat_id, username, f"получил вопрос: {description} (Ответ: {word})")
    else:
        bot.send_message(chat_id, "Нет доступных вопросов. Импортируйте их из файла.")


def remove_silence(audio_path):
    try:
        logging.debug(f"[remove_silence] Processing {audio_path}")
        sound = AudioSegment.from_file(audio_path)
        non_silent_chunks = silence.detect_nonsilent(sound, silence_thresh=-50, min_silence_len=150)
        if not non_silent_chunks:
            return audio_path
        start_trim, end_trim = non_silent_chunks[0][0], non_silent_chunks[-1][1]
        trimmed_sound = sound[start_trim:end_trim]
        trimmed_path = "trimmed_" + audio_path
        trimmed_sound.export(trimmed_path, format="wav")
        logging.debug(f"[remove_silence] Trimmed audio saved to {trimmed_path}")
        return trimmed_path
    except Exception as e:
        logging.error(f"[remove_silence] Error processing {audio_path}: {e}")
        return audio_path

def normalize_audio(audio_path):
    try:
        logging.debug(f"[normalize_audio] Normalizing {audio_path}")
        sound = AudioSegment.from_file(audio_path)
        normalized_sound = sound.apply_gain(-sound.max_dBFS)
        normalized_path = "normalized_" + audio_path
        normalized_sound.export(normalized_path, format="wav")
        logging.debug(f"[normalize_audio] Normalized audio saved to {normalized_path}")
        return normalized_path
    except Exception as e:
        logging.error(f"[normalize_audio] Error normalizing {audio_path}: {e}")
        return audio_path

def match_audio_length(user_audio, reference_audio):
    try:
        logging.debug(f"[match_audio_length] Matching {user_audio} and {reference_audio}")
        user_sound = parselmouth.Sound(user_audio)
        reference_sound = parselmouth.Sound(reference_audio)
        
        if user_sound is None or reference_sound is None:
            logging.error("[match_audio_length] One or both audio files could not be loaded.")
            return None, None
        
        min_duration = min(user_sound.get_total_duration(), reference_sound.get_total_duration())
        user_sound = user_sound.extract_part(from_time=0, to_time=min_duration)
        reference_sound = reference_sound.extract_part(from_time=0, to_time=min_duration)
        
        logging.debug(f"[match_audio_length] Trimmed to {min_duration} seconds")
        return user_sound, reference_sound
    except Exception as e:
        logging.error(f"[match_audio_length] Error processing audio: {e}")
        return None, None

def analyze_speech(user_audio, reference_audio):
    try:
        logging.debug(f"[analyze_speech] Analyzing {user_audio} and {reference_audio}")
        user_audio = remove_silence(user_audio)
        reference_audio = remove_silence(reference_audio)
        
        user_audio = normalize_audio(user_audio)
        reference_audio = normalize_audio(reference_audio)
        
        user_sound, reference_sound = match_audio_length(user_audio, reference_audio)
        if user_sound is None or reference_sound is None:
            logging.error("[analyze_speech] Failed to process audio, returning default scores.")
            return 0, 0, 0
        
        user_pitch = user_sound.to_pitch().selected_array['frequency']
        ref_pitch = reference_sound.to_pitch().selected_array['frequency']
        
        if user_pitch.size == 0 or ref_pitch.size == 0:
            logging.error(f"[analyze_speech] Empty pitch array: user={user_pitch.size}, ref={ref_pitch.size}")
            return 0, 0, 0
        
        pitch_score = 100 - np.abs(np.mean(user_pitch) - np.mean(ref_pitch))
        jitter_score = 100 - np.abs(np.std(user_pitch) - np.std(ref_pitch)) * 10
        shimmer_score = 100 - np.abs(np.var(user_pitch) - np.var(ref_pitch)) * 10
        
        return max(0, pitch_score), max(0, jitter_score), max(0, shimmer_score)
    except Exception as e:
        logging.error(f"[analyze_speech] Error analyzing speech: {e}")
        return 0, 0, 0


@bot.message_handler(content_types=['voice'])
def check_voice_answer(message):
    chat_id = message.chat.id
    session = user_sessions.get(chat_id)
    logging.info(f"[check_voice_answer] Chat {chat_id}: session found = {session is not None}")
    
    if not session:
        logging.warning(f"[check_voice_answer] Chat {chat_id}: No active session.")
        return
    
    if not session.get("is_speaking_task"):
        logging.warning(f"[check_voice_answer] Chat {chat_id}: Received voice but task is not speaking. Ignoring.")
        return
    
    file_id = message.voice.file_id
    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    audio_path = f"voice_{chat_id}.ogg"
    with open(audio_path, "wb") as f:
        f.write(downloaded_file)
    
    wav_path = f"voice_{chat_id}.wav"
    AudioSegment.from_file(audio_path).export(wav_path, format="wav")
    os.remove(audio_path)
    
    tts_file = speak_text(session["correct_answer"])
    
    logging.info(f"[check_voice_answer] Chat {chat_id}: Analyzing speech...")
    try:
        pitch_score, jitter_score, shimmer_score = analyze_speech(wav_path, tts_file)
    except Exception as e:
        logging.error(f"[analyze_speech] Error analyzing speech: {e}")
    
    recognizer = sr.Recognizer()
    with sr.AudioFile(wav_path) as source:
        try:
            audio = recognizer.record(source)
            user_transcription = recognizer.recognize_google(audio).lower()
            logging.info(f"[check_voice_answer] Transcribed speech: {user_transcription}")
            correct_transcription = session["correct_answer"].lower()
            match_percentage = compare_texts(user_transcription, correct_transcription)
            final_score = (match_percentage + pitch_score + jitter_score + shimmer_score) / 4
            final_score = min(100, round(final_score * 2, 2))  # Ограничение 100
            
            # Новая логика награждения
            base_points = session["difficulty"]  # Исходный балл = сложность задания
            awarded_points = base_points + (final_score / 10)
            awarded_points = round(awarded_points, 2)
            
            user_id = message.from_user.id
            username = message.from_user.username or message.from_user.first_name
            update_user_stats(user_id, username, session["difficulty"], awarded_points)
            
            # Обновление среднего процента
            with sqlite3.connect("quiz.db") as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT avg_percentage FROM leaderboard WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                if row:
                    prev_avg = row[0]
                    new_avg = (prev_avg + final_score) / 2  # Новая средняя арифметическая
                    cursor.execute("UPDATE leaderboard SET avg_percentage = ? WHERE user_id = ?", (new_avg, user_id))
                else:
                    cursor.execute("INSERT INTO leaderboard (user_id, username, avg_percentage) VALUES (?, ?, ?)", (user_id, username, final_score))
                conn.commit()
            
            bot.send_message(chat_id, f"🎯 Точность: {final_score}%\n🏆 Получено баллов: {awarded_points}\n📊 Новый средний процент: {new_avg if row else final_score}")
            session["new_question_sent"] = True
            send_question(message)
        except sr.UnknownValueError:
            logging.error(f"[check_voice_answer] Speech recognition failed.")
            bot.send_message(chat_id, "❌ Не удалось распознать голос. Попробуй снова!")
    
    os.remove(wav_path)
    

def compare_texts(user_text, correct_text):
    user_words = set(re.findall(r'\w+', user_text))
    correct_words = set(re.findall(r'\w+', correct_text))
    
    common_words = user_words & correct_words
    return int((len(common_words) / len(correct_words)) * 100) if correct_words else 0



def get_hint(word):
    if len(word) < 3:
        return word[0] + "$" * (len(word) - 1)  # Если слово короткое, скрываем всё кроме первой буквы
    middle_index = len(word) // 2
    hint = word[0] + "$" * (middle_index - 1) + word[middle_index] + "$" * (len(word) - middle_index - 1)
    return hint
    
@bot.message_handler(commands=['stats', 'global_rating', 'clean'])
def handle_commands(message):
    if message.text == '/stats':
        send_stats(message)
    elif message.text == '/global_rating':
        leaderboard(message)
    elif message.text == '/clean':
        clean(message)




API_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/"

def get_transcription(word):
    try:
        response = requests.get(f"{API_URL}{word}")
        data = response.json()
        return data[0]["phonetics"][0]["text"] if "phonetics" in data[0] else ""
    except Exception as e:
        print(f"Ошибка получения транскрипции: {e}")
        return ""

@bot.message_handler(func=lambda message: message.chat.id in user_sessions and not is_button(message.text) and not message.text.startswith("#"))
def check_answer(message):
    chat_id = message.chat.id
    username = message.from_user.username or message.from_user.first_name
    session = user_sessions.get(chat_id)
    user_id = message.from_user.id

    if not session:
        return
    
    # Добавлена проверка, если задание - голосовое, игнорируем текстовый ответ
    if session.get("is_speaking_task"):
        logging.debug(f"[check_answer] Chat {chat_id}: Игнорируем текст, так как задание голосовое.")
        return

    correct_answer = session["correct_answer"].lower()
    difficulty = session["difficulty"]
    elapsed_time = int(time.time() - session["start_time"])
    user_answer = message.text.strip().lower()
    
    log_event(chat_id, username, f"Ответил: {user_answer} за {elapsed_time} сек (Правильный: {correct_answer})")
    
    if user_answer == correct_answer:
        update_user_stats(user_id, username, difficulty, elapsed_time)
        transcription = get_transcription(correct_answer)
        
        success_messages = {
            1: f"✅ {username}, Ну, неплохо! 🎉\nСлово: {correct_answer} {transcription}",
            3: f"🎯 {username}, А ты не промах 🚀\nСлово: {correct_answer} {transcription}",
            7: f"🎧 {username}, Умеешь слушать 👂\nСлово: {correct_answer} {transcription}",
            10: f"🔥 {username}, Умничка 💪\nСлово: {correct_answer} {transcription}",
            15: f"🎻 {username}, Может, станешь музыкантом? Великолепно ✨\nСлово: {correct_answer} {transcription}",
        }
        
        success_message = success_messages.get(difficulty, f"✅ {username}, правильно! Так держать! ✨\nСлово: {correct_answer} {transcription}")
        
        bot.send_message(chat_id, success_message)
        del user_sessions[chat_id]
    else:
        feedback_messages = {
            1: f"😕 {username}, балони йепсан! Подумай ещё раз.",
            3: f"🤨 {username}, это что за ответ ?!?!?!?. Марш учить!",
            7: f"🧏 {username}, Рыбак рыбака НЕ СЛЫШИТ издалека!",
            10: f"🧠💨 {username}, мозг вышел из чата",
            15: f"🤯👂 {username}, уши, вы существуете ?!?!?!?",
        }
        
        feedback = feedback_messages.get(difficulty, f"❌ {username}, неверно. Попробуй снова.")
        hint = get_hint(correct_answer)
        bot.send_message(chat_id, f"{feedback}\nПодсказка: {hint}")
        time.sleep(4)
    
    if session.get("new_question_sent"):
        return
    
    send_main_menu(chat_id)
    session["new_question_sent"] = True
    send_question(message)


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
    
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    if call.data == "get_question":
        send_question(call.message)
    elif call.data == "leaderboard":
        leaderboard(call.message)
    elif call.data == "stats":
        send_stats(call)
    elif call.data == "clean":
        clean(call.message)
    bot.answer_callback_query(call.id)  # Закрываем уведомление о нажатии

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


