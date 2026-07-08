"""
Habla Argentina — бот для продажи доступа к курсам через Telegram Stars.

Что делает:
  /start        — приветствие и кнопки с курсами
  оплата Stars  — после оплаты бот просит почту и создаёт личный аккаунт
                  (логин = почта, пароль генерируется автоматически)
  /mydostup     — повторно прислать логин, пароль и список купленных курсов

Аккаунты хранятся в Firebase (Authentication + Firestore, бесплатный тариф).
Настройки ниже (BOT_TOKEN, курсы в COURSES, FIREBASE_*) — меняются в одном месте.
"""

import os
import re
import json
import string
import secrets
import logging

import requests

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ============ НАСТРОЙКИ (меняй здесь) ============

# Токен бота от @BotFather. Лучше задать через переменную окружения BOT_TOKEN,
# но можно вписать прямо сюда в кавычки (менее безопасно).
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВСТАВЬ_СЮДА_ТОКЕН_ОТ_BOTFATHER")

# Firebase-проект, который хранит аккаунты покупателей (бесплатный тариф Spark).
# apiKey — публичный идентификатор веб-приложения, это нормально, что он виден в коде.
FIREBASE_API_KEY = "AIzaSyBDUVPQEpfPOGvkv6trd1GWZAVtesBmMg0"
FIREBASE_PROJECT_ID = "habla-argentina"

# Курсы, которые продаёт бот. Ключ ("quickstart", "a1") используется как
# invoice payload, поэтому менять его после запуска в проде не стоит —
# лучше просто менять цену/ссылку/описание внутри.
COURSES = {
    "quickstart": {
        "title": "Быстрый старт",
        "product_title": "Курс «Быстрый старт»",
        "product_desc": "Полный доступ навсегда: 16 уроков, 8 диалогов, умное повторение.",
        "price_stars": 580,
        "course_url": "https://hablaargentina.com/app.html",
        "button_label": "Быстрый старт — 580 ⭐",
    },
    "a1": {
        "title": "Курс А1",
        "product_title": "Курс «А1»",
        "product_desc": "24 урока по официальной программе уровня А1: грамматика, voseo, живые аргентинские конструкции.",
        "price_stars": 1200,
        "course_url": "https://hablaargentina.com/a1.html",
        "button_label": "Курс А1 — 1200 ⭐",
    },
    "a2": {
        "title": "Курс А2",
        "product_title": "Курс «А2»",
        "product_desc": "22 урока по официальной программе уровня А2: продолжение грамматики после А1, живые диалоги и тексты.",
        "price_stars": 1200,
        "course_url": "https://hablaargentina.com/a2.html",
        "button_label": "Курс А2 — 1200 ⭐",
    },
}

# Комбо-предложение: все три курса вместе со скидкой 30% от суммы цен по отдельности.
# 580 + 1200 + 1200 = 2980 звёзд; 2980 * 0.7 = 2086 звёзд.
BUNDLE = {
    "title": "Все три курса",
    "product_title": "Все три курса «Быстрый старт» + «А1» + «А2» (-30%)",
    "product_desc": "Полный доступ навсегда ко всем трём курсам сразу, дешевле на 30%, чем покупать по отдельности.",
    "price_stars": 2086,
    "button_label": "🔥 Все три курса со скидкой 30% — 2086 ⭐",
    "includes": ["quickstart", "a1", "a2"],
}

# Файл, где хранится информация о покупателях (user_id -> email/пароль/курсы).
BUYERS_FILE = "buyers.json"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ============ ХРАНИЛИЩЕ ПОКУПАТЕЛЕЙ ============
# Формат: {"<user_id>": {"email":..., "password":..., "uid":..., "courses": [...]}}

def load_buyers():
    try:
        with open(BUYERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    normalized = {}
    for key, value in data.items():
        if isinstance(value, list):
            # Старый формат (общий код доступа, без личного аккаунта).
            normalized[key] = {"courses": value}
        else:
            normalized[key] = value
    return normalized

def save_buyers(buyers):
    try:
        with open(BUYERS_FILE, "w", encoding="utf-8") as f:
            json.dump(buyers, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error("Не удалось сохранить покупателей: %s", e)

# ============ FIREBASE (аккаунты покупателей) ============

def firebase_sign_up(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_API_KEY}"
    resp = requests.post(
        url,
        json={"email": email, "password": password, "returnSecureToken": True},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()

def firebase_sign_in(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
    resp = requests.post(
        url,
        json={"email": email, "password": password, "returnSecureToken": True},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()

def firestore_set_courses(uid, id_token, courses):
    url = (
        f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}"
        f"/databases/(default)/documents/purchases/{uid}"
    )
    body = {
        "fields": {
            "courses": {
                "arrayValue": {"values": [{"stringValue": c} for c in courses]}
            }
        }
    }
    resp = requests.patch(
        url,
        params={"updateMask.fieldPaths": "courses"},
        json=body,
        headers={"Authorization": f"Bearer {id_token}"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()

def generate_password(length=10):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

def create_account_and_grant(email, password, courses):
    """Создаёт новый Firebase-аккаунт и записывает купленные курсы."""
    auth = firebase_sign_up(email, password)
    uid = auth["localId"]
    id_token = auth["idToken"]
    firestore_set_courses(uid, id_token, courses)
    return uid

def grant_courses_to_existing(email, password, courses):
    """Логинится в уже созданный аккаунт и обновляет список купленных курсов."""
    auth = firebase_sign_in(email, password)
    firestore_set_courses(auth["localId"], auth["idToken"], courses)

# ============ ЛОГИКА БОТА ============

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

WELCOME = (
    "¡Hola! 🇦🇷\n\n"
    "Это бот курсов *Habla Argentina*.\n\n"
    "🇦🇷 *Быстрый старт* — 16 уроков и 8 диалогов на реальные бытовые ситуации: "
    "магазин, лавка, аптека, транспорт, аэропорт.\n\n"
    "📘 *Курс А1* — 24 урока по грамматике и voseo, для тех, кто хочет говорить увереннее.\n\n"
    "📗 *Курс А2* — 22 урока, продолжение грамматики после А1.\n\n"
    "🔥 Можно взять все три курса сразу со скидкой 30%.\n\n"
    "Выбери вариант ниже 👇"
)

def courses_keyboard():
    buttons = [
        [InlineKeyboardButton(c["button_label"], callback_data=f"buy:{key}")]
        for key, c in COURSES.items()
    ]
    buttons.append([InlineKeyboardButton(BUNDLE["button_label"], callback_data="buy:bundle")])
    return InlineKeyboardMarkup(buttons)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        WELCOME, parse_mode="Markdown", reply_markup=courses_keyboard()
    )

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    course_key = query.data.split(":", 1)[1]

    if course_key == "bundle":
        prices = [LabeledPrice(label=BUNDLE["product_title"], amount=BUNDLE["price_stars"])]
        await context.bot.send_invoice(
            chat_id=query.from_user.id,
            title=BUNDLE["product_title"],
            description=BUNDLE["product_desc"],
            payload="habla_course_bundle",
            provider_token="",           # пусто — это оплата звёздами
            currency="XTR",              # XTR = Telegram Stars
            prices=prices,
            start_parameter="habla",
        )
        return

    course = COURSES.get(course_key)
    if not course:
        return
    # Для Telegram Stars: currency="XTR", provider_token пустой.
    prices = [LabeledPrice(label=course["product_title"], amount=course["price_stars"])]
    await context.bot.send_invoice(
        chat_id=query.from_user.id,
        title=course["product_title"],
        description=course["product_desc"],
        payload=f"habla_course_{course_key}",
        provider_token="",           # пусто — это оплата звёздами
        currency="XTR",              # XTR = Telegram Stars
        prices=prices,
        start_parameter="habla",
    )

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Telegram требует подтвердить перед списанием — всегда ok=True.
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = update.message.successful_payment.invoice_payload
    course_key = payload.replace("habla_course_", "")
    user_id = update.message.from_user.id

    new_courses = BUNDLE["includes"] if course_key == "bundle" else [course_key]

    buyers = load_buyers()
    record = buyers.get(str(user_id), {})
    owned = list(dict.fromkeys(record.get("courses", []) + new_courses))

    if record.get("email") and record.get("password") and record.get("uid"):
        # Аккаунт уже есть — просто добавляем новые курсы к нему.
        try:
            grant_courses_to_existing(record["email"], record["password"], owned)
        except Exception as e:
            logging.error("Не удалось обновить курсы существующего аккаунта: %s", e)
        record["courses"] = owned
        buyers[str(user_id)] = record
        save_buyers(buyers)

        names = ", ".join(f"«{COURSES[k]['title']}»" for k in new_courses if k in COURSES)
        await update.message.reply_text(
            "¡Gracias! 🎉 Оплата прошла успешно.\n\n"
            f"Курс {names} добавлен на твой аккаунт {record['email']}.\n"
            "Логин и пароль те же, что и раньше — заходи на hablaargentina.com и вводи их "
            "на странице курса.\n\n"
            "¡Buena suerte! 🇦🇷"
        )
        return

    # Аккаунта ещё нет — просим почту, чтобы его создать.
    context.user_data["awaiting_email"] = True
    context.user_data["pending_courses"] = owned
    await update.message.reply_text(
        "¡Gracias! 🎉 Оплата прошла успешно.\n\n"
        "Последний шаг — напиши свою почту (email). На неё я заведу личный аккаунт "
        "для входа на сайт с курсом (это займёт секунду):"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_email"):
        return

    email = update.message.text.strip()
    if not EMAIL_RE.match(email):
        await update.message.reply_text(
            "Это не похоже на почту. Напиши в формате name@mail.com:"
        )
        return

    user_id = update.message.from_user.id
    pending = context.user_data.get("pending_courses", [])
    password = generate_password()

    try:
        uid = create_account_and_grant(email, password, pending)
    except requests.HTTPError as e:
        logging.error("Firebase signUp failed: %s", e)
        await update.message.reply_text(
            "Не получилось создать аккаунт на эту почту — возможно, она уже "
            "используется другим покупателем. Напиши другую почту, или напиши мне "
            "лично, разберёмся:"
        )
        return
    except Exception as e:
        logging.error("Ошибка при создании аккаунта: %s", e)
        await update.message.reply_text(
            "Что-то пошло не так при создании аккаунта. Попробуй ещё раз через минуту "
            "или напиши мне лично."
        )
        return

    buyers = load_buyers()
    buyers[str(user_id)] = {
        "email": email,
        "password": password,
        "uid": uid,
        "courses": pending,
    }
    save_buyers(buyers)

    context.user_data["awaiting_email"] = False
    context.user_data.pop("pending_courses", None)

    names = ", ".join(f"«{COURSES[k]['title']}»" for k in pending if k in COURSES)
    await update.message.reply_text(
        "Готово! Аккаунт создан. 🎉\n\n"
        f"Логин: {email}\n"
        f"Пароль: {password}\n\n"
        f"Курсы: {names}\n\n"
        "Зайди на hablaargentina.com, открой страницу курса и введи логин с паролем — "
        "доступ остаётся навсегда.\n"
        "Если потеряешь пароль, напиши /mydostup, и я пришлю его снова.\n\n"
        "¡Buena suerte! 🇦🇷"
    )

async def mydostup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    buyers = load_buyers()
    record = buyers.get(user_id)
    if not record or not record.get("email"):
        await update.message.reply_text(
            "Пока не вижу твоей оплаты. Нажми /start и купи курс, "
            "а если ты уже платил — напиши мне, разберёмся."
        )
        return

    names = ", ".join(
        f"«{COURSES[k]['title']}»" for k in record.get("courses", []) if k in COURSES
    )
    await update.message.reply_text(
        f"Логин: {record['email']}\n"
        f"Пароль: {record.get('password', '—')}\n\n"
        f"Курсы: {names}\n\n"
        "Заходи на hablaargentina.com, открой страницу курса и введи эти логин и пароль."
    )

def main():
    if not BOT_TOKEN or "ВСТАВЬ" in BOT_TOKEN:
        raise SystemExit("Ошибка: не задан BOT_TOKEN. Вставь токен от @BotFather.")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mydostup", mydostup))
    app.add_handler(CallbackQueryHandler(buy, pattern="^buy:"))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(
        MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment)
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )
    logging.info("Бот запущен.")
    app.run_polling()

if __name__ == "__main__":
    main()
