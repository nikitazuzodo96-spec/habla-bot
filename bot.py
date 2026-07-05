"""
Habla Argentina — бот для продажи доступа к курсу через Telegram Stars.

Что делает:
  /start        — приветствие и кнопка "Купить курс"
  оплата Stars  — после успешной оплаты бот присылает ссылку на курс
  /mydostup     — повторно прислать ссылку тем, кто уже оплатил

Настройки ниже (BOT_TOKEN, PRICE_STARS, COURSE_URL) — меняются в одном месте.
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

# Цена в звёздах Telegram Stars.
# Курс на момент настройки: 500 звёзд = 849 ₽, т.е. 1 звезда ≈ 1.70 ₽.
# 580 звёзд ≈ 990 ₽. Курс плавает — при необходимости подстрой это число.
PRICE_STARS = 580

# Ссылка на курс, которую бот присылает после оплаты.
COURSE_URL = "https://hablaargentina.com/app.html"

# Название и описание товара (видит покупатель на экране оплаты).
PRODUCT_TITLE = "Курс «Habla Argentina»"
PRODUCT_DESC = "Полный доступ навсегда: 15 уроков, 8 диалогов, озвучка и умное повторение."

# Файл, где хранится список оплативших (id пользователей).
BUYERS_FILE = "buyers.json"

# ============ ХРАНИЛИЩЕ ОПЛАТИВШИХ ============

def load_buyers():
    try:
        with open(BUYERS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_buyer(user_id):
    buyers = load_buyers()
    buyers.add(user_id)
    try:
        with open(BUYERS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(buyers), f)
    except Exception as e:
        logging.error("Не удалось сохранить покупателя: %s", e)

# ============ ЛОГИКА БОТА ============

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

WELCOME = (
    "¡Hola! 🇦🇷\n\n"
    "Это бот курса *Habla Argentina* — практический аргентинский испанский "
    "для тех, кто только приехал.\n\n"
    "15 уроков, 8 диалогов-симуляций, озвучка и умное повторение. "
    "Доступ навсегда.\n\n"
    "Нажми кнопку ниже, чтобы получить курс 👇"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"Купить курс — {PRICE_STARS} ⭐", callback_data="buy")]]
    )
    await update.message.reply_text(
        WELCOME, parse_mode="Markdown", reply_markup=keyboard
    )

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Для Telegram Stars: currency="XTR", provider_token пустой.
    prices = [LabeledPrice(label=PRODUCT_TITLE, amount=PRICE_STARS)]
    await context.bot.send_invoice(
        chat_id=query.from_user.id,
        title=PRODUCT_TITLE,
        description=PRODUCT_DESC,
        payload="habla_course_access",
        provider_token="",           # пусто — это оплата звёздами
        currency="XTR",              # XTR = Telegram Stars
        prices=prices,
        start_parameter="habla",
    )

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Telegram требует подтвердить перед списанием — всегда ok=True.
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    save_buyer(user_id)
    await update.message.reply_text(
        "¡Gracias! 🎉 Оплата прошла успешно.\n\n"
        f"Вот твой доступ к курсу:\n{COURSE_URL}\n\n"
        "Открой ссылку на телефоне или компьютере — доступ остаётся навсегда. "
        "Если потеряешь ссылку, напиши /mydostup, и я пришлю её снова.\n\n"
        "¡Buena suerte! 🇦🇷"
    )

async def mydostup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in load_buyers():
        await update.message.reply_text(
            f"Твой доступ к курсу:\n{COURSE_URL}"
        )
    else:
        await update.message.reply_text(
            "Пока не вижу твоей оплаты. Нажми /start и купи курс, "
            "а если ты уже платил — напиши мне, разберёмся."
        )

def main():
    if not BOT_TOKEN or "ВСТАВЬ" in BOT_TOKEN:
        raise SystemExit("Ошибка: не задан BOT_TOKEN. Вставь токен от @BotFather.")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mydostup", mydostup))
    app.add_handler(CallbackQueryHandler(buy, pattern="^buy$"))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(
        MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment)
    )
    logging.info("Бот запущен.")
    app.run_polling()

if __name__ == "__main__":
    main()
