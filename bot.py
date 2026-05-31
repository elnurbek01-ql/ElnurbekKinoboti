import asyncio
import sqlite3
import os
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, InlineQuery,
    InlineQueryResultCachedVideo, InlineQueryResultCachedPhoto,
    InlineQueryResultArticle,
    InputTextMessageContent, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# =================== SOZLAMALAR ===================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6884014716"))
START_IMAGE_PATH = "start.jpg"

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# =================== DATABASE ======================
DB_PATH = "kino.db"
db = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS movies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE,
    title TEXT,
    file_id TEXT,
    views INTEGER DEFAULT 0,
    protect_forward INTEGER DEFAULT 0,
    premium_only INTEGER DEFAULT 0
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS serials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE,
    title TEXT,
    file_id TEXT
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS saved (
    user_id INTEGER,
    movie_id TEXT
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS premium_users (
    user_id INTEGER PRIMARY KEY,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP,
    expiry_at TEXT,
    warned INTEGER DEFAULT 0
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS ads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT,
    file_id TEXT,
    file_type TEXT DEFAULT 'text',
    active INTEGER DEFAULT 1
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS payment_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    plan_type TEXT,
    plan_amount INTEGER,
    photo_file_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending'
)
""")

# Eski bazalarda ustunlar yo'q bo'lishi mumkin — xavfsiz qo'shamiz
for col_sql in [
    "ALTER TABLE movies ADD COLUMN views INTEGER DEFAULT 0",
    "ALTER TABLE movies ADD COLUMN protect_forward INTEGER DEFAULT 0",
    "ALTER TABLE movies ADD COLUMN premium_only INTEGER DEFAULT 0",
    "ALTER TABLE movies ADD COLUMN poster_file_id TEXT DEFAULT ''",
    "ALTER TABLE premium_users ADD COLUMN expiry_at TEXT",
    "ALTER TABLE premium_users ADD COLUMN warned INTEGER DEFAULT 0",
]:
    try:
        cur.execute(col_sql)
    except Exception:
        pass

# Default sozlamalar
cur.execute("INSERT OR IGNORE INTO settings VALUES ('global_protect_forward', '0')")
cur.execute("INSERT OR IGNORE INTO channels (username) VALUES ('@kinolashamz')")
cur.execute("""INSERT OR IGNORE INTO settings VALUES ('start_text',
'👋 Assalomu alaykum {name}!\n\n🎬 Botimiz orqali siz:\n\n🔎 Inline qidiruv — kinolarni tez topish\n🎬 Barcha filmlar — hamma kinolar ro\u2019yxati\n🏆 Top kinolar — eng ko\u2019p ko\u2019rilganlar\n💾 Saqlanganlar — o\u2019zingiz saqlagan kinolar\n💎 Premium — maxsus kontentlar\n📟 Kod orqali — kino kodini yuboring\n\n👇 Kerakli bo\u2019limni tanlang:')""")
cur.execute("INSERT OR IGNORE INTO settings VALUES ('start_photo_id', '')")
cur.execute("INSERT OR IGNORE INTO settings VALUES ('btn_1_text', '🔍 Inline qidiruv')")
cur.execute("INSERT OR IGNORE INTO settings VALUES ('btn_2_text', '🎬 Barcha filmlar')")
cur.execute("INSERT OR IGNORE INTO settings VALUES ('btn_3_text', '🏆 Top kinolar')")
cur.execute("INSERT OR IGNORE INTO settings VALUES ('btn_4_text', '💾 Saqlanganlar')")
cur.execute("INSERT OR IGNORE INTO settings VALUES ('btn_5_text', '💎 Premium')")
cur.execute("INSERT OR IGNORE INTO settings VALUES ('btn_6_text', '🆘 24/7 Support')")
cur.execute("INSERT OR IGNORE INTO settings VALUES ('menu_cols', '2')")
cur.execute("INSERT OR IGNORE INTO settings VALUES ('admin_card', '')")
db.commit()


# =================== YORDAMCHI FUNKSIYALAR ===================
def get_setting(key, default="0"):
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    return row[0] if row else default


def is_premium(user_id):
    cur.execute("SELECT expiry_at FROM premium_users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row:
        return False
    expiry_at = row[0]
    if expiry_at is None:
        return True
    try:
        exp = datetime.fromisoformat(expiry_at)
        return exp > datetime.now()
    except Exception:
        return False


def should_protect(movie_protect_forward):
    if get_setting("global_protect_forward") == "1":
        return True
    return movie_protect_forward == 1


def premium_expiry_text(user_id):
    cur.execute("SELECT expiry_at FROM premium_users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row or not row[0]:
        return "♾ Muddatsiz"
    try:
        exp = datetime.fromisoformat(row[0])
        delta = exp - datetime.now()
        if delta.total_seconds() <= 0:
            return "❌ Muddati tugagan"
        days = delta.days
        hours = delta.seconds // 3600
        return f"⏳ {days} kun {hours} soat qoldi ({exp.strftime('%d.%m.%Y %H:%M')})"
    except Exception:
        return "—"


# =================== OBUNA TEKSHIRISH ===================
def get_channels():
    cur.execute("SELECT username FROM channels")
    return [r[0] for r in cur.fetchall()]


async def check_sub(user_id):
    channels = get_channels()
    if not channels:
        return True
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception:
            pass
    return True


async def get_sub_keyboard():
    channels = get_channels()
    kb = InlineKeyboardBuilder()
    for ch in channels:
        name = ch.lstrip("@")
        kb.row(InlineKeyboardButton(text=f"📢 {ch}", url=f"https://t.me/{name}"))
    kb.row(InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub"))
    return kb


def _find_by_code(code: str):
    cur.execute(
        "SELECT id, title, file_id, protect_forward, premium_only FROM movies "
        "WHERE code=? OR (code GLOB '[0-9]*' AND CAST(code AS INTEGER)=CAST(? AS INTEGER))",
        (code, code)
    )
    row = cur.fetchone()
    if row:
        return row, "movie"
    cur.execute(
        "SELECT id, title, file_id, 0, 0 FROM serials "
        "WHERE code=? OR (code GLOB '[0-9]*' AND CAST(code AS INTEGER)=CAST(? AS INTEGER))",
        (code, code)
    )
    row = cur.fetchone()
    return (row, "serial") if row else (None, None)


async def send_movie_by_code(chat_id: int, code: str, user_id: int):
    movie, _ = _find_by_code(code)
    if not movie:
        await bot.send_message(chat_id, f"❌ <code>{code}</code> kodli kino topilmadi.", parse_mode="HTML")
        return
    movie_id, title, file_id, protect_forward, premium_only = movie
    if premium_only and not is_premium(user_id):
        await bot.send_message(
            chat_id,
            "💎 Bu kino faqat Premium foydalanuvchilar uchun!\n"
            "Premium olish uchun adminga murojaat qiling."
        )
        return
    cur.execute("UPDATE movies SET views = views + 1 WHERE id=?", (movie_id,))
    db.commit()
    kb = InlineKeyboardBuilder()
    kb.button(text="💾 Saqlash", callback_data=f"save_{movie_id}")
    await bot.send_video(
        chat_id, file_id,
        caption=f"🎬 {title}\n🔢 Kod: {code}",
        reply_markup=kb.as_markup(),
        protect_content=should_protect(protect_forward)
    )
    await send_active_ad(chat_id)


async def send_active_ad(chat_id):
    cur.execute("SELECT text, file_id, file_type FROM ads WHERE active=1 ORDER BY RANDOM() LIMIT 1")
    ad = cur.fetchone()
    if not ad:
        return
    ad_text, file_id, file_type = ad
    try:
        if file_type == "photo" and file_id:
            await bot.send_photo(chat_id, file_id, caption=ad_text)
        elif file_type == "video" and file_id:
            await bot.send_video(chat_id, file_id, caption=ad_text)
        else:
            await bot.send_message(chat_id, ad_text)
    except Exception:
        pass


# =================== VAQTINCHALIK HOLAT ===================
admin_state = {}


# =================== PREMIUM MUDDAT TANLASH ===================
def plan_duration_label(plan_type, amount):
    if plan_type == "kunlik":
        return f"{amount} kunlik"
    elif plan_type == "haftalik":
        return f"{amount} haftalik"
    elif plan_type == "oylik":
        return f"{amount} oylik"
    elif plan_type == "yillik":
        return f"{amount} yillik"
    return f"{amount} {plan_type}"


def calc_expiry(plan_type, amount):
    now = datetime.now()
    if plan_type == "kunlik":
        return now + timedelta(days=amount)
    elif plan_type == "haftalik":
        return now + timedelta(weeks=amount)
    elif plan_type == "oylik":
        return now + timedelta(days=amount * 30)
    elif plan_type == "yillik":
        return now + timedelta(days=amount * 365)
    return now + timedelta(days=amount)


def premium_plan_keyboard(prefix="adminplan", uid=None):
    kb = InlineKeyboardBuilder()
    uid_part = f"_{uid}" if uid else ""
    kb.row(InlineKeyboardButton(text="📅 Kunlik", callback_data=f"{prefix}_type_kunlik{uid_part}"))
    kb.row(InlineKeyboardButton(text="📅 Haftalik", callback_data=f"{prefix}_type_haftalik{uid_part}"))
    kb.row(InlineKeyboardButton(text="📅 Oylik", callback_data=f"{prefix}_type_oylik{uid_part}"))
    kb.row(InlineKeyboardButton(text="📅 Yillik", callback_data=f"{prefix}_type_yillik{uid_part}"))
    return kb


def plan_amount_keyboard(plan_type, prefix="adminplan", uid=None):
    kb = InlineKeyboardBuilder()
    if plan_type == "kunlik":
        amounts = list(range(1, 11))
    elif plan_type == "haftalik":
        amounts = list(range(1, 11))
    elif plan_type == "oylik":
        amounts = list(range(1, 13))
    elif plan_type == "yillik":
        amounts = list(range(1, 11))
    else:
        amounts = list(range(1, 11))

    uid_part = f"_{uid}" if uid else ""
    btns = [InlineKeyboardButton(text=str(a), callback_data=f"{prefix}_amt_{plan_type}_{a}{uid_part}")
            for a in amounts]
    for i in range(0, len(btns), 5):
        kb.row(*btns[i:i+5])
    return kb


# =================== ASOSIY MENU ===================
SUPPORT_USERNAME = "@getch_support"


def main_menu_kb():
    b1 = get_setting("btn_1_text", "🔍 Inline qidiruv")
    b2 = get_setting("btn_2_text", "🎬 Barcha filmlar")
    b3 = get_setting("btn_3_text", "🏆 Top kinolar")
    b4 = get_setting("btn_4_text", "💾 Saqlanganlar")
    b5 = get_setting("btn_5_text", "💎 Premium")
    b6 = get_setting("btn_6_text", "🆘 24/7 Support")
    cols = get_setting("menu_cols", "2")

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=b1, switch_inline_query_current_chat=""))
    if cols == "1":
        kb.row(InlineKeyboardButton(text=b2, callback_data="all_movies"))
        kb.row(InlineKeyboardButton(text=b3, callback_data="top_movies"))
        kb.row(InlineKeyboardButton(text=b4, callback_data="saved_movies"))
        kb.row(InlineKeyboardButton(text=b5, callback_data="premium_info"))
    else:
        kb.row(
            InlineKeyboardButton(text=b2, callback_data="all_movies"),
            InlineKeyboardButton(text=b3, callback_data="top_movies"),
        )
        kb.row(
            InlineKeyboardButton(text=b4, callback_data="saved_movies"),
            InlineKeyboardButton(text=b5, callback_data="premium_info"),
        )
    kb.row(InlineKeyboardButton(text=b6, callback_data="support"))
    return kb


# =================== START ===================
@dp.message(F.text.startswith("/start"))
async def start(msg: Message):
    user_name = msg.from_user.full_name

    parts = msg.text.strip().split(maxsplit=1)
    deep_code = parts[1].strip() if len(parts) > 1 else ""

    if not await check_sub(msg.from_user.id):
        kb = await get_sub_keyboard()
        html_link_sub = f'<a href="tg://user?id={msg.from_user.id}">{msg.from_user.full_name}</a>'
        text_msg = (
            f"👋 Assalomu alaykum {html_link_sub}\n"
            "🎬 Botdagi eng zo'r filmlarni tomosha qilish uchun faqat 1ta rasmiy kanalimizga obuna bo'lishingiz kerak!\n"
            "💡 Kanalga obuna bo'lgach, siz barcha filmlarga kirish huquqiga ega bo'lasiz!"
        )
        if deep_code:
            admin_state[f"deeplink_{msg.from_user.id}"] = deep_code
        photo_id = get_setting("start_photo_id", "")
        if photo_id:
            await msg.answer_photo(photo_id, caption=text_msg,
                                   reply_markup=kb.as_markup(), parse_mode="HTML")
        else:
            await msg.answer(text_msg, reply_markup=kb.as_markup(), parse_mode="HTML")
        return

    cur.execute("INSERT OR IGNORE INTO users VALUES (?,?)", (msg.from_user.id, msg.from_user.username))
    db.commit()
    try:
        await bot.send_message(ADMIN_ID, f"🆕 Yangi foydalanuvchi\n👤 {user_name}\n🆔 {msg.from_user.id}")
    except Exception:
        pass

    premium_badge = " 💎" if is_premium(msg.from_user.id) else ""
    html_link = f'<a href="tg://user?id={msg.from_user.id}">{msg.from_user.full_name}</a>{premium_badge}'
    start_text = get_setting("start_text", "👋 Xush kelibsiz!")
    text_msg = start_text.replace("{name}", html_link)
    photo_id = get_setting("start_photo_id", "")
    if photo_id:
        await msg.answer_photo(photo_id, caption=text_msg,
                               reply_markup=main_menu_kb().as_markup(), parse_mode="HTML")
    else:
        await msg.answer(text_msg, reply_markup=main_menu_kb().as_markup(), parse_mode="HTML")

    if deep_code:
        await send_movie_by_code(msg.chat.id, deep_code, msg.from_user.id)


# ============== OBUNA TEKSHIRISH CALLBACK ==============
@dp.callback_query(F.data == "check_sub")
async def check_subscription(call: CallbackQuery):
    user_name = call.from_user.full_name

    if await check_sub(call.from_user.id):
        cur.execute("INSERT OR IGNORE INTO users VALUES (?,?)",
                    (call.from_user.id, call.from_user.username))
        db.commit()
        try:
            await bot.send_message(ADMIN_ID,
                f"🆕 Yangi foydalanuvchi\n👤 {user_name}\n🆔 {call.from_user.id}")
        except Exception:
            pass

        premium_badge = " 💎" if is_premium(call.from_user.id) else ""
        html_link = f'<a href="tg://user?id={call.from_user.id}">{user_name}</a>{premium_badge}'
        start_text = get_setting("start_text", "👋 Xush kelibsiz!")
        text_msg = start_text.replace("{name}", html_link)
        photo_id = get_setting("start_photo_id", "")
        if photo_id:
            await call.message.answer_photo(photo_id, caption=text_msg,
                                            reply_markup=main_menu_kb().as_markup(),
                                            parse_mode="HTML")
            await call.message.delete()
        else:
            await call.message.edit_text(text_msg, reply_markup=main_menu_kb().as_markup(),
                                         parse_mode="HTML")

        saved_code = admin_state.pop(f"deeplink_{call.from_user.id}", None)
        if saved_code:
            await send_movie_by_code(call.message.chat.id, saved_code, call.from_user.id)
    else:
        await call.answer("❌ Obuna bo'lmadingiz", show_alert=True)


# =================== INLINE QIDIRUV ===================
@dp.inline_query()
async def inline_search(query: InlineQuery):
    text = query.query.strip()
    results = []
    pro_mode = get_setting("pro_inline", "0") == "1"

    if pro_mode:
        # ---- PRO REJIM: poster bo'lsa GRID (CachedPhoto), bo'lmasa LIST (CachedVideo) ----
        if text:
            cur.execute(
                "SELECT id, title, file_id, code, premium_only, poster_file_id FROM movies "
                "WHERE title LIKE ? OR code LIKE ? ORDER BY id DESC LIMIT 50",
                (f"%{text}%", f"%{text}%")
            )
        else:
            cur.execute(
                "SELECT id, title, file_id, code, premium_only, poster_file_id FROM movies ORDER BY id DESC LIMIT 50"
            )
        movies = cur.fetchall()
        for m in movies:
            if m[4] and not is_premium(query.from_user.id):
                continue
            poster = m[5] if m[5] else ""
            if poster:
                # GRID ko'rinish — poster rasm bor → CachedPhoto → 2 ustunli grid
                results.append(InlineQueryResultCachedPhoto(
                    id=f"m{m[0]}",
                    photo_file_id=poster,
                    title=m[1],
                    description=f"📽 Kod: {m[3]}",
                    caption=f"🎬 {m[1]}",
                    input_message_content=InputTextMessageContent(
                        message_text=str(m[3])
                    )
                ))
            else:
                # LIST ko'rinish — poster yo'q → Article (video xatosiz)
                results.append(InlineQueryResultArticle(
                    id=f"m{m[0]}",
                    title=f"🎬 {m[1]}",
                    description=f"📽 Kod: {m[3]}",
                    input_message_content=InputTextMessageContent(
                        message_text=str(m[3])
                    )
                ))

        if text:
            cur.execute(
                "SELECT id, title, file_id, code FROM serials "
                "WHERE title LIKE ? OR code LIKE ? ORDER BY id DESC LIMIT 25",
                (f"%{text}%", f"%{text}%")
            )
        else:
            cur.execute(
                "SELECT id, title, file_id, code FROM serials ORDER BY id DESC LIMIT 25"
            )
        serials = cur.fetchall()
        for s in serials:
            results.append(InlineQueryResultArticle(
                id=f"s{s[0]}",
                title=f"📺 {s[1]}",
                description=f"Serial | Kod: {s[3]}",
                input_message_content=InputTextMessageContent(
                    message_text=str(s[3])
                )
            ))

    else:
        # ---- ODDIY REJIM ----
        if text:
            cur.execute(
                "SELECT id, title, file_id, code FROM movies WHERE title LIKE ? OR code LIKE ? LIMIT 25",
                (f"%{text}%", f"%{text}%")
            )
            movies = cur.fetchall()
            for m in movies:
                kb = InlineKeyboardBuilder()
                kb.button(text="💾 Saqlash", callback_data=f"save_inline_{m[0]}")
                results.append(InlineQueryResultCachedVideo(
                    id=f"m{m[0]}", video_file_id=m[2], title=m[1],
                    reply_markup=kb.as_markup()
                ))

            cur.execute(
                "SELECT id, title, file_id, code FROM serials WHERE title LIKE ? OR code LIKE ? LIMIT 25",
                (f"%{text}%", f"%{text}%")
            )
            serials = cur.fetchall()
            for s in serials:
                kb = InlineKeyboardBuilder()
                kb.button(text="💾 Saqlash", callback_data=f"save_inline_{s[0]}")
                results.append(InlineQueryResultCachedVideo(
                    id=f"s{s[0]}", video_file_id=s[2], title=s[1],
                    reply_markup=kb.as_markup()
                ))
        else:
            cur.execute("SELECT id, title, code FROM movies ORDER BY id DESC LIMIT 30")
            movies = cur.fetchall()
            for m in movies:
                results.append(InlineQueryResultArticle(
                    id=f"ma{m[0]}",
                    title=f"🎬 {m[1]}",
                    description=f"Kod: {m[2]}",
                    input_message_content=InputTextMessageContent(
                        message_text=str(m[2])
                    )
                ))

            cur.execute("SELECT id, title, code FROM serials ORDER BY id DESC LIMIT 20")
            serials = cur.fetchall()
            for s in serials:
                results.append(InlineQueryResultArticle(
                    id=f"sa{s[0]}",
                    title=f"🎞 {s[1]}",
                    description=f"Kod: {s[2]}",
                    input_message_content=InputTextMessageContent(
                        message_text=str(s[2])
                    )
                ))

    await query.answer(results, cache_time=1, is_personal=True)


# =================== SUPPORT ===================
async def _do_support_forward(msg: Message):
    user_name = msg.from_user.full_name
    user_id = msg.from_user.id
    username = f"@{msg.from_user.username}" if msg.from_user.username else "username yo'q"
    header = (
        f"📩 Yangi support xabari\n"
        f"👤 {user_name} ({username})\n"
        f"🆔 {user_id}\n"
        f"{'—' * 20}"
    )
    try:
        reply_kb = InlineKeyboardBuilder()
        reply_kb.button(text="💬 Javob yozish", callback_data=f"reply_user_{user_id}")
        await bot.send_message(ADMIN_ID, header, reply_markup=reply_kb.as_markup())
        await msg.forward(ADMIN_ID)
        admin_state[f"support_mode_{user_id}"] = False
        await msg.answer(
            "✅ Xabaringiz adminga yuborildi!\nTez orada javob beramiz 🙏",
            reply_markup=main_menu_kb().as_markup()
        )
    except Exception:
        await msg.answer(
            "❌ Xabar yuborishda xatolik. Bevosita murojaat qiling: " + SUPPORT_USERNAME
        )


@dp.callback_query(F.data.startswith("reply_user_"), F.from_user.id == ADMIN_ID)
async def admin_reply_user_start(call: CallbackQuery):
    target_id = int(call.data.split("reply_user_")[1])
    admin_state["reply_to_user"] = target_id
    await call.message.answer(
        f"✏️ Foydalanuvchi ({target_id}) ga javob yozing:\n"
        f"(Bekor qilish uchun /cancel)"
    )
    await call.answer()


@dp.message(F.from_user.id == ADMIN_ID, F.text == "/cancel")
async def admin_cancel_reply(msg: Message):
    if admin_state.pop("reply_to_user", None):
        await msg.answer("❌ Javob bekor qilindi.")
    else:
        await msg.answer("Hech narsa bekor qilinmadi.")


# Foydalanuvchi admin javobiga "Javob yozish" tugmasini bosadi
@dp.callback_query(F.data == "user_reply_to_admin")
async def user_reply_to_admin_start(call: CallbackQuery):
    user_id = call.from_user.id
    admin_state[f"support_mode_{user_id}"] = True
    await call.message.answer(
        "✏️ Adminga javobingizni yozing:\n"
        "(Bekor qilish uchun /cancel)"
    )
    await call.answer()


# =================== KOD ORQALI KINO ===================
@dp.message(F.text.regexp(r"^\d+$"), F.from_user.id != ADMIN_ID)
async def by_code(msg: Message):
    if admin_state.get(f"support_mode_{msg.from_user.id}"):
        await _do_support_forward(msg)
        return

    if not await check_sub(msg.from_user.id):
        await msg.answer("❗ Avval obuna bo'ling")
        return

    movie, _ = _find_by_code(msg.text.strip())
    if not movie:
        await msg.answer("❌ Topilmadi")
        return

    movie_id, title, file_id, protect_forward, premium_only = movie

    if premium_only and not is_premium(msg.from_user.id):
        await msg.answer("💎 Bu kino faqat Premium foydalanuvchilar uchun!\n"
                         "Premium olish uchun adminga murojaat qiling.")
        return

    cur.execute("UPDATE movies SET views = views + 1 WHERE id=?", (movie_id,))
    db.commit()

    kb = InlineKeyboardBuilder()
    kb.button(text="💾 Saqlash", callback_data=f"save_{movie_id}")
    await bot.send_video(
        msg.chat.id, file_id,
        caption=f"🎬 {title}\n🔢 Kod: {msg.text}",
        reply_markup=kb.as_markup(),
        protect_content=should_protect(protect_forward)
    )
    await send_active_ad(msg.chat.id)


# =================== SAQLASH ===================
@dp.callback_query(F.data.startswith("save_inline_"))
async def save_inline(call: CallbackQuery):
    movie_id = call.data.split("save_inline_")[1]
    cur.execute("INSERT INTO saved (user_id, movie_id) VALUES (?,?)",
                (call.from_user.id, movie_id))
    db.commit()
    await call.answer("💾 Saqlandi")


@dp.callback_query(F.data.startswith("save_") & ~F.data.startswith("save_inline_"))
async def save_movie(call: CallbackQuery):
    movie_id = call.data.split("_")[1]
    cur.execute("INSERT INTO saved (user_id, movie_id) VALUES (?, ?)",
                (call.from_user.id, movie_id))
    db.commit()
    try:
        await bot.copy_message(
            chat_id=call.from_user.id,
            from_chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
        await call.answer("💾 Saqlandi va Saved Messages ga yuborildi")
    except Exception:
        await call.answer("❌ Xatolik yuz berdi", show_alert=True)


# =================== PREMIUM INFO ===================
@dp.callback_query(F.data == "premium_info")
async def premium_info(call: CallbackQuery):
    if is_premium(call.from_user.id):
        cur.execute("SELECT id, title, premium_only FROM movies WHERE premium_only=1 ORDER BY id ASC")
        movies = cur.fetchall()
        if not movies:
            expiry = premium_expiry_text(call.from_user.id)
            kb = InlineKeyboardBuilder()
            kb.button(text="🔄 Premiumni uzaytirish", callback_data="extend_premium_start")
            await call.message.answer(
                f"💎 Siz Premium foydalanuvchisiz!\n\n✅ Hozircha premium kino yo'q.\n{expiry}",
                reply_markup=kb.as_markup()
            )
        else:
            total_pages = (len(movies) + PAGE_SIZE - 1) // PAGE_SIZE
            text, kb = build_movie_page(movies, 0, total_pages, "prem", "💎 Premium kinolar")
            expiry = premium_expiry_text(call.from_user.id)
            kb.row(InlineKeyboardButton(text="🔄 Uzaytirish", callback_data="extend_premium_start"))
            await call.message.answer(expiry + "\n" + text, reply_markup=kb.as_markup())
    else:
        text = (
            "💎 Premium obuna\n\n"
            "Premium orqali siz:\n"
            "🎬 Maxsus premium kinolarni tomosha qilishingiz mumkin\n\n"
            "📩 Premium olish uchun adminga murojaat qiling."
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="🔄 Premium sotib olish", callback_data="extend_premium_start")
        await call.message.answer(text, reply_markup=kb.as_markup())
    await call.answer()


@dp.callback_query(F.data.startswith("prem_page_"))
async def premium_movies_page(call: CallbackQuery):
    if not is_premium(call.from_user.id):
        await call.answer("💎 Premium obuna kerak!", show_alert=True)
        return
    page = int(call.data.split("prem_page_")[1])
    cur.execute("SELECT id, title, premium_only FROM movies WHERE premium_only=1 ORDER BY id ASC")
    movies = cur.fetchall()
    if not movies:
        return await call.answer("❌ Premium kinolar yo'q", show_alert=True)
    total_pages = (len(movies) + PAGE_SIZE - 1) // PAGE_SIZE
    text, kb = build_movie_page(movies, page, total_pages, "prem", "💎 Premium kinolar")
    kb.row(InlineKeyboardButton(text="🔄 Uzaytirish", callback_data="extend_premium_start"))
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await call.message.answer(text, reply_markup=kb.as_markup())
    await call.answer()


# =================== PREMIUM UZAYTIRISH (foydalanuvchi) ===================
@dp.callback_query(F.data == "extend_premium_start")
async def extend_premium_start(call: CallbackQuery):
    await call.message.answer(
        "🔄 Premiumni uzaytirish uchun tarif turini tanlang:",
        reply_markup=premium_plan_keyboard("extplan").as_markup()
    )
    await call.answer()


@dp.callback_query(F.data.startswith("extplan_type_"))
async def extplan_type(call: CallbackQuery):
    plan_type = call.data.split("extplan_type_")[1]
    await call.message.answer(
        f"📅 <b>{plan_type.capitalize()}</b> uchun miqdorni tanlang:",
        reply_markup=plan_amount_keyboard(plan_type, "extplan").as_markup(),
        parse_mode="HTML"
    )
    await call.answer()


@dp.callback_query(F.data.startswith("extplan_amt_"))
async def extplan_amount(call: CallbackQuery):
    # format: extplan_amt_kunlik_5
    raw = call.data[len("extplan_amt_"):]
    parts = raw.rsplit("_", 1)
    plan_type = parts[0]
    amount = int(parts[1])

    admin_state[f"extplan_final_{call.from_user.id}"] = (plan_type, amount)

    card = get_setting("admin_card", "")
    card_text = f"\n💳 Karta: <code>{card}</code>" if card else "\n💳 Karta: admin bilan bog'laning"

    label = plan_duration_label(plan_type, amount)
    await call.message.answer(
        f"✅ Siz tanlagan tarif: <b>{label}</b>\n"
        f"{card_text}\n\n"
        f"📸 To'lovni amalga oshirib, skrinshot yuboring.\n"
        f"Admin tasdiqlashi bilan premium avtomatik yonadi!",
        parse_mode="HTML"
    )
    admin_state[f"awaiting_payment_screenshot_{call.from_user.id}"] = True
    await call.answer()


@dp.message(F.photo, F.from_user.id != ADMIN_ID)
async def handle_payment_screenshot(msg: Message):
    user_id = msg.from_user.id
    # Support rejimida bo'lsa — adminga forward qil
    if admin_state.get(f"support_mode_{user_id}"):
        await _do_support_forward(msg)
        return
    if not admin_state.get(f"awaiting_payment_screenshot_{user_id}"):
        return

    plan_data = admin_state.get(f"extplan_final_{user_id}")
    if not plan_data:
        await msg.answer("❌ Avval tarif tanlang.")
        return

    plan_type, amount = plan_data
    label = plan_duration_label(plan_type, amount)
    photo_file_id = msg.photo[-1].file_id

    cur.execute(
        "INSERT INTO payment_requests (user_id, plan_type, plan_amount, photo_file_id) VALUES (?,?,?,?)",
        (user_id, plan_type, amount, photo_file_id)
    )
    db.commit()
    req_id = cur.lastrowid

    admin_state.pop(f"awaiting_payment_screenshot_{user_id}", None)
    admin_state.pop(f"extplan_final_{user_id}", None)

    username = f"@{msg.from_user.username}" if msg.from_user.username else "username yo'q"
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tasdiqlash", callback_data=f"pay_approve_{req_id}")
    kb.button(text="❌ Rad etish", callback_data=f"pay_reject_{req_id}")
    kb.adjust(2)

    try:
        await bot.send_photo(
            ADMIN_ID,
            photo_file_id,
            caption=(
                f"💳 To'lov so'rovi #{req_id}\n"
                f"👤 {msg.from_user.full_name} ({username})\n"
                f"🆔 {user_id}\n"
                f"📅 Tarif: {label}"
            ),
            reply_markup=kb.as_markup()
        )
    except Exception:
        pass

    await msg.answer(
        "✅ To'lov screenshoti adminга yuborildi!\n"
        "Admin tekshirib, premiumingizni yoqib beradi. Kuting 🙏"
    )


@dp.callback_query(F.data.startswith("pay_approve_"))
async def pay_approve(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Ruxsat yo'q")
        return
    req_id = int(call.data.split("pay_approve_")[1])
    cur.execute("SELECT user_id, plan_type, plan_amount FROM payment_requests WHERE id=?", (req_id,))
    row = cur.fetchone()
    if not row:
        await call.answer("❌ So'rov topilmadi")
        return
    user_id, plan_type, amount = row

    expiry = calc_expiry(plan_type, amount)
    expiry_str = expiry.strftime("%Y-%m-%d %H:%M:%S")
    label = plan_duration_label(plan_type, amount)

    cur.execute(
        "INSERT OR REPLACE INTO premium_users (user_id, added_at, expiry_at, warned) VALUES (?,?,?,0)",
        (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), expiry_str)
    )
    cur.execute("UPDATE payment_requests SET status='approved' WHERE id=?", (req_id,))
    db.commit()

    try:
        await bot.send_message(
            user_id,
            f"🎉 Tabriklaymiz! Sizga <b>{label}</b> Premium berildi! 💎\n"
            f"⏳ Muddat: {expiry.strftime('%d.%m.%Y %H:%M')} gacha",
            parse_mode="HTML"
        )
    except Exception:
        pass

    await call.message.edit_caption(
        call.message.caption + f"\n\n✅ TASDIQLANDI — {label}"
    )
    await call.answer("✅ Premium berildi!")


@dp.callback_query(F.data.startswith("pay_reject_"))
async def pay_reject(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Ruxsat yo'q")
        return
    req_id = int(call.data.split("pay_reject_")[1])
    cur.execute("SELECT user_id FROM payment_requests WHERE id=?", (req_id,))
    row = cur.fetchone()
    if not row:
        await call.answer("❌ So'rov topilmadi")
        return
    user_id = row[0]

    cur.execute("UPDATE payment_requests SET status='rejected' WHERE id=?", (req_id,))
    db.commit()

    try:
        await bot.send_message(
            user_id,
            "❌ Afsuski, to'lovingiz tasdiqlanmadi.\n"
            "Muammo bo'lsa adminga murojaat qiling."
        )
    except Exception:
        pass

    await call.message.edit_caption(call.message.caption + "\n\n❌ RAD ETILDI")
    await call.answer("❌ Rad etildi")


# =================== 24/7 SUPPORT ===================
@dp.callback_query(F.data == "support")
async def support_menu(call: CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💬 Support bilan bog'lanish",
                                url=f"https://t.me/{SUPPORT_USERNAME[1:]}"))
    kb.row(InlineKeyboardButton(text="✉️ Bot orqali xabar yuborish",
                                callback_data="support_send"))
    await call.message.answer(
        "🆘 24/7 Support\n\n"
        "Muammo yoki savolingiz bormi?\n\n"
        f"📌 To'g'ridan-to'g'ri: {SUPPORT_USERNAME}\n"
        "📌 Yoki bot orqali xabar yuboring — adminimiz tez javob beradi!",
        reply_markup=kb.as_markup()
    )
    await call.answer()


@dp.callback_query(F.data == "support_send")
async def support_send(call: CallbackQuery):
    admin_state[f"support_mode_{call.from_user.id}"] = True
    await call.message.answer(
        "✉️ Xabaringizni yozing (matn, rasm, video — istalgan format).\n"
        "Admin imkon qadar tez javob beradi!\n\n"
        "❌ Bekor qilish uchun /cancel yozing."
    )
    await call.answer()


@dp.message(F.text == "/cancel")
async def cancel_support(msg: Message):
    if admin_state.pop(f"support_mode_{msg.from_user.id}", None):
        await msg.answer("✅ Bekor qilindi.", reply_markup=main_menu_kb().as_markup())
    else:
        await msg.answer("❌ Hech narsa bajarilmadi.")


@dp.message(~F.from_user.id.in_({ADMIN_ID}))
async def handle_support_message(msg: Message):
    if not admin_state.get(f"support_mode_{msg.from_user.id}"):
        return
    await _do_support_forward(msg)


# =================== SAHIFA YARATISH ===================
PAGE_SIZE = 10


def build_movie_page(movies, page, total_pages, prefix, title_header):
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_movies = movies[start:end]

    text = f"📋🎬 {title_header}: ({page + 1}/{total_pages})\n\n"
    kb = InlineKeyboardBuilder()

    movie_btns = []
    for i, m in enumerate(page_movies, start=start + 1):
        if len(m) > 3 and m[3]:
            text += f"{i}. 💎 {m[1]}\n"
        else:
            text += f"{i}. {m[1]}\n"
        movie_btns.append(InlineKeyboardButton(text=str(i), callback_data=f"movie_{m[0]}"))

    for j in range(0, len(movie_btns), 5):
        kb.row(*movie_btns[j:j + 5])

    text += "\nIzoh: kerakli filmni ko'rish uchun tanlang!"

    nav_btns = []
    if page > 0:
        nav_btns.append(InlineKeyboardButton(text="⬅️ Oldingi",
                                             callback_data=f"{prefix}_page_{page - 1}"))
    if page < total_pages - 1:
        nav_btns.append(InlineKeyboardButton(text="Keyingi ➡️",
                                             callback_data=f"{prefix}_page_{page + 1}"))
    if nav_btns:
        kb.row(*nav_btns)

    if page > 0:
        kb.row(InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="main_menu"))

    return text, kb


# =================== BARCHA FILMLAR ===================
@dp.callback_query(F.data == "all_movies")
async def all_movies_btn(call: CallbackQuery):
    cur.execute("SELECT id, title FROM movies ORDER BY id ASC")
    movies = cur.fetchall()
    if not movies:
        return await call.answer("❌ Kinolar yo'q", show_alert=True)
    total_pages = (len(movies) + PAGE_SIZE - 1) // PAGE_SIZE
    text, kb = build_movie_page(movies, 0, total_pages, "all", "Kinofilmlar ro'yxati")
    await call.message.answer(text, reply_markup=kb.as_markup())
    await call.answer()


@dp.callback_query(F.data.startswith("all_page_"))
async def all_movies_page(call: CallbackQuery):
    page = int(call.data.split("all_page_")[1])
    cur.execute("SELECT id, title FROM movies ORDER BY id ASC")
    movies = cur.fetchall()
    if not movies:
        return await call.answer("❌ Kinolar yo'q", show_alert=True)
    total_pages = (len(movies) + PAGE_SIZE - 1) // PAGE_SIZE
    text, kb = build_movie_page(movies, page, total_pages, "all", "Kinofilmlar ro'yxati")
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await call.message.answer(text, reply_markup=kb.as_markup())
    await call.answer()


# =================== TOP KINOLAR ===================
@dp.callback_query(F.data == "top_movies")
async def top_movies_btn(call: CallbackQuery):
    cur.execute("SELECT id, title, views FROM movies WHERE views > 0 ORDER BY views DESC")
    movies = cur.fetchall()
    if not movies:
        return await call.answer("❌ Hali ko'rilgan kinolar yo'q", show_alert=True)
    total_pages = (len(movies) + PAGE_SIZE - 1) // PAGE_SIZE
    text, kb = build_top_page(movies, 0, total_pages, "top")
    await call.message.answer(text, reply_markup=kb.as_markup())
    await call.answer()


@dp.callback_query(F.data.startswith("top_page_"))
async def top_movies_page(call: CallbackQuery):
    page = int(call.data.split("top_page_")[1])
    cur.execute("SELECT id, title, views FROM movies WHERE views > 0 ORDER BY views DESC")
    movies = cur.fetchall()
    if not movies:
        return await call.answer("❌ Hali ko'rilgan kinolar yo'q", show_alert=True)
    total_pages = (len(movies) + PAGE_SIZE - 1) // PAGE_SIZE
    text, kb = build_top_page(movies, page, total_pages, "top")
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await call.message.answer(text, reply_markup=kb.as_markup())
    await call.answer()


def build_top_page(movies, page, total_pages, prefix):
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_movies = movies[start:end]

    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    text = f"🏆 Top kinolar: ({page + 1}/{total_pages})\n\n"
    kb = InlineKeyboardBuilder()

    movie_btns = []
    for rank_offset, m in enumerate(page_movies):
        rank = start + rank_offset
        medal = medals.get(rank, f"{rank + 1}.")
        text += f"{medal} {m[1]} — 👁 {m[2]}\n"
        movie_btns.append(InlineKeyboardButton(text=str(rank + 1), callback_data=f"movie_{m[0]}"))

    for j in range(0, len(movie_btns), 5):
        kb.row(*movie_btns[j:j + 5])

    text += "\nIzoh: kerakli filmni ko'rish uchun tanlang!"

    nav_btns = []
    if page > 0:
        nav_btns.append(InlineKeyboardButton(text="⬅️ Oldingi",
                                             callback_data=f"{prefix}_page_{page - 1}"))
    if page < total_pages - 1:
        nav_btns.append(InlineKeyboardButton(text="Keyingi ➡️",
                                             callback_data=f"{prefix}_page_{page + 1}"))
    if nav_btns:
        kb.row(*nav_btns)

    if page > 0:
        kb.row(InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="main_menu"))

    return text, kb


# =================== SAQLANGANLAR ===================
@dp.callback_query(F.data == "saved_movies")
async def saved_movies_btn(call: CallbackQuery):
    cur.execute("""
        SELECT movies.id, movies.title
        FROM movies JOIN saved ON movies.id = saved.movie_id
        WHERE saved.user_id = ?
    """, (call.from_user.id,))
    movies = cur.fetchall()
    if not movies:
        return await call.answer("❌ Saqlanganlar yo'q", show_alert=True)
    total_pages = (len(movies) + PAGE_SIZE - 1) // PAGE_SIZE
    text, kb = build_movie_page(movies, 0, total_pages, "svd", "Saqlangan kinolar")
    await call.message.answer(text, reply_markup=kb.as_markup())
    await call.answer()


@dp.callback_query(F.data.startswith("svd_page_"))
async def saved_movies_page(call: CallbackQuery):
    page = int(call.data.split("svd_page_")[1])
    cur.execute("""
        SELECT movies.id, movies.title
        FROM movies JOIN saved ON movies.id = saved.movie_id
        WHERE saved.user_id = ?
    """, (call.from_user.id,))
    movies = cur.fetchall()
    if not movies:
        return await call.answer("❌ Saqlanganlar yo'q", show_alert=True)
    total_pages = (len(movies) + PAGE_SIZE - 1) // PAGE_SIZE
    text, kb = build_movie_page(movies, page, total_pages, "svd", "Saqlangan kinolar")
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await call.message.answer(text, reply_markup=kb.as_markup())
    await call.answer()


# =================== BOSH MENYU ===================
@dp.callback_query(F.data == "main_menu")
async def go_main_menu(call: CallbackQuery):
    user_name = call.from_user.full_name
    premium_badge = " 💎" if is_premium(call.from_user.id) else ""
    text = get_setting("start_text",
        f"👋 Assalomu alaykum {user_name}!\n\n🎬 Botimiz orqali siz:\n\n"
        "🔎 Inline qidiruv — kinolarni tez topish\n"
        "🎬 Barcha filmlar — hamma kinolar ro'yxati\n"
        "🏆 Top kinolar — eng ko'p ko'rilganlar\n"
        "💾 Saqlanganlar — o'zingiz saqlagan kinolar\n"
        "💎 Premium — maxsus kontentlar\n"
        "📟 Kod orqali — kino kodini yuboring\n\n"
        "👇 Kerakli bo'limni tanlang:"
    ).format(name=user_name + premium_badge)
    photo_id = get_setting("start_photo_id", "")
    try:
        if photo_id:
            await call.message.answer_photo(photo_id, caption=text,
                                            reply_markup=main_menu_kb().as_markup(),
                                            parse_mode="HTML")
        else:
            await call.message.answer(text, reply_markup=main_menu_kb().as_markup(),
                                      parse_mode="HTML")
    except Exception:
        await call.message.answer("👇 Bosh menyu:", reply_markup=main_menu_kb().as_markup())
    await call.answer()


# =================== KINO OCHISH ===================
@dp.callback_query(F.data.startswith("movie_"))
async def open_movie(call: CallbackQuery):
    movie_id = call.data.split("_")[1]
    cur.execute("SELECT title, file_id, protect_forward, premium_only FROM movies WHERE id=?",
                (movie_id,))
    movie = cur.fetchone()
    if not movie:
        return await call.answer("❌ Topilmadi", show_alert=True)

    title, file_id, protect_forward, premium_only = movie

    if premium_only and not is_premium(call.from_user.id):
        await call.answer("💎 Bu kino faqat Premium foydalanuvchilar uchun!\n"
                          "Premium olish uchun adminga murojaat qiling.", show_alert=True)
        return

    cur.execute("UPDATE movies SET views = views + 1 WHERE id=?", (movie_id,))
    db.commit()

    kb = InlineKeyboardBuilder()
    kb.button(text="💾 Saqlash", callback_data=f"save_{movie_id}")
    await bot.send_video(
        chat_id=call.message.chat.id,
        video=file_id,
        caption=f"🎬 {title}",
        reply_markup=kb.as_markup(),
        protect_content=should_protect(protect_forward)
    )
    await send_active_ad(call.message.chat.id)
    await call.answer()


# =================== ADMIN PANEL ===================
@dp.message(F.from_user.id == ADMIN_ID, F.text == "/admin")
async def admin_panel(msg: Message):
    await show_admin_panel(msg)


async def show_admin_panel(msg):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎬 Kino qo'shish", callback_data="admin_add_movie")
    kb.button(text="🗑 Kino o'chirish", callback_data="admin_delete_movie")
    kb.button(text="✏️ Kino tahrirlash", callback_data="admin_edit_movie")
    kb.button(text="📃 Kino ro'yxati", callback_data="admin_list_movies")
    kb.button(text="🎞 Serial qo'shish", callback_data="admin_add_serial")
    kb.button(text="🗑 Serial o'chirish", callback_data="admin_delete_serial")
    kb.button(text="✏️ Serial tahrirlash", callback_data="admin_edit_serial")
    kb.button(text="📃 Serial ro'yxati", callback_data="admin_list_serials")
    kb.button(text="👤 Foydalanuvchilar", callback_data="admin_users")
    kb.button(text="📊 Statistika", callback_data="admin_stats")
    kb.button(text="📣 Broadcast (tugma bilan)", callback_data="admin_broadcast_inline")
    kb.button(text="📢 Broadcast (oddiy)", callback_data="admin_broadcast_text")
    kb.button(text="💎 Premium boshqarish", callback_data="admin_premium")
    kb.button(text="🔒 Uzatish sozlamalari", callback_data="admin_forward")
    kb.button(text="📡 Majburiy obuna", callback_data="admin_channels")
    kb.button(text="📣 Reklama boshqarish", callback_data="admin_ads")
    kb.button(text="🖼 Start xabar sozlash", callback_data="admin_start_msg")
    kb.button(text="🎛 Menu tugmalari", callback_data="admin_menu_btns")
    kb.button(text="💳 Karta sozlash", callback_data="admin_set_card")
    pro_inline_on = get_setting("pro_inline", "0") == "1"
    pro_label = "🔍 Pro inline: ✅ Yoqiq" if pro_inline_on else "🔍 Pro inline: ❌ O'chiq"
    kb.button(text=pro_label, callback_data="admin_toggle_pro_inline")
    kb.button(text="🖼 Poster qo'shish", callback_data="admin_add_poster")
    kb.adjust(2)
    await msg.answer("🛠 Admin panelga xush kelibsiz!", reply_markup=kb.as_markup())


# =================== ADMIN — POSTER QO'SHISH ===================
@dp.callback_query(F.data == "admin_add_poster")
async def admin_add_poster(call: CallbackQuery):
    admin_state["awaiting_poster_code"] = "WAITING_CODE"
    await call.message.answer(
        "🖼 Qaysi filmga poster qo'shmoqchisiz?\n"
        "Film kodini yuboring (masalan: 001):"
    )
    await call.answer()


# =================== ADMIN — PRO INLINE TOGGLE ===================
@dp.callback_query(F.data == "admin_toggle_pro_inline")
async def admin_toggle_pro_inline(call: CallbackQuery):
    current = get_setting("pro_inline", "0")
    new_val = "1" if current == "0" else "0"
    cur.execute("INSERT OR REPLACE INTO settings VALUES ('pro_inline', ?)", (new_val,))
    db.commit()
    if new_val == "1":
        await call.message.answer(
            "✅ Pro inline qidiruv yoqildi!\n\n"
            "Endi foydalanuvchilar inline qidiruv orqali filmlarni poster ko'rinishida ko'radi.\n"
            "Bo'sh so'rov ham hamma filmlarni ko'rsatadi."
        )
    else:
        await call.message.answer("❌ Pro inline qidiruv o'chirildi. Oddiy rejimga qaytildi.")
    await call.answer()


# =================== ADMIN — KARTA SOZLASH ===================
@dp.callback_query(F.data == "admin_set_card")
async def admin_set_card(call: CallbackQuery):
    current = get_setting("admin_card", "")
    admin_state["admin_action"] = "set_card"
    await call.message.answer(
        f"💳 Hozirgi karta: <code>{current if current else 'Belgilanmagan'}</code>\n\n"
        "Yangi karta raqamini yuboring:",
        parse_mode="HTML"
    )
    await call.answer()


# =================== ADMIN — PREMIUM ===================
@dp.callback_query(F.data == "admin_premium")
async def admin_premium(call: CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Premium qo'shish", callback_data="premium_add")
    kb.button(text="➖ Premium o'chirish", callback_data="premium_remove")
    kb.button(text="📋 Premium ro'yxati", callback_data="premium_list")
    kb.adjust(2)
    await call.message.answer("💎 Premium boshqarish:", reply_markup=kb.as_markup())
    await call.answer()


@dp.callback_query(F.data == "premium_add")
async def premium_add_cb(call: CallbackQuery):
    admin_state["premium_action"] = "add_step1"
    await call.message.answer("💎 Premium qo'shish.\nFoydalanuvchi ID sini yuboring:")
    await call.answer()


@dp.callback_query(F.data == "premium_remove")
async def premium_remove_cb(call: CallbackQuery):
    await call.message.answer("➖ Premium o'chirish.\nFoydalanuvchi ID sini yuboring:")
    admin_state["premium_action"] = "remove"
    await call.answer()


@dp.callback_query(F.data == "premium_list")
async def premium_list_cb(call: CallbackQuery):
    cur.execute("SELECT user_id, added_at, expiry_at FROM premium_users")
    rows = cur.fetchall()
    if not rows:
        await call.message.answer("💎 Premium foydalanuvchilar yo'q")
        return
    text = "💎 Premium foydalanuvchilar:\n\n"
    now = datetime.now()
    for r in rows:
        uid, added_at, expiry_at = r
        if expiry_at:
            try:
                exp = datetime.fromisoformat(expiry_at)
                status = f"⏳ {exp.strftime('%d.%m.%Y %H:%M')} gacha"
                if exp <= now:
                    status = "❌ Tugagan"
            except Exception:
                status = expiry_at
        else:
            status = "♾ Muddatsiz"
        text += f"🆔 {uid} — {status}\n"
    await call.message.answer(text)
    await call.answer()


# =================== ADMIN — PREMIUM TARIF TANLASH ===================
# UID callback data ichiga joylashtirilgan — dp.data ga bog'liq emas
@dp.callback_query(F.data.startswith("adminplan_type_"))
async def adminplan_type(call: CallbackQuery):
    # format: adminplan_type_kunlik_12345678
    raw = call.data[len("adminplan_type_"):]
    parts = raw.rsplit("_", 1)
    if len(parts) != 2:
        await call.answer("❌ Xato format. Qaytadan boshlang.")
        return
    plan_type, uid_str = parts[0], parts[1]
    try:
        uid = int(uid_str)
    except ValueError:
        await call.answer("❌ Foydalanuvchi ID xato.")
        return
    await call.message.answer(
        f"📅 <b>{plan_type.capitalize()}</b> uchun miqdorni tanlang:\n"
        f"👤 Foydalanuvchi: <code>{uid}</code>",
        reply_markup=plan_amount_keyboard(plan_type, "adminplan", uid=uid).as_markup(),
        parse_mode="HTML"
    )
    await call.answer()


@dp.callback_query(F.data.startswith("adminplan_amt_"))
async def adminplan_amount(call: CallbackQuery):
    # format: adminplan_amt_kunlik_5_12345678
    raw = call.data[len("adminplan_amt_"):]
    parts = raw.rsplit("_", 2)
    if len(parts) != 3:
        await call.answer("❌ Xato format. Qaytadan boshlang.")
        return
    plan_type, amount_str, uid_str = parts[0], parts[1], parts[2]
    try:
        amount = int(amount_str)
        uid = int(uid_str)
    except ValueError:
        await call.answer("❌ Xato ma'lumot.")
        return

    expiry = calc_expiry(plan_type, amount)
    expiry_str = expiry.strftime("%Y-%m-%d %H:%M:%S")
    label = plan_duration_label(plan_type, amount)

    cur.execute(
        "INSERT OR REPLACE INTO premium_users (user_id, added_at, expiry_at, warned) VALUES (?,?,?,0)",
        (uid, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), expiry_str)
    )
    db.commit()
    admin_state["premium_action"] = None

    await call.message.answer(
        f"✅ <code>{uid}</code> ga <b>{label}</b> Premium berildi! 💎\n"
        f"⏳ Muddat: {expiry.strftime('%d.%m.%Y %H:%M')} gacha",
        parse_mode="HTML"
    )
    try:
        await bot.send_message(
            uid,
            f"🎉 Sizga <b>{label}</b> Premium berildi! 💎\n"
            f"⏳ Muddat: {expiry.strftime('%d.%m.%Y %H:%M')} gacha",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer()


# =================== ADMIN — START XABAR SOZLASH ===================
@dp.callback_query(F.data == "admin_start_msg")
async def admin_start_msg(call: CallbackQuery):
    current_text = get_setting("start_text", "")
    photo_id = get_setting("start_photo_id", "")
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Matnni tahrirlash", callback_data="start_edit_text")
    kb.button(text="🖼 Rasm qo'shish/almashtirish", callback_data="start_add_photo")
    if photo_id:
        kb.button(text="🗑 Rasmni o'chirish", callback_data="start_del_photo")
    kb.adjust(1)
    preview = current_text[:300] + ("..." if len(current_text) > 300 else "")
    photo_status = "✅ Rasm bor" if photo_id else "❌ Rasm yo'q"
    await call.message.answer(
        f"🖼 Start xabar sozlamalari\n\n"
        f"📷 Rasm holati: {photo_status}\n\n"
        f"📝 Joriy matn:\n{preview}\n\n"
        f"💡 Matndagi {{name}} — foydalanuvchi ismi bilan almashtiriladi.",
        reply_markup=kb.as_markup()
    )
    await call.answer()


@dp.callback_query(F.data == "start_edit_text")
async def start_edit_text_cb(call: CallbackQuery):
    admin_state["start_action"] = "text"
    await call.message.answer(
        "✏️ Yangi start matnini yuboring.\n\n"
        "💡 {name} yozsangiz — foydalanuvchi ismi o'rniga qo'yiladi."
    )
    await call.answer()


@dp.callback_query(F.data == "start_add_photo")
async def start_add_photo_cb(call: CallbackQuery):
    admin_state["start_action"] = "photo"
    await call.message.answer("🖼 Start uchun rasm yuboring:")
    await call.answer()


@dp.callback_query(F.data == "start_del_photo")
async def start_del_photo_cb(call: CallbackQuery):
    cur.execute("INSERT OR REPLACE INTO settings VALUES ('start_photo_id', '')")
    db.commit()
    await call.message.answer("🗑 Start rasmi o'chirildi.")
    await call.answer()


# =================== ADMIN — MENU TUGMALARI ===================
MENU_BTN_LABELS = {
    "btn_1_text": "1 — Inline qidiruv tugmasi",
    "btn_2_text": "2 — Barcha filmlar tugmasi",
    "btn_3_text": "3 — Top kinolar tugmasi",
    "btn_4_text": "4 — Saqlanganlar tugmasi",
    "btn_5_text": "5 — Premium tugmasi",
    "btn_6_text": "6 — Support tugmasi",
}


def _btn_num_from_key(key: str) -> str:
    return key.replace("btn_", "").replace("_text", "")


@dp.callback_query(F.data == "admin_menu_btns")
async def admin_menu_btns(call: CallbackQuery):
    cols = get_setting("menu_cols", "2")
    kb = InlineKeyboardBuilder()
    for key, label in MENU_BTN_LABELS.items():
        cur_text = get_setting(key, "—")
        kb.button(text=f"✏️ {label}: {cur_text}", callback_data=f"btn_edit_{key}")
    cols_toggle = "1 ustun" if cols == "1" else "2 ustun"
    kb.button(text=f"🔀 Tartib: {cols_toggle}", callback_data="btn_toggle_cols")
    kb.adjust(1)
    await call.message.answer(
        "🎛 Menu tugmalarini sozlash\n\n"
        "Tugmani bosing — matn o'zgartirishingiz mumkin.",
        reply_markup=kb.as_markup()
    )
    await call.answer()


@dp.callback_query(F.data.startswith("btn_edit_"))
async def btn_edit_cb(call: CallbackQuery):
    key = call.data.split("btn_edit_")[1]
    if key not in MENU_BTN_LABELS:
        await call.answer("❌ Noto'g'ri kalit")
        return
    admin_state["btn_edit_key"] = key
    cur_text = get_setting(key, "—")
    await call.message.answer(
        f"🎛 <b>{MENU_BTN_LABELS[key]}</b>\n\n"
        f"📝 Hozirgi matn: <code>{cur_text}</code>\n\n"
        "Yangi matn yozing:",
        parse_mode="HTML"
    )
    await call.answer()


@dp.callback_query(F.data == "btn_toggle_cols")
async def btn_toggle_cols(call: CallbackQuery):
    cur_cols = get_setting("menu_cols", "2")
    new_cols = "1" if cur_cols == "2" else "2"
    cur.execute("INSERT OR REPLACE INTO settings VALUES ('menu_cols', ?)", (new_cols,))
    db.commit()
    status = "1 ustunli" if new_cols == "1" else "2 ustunli"
    await call.message.answer(f"✅ Menu ko'rinishi {status} qilib o'zgartirildi!")
    await call.answer()


# =================== ADMIN — MAJBURIY OBUNA ===================
@dp.callback_query(F.data == "admin_channels")
async def admin_channels(call: CallbackQuery):
    channels = get_channels()
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Kanal qo'shish", callback_data="channel_add")
    kb.button(text="➖ Kanal o'chirish", callback_data="channel_remove")
    kb.adjust(2)
    ch_list = "\n".join([f"• {c}" for c in channels]) if channels else "Hozircha kanal yo'q"
    await call.message.answer(
        f"📡 Majburiy obuna kanallari:\n\n{ch_list}\n\n"
        "Kanal qo'shishda @ belgisi bilan yozing: @kanalname",
        reply_markup=kb.as_markup()
    )
    await call.answer()


@dp.callback_query(F.data == "channel_add")
async def channel_add_cb(call: CallbackQuery):
    admin_state["channel_action"] = "add"
    await call.message.answer("📡 Kanal username ni yuboring (@kanalname):")
    await call.answer()


@dp.callback_query(F.data == "channel_remove")
async def channel_remove_cb(call: CallbackQuery):
    admin_state["channel_action"] = "remove"
    await call.message.answer("➖ O'chirish uchun kanal username ni yuboring (@kanalname):")
    await call.answer()


# =================== ADMIN — REKLAMA ===================
@dp.callback_query(F.data == "admin_ads")
async def admin_ads(call: CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Matn reklama", callback_data="ad_add_text")
    kb.button(text="➕ Rasm reklama", callback_data="ad_add_photo")
    kb.button(text="📋 Reklamalar ro'yxati", callback_data="ad_list")
    kb.adjust(2)
    await call.message.answer("📣 Reklama boshqarish:", reply_markup=kb.as_markup())
    await call.answer()


@dp.callback_query(F.data == "ad_add_text")
async def ad_add_text_cb(call: CallbackQuery):
    admin_state["ad_action"] = "text"
    await call.message.answer("📝 Reklama matnini yuboring:")
    await call.answer()


@dp.callback_query(F.data == "ad_add_photo")
async def ad_add_photo_cb(call: CallbackQuery):
    admin_state["ad_action"] = "photo"
    await call.message.answer("🖼 Reklama rasmini yuboring (caption ham qo'shishingiz mumkin):")
    await call.answer()


@dp.callback_query(F.data == "ad_list")
async def ad_list_cb(call: CallbackQuery):
    cur.execute("SELECT id, text, file_type, active FROM ads")
    ads = cur.fetchall()
    if not ads:
        await call.message.answer("📣 Reklamalar yo'q")
        return
    for ad in ads:
        ad_id, text, file_type, active = ad
        status = "✅ Aktiv" if active else "❌ Nofaol"
        preview = (text or "")[:100]
        kb = InlineKeyboardBuilder()
        if active:
            kb.button(text="❌ O'chirish", callback_data=f"ad_deactivate_{ad_id}")
        else:
            kb.button(text="✅ Yoqish", callback_data=f"ad_activate_{ad_id}")
        kb.button(text="🗑 O'chirish", callback_data=f"ad_delete_{ad_id}")
        kb.adjust(2)
        await call.message.answer(
            f"#{ad_id} | {file_type} | {status}\n{preview}",
            reply_markup=kb.as_markup()
        )
    await call.answer()


@dp.callback_query(F.data.startswith("ad_deactivate_"))
async def ad_deactivate(call: CallbackQuery):
    ad_id = call.data.split("ad_deactivate_")[1]
    cur.execute("UPDATE ads SET active=0 WHERE id=?", (ad_id,))
    db.commit()
    await call.message.answer(f"❌ #{ad_id} reklama nofaol qilindi")
    await call.answer()


@dp.callback_query(F.data.startswith("ad_activate_"))
async def ad_activate(call: CallbackQuery):
    ad_id = call.data.split("ad_activate_")[1]
    cur.execute("UPDATE ads SET active=1 WHERE id=?", (ad_id,))
    db.commit()
    await call.message.answer(f"✅ #{ad_id} reklama faollashtirildi")
    await call.answer()


@dp.callback_query(F.data.startswith("ad_delete_"))
async def ad_delete(call: CallbackQuery):
    ad_id = call.data.split("ad_delete_")[1]
    cur.execute("DELETE FROM ads WHERE id=?", (ad_id,))
    db.commit()
    await call.message.answer(f"🗑 #{ad_id} reklama o'chirildi")
    await call.answer()


# =================== ADMIN — KINO/SERIAL BOSHQARUVI ===================
@dp.callback_query(F.data == "admin_add_movie")
async def admin_add_movie(call: CallbackQuery):
    admin_state["add_type"] = "movie"
    await call.message.answer("🎬 Kino videosini yuboring (caption da: Kod|Nom yozing):")
    await call.answer()


@dp.callback_query(F.data == "admin_add_serial")
async def admin_add_serial(call: CallbackQuery):
    admin_state["add_type"] = "serial"
    await call.message.answer("🎞 Serial videosini yuboring (caption da: Kod|Nom yozing):")
    await call.answer()


@dp.callback_query(F.data == "admin_delete_movie")
async def admin_delete_movie(call: CallbackQuery):
    admin_state["delete_type"] = "movie"
    await call.message.answer("🗑 O'chirish uchun kino kodini yuboring:")
    await call.answer()


@dp.callback_query(F.data == "admin_delete_serial")
async def admin_delete_serial(call: CallbackQuery):
    admin_state["delete_type"] = "serial"
    await call.message.answer("🗑 O'chirish uchun serial kodini yuboring:")
    await call.answer()


@dp.callback_query(F.data == "admin_edit_movie")
async def admin_edit_movie(call: CallbackQuery):
    admin_state["edit_type"] = "movie"
    await call.message.answer("✏️ Format: Kod|Yangi nom\nMisol: 001|Yangi Film Nomi")
    await call.answer()


@dp.callback_query(F.data == "admin_edit_serial")
async def admin_edit_serial(call: CallbackQuery):
    admin_state["edit_type"] = "serial"
    await call.message.answer("✏️ Format: Kod|Yangi nom\nMisol: 001|Yangi Serial Nomi")
    await call.answer()


@dp.callback_query(F.data == "admin_list_movies")
async def admin_list_movies(call: CallbackQuery):
    cur.execute("SELECT id, code, title, premium_only FROM movies ORDER BY id DESC LIMIT 50")
    movies = cur.fetchall()
    if not movies:
        await call.message.answer("🎬 Kinolar yo'q")
        return
    text = "🎬 Kinolar ro'yxati:\n\n"
    for m in movies:
        prem = " 💎" if m[3] else ""
        text += f"#{m[0]} | Kod: {m[1]} | {m[2]}{prem}\n"
    await call.message.answer(text[:4000])
    await call.answer()


@dp.callback_query(F.data == "admin_list_serials")
async def admin_list_serials(call: CallbackQuery):
    cur.execute("SELECT id, code, title FROM serials ORDER BY id DESC LIMIT 50")
    serials = cur.fetchall()
    if not serials:
        await call.message.answer("🎞 Seriallar yo'q")
        return
    text = "🎞 Seriallar ro'yxati:\n\n"
    for s in serials:
        text += f"#{s[0]} | Kod: {s[1]} | {s[2]}\n"
    await call.message.answer(text[:4000])
    await call.answer()


@dp.callback_query(F.data == "admin_users")
async def admin_users(call: CallbackQuery):
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    cur.execute("SELECT user_id, username FROM users ORDER BY user_id DESC LIMIT 20")
    users = cur.fetchall()
    text = f"👤 Jami foydalanuvchilar: {count}\n\nSo'nggi 20:\n"
    for u in users:
        uname = f"@{u[1]}" if u[1] else "—"
        text += f"🆔 {u[0]} — {uname}\n"
    await call.message.answer(text[:4000])
    await call.answer()


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    cur.execute("SELECT COUNT(*) FROM users")
    users_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM movies")
    movies_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM serials")
    serials_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM premium_users")
    premium_count = cur.fetchone()[0]
    cur.execute("SELECT SUM(views) FROM movies")
    total_views = cur.fetchone()[0] or 0
    await call.message.answer(
        f"📊 Statistika:\n\n"
        f"👤 Foydalanuvchilar: {users_count}\n"
        f"💎 Premium: {premium_count}\n"
        f"🎬 Kinolar: {movies_count}\n"
        f"🎞 Seriallar: {serials_count}\n"
        f"👁 Jami ko'rishlar: {total_views}"
    )
    await call.answer()


@dp.callback_query(F.data == "admin_broadcast_inline")
async def admin_broadcast_inline(call: CallbackQuery):
    admin_state["broadcast_type"] = "inline"
    await call.message.answer(
        "📣 Inline tugmali broadcast\n\n"
        "Format: Xabar matni | Tugma matni | URL\n"
        "Misol: Yangi kino! | Ko'rish | https://t.me/kanal"
    )
    await call.answer()


@dp.callback_query(F.data == "admin_broadcast_text")
async def admin_broadcast_text(call: CallbackQuery):
    admin_state["broadcast_type"] = "text"
    await call.message.answer("📢 Yuborish uchun xabar matnini yuboring:")
    await call.answer()


@dp.callback_query(F.data == "admin_forward")
async def admin_forward(call: CallbackQuery):
    global_pf = get_setting("global_protect_forward")
    status = "🔴 Yoqilgan" if global_pf == "1" else "🟢 O'chirilgan"
    kb = InlineKeyboardBuilder()
    kb.button(
        text="🔄 Global holatni o'zgartirish",
        callback_data="fwd_global_toggle"
    )
    kb.button(
        text="🎬 Kino bo'yicha sozlash",
        callback_data="fwd_per_movie"
    )
    kb.adjust(1)
    await call.message.answer(
        f"🔒 Uzatish sozlamalari\n\n"
        f"Global taqiq: {status}",
        reply_markup=kb.as_markup()
    )
    await call.answer()


@dp.callback_query(F.data == "fwd_global_toggle")
async def fwd_global_toggle(call: CallbackQuery):
    cur_val = get_setting("global_protect_forward")
    new_val = "0" if cur_val == "1" else "1"
    cur.execute("INSERT OR REPLACE INTO settings VALUES ('global_protect_forward', ?)", (new_val,))
    db.commit()
    status = "🔴 Yoqildi" if new_val == "1" else "🟢 O'chirildi"
    await call.message.answer(f"✅ Global uzatish taqiqi: {status}")
    await call.answer()


@dp.callback_query(F.data == "fwd_per_movie")
async def fwd_per_movie(call: CallbackQuery):
    admin_state["forward_action"] = "per_movie"
    await call.message.answer("🎬 Kino kodini yuboring:")
    await call.answer()


# =================== ADMIN VIDEO HANDLER ===================
@dp.message(F.from_user.id == ADMIN_ID, F.video)
async def admin_video(msg: Message):
    add_type = admin_state.get("add_type")
    start_action = admin_state.get("start_action")

    if add_type in ("movie", "serial"):
        caption = msg.caption or ""
        if "|" not in caption:
            await msg.answer("❌ Format noto'g'ri.\nMisol: 001|Film Nomi  yoki  001|Film Nomi|premium")
            return
        parts = [p.strip() for p in caption.split("|")]
        code = parts[0]
        title = parts[1] if len(parts) > 1 else "Nomsiz"
        is_premium_movie = 1 if len(parts) > 2 and parts[2].lower() == "premium" else 0
        file_id = msg.video.file_id
        prem_label = " 💎 (Premium)" if is_premium_movie else ""
        try:
            if add_type == "movie":
                cur.execute("INSERT INTO movies (code, title, file_id, premium_only) VALUES (?,?,?,?)",
                            (code, title, file_id, is_premium_movie))
                db.commit()
                movie_row = cur.execute("SELECT id FROM movies WHERE code=?", (code,)).fetchone()
                admin_state["awaiting_poster_for"] = movie_row[0] if movie_row else None
                await msg.answer(
                    f"✅ {title}{prem_label} qo'shildi! Kod: {code}\n\n"
                    "🖼 Endi poster rasm yuboring (Pro inline uchun grid ko'rinish)\n"
                    "Yo'q bo'lsa — /skip yozing"
                )
            elif add_type == "serial":
                cur.execute("INSERT INTO serials (code, title, file_id) VALUES (?,?,?)",
                            (code, title, file_id))
                db.commit()
                await msg.answer(f"✅ {title} qo'shildi!\nKod: {code}")
        except sqlite3.IntegrityError:
            await msg.answer("❌ Bu kod mavjud! Boshqa kod kiriting.")
        admin_state["add_type"] = None
    elif start_action == "photo":
        pass


# =================== ADMIN RASM HANDLER ===================
@dp.message(F.from_user.id == ADMIN_ID, F.photo)
async def admin_photo(msg: Message):
    start_action = admin_state.get("start_action")
    ad_action = admin_state.get("ad_action")
    awaiting_poster_for = admin_state.get("awaiting_poster_for")
    awaiting_poster_code = admin_state.get("awaiting_poster_code")

    if awaiting_poster_for:
        photo_id = msg.photo[-1].file_id
        cur.execute("UPDATE movies SET poster_file_id=? WHERE id=?", (photo_id, awaiting_poster_for))
        db.commit()
        await msg.answer("✅ Poster saqlandi! Pro inline da ushbu film grid ko'rinishda chiqadi.")
        admin_state["awaiting_poster_for"] = None
    elif awaiting_poster_code:
        photo_id = msg.photo[-1].file_id
        cur.execute("UPDATE movies SET poster_file_id=? WHERE code=?", (photo_id, awaiting_poster_code))
        db.commit()
        await msg.answer(f"✅ Kod: {awaiting_poster_code} — poster saqlandi!")
        admin_state["awaiting_poster_code"] = None
    elif start_action == "photo":
        photo_id = msg.photo[-1].file_id
        cur.execute("INSERT OR REPLACE INTO settings VALUES ('start_photo_id', ?)", (photo_id,))
        db.commit()
        await msg.answer("✅ Start rasmi saqlandi!")
        admin_state["start_action"] = None
    elif ad_action == "photo":
        photo_id = msg.photo[-1].file_id
        caption = msg.caption or ""
        cur.execute("INSERT INTO ads (text, file_id, file_type) VALUES (?, ?, 'photo')",
                    (caption, photo_id))
        db.commit()
        await msg.answer("✅ Rasm reklama qo'shildi!")
        admin_state["ad_action"] = None


# =================== ADMIN MATN HANDLERI ===================
@dp.message(F.from_user.id == ADMIN_ID, F.text)
async def handle_admin_text(msg: Message):
    # Foydalanuvchiga javob yozish rejimi
    if admin_state.get("reply_to_user"):
        target_id = admin_state.pop("reply_to_user")
        try:
            user_reply_kb = InlineKeyboardBuilder()
            user_reply_kb.button(text="💬 Javob yozish", callback_data="user_reply_to_admin")
            await bot.send_message(
                target_id,
                f"📨 Admin javobi:\n\n{msg.text}",
                reply_markup=user_reply_kb.as_markup()
            )
            await msg.answer(f"✅ Javob yuborildi → {target_id}")
        except Exception as e:
            await msg.answer(f"❌ Xatolik: {e}")
        return

    # /skip — poster o'tkazib yuborish
    if msg.text.strip().lower() == "/skip":
        if admin_state.get("awaiting_poster_for") or admin_state.get("awaiting_poster_code"):
            admin_state["awaiting_poster_for"] = None
            admin_state["awaiting_poster_code"] = None
            await msg.answer("⏭ Poster o'tkazib yuborildi.")
            return

    # Poster uchun film kodi kutilmoqda
    if admin_state.get("awaiting_poster_code") == "WAITING_CODE":
        code = msg.text.strip()
        row = cur.execute("SELECT id, title FROM movies WHERE code=?", (code,)).fetchone()
        if not row:
            await msg.answer(f"❌ Kod: {code} topilmadi. Qayta kiriting yoki /skip yozing.")
            return
        admin_state["awaiting_poster_code"] = code
        await msg.answer(
            f"✅ Film topildi: <b>{row[1]}</b>\n\n"
            "🖼 Endi poster rasmini yuboring:",
            parse_mode="HTML"
        )
        return

    # Karta sozlash
    if admin_state.get("admin_action") == "set_card":
        card_num = msg.text.strip()
        cur.execute("INSERT OR REPLACE INTO settings VALUES ('admin_card', ?)", (card_num,))
        db.commit()
        await msg.answer(f"✅ Karta raqami saqlandi: <code>{card_num}</code>", parse_mode="HTML")
        admin_state["admin_action"] = None
        return

    # Premium qo'shish — step 1: ID olish
    premium_action = admin_state.get("premium_action")
    if premium_action == "add_step1":
        try:
            uid = int(msg.text.strip())
        except ValueError:
            await msg.answer("❌ ID noto'g'ri. Faqat raqam kiriting.")
            return
        admin_state["premium_action"] = None
        await msg.answer(
            f"✅ ID qabul qilindi: <b>{uid}</b>\n\n"
            "📅 Endi tarif turini tanlang:",
            reply_markup=premium_plan_keyboard("adminplan", uid=uid).as_markup(),
            parse_mode="HTML"
        )
        return

    # Premium o'chirish
    if premium_action == "remove":
        try:
            uid = int(msg.text.strip())
        except ValueError:
            await msg.answer("❌ ID noto'g'ri. Faqat raqam kiriting.")
            return
        cur.execute("DELETE FROM premium_users WHERE user_id=?", (uid,))
        db.commit()
        await msg.answer(f"✅ {uid} dan Premium olindi")
        try:
            await bot.send_message(uid, "⚠️ Sizning premium obunangiz bekor qilindi.")
        except Exception:
            pass
        admin_state["premium_action"] = None
        return

    # Menu tugmasi matnini yangilash
    btn_edit_key = admin_state.get("btn_edit_key")
    if btn_edit_key and btn_edit_key in MENU_BTN_LABELS:
        new_btn_text = msg.text.strip()
        if not new_btn_text:
            await msg.answer("❌ Matn bo'sh bo'lmasligi kerak.")
            return
        cur.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (btn_edit_key, new_btn_text))
        db.commit()
        await msg.answer(
            f"✅ Tugma matni yangilandi!\n\n"
            f"<b>{MENU_BTN_LABELS[btn_edit_key]}</b>: <code>{new_btn_text}</code>",
            parse_mode="HTML"
        )
        admin_state["btn_edit_key"] = None
        return

    # Start xabar matni yangilash
    start_action = admin_state.get("start_action")
    if start_action == "text":
        new_text = msg.html_text
        cur.execute("INSERT OR REPLACE INTO settings VALUES ('start_text', ?)", (new_text,))
        db.commit()
        await msg.answer("✅ Start matni yangilandi!")
        admin_state["start_action"] = None
        return

    # Kanal qo'shish
    channel_action = admin_state.get("channel_action")
    if channel_action == "add":
        username = msg.text.strip()
        if not username.startswith("@"):
            username = "@" + username
        cur.execute("INSERT OR IGNORE INTO channels (username) VALUES (?)", (username,))
        db.commit()
        await msg.answer(f"✅ {username} kanali majburiy obunaga qo'shildi!")
        admin_state["channel_action"] = None
        return
    if channel_action == "remove":
        username = msg.text.strip()
        if not username.startswith("@"):
            username = "@" + username
        cur.execute("DELETE FROM channels WHERE username=?", (username,))
        db.commit()
        await msg.answer(f"✅ {username} o'chirildi!")
        admin_state["channel_action"] = None
        return

    # Matn reklama qo'shish
    ad_action = admin_state.get("ad_action")
    if ad_action == "text":
        cur.execute("INSERT INTO ads (text, file_type) VALUES (?, 'text')", (msg.text,))
        db.commit()
        await msg.answer("✅ Matn reklama qo'shildi!")
        admin_state["ad_action"] = None
        return

    # Kino uchun uzatish sozlash
    forward_action = admin_state.get("forward_action")
    if forward_action == "per_movie":
        code = msg.text.strip()
        cur.execute("SELECT id, title, protect_forward FROM movies WHERE code=?", (code,))
        movie = cur.fetchone()
        if not movie:
            await msg.answer("❌ Bu kodda kino topilmadi")
            admin_state["forward_action"] = None
            return
        movie_id, title, pf = movie
        current_status = "🔴 Taqiqlangan" if pf else "🟢 Ruxsat"
        toggle_text = "🟢 Uzatishni yoqish" if pf else "🔴 Uzatishni o'chirish"
        kb = InlineKeyboardBuilder()
        kb.button(text=toggle_text, callback_data=f"fwd_toggle_{movie_id}")
        await msg.answer(
            f"🎬 {title}\nUzatish holati: {current_status}",
            reply_markup=kb.as_markup()
        )
        admin_state["forward_action"] = None
        return

    # O'chirish
    delete_type = admin_state.get("delete_type")
    if delete_type:
        code = msg.text.strip()
        if delete_type == "movie":
            cur.execute("DELETE FROM movies WHERE code=?", (code,))
            db.commit()
            await msg.answer(f"🎬 {code} kodi bilan kino o'chirildi!")
        elif delete_type == "serial":
            cur.execute("DELETE FROM serials WHERE code=?", (code,))
            db.commit()
            await msg.answer(f"🎞 {code} kodi bilan serial o'chirildi!")
        admin_state["delete_type"] = None
        return

    # Tahrirlash
    edit_type = admin_state.get("edit_type")
    if edit_type:
        if "|" not in msg.text:
            await msg.answer("❌ Format noto'g'ri. Kod|Yangi nom")
            return
        code, new_title = [p.strip() for p in msg.text.split("|", 1)]
        if edit_type == "movie":
            cur.execute("UPDATE movies SET title=? WHERE code=?", (new_title, code))
            db.commit()
            await msg.answer(f"🎬 {code} — <code>{new_title}</code> ga o'zgartirildi!",
                             parse_mode="HTML")
        elif edit_type == "serial":
            cur.execute("UPDATE serials SET title=? WHERE code=?", (new_title, code))
            db.commit()
            await msg.answer(f"🎞 {code} — <code>{new_title}</code> ga o'zgartirildi!",
                             parse_mode="HTML")
        admin_state["edit_type"] = None
        return

    # Broadcast
    broadcast_type = admin_state.get("broadcast_type")
    if not broadcast_type:
        return
    cur.execute("SELECT user_id FROM users")
    users = cur.fetchall()
    if not users:
        await msg.answer("❌ Foydalanuvchi yo'q")
        admin_state["broadcast_type"] = None
        return

    if broadcast_type == "inline":
        parts = msg.text.split("|")
        if len(parts) < 3:
            await msg.answer("❌ Format: Xabar matni | Tugma matni | URL")
            return
        text, btn_text, url = parts[0].strip(), parts[1].strip(), parts[2].strip()
        kb = InlineKeyboardBuilder()
        kb.button(text=btn_text, url=url)
        sent_count = 0
        for u in users:
            try:
                await bot.send_message(u[0], text, reply_markup=kb.as_markup())
                sent_count += 1
            except Exception:
                continue
        await msg.answer(f"✅ Xabar {sent_count} foydalanuvchiga yuborildi!")
    else:
        sent_count = 0
        for u in users:
            try:
                await bot.send_message(u[0], msg.text)
                sent_count += 1
            except Exception:
                continue
        await msg.answer(f"✅ Xabar {sent_count} foydalanuvchiga yuborildi!")
    admin_state["broadcast_type"] = None


# =================== KINO UZATISH TOGGLE ===================
@dp.callback_query(F.data.startswith("fwd_toggle_"))
async def fwd_toggle(call: CallbackQuery):
    movie_id = call.data.split("fwd_toggle_")[1]
    cur.execute("SELECT title, protect_forward FROM movies WHERE id=?", (movie_id,))
    row = cur.fetchone()
    if not row:
        await call.answer("❌ Topilmadi", show_alert=True)
        return
    title, pf = row
    new_pf = 0 if pf else 1
    cur.execute("UPDATE movies SET protect_forward=? WHERE id=?", (new_pf, movie_id))
    db.commit()
    new_status = "🔴 Taqiqlangan" if new_pf else "🟢 Ruxsat"
    await call.message.edit_text(f"🎬 {title}\nUzatish holati: {new_status} ✅")
    await call.answer()


# =================== PREMIUM EXPIRY CHECKER (24/7 BACKGROUND TASK) ===================
async def premium_expiry_checker():
    while True:
        try:
            now = datetime.now()
            two_days_later = now + timedelta(days=2)

            # Muddati o'tgan premiumlarni o'chirish
            cur.execute(
                "SELECT user_id FROM premium_users WHERE expiry_at IS NOT NULL AND expiry_at <= ?",
                (now.strftime("%Y-%m-%d %H:%M:%S"),)
            )
            expired = cur.fetchall()
            for row in expired:
                uid = row[0]
                cur.execute("DELETE FROM premium_users WHERE user_id=?", (uid,))
                db.commit()
                try:
                    kb_exp = InlineKeyboardBuilder()
                    kb_exp.button(text="🔄 Premiumni uzaytirish", callback_data="extend_premium_start")
                    await bot.send_message(
                        uid,
                        "⏰ Sizning premium obunangiz muddati tugadi!\n\n"
                        "Agar muddatni uzaytirmoqchi bo'lsangiz pastdagi tugmani bosing!",
                        reply_markup=kb_exp.as_markup()
                    )
                except Exception:
                    pass

            # 2 kun oldin ogohlantirish (faqat muddati 2+ kunlik bo'lganlar uchun)
            cur.execute(
                """SELECT user_id, added_at, expiry_at FROM premium_users
                   WHERE expiry_at IS NOT NULL
                   AND expiry_at > ?
                   AND expiry_at <= ?
                   AND (warned IS NULL OR warned = 0)""",
                (now.strftime("%Y-%m-%d %H:%M:%S"),
                 two_days_later.strftime("%Y-%m-%d %H:%M:%S"))
            )
            to_warn = cur.fetchall()
            for row in to_warn:
                uid, added_at, expiry_at = row[0], row[1], row[2]
                # Jami muddat 2 kundan kam bo'lsa ogohlantirma (masalan kunlik tarif)
                try:
                    exp_dt = datetime.fromisoformat(expiry_at)
                    add_dt = datetime.fromisoformat(added_at) if added_at else None
                    if add_dt:
                        total_days = (exp_dt - add_dt).total_seconds() / 86400
                        if total_days < 2:
                            cur.execute("UPDATE premium_users SET warned=1 WHERE user_id=?", (uid,))
                            db.commit()
                            continue
                    exp_str = exp_dt.strftime("%d.%m.%Y %H:%M")
                except Exception:
                    exp_str = expiry_at

                cur.execute("UPDATE premium_users SET warned=1 WHERE user_id=?", (uid,))
                db.commit()

                kb = InlineKeyboardBuilder()
                kb.button(text="🔄 Premiumni uzaytirish", callback_data="extend_premium_start")
                try:
                    await bot.send_message(
                        uid,
                        f"⚠️ Diqqat! Sizning premium obunangiz <b>2 kun ichida tugaydi</b>.\n"
                        f"⏳ Tugash vaqti: {exp_str}\n\n"
                        f"Uzaytirish uchun quyidagi tugmani bosing 👇",
                        reply_markup=kb.as_markup(),
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

        except Exception:
            pass

        await asyncio.sleep(3600)


# =================== HEALTH CHECK SERVER (UptimeRobot uchun) ===================
async def health_check_handler(request):
    return web.Response(text="OK", status=200)


async def run_health_server():
    port = int(os.getenv("BOT_PORT", "5000"))
    app = web.Application()
    app.router.add_get("/", health_check_handler)
    app.router.add_get("/health", health_check_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()


# =================== RUN ===================
async def main():
    asyncio.create_task(premium_expiry_checker())
    asyncio.create_task(run_health_server())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
