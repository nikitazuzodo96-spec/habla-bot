"""
Habla Argentina — бот для продажи доступа к курсам через Telegram Stars.

Что делает:
  /start        — приветствие и кнопки с обоими курсами
  оплата Stars  — после успешной оплаты бот присылает ссылку на купленный курс
  /mydostup     — повторно прислать ссылки на все оплаченные курсы

Настройки ниже (BOT_TOKEN, курсы в COURSES) — меняются в одном месте.
"""

import os
import json
import logging

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
        # Код доступа должен совпадать с ACCESS_CODE в app.html.
        "access_code": "HABLA2026",
        "button_label": "Быстрый старт — 580 ⭐",
    },
    "a1": {
        "title": "Курс А1",
        "product_title": "Курс «А1»",
        "product_desc": "24 урока по официальной программе уровня А1: грамматика, voseo, живые аргентинские конструкции.",
        "price_stars": 1200,
        "course_url": "https://hablaargentina.com/a1.html",
        # Код доступа должен совпадать с ACCESS_CODE в a1.html.
        "access_code": "A1HABLA2026",
        "button_label": "Курс А1 — 1200 ⭐",
    },
    "a2": {
        "title": "Курс А2",
        "product_title": "Курс «А2»",
        "product_desc": "22 урока по официальной программе уровня А2: продолжение грамматики после А1, живые диалоги и тексты.",
        "price_stars": 580,
        "course_url": "https://hablaargentina.com/a2.html",
        # Код доступа должен совпадать с ACCESS_CODE в a2.html.
        "access_code": "A2HABLA2026",
        "button_label": "Курс А2 — 580 ⭐",
    },
}

# Комбо-предложение: все три курса вместе со скидкой 30% от суммы цен по отдельности.
# 580 + 1200 + 580 = 2360 звёзд; 2360 * 0.7 = 1652 звезды.
BUNDLE = {
    "title": "Все три курса",
    "product_title": "Все три курса «Быстрый старт» + «А1» + «А2» (-30%)",
    "product_desc": "Полный доступ навсегда ко всем трём курсам сразу, дешевле на 30%, чем покупать по отдельности.",
    "price_stars": 1652,
    "button_label": "🔥 Все три курса со скидкой 30% — 1652 ⭐",
    "includes": ["quickstart", "a1", "a2"],
}

# Файл, где хранится список оплативших (user_id -> список купленных курсов).
BUYERS_FILE = "buyers.json"

# ============ ХРАНИЛИЩЕ ОПЛАТИВШИХ ============
# Новый формат: {"<user_id>": ["quickstart", "a1"]}

def load_buyers():
    try:
        with open(BUYERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    if isinstance(data, list):
        # Старый формат (до появления второго курса) — просто список id,
        # все они покупали единственный на тот момент курс "Быстрый старт".
        return {str(uid): ["quickstart"] for uid in data}
    return data

def save_buyer(user_id, course_key):
    buyers = load_buyers()
    key = str(user_id)
    owned = set(buyers.get(key, []))
    owned.add(course_key)
    buyers[key] = list(owned)
    try:
        with open(BUYERS_FILE, "w", encoding="utf-8") as f:
            json.dump(buyers, f)
    except Exception as e:
        logging.error("Не удалось сохранить покупателя: %s", e)

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

    if course_key == "bundle":
        for key in BUNDLE["includes"]:
            save_buyer(user_id, key)
        links = "\n".join(
            f"«{COURSES[key]['title']}»: {COURSES[key]['course_url']}?code={COURSES[key]['access_code']}"
            for key in BUNDLE["includes"]
        )
        await update.message.reply_text(
            "¡Gracias! 🎉 Оплата прошла успешно.\n\n"
            f"Вот доступ ко всем курсам:\n{links}\n\n"
            "Открой ссылки на телефоне или компьютере — доступ остаётся навсегда. "
            "Если потеряешь ссылки, напиши /mydostup, и я пришлю их снова.\n\n"
            "¡Buena suerte! 🇦🇷"
        )
        return

    course = COURSES.get(course_key)
    if not course:
        await update.message.reply_text(
            "Оплата прошла, но не удалось определить курс. Напиши мне, разберёмся."
        )
        return
    save_buyer(user_id, course_key)
    link = course["course_url"] + "?code=" + course["access_code"]
    await update.message.reply_text(
        "¡Gracias! 🎉 Оплата прошла успешно.\n\n"
        f"Вот твой доступ к курсу «{course['title']}»:\n{link}\n\n"
        "Открой ссылку на телефоне или компьютере — доступ остаётся навсегда. "
        "Если потеряешь ссылку, напиши /mydostup, и я пришлю её снова.\n\n"
        "¡Buena suerte! 🇦🇷"
    )

async def mydostup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    buyers = load_buyers()
    owned = buyers.get(user_id, [])
    if not owned:
        await update.message.reply_text(
            "Пока не вижу твоей оплаты. Нажми /start и купи курс, "
            "а если ты уже платил — напиши мне, разберёмся."
        )
        return
    lines = ["Твои курсы:"]
    for key in owned:
        course = COURSES.get(key)
        if course:
            link = course["course_url"] + "?code=" + course["access_code"]
            lines.append(f"«{course['title']}»: {link}")
    await update.message.reply_text("\n".join(lines))

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
    logging.info("Бот запущен.")
    app.run_polling()

if __name__ == "__main__":
    main()
