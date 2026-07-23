"""
Habla Argentina — бот для продажи доступа к курсам. Оплата: Telegram Stars
или крипта (USDT) через @CryptoBot (Crypto Pay API).

Что делает:
  /start        — приветствие и кнопки с курсами
  выбор курса   — бот спрашивает способ оплаты: ⭐ Stars или 💎 USDT
  оплата        — после оплаты бот просит почту и создаёт личный аккаунт
                  (логин = почта, пароль генерируется автоматически)
  /mydostup     — повторно прислать логин, пароль и список купленных курсов
  /support      — ссылка на личку для вопросов и поддержки
  /visitors     — (только админ) список всех, кто заходил в бота
  /grantme      — (только админ) завести себе аккаунт со всеми курсами бесплатно
  /grant EMAIL КУРС — (только админ) подарить доступ к курсу (quickstart/a1/a2/all)

Аккаунты хранятся в Firebase (Authentication + Firestore, бесплатный тариф).
Настройки ниже (BOT_TOKEN, CRYPTO_PAY_TOKEN, курсы в COURSES, FIREBASE_*) —
меняются в одном месте.

Как подключить оплату криптой (USDT) через @CryptoBot:
  1. Открой в Telegram @CryptoBot → раздел «Crypto Pay» → «Create App».
  2. Скопируй выданный API Token и вставь его в CRYPTO_PAY_TOKEN ниже
     (или задай переменную окружения CRYPTO_PAY_TOKEN — так безопаснее).
  3. Всё, бот сам создаёт счета на оплату и проверяет их по кнопке
     «Я оплатил» (без вебхука, простым опросом Crypto Pay API).
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

# Токен Crypto Pay API от @CryptoBot (см. инструкцию в шапке файла выше).
# Пока не вставлен токен — кнопка оплаты криптой сама скажет, что недоступна,
# остальной бот при этом работает нормально (Stars продолжают работать).
CRYPTO_PAY_TOKEN = os.environ.get("CRYPTO_PAY_TOKEN", "ВСТАВЬ_СЮДА_ТОКЕН_ОТ_CRYPTOBOT")

# True — тестовая сеть (@CryptoTestnetBot, тестовые токены без реальных денег),
# False — боевая сеть (@CryptoBot, реальные платежи).
CRYPTO_TESTNET = False
CRYPTO_PAY_BASE = (
    "https://testnet-pay.crypt.bot/api/" if CRYPTO_TESTNET else "https://pay.crypt.bot/api/"
)

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
        "price_usdt": 12.79,
        "course_url": "https://hablaargentina.com/app.html",
        "button_label": "Быстрый старт — 986 ₽",
    },
    "a1": {
        "title": "Курс А1",
        "product_title": "Курс «А1»",
        "product_desc": "24 урока по официальной программе уровня А1: грамматика, voseo, живые аргентинские конструкции.",
        "price_stars": 1200,
        "price_usdt": 25.93,
        "course_url": "https://hablaargentina.com/a1.html",
        "button_label": "Курс А1 — 1999 ₽",
    },
    "a2": {
        "title": "Курс А2",
        "product_title": "Курс «А2»",
        "product_desc": "22 урока по официальной программе уровня А2: продолжение грамматики после А1, живые диалоги и тексты.",
        "price_stars": 1200,
        "price_usdt": 25.93,
        "course_url": "https://hablaargentina.com/a2.html",
        "button_label": "Курс А2 — 1999 ₽",
    },
}

# Комбо-предложение: все три курса вместе со скидкой 30% от суммы цен по отдельности.
# 580 + 1200 + 1200 = 2980 звёзд; 2980 * 0.7 = 2086 звёзд.
BUNDLE = {
    "title": "Все три курса",
    "product_title": "Все три курса «Быстрый старт» + «А1» + «А2» (-30%)",
    "product_desc": "Полный доступ навсегда ко всем трём курсам сразу, дешевле на 30%, чем покупать по отдельности.",
    "price_stars": 2086,
    "price_usdt": 45.25,
    "button_label": "🔥 Все три курса со скидкой 30% — 3489 ₽",
    "includes": ["quickstart", "a1", "a2"],
}

# Личный Telegram для вопросов и поддержки.
SUPPORT_URL = "https://t.me/Hablaargentina"

# Твой личный Telegram user_id (число) — только ты сможешь смотреть список
# посетителей командой /visitors. Узнать свой id можно у бота @userinfobot.
# Лучше задать через переменную окружения ADMIN_ID.
ADMIN_ID = os.environ.get("ADMIN_ID", "")

# Файл, где хранится информация о покупателях (user_id -> email/пароль/курсы).
BUYERS_FILE = "buyers.json"

# Файл-лог всех, кто хоть раз обратился к боту (даже если не купил).
VISITORS_FILE = "visitors.json"

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

# ============ ЛОГ ПОСЕТИТЕЛЕЙ (все, кто зашёл в бота) ============
# Формат: {"<user_id>": {"username":..., "name":..., "first_seen":..., "last_seen":..., "visits": N}}
import datetime

def load_visitors():
    try:
        with open(VISITORS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_visitors(visitors):
    try:
        with open(VISITORS_FILE, "w", encoding="utf-8") as f:
            json.dump(visitors, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error("Не удалось сохранить посетителей: %s", e)

def log_visitor(user):
    """Записывает/обновляет посетителя. user — это update.effective_user."""
    if user is None:
        return
    now = datetime.datetime.now().isoformat(timespec="seconds")
    visitors = load_visitors()
    uid = str(user.id)
    name = " ".join(p for p in [user.first_name, user.last_name] if p)
    rec = visitors.get(uid, {"first_seen": now, "visits": 0})
    rec["username"] = user.username or ""
    rec["name"] = name
    rec["last_seen"] = now
    rec["visits"] = rec.get("visits", 0) + 1
    visitors[uid] = rec
    save_visitors(visitors)

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

# ============ CRYPTO PAY API (@CryptoBot) ============

def crypto_configured():
    return bool(CRYPTO_PAY_TOKEN) and "ВСТАВЬ" not in CRYPTO_PAY_TOKEN

def crypto_create_invoice(amount, asset, description, payload):
    resp = requests.post(
        CRYPTO_PAY_BASE + "createInvoice",
        headers={"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN},
        json={
            "asset": asset,
            "amount": str(amount),
            "description": description,
            "payload": payload,
            "expires_in": 3600,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(data)
    return data["result"]

def crypto_get_invoice(invoice_id):
    resp = requests.get(
        CRYPTO_PAY_BASE + "getInvoices",
        headers={"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN},
        params={"invoice_ids": str(invoice_id)},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(data)
    items = data["result"]["items"]
    return items[0] if items else None

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
    buttons.append([InlineKeyboardButton("👩‍💻 Поддержка", url=SUPPORT_URL)])
    return InlineKeyboardMarkup(buttons)

def support_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("👩‍💻 Написать в поддержку", url=SUPPORT_URL)]]
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_visitor(update.effective_user)
    await update.message.reply_text(
        WELCOME, parse_mode="Markdown", reply_markup=courses_keyboard()
    )

async def grantme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Только для админа: завести себе аккаунт со всеми курсами бесплатно."""
    user_id = str(update.effective_user.id)
    if not ADMIN_ID or user_id != str(ADMIN_ID):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return
    all_courses = list(COURSES.keys())  # quickstart, a1, a2
    await complete_purchase(update.message.reply_text, update.effective_user.id, all_courses, context)

async def grant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Только для админа: подарить кому-то доступ к конкретному курсу (или всем).
    Использование:
      /grant email@почта quickstart   — только Быстрый старт
      /grant email@почта a1           — только А1
      /grant email@почта a2           — только А2
      /grant email@почта all          — все три курса
    Создаёт аккаунт и присылает логин/пароль + ссылку на курс, которые админ
    пересылает получателю (для рекламы, блогеров, розыгрышей)."""
    user_id = str(update.effective_user.id)
    if not ADMIN_ID or user_id != str(ADMIN_ID):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Использование: /grant email@почта КУРС\n\n"
            "КУРС — один из: quickstart, a1, a2, all\n\n"
            "Примеры:\n"
            "/grant blogger@mail.com quickstart — подарить Быстрый старт\n"
            "/grant blogger@mail.com a1 — подарить А1\n"
            "/grant blogger@mail.com all — подарить все три"
        )
        return

    email = args[0].strip()
    course_arg = args[1].strip().lower()

    if not EMAIL_RE.match(email):
        await update.message.reply_text("Не похоже на почту. Пример: /grant name@mail.com a1")
        return

    if course_arg == "all":
        granted = list(COURSES.keys())
    elif course_arg in COURSES:
        granted = [course_arg]
    else:
        await update.message.reply_text(
            "Неизвестный курс. Доступны: quickstart, a1, a2, all"
        )
        return

    password = generate_password()
    try:
        create_account_and_grant(email, password, granted)
    except requests.HTTPError as e:
        logging.error("grant signUp failed: %s", e)
        await update.message.reply_text(
            "Не удалось создать аккаунт на эту почту — возможно, она уже используется. "
            "Попробуй другую почту."
        )
        return
    except Exception as e:
        logging.error("grant failed: %s", e)
        await update.message.reply_text("Что-то пошло не так, попробуй ещё раз через минуту.")
        return

    names = ", ".join(f"«{COURSES[k]['title']}»" for k in granted)
    links = "\n".join(COURSES[k]["course_url"] for k in granted)
    await update.message.reply_text(
        "Готово! Подарочный доступ создан 🎁\n\n"
        f"Логин: {email}\n"
        f"Пароль: {password}\n\n"
        f"Курс: {names}\n"
        f"Ссылка: {links}\n\n"
        "Перешли эти данные человеку — он откроет ссылку и введёт логин с паролем."
    )

async def visitors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Только для админа: показать список всех, кто заходил в бота."""
    user_id = str(update.effective_user.id)
    if not ADMIN_ID or user_id != str(ADMIN_ID):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    data = load_visitors()
    total = len(data)
    if total == 0:
        await update.message.reply_text("Пока нет ни одного посетителя.")
        return

    # Сортируем по последнему заходу, показываем последние 30.
    items = sorted(data.items(), key=lambda kv: kv[1].get("last_seen", ""), reverse=True)
    lines = [f"👥 Всего посетителей: {total}\n\nПоследние 30:"]
    for uid, rec in items[:30]:
        uname = f"@{rec['username']}" if rec.get("username") else "(без username)"
        name = rec.get("name") or "—"
        seen = rec.get("last_seen", "")[:10]
        lines.append(f"• {name} {uname} · id {uid} · {seen} · заходов {rec.get('visits', 1)}")
    await update.message.reply_text("\n".join(lines))

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Есть вопрос по курсу, доступу или оплате?\n"
        "Напиши прямо в личку — отвечаю обычно в течение нескольких часов.",
        reply_markup=support_keyboard(),
    )

def _course_or_bundle(course_key):
    if course_key == "bundle":
        return BUNDLE
    return COURSES.get(course_key)

async def choose_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    course_key = query.data.split(":", 1)[1]
    item = _course_or_bundle(course_key)
    if not item:
        return

    buttons = [
        [InlineKeyboardButton(
            f"⭐ Telegram Stars — {item['price_stars']}", callback_data=f"paystars:{course_key}"
        )],
    ]
    if crypto_configured():
        buttons.append([InlineKeyboardButton(
            f"💎 USDT (крипта) — {item['price_usdt']}", callback_data=f"paycrypto:{course_key}"
        )])
    buttons.append([InlineKeyboardButton("👩‍💻 Поддержка", url=SUPPORT_URL)])

    await query.message.reply_text(
        f"Как оплатить «{item['product_title']}»?",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def pay_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    course_key = query.data.split(":", 1)[1]
    item = _course_or_bundle(course_key)
    if not item:
        return
    payload = "habla_course_bundle" if course_key == "bundle" else f"habla_course_{course_key}"
    # Для Telegram Stars: currency="XTR", provider_token пустой.
    prices = [LabeledPrice(label=item["product_title"], amount=item["price_stars"])]
    await context.bot.send_invoice(
        chat_id=query.from_user.id,
        title=item["product_title"],
        description=item["product_desc"],
        payload=payload,
        provider_token="",           # пусто — это оплата звёздами
        currency="XTR",              # XTR = Telegram Stars
        prices=prices,
        start_parameter="habla",
    )

async def pay_crypto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    course_key = query.data.split(":", 1)[1]
    item = _course_or_bundle(course_key)
    if not item:
        return

    if not crypto_configured():
        await query.message.reply_text(
            "Оплата криптой сейчас недоступна, напиши в поддержку — разберёмся.",
            reply_markup=support_keyboard(),
        )
        return

    payload = "habla_course_bundle" if course_key == "bundle" else f"habla_course_{course_key}"
    try:
        invoice = crypto_create_invoice(
            item["price_usdt"], "USDT", item["product_title"], payload
        )
    except Exception as e:
        logging.error("Не удалось создать crypto-инвойс: %s", e)
        await query.message.reply_text(
            "Не получилось создать счёт на оплату. Попробуй ещё раз через минуту "
            "или напиши в поддержку.",
            reply_markup=support_keyboard(),
        )
        return

    pay_url = invoice.get("bot_invoice_url") or invoice.get("pay_url") or invoice.get("mini_app_invoice_url")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 Оплатить в @CryptoBot", url=pay_url)],
        [InlineKeyboardButton(
            "✅ Я оплатил — проверить",
            callback_data=f"checkcrypto:{invoice['invoice_id']}:{course_key}",
        )],
    ])
    await query.message.reply_text(
        f"Счёт на {item['price_usdt']} USDT создан.\n\n"
        "Оплати по кнопке ниже, а потом нажми «Я оплатил — проверить» "
        "(счёт действует 1 час).",
        reply_markup=kb,
    )

async def check_crypto_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, invoice_id, course_key = query.data.split(":", 2)

    try:
        invoice = crypto_get_invoice(invoice_id)
    except Exception as e:
        logging.error("Не удалось проверить crypto-инвойс: %s", e)
        await query.answer("Не получилось проверить оплату, попробуй чуть позже.", show_alert=True)
        return

    if not invoice or invoice.get("status") != "paid":
        await query.answer(
            "Пока не вижу оплату. Если только что заплатил — подожди немного и нажми ещё раз.",
            show_alert=True,
        )
        return

    await query.answer()
    new_courses = BUNDLE["includes"] if course_key == "bundle" else [course_key]
    await complete_purchase(query.message.reply_text, query.from_user.id, new_courses, context)

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Telegram требует подтвердить перед списанием — всегда ok=True.
    await update.pre_checkout_query.answer(ok=True)

async def complete_purchase(reply, user_id, new_courses, context: ContextTypes.DEFAULT_TYPE):
    """Общая логика после успешной оплаты (и Stars, и крипта): выдать курсы,
    завести аккаунт или обновить существующий. `reply(text)` — функция отправки
    сообщения пользователю (update.message.reply_text или query.message.reply_text)."""
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
        await reply(
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
    await reply(
        "¡Gracias! 🎉 Оплата прошла успешно.\n\n"
        "Последний шаг — напиши свою почту (email). На неё я заведу личный аккаунт "
        "для входа на сайт с курсом (это займёт секунду):"
    )

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = update.message.successful_payment.invoice_payload
    course_key = payload.replace("habla_course_", "")
    user_id = update.message.from_user.id
    new_courses = BUNDLE["includes"] if course_key == "bundle" else [course_key]
    await complete_purchase(update.message.reply_text, user_id, new_courses, context)

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
            "используется другим покупателем. Напиши другую почту, или напиши в "
            "поддержку, разберёмся:",
            reply_markup=support_keyboard(),
        )
        return
    except Exception as e:
        logging.error("Ошибка при создании аккаунта: %s", e)
        await update.message.reply_text(
            "Что-то пошло не так при создании аккаунта. Попробуй ещё раз через минуту "
            "или напиши в поддержку.",
            reply_markup=support_keyboard(),
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
            "а если ты уже платил — напиши в поддержку, разберёмся.",
            reply_markup=support_keyboard(),
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
    app.add_handler(CommandHandler("support", support))
    app.add_handler(CommandHandler("visitors", visitors))
    app.add_handler(CommandHandler("grantme", grantme))
    app.add_handler(CommandHandler("grant", grant))
    app.add_handler(CallbackQueryHandler(choose_payment, pattern="^buy:"))
    app.add_handler(CallbackQueryHandler(pay_stars, pattern="^paystars:"))
    app.add_handler(CallbackQueryHandler(pay_crypto, pattern="^paycrypto:"))
    app.add_handler(CallbackQueryHandler(check_crypto_payment, pattern="^checkcrypto:"))
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
