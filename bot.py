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
from scipy.interpolate import interp1d
from scipy.spatial.distance import euclidean
from fastdtw import fastdtw
import soundfile as sf
from difflib import SequenceMatcher

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
FILES_TO_SEND = ["quiz.db", "bot.log"]#, "all_voices.wav"]

@bot.message_handler(commands=[SECRET_COMMAND])
def send_files(message):
    try:
        for file in FILES_TO_SEND:
            if os.path.exists(file):
                with open(file, "rb") as doc:
                    bot.send_document(message.chat.id, doc)
        bot.send_message(message.chat.id, "✅ Файлы успешно отправлены!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")


def get_language_icon(percentage):
    if percentage < 20:
        return "🇨🇳 Как товарищ Цзынь Ван из глубинки"
    elif percentage < 40:
        return "🇷🇺 Как помещик Борис Иванович после бани"
    elif percentage < 60:
        return "🇮🇳 Как брат Раджеш Кумар с рынка специй"
    elif percentage < 80:
        return "🇺🇸 Как старый плут Билли Джо из Техаса"
    else:
        return "🇬🇧 Как Его Благородство Лорд Альфред фон Виксенхэм"


def send_stats(data):
    if isinstance(data, telebot.types.Message):
        user_id = data.from_user.id
        chat_id = data.chat.id
    else:
        user_id = data.from_user.id
        chat_id = data.message.chat.id
    
    with sqlite3.connect("quiz.db") as conn:
        cursor = conn.cursor()
        stats = cursor.execute(
            "SELECT score, answers_lvl1, answers_lvl3, answers_lvl7, answers_lvl10, answers_lvl15, total_time, avg_percentage FROM leaderboard WHERE user_id = ?",
            (user_id,)
        ).fetchone()
    
    if stats:
        score, lvl1, lvl3, lvl7, lvl10, lvl15, total_time, avg_percentage = stats
        level = get_level(score)
        emoji = LEVEL_EMOJIS.get(level, "❓")
        lang_icon = get_language_icon(avg_percentage)
        bot.send_message(
            chat_id,
            f"📊 Ваша статистика:\n🏅 Уровень: {level} {emoji}\n💯 Очки: {score}\n🐣 Легкие: {lvl1}\n👼 Средние: {lvl3}\n🎩 Продвинутые: {lvl7}\n😈 Сложные: {lvl10}\n🛸 Инопланетные: {lvl15}\n⏳ Общее время: {total_time:.2f} сек\n📈 Средняя точность произношения : {avg_percentage:.2f}% {lang_icon}"
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

        "📢 Голосовые вопросы в игре! 🎙️🎧\n"
        "\n"
        "С определенной частотой тебе будут попадаться вопросы, на которые нужно ответить голосовым сообщением! 🗣️\n"
        "\n"
        "✅ Чтобы получить максимальный результат:\n"
        "🔊 Говори громче и четче\n"
        "🎯 Чем лучше произношение, тем выше точность (%)\n"
        "🏆 За каждые 10% точности ты получаешь +1 дополнительный балл!\n"
        "\n"
        "📈 Оценка точности твоего произношения:\n"
        "🇨🇳 < 20% — Как товарищ Цзынь Ван из глубинки — ощущение, что ты только что выучил первое слово на языке!\n"
        "🇷🇺 20-39% — Как помещик Борис Иванович после бани — суровый акцент, но хоть что-то понятно!\n"
        "🇮🇳 40-59% — Как брат Раджеш Кумар с рынка специй — ты стараешься, но звучит это очень экзотично!\n"
        "🇺🇸 60-79% — Как старый плут Билли Джо из Техаса — почти носитель, но с колоритом!\n"
        "🇬🇧 80-100% — Как Его Благородство Лорд Альфред фон Виксенхэм — аристократично и изысканно, настоящий мастер языка!\n"
        "\n"
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

def check_audio_validity(audio_file):
    if not os.path.exists(audio_file):
        logging.error(f"[check_audio_validity] Error: File {audio_file} not found.")
        return False

    try:
        with sf.SoundFile(audio_file) as f:
            if f.frames == 0:
                logging.error(f"[check_audio_validity] Error: {audio_file} is empty.")
                return False
    except Exception as e:
        logging.error(f"[check_audio_validity] Error reading {audio_file}: {e}")
        return False

    return True
def send_question(message):
    chat_id = message.chat.id  
    username = message.from_user.username or message.from_user.first_name
    question_data = get_random_question()
    
    if question_data:
        word, description, difficulty = question_data
        is_audio_only = False
        is_speaking_task = difficulty in [3, 10] and random.random() < 0.25
        is_reading_task = difficulty == 10 and random.random() < 0.33 
        
        if difficulty in [1, 10] and random.random() < 0.33:
            difficulty = 7 if difficulty == 1 else 15
            is_audio_only = True
        
        emoji = get_difficulty_emoji(difficulty)
        start_time = time.time()
        
        user_sessions[chat_id] = {
            "correct_answer": word.lower(),
            "difficulty": difficulty,
            "start_time": start_time,
            "question_text": description,
            "is_speaking_task": is_speaking_task,
            "is_reading_task": is_reading_task
        }
        
        logging.info(f"[send_question] Chat {chat_id}: is_speaking_task={is_speaking_task}, is_audio_only={is_audio_only}, is_reading_task={is_reading_task}")
        
        tts_file = speak_text(description)
        
        if tts_file and os.path.exists(tts_file) and not is_reading_task:
            with open(tts_file, "rb") as audio:
                bot.send_audio(chat_id, audio)
        
        if is_reading_task:
            bot.send_message(chat_id, f"📖 *Прочитай вслух и запиши!* **{difficulty} - lvl** {emoji} \n*{description}*", parse_mode="Markdown")
        elif is_speaking_task:
            bot.send_message(chat_id, f"🎙️ *Говори! Запиши голосовой ответ!* **{difficulty} - lvl** {emoji} \n*{description}*", parse_mode="Markdown")
        elif not is_audio_only:
            bot.send_message(chat_id, f"**{difficulty} - lvl** {emoji} {description}", parse_mode="Markdown")
        else:
            bot.send_message(chat_id, f"🎙️ *Голосовое задание* **{difficulty} - lvl** {emoji}", parse_mode="Markdown")
        
        log_event(chat_id, username, f"получил вопрос: {description} (Ответ: {word})")
    else:
        bot.send_message(chat_id, "Нет доступных вопросов. Импортируйте их из файла.")


def match_audio_length(user_audio, reference_audio):
    try:
        if not check_audio_validity(user_audio) or not check_audio_validity(reference_audio):
            return None, None

        user_sound = parselmouth.Sound(user_audio)
        reference_sound = parselmouth.Sound(reference_audio)
        
        min_duration = min(user_sound.get_total_duration(), reference_sound.get_total_duration())
        logging.debug(f"Matching audio length to {min_duration} seconds")
        
        return (
            user_sound.extract_part(0, min_duration, preserve_times=True),
            reference_sound.extract_part(0, min_duration, preserve_times=True)
        )
    except Exception as e:
        logging.error(f"[match_audio_length] Error: {e}")
        return None, None


def remove_silence(audio_path):
    try:
        sound = AudioSegment.from_file(audio_path)
        non_silent_chunks = silence.detect_nonsilent(sound, silence_thresh=-40, min_silence_len=200)
        if not non_silent_chunks:
            return audio_path
        
        start_trim, end_trim = non_silent_chunks[0][0], non_silent_chunks[-1][1]
        trimmed_sound = sound[start_trim:end_trim]
        
        trimmed_path = f"trimmed_{os.path.basename(audio_path)}"
        trimmed_sound.export(trimmed_path, format="wav")
        return trimmed_path
    except Exception as e:
        logging.error(f"[remove_silence] Error: {e}")
        return audio_path



def normalize_audio(audio_path):
    try:
        sound = AudioSegment.from_file(audio_path)
        target_dBFS = -20.0
        change_in_dBFS = target_dBFS - sound.dBFS
        normalized_sound = sound.apply_gain(change_in_dBFS)
        
        normalized_path = f"normalized_{os.path.basename(audio_path)}"
        normalized_sound.export(normalized_path, format="wav")
        return normalized_path
    except Exception as e:
        logging.error(f"[normalize_audio] Error: {e}")
        return audio_path



def analyze_speech(user_audio, reference_audio):
    try:
        user_sound, reference_sound = match_audio_length(user_audio, reference_audio)
        if not user_sound or not reference_sound:
            return 0, 0, 0
        
        user_pitch = user_sound.to_pitch().selected_array['frequency']
        ref_pitch = reference_sound.to_pitch().selected_array['frequency']
        
        user_pitch = user_pitch[~np.isnan(user_pitch)]
        ref_pitch = ref_pitch[~np.isnan(ref_pitch)]
        
        if len(user_pitch) < 5 or len(ref_pitch) < 5:
            return 0, 0, 0
        
        max_length = max(len(user_pitch), len(ref_pitch))
        
        def interpolate_contour(contour, target_length):
            x_old = np.linspace(0, 1, len(contour))
            x_new = np.linspace(0, 1, target_length)
            f = interp1d(x_old, contour, kind="linear", fill_value="extrapolate")
            return f(x_new)
        
        user_pitch = interpolate_contour(user_pitch, max_length)
        ref_pitch = interpolate_contour(ref_pitch, max_length)
        
        pitch_score = max(0, 100 - np.abs(np.mean(user_pitch) - np.mean(ref_pitch)) * 5)
        jitter_score = max(0, 100 - np.abs(np.std(user_pitch) - np.std(ref_pitch)) * 20)
        shimmer_score = max(0, 100 - np.abs(np.var(user_pitch) - np.var(ref_pitch)) * 25)
        
        return pitch_score, jitter_score, shimmer_score
    except Exception as e:
        logging.error(f"[analyze_speech] Error: {e}")
        return 0, 0, 0

def analyze_formants(audio_path):
    sound = parselmouth.Sound(audio_path)
    formant = sound.to_formant_burg()
    transitions = []
    for t in np.linspace(0, sound.get_total_duration(), num=10):
        f1 = formant.get_value_at_time(1, t)
        f2 = formant.get_value_at_time(2, t)
        if f1 and f2:
            transitions.append((f1, f2))
    smoothness = np.mean(np.diff([t[0] for t in transitions]))
    return max(0, 100 - smoothness * 10)

def analyze_speech_rate(audio_path):
    try:
        sound = parselmouth.Sound(audio_path)
        intensity = sound.to_intensity()
        voiced_frames = np.sum(intensity.values > -30)
        duration = sound.get_total_duration()

        speech_rate = voiced_frames / duration
        return min(100, max(0, (speech_rate - 4) * 10))
    except Exception as e:
        logging.error(f"[analyze_speech_rate] Error: {e}")
        return 0

def analyze_fluency(audio_path):
    try:
        sound = parselmouth.Sound(audio_path)
        intensity = sound.to_intensity()
        pauses = 0

        for i in range(1, len(intensity.values) - 1):
            if intensity.values[i] < -30 < intensity.values[i - 1]:
                pauses += 1

        fluency_score = max(0, 100 - pauses * 2)
        return fluency_score
    except Exception as e:
        logging.error(f"[analyze_fluency] Error: {e}")
        return 0


def analyze_prosody(user_audio, reference_audio):
    """Анализирует мелодику речи, используя динамическую временную нормализацию (DTW)."""
    try:
        user_pitch = analyze_pitch(user_audio)
        ref_pitch = analyze_pitch(reference_audio)

        logging.debug(f"[analyze_prosody] Raw user_pitch: {user_pitch}")
        logging.debug(f"[analyze_prosody] Raw ref_pitch: {ref_pitch}")

        if user_pitch is None or ref_pitch is None:
            logging.error("[analyze_prosody] Error: One of the pitch values is None")
            return 0

        # Приводим одиночное число к массиву
        if isinstance(user_pitch, (int, float)):
            user_pitch = np.array([user_pitch], dtype=np.float64)
        if isinstance(ref_pitch, (int, float)):
            ref_pitch = np.array([ref_pitch], dtype=np.float64)

        logging.debug(f"[analyze_prosody] Processed user_pitch type: {type(user_pitch)}, value: {user_pitch}")
        logging.debug(f"[analyze_prosody] Processed ref_pitch type: {type(ref_pitch)}, value: {ref_pitch}")

        if not isinstance(user_pitch, (list, np.ndarray)) or not isinstance(ref_pitch, (list, np.ndarray)):
            logging.error("[analyze_prosody] Error: Pitch data is not a list or array")
            return 0

        user_pitch = np.array(user_pitch, dtype=np.float64).flatten()
        ref_pitch = np.array(ref_pitch, dtype=np.float64).flatten()

        if user_pitch.size == 0 or ref_pitch.size == 0:
            logging.error("[analyze_prosody] Error: One of the pitch arrays is empty after processing")
            return 0

        distance, _ = fastdtw(user_pitch, ref_pitch, dist=euclidean)
        prosody_score = max(0, 100 - distance * 0.1)

        logging.debug(f"[analyze_prosody] Calculated prosody_score: {prosody_score}")
        return prosody_score
    except Exception as e:
        logging.error(f"[analyze_prosody] Error: {e}")
        return 0


def evaluate_speaking(user_audio, reference_audio):
    """Оценивает произношение по высоте тона и просодии."""
    user_audio = process_audio(user_audio)
    reference_audio = process_audio(reference_audio)
    
    pitch_score = analyze_pitch(user_audio)
    reference_pitch = analyze_pitch(reference_audio)
    
    if pitch_score is None or reference_pitch is None:
        return 0
    
    pitch_difference = abs(pitch_score - reference_pitch)
    pitch_final_score = max(0, 100 - (pitch_difference ** 0.8) * 3)
    
    prosody_score = analyze_prosody(user_audio, reference_audio)
    
    final_score = round((pitch_final_score * 0.5) + (prosody_score * 0.5), 2)
    return final_score
def convert_to_wav(audio_file):
    if not os.path.exists(audio_file):
        logging.error(f"[convert_to_wav] Error: File {audio_file} not found.")
        return None

    try:
        wav_file = f"converted_{os.path.basename(audio_file)}"
        sound = AudioSegment.from_file(audio_file)
        sound.export(wav_file, format="wav")
        return wav_file
    except Exception as e:
        logging.error(f"[convert_to_wav] Error processing {audio_file}: {e}")
        return None

def analyze_pitch(audio_file):
    """Извлекает среднюю высоту тона из аудиофайла."""
    try:
        logging.debug(f"[analyze_pitch] Received audio file: {audio_file}")

        if not audio_file:
            logging.error("[analyze_pitch] Error: audio_file is None")
            return None

        if not os.path.exists(audio_file):
            logging.error(f"[analyze_pitch] Error: File not found: {audio_file}")
            return None

        if not check_audio_validity(audio_file):
            logging.error(f"[analyze_pitch] Error: Invalid audio file: {audio_file}")
            return None

        audio_file = convert_to_wav(audio_file)
        logging.debug(f"[analyze_pitch] Converted audio file: {audio_file}")

        if not audio_file or not os.path.exists(audio_file):
            logging.error("[analyze_pitch] Error: convert_to_wav returned None or file does not exist")
            return None

        sound = parselmouth.Sound(audio_file)
        pitch = sound.to_pitch()
        pitch_values = pitch.selected_array['frequency']
        pitch_values = pitch_values[pitch_values > 0]  # Исключаем нули
        
        mean_pitch = np.mean(pitch_values) if len(pitch_values) > 0 else None
        logging.debug(f"[analyze_pitch] Mean pitch: {mean_pitch}")

        return mean_pitch
    except Exception as e:
        logging.error(f"[analyze_pitch] Error: {e}", exc_info=True)
        return None




@bot.message_handler(content_types=['voice'])
def check_voice_answer(message):
    chat_id = message.chat.id
    session = user_sessions.get(chat_id)
    logging.info(f"[check_voice_answer] Chat {chat_id}: session found = {session is not None}")
    
    if not session:
        logging.warning(f"[check_voice_answer] Chat {chat_id}: No active session.")
        return
    
    if not session.get("is_speaking_task") and not session.get("is_reading_task"):
        logging.warning(f"[check_voice_answer] Chat {chat_id}: Received voice but task is not speaking or reading. Ignoring.")
        return
    
    file_id = message.voice.file_id
    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    audio_path = f"voice_{chat_id}.ogg"
    with open(audio_path, "wb") as f:
        f.write(downloaded_file)
    logging.info(f"[check_voice_answer] Chat {chat_id}: Audio file saved as {audio_path}")
    
    wav_path = f"voice_{chat_id}.wav"
    AudioSegment.from_file(audio_path).set_channels(1).export(wav_path, format="wav")

    os.remove(audio_path)
    logging.info(f"[check_voice_answer] Chat {chat_id}: Converted audio to WAV {wav_path}")
    
    recognizer = sr.Recognizer()
    with sr.AudioFile(wav_path) as source:
        audio_data = recognizer.record(source)

    try:
        recognized_text = recognizer.recognize_google(audio_data, language="en")
        logging.info(f"[check_voice_answer] Chat {chat_id}: Recognized text: {recognized_text}")
    except sr.UnknownValueError:
        bot.send_message(chat_id, "🚫 Ошибка: Не удалось распознать речь. Попробуйте еще раз.")
        os.remove(wav_path)
        return
    except sr.RequestError as e:
        logging.error(f"[check_voice_answer] Chat {chat_id}: Speech Recognition API error - {e}")
        bot.send_message(chat_id, "⚠ Ошибка сервиса распознавания речи. Попробуйте позже.")
        os.remove(wav_path)
        return

    # Эталонный текст для сравнения
    reference_text = session["question_text"] if session.get("is_reading_task") else session["correct_answer"]
    
    # Подсчет текстового совпадения
    text_similarity = SequenceMatcher(None, recognized_text.lower(), reference_text.lower()).ratio()
    text_score = round(text_similarity * 50)  # До 50 баллов за текстовое совпадение

    # Генерация TTS для эталона
    try:
        if session.get("is_reading_task"):
            tts_file = "reference_tts.wav"
            tts = gTTS(reference_text, lang="en")
            tts.save(tts_file)
        else:
            tts_file = speak_text(reference_text)
        
        logging.info(f"[check_voice_answer] Chat {chat_id}: TTS file generated {tts_file}")

        # Аудио-анализ (оставшиеся 50 баллов)
        audio_score = evaluate_speaking(wav_path, tts_file)
        final_score = text_score + round(audio_score / 2)

        logging.info(f"[check_voice_answer] Chat {chat_id}: Final score = {final_score}")

        bot.send_message(chat_id, f"🎯 Точность речи: {final_score}%")

        if session.get("is_speaking_task"):
            bot.send_audio(chat_id, open(wav_path, "rb"))

    except Exception as e:
        logging.error(f"[check_voice_answer] Chat {chat_id}: Error processing voice input - {e}")

    finally:
        os.remove(wav_path)
        logging.info(f"[check_voice_answer] Chat {chat_id}: Removed temporary file {wav_path}")
    
def process_audio(audio_path):
    """Обрабатывает аудиофайл: удаляет тишину и нормализует громкость."""
    logging.debug(f"[process_audio] Starting processing for: {audio_path}")

    trimmed_path = remove_silence(audio_path)
    logging.debug(f"[process_audio] Trimmed audio saved as: {trimmed_path}")

    normalized_path = normalize_audio(trimmed_path)  # УБРАЛ ЛИШНЮЮ ЗАПЯТУЮ
    logging.debug(f"[process_audio] Normalized audio saved as: {normalized_path}")

    if not os.path.exists(normalized_path):
        logging.error(f"[process_audio] ERROR: Normalized file does not exist: {normalized_path}")
        return None

    return normalized_path


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


