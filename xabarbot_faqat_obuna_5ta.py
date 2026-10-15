import asyncio
import json
import os
import random
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    FSInputFile,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder


# =========================
# ASOSIY SOZLAMALAR
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")

BASE_DIR = Path(__file__).resolve().parent
PROFILES_FILE = BASE_DIR / "user_profiles.json"
PROFILE_MEDIA_DIR = BASE_DIR / "profile_media"
PROFILE_MEDIA_DIR.mkdir(exist_ok=True)
TZ = ZoneInfo("Asia/Tashkent")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi! PyCharm Environment Variables ga BOT_TOKEN qo'ying.")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# Faqat DEMO/TEST mazmuni uchun.
DEFAULT_TEXT = """🧪 DEMO
👤 {randomnik}
➖ {randomsumma} UZS
📍 demo P2P TEZ B.N
💳 {randomkarta}
🕓 {vaqt}"""

DEFAULT_AMOUNTS = [50000, 100000, 150000, 250000, 900000]

# Tugma ranglari (Telegram "style" maydoni)
COLOR_NAMES = {
    "": "⚪ Oddiy",
    "primary": "🔵 Ko‘k",
    "danger": "🔴 Qizil",
    "success": "🟢 Yashil",
}

MAX_CHANNELS = 20


# =========================
# SOZLAMALAR: HAR BIR FOYDALANUVCHI UCHUN ALOHIDA
# =========================
def load_profiles():
    if not PROFILES_FILE.exists():
        return {}
    try:
        data = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


profiles = load_profiles()


def save_profiles():
    PROFILES_FILE.write_text(
        json.dumps(profiles, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def default_settings():
    return {
        # Majburiy obuna (foydalanuvchi darajasida)
        "subscription_channel_id": "",
        "subscription_link": "",
        "subscription_channels": [],
        # Yuboriladigan kanallar: {"c1": {...}, "c2": {...}}
        "channels": {},
        "channel_counter": 0,
    }


def default_channel(channel_id: str, name: str):
    return {
        "name": name,
        "channel_id": channel_id,
        "message_text": DEFAULT_TEXT,
        "inline_text": "",
        "inline_url": "",
        "inline_style": "",
        "limit": 100,
        "intervals": [180, 240],
        "amounts": list(DEFAULT_AMOUNTS),
        "running": False,
        # [{"time": "20:00", "count": 20, "last_date": ""}, ...]
        "schedules": [],
        "sent_count": 0,
        "start_time": "",
    }


def get_channel_image(user_id: int, cid: str) -> Path:
    """Har bir kanalning o'z rasmi."""
    user_dir = PROFILE_MEDIA_DIR / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / f"{cid}.png"


def migrate_legacy(user_id: int, s: dict) -> bool:
    """Eski (1 kanalli) sozlamani yangi ko'p kanalli formatga ko'chiradi."""
    if "channels" in s:
        return False

    channels = {}
    counter = 0

    if s.get("channel_id"):
        counter = 1
        ch = default_channel(str(s.get("channel_id")), "Kanal 1")
        ch["message_text"] = s.get("message_text") or DEFAULT_TEXT
        ch["inline_text"] = s.get("inline_text", "")
        ch["inline_url"] = s.get("inline_url", "")
        ch["limit"] = int(s.get("limit", 100))
        ch["intervals"] = s.get("intervals") or [180, 240]
        ch["amounts"] = s.get("amounts") or list(DEFAULT_AMOUNTS)
        ch["running"] = bool(s.get("running", False))
        ch["sent_count"] = int(s.get("sent_count", 0))
        ch["start_time"] = s.get("start_time", "")
        if s.get("schedule_time") and int(s.get("schedule_count", 0)) > 0:
            ch["schedules"] = [{
                "time": s["schedule_time"],
                "count": int(s["schedule_count"]),
                "last_date": s.get("last_schedule_date", ""),
            }]
        channels["c1"] = ch

        old_img = PROFILE_MEDIA_DIR / str(user_id) / "promo.png"
        new_img = get_channel_image(user_id, "c1")
        if old_img.exists() and not new_img.exists():
            try:
                shutil.copy(old_img, new_img)
            except Exception:
                pass

    s["channels"] = channels
    s["channel_counter"] = counter
    return True


def get_settings(user_id: int):
    key = str(user_id)

    if key not in profiles or not isinstance(profiles[key], dict):
        profiles[key] = default_settings()
        save_profiles()

    s = profiles[key]
    changed = migrate_legacy(user_id, s)

    # Kelajakdagi yangi sozlamalar uchun ham default qiymatlar qo'shiladi.
    for k, v in default_settings().items():
        if k not in s:
            s[k] = v
            changed = True

    if changed:
        save_profiles()

    return s


def get_channel(user_id: int, cid: str):
    return get_settings(user_id).get("channels", {}).get(cid)


# =========================
# HOLATLAR
# =========================
# admin_waiting[user_id] = {"action": "...", "cid": "c1" yoki None}
admin_waiting = {}
# running_tasks[(user_id, cid)] = asyncio.Task
running_tasks = {}


def is_admin(message: Message) -> bool:
    # Panel hammaga ochiq.
    return True


# =========================
# RANDOM MA'LUMOTLAR
# =========================
GIRL_NAMES = [
    "Madina", "Zarina", "Malika", "Dilnoza", "Sevinch", "Shahnoza",
    "Mohira", "Gulnoza", "Nilufar", "Diyora", "Feruza", "Aziza",
    "Mubina", "Laylo", "Shahzoda", "Sabina", "Munisa", "Nodira",
    "Rayhona", "Maftuna", "Umida", "Iroda", "Zebo", "Yulduz",
]

BOY_NAMES = [
    "Aziz", "Jasur", "Bekzod", "Sardor", "Bobur", "Akmal",
    "Diyor", "Oybek", "Shoxrux", "Jamshid", "Davron", "Islom",
    "Asadbek", "Mirjalol", "Muhammad", "Abdulloh", "Temur", "Sanjar",
    "Otabek", "Farrux", "Sherzod", "Ulugbek", "Rustam", "Kamron",
]

FEMALE_SURNAMES = [
    "Abdullayeva", "Karimova", "Tursunova", "Ismoilova", "Yusupova",
    "Rahimova", "Saidova", "Qodirova", "Aliyeva", "Nazarova",
    "Usmonova", "Ergasheva", "Xolmatova", "Mamatqulova", "Sobirova",
]

MALE_SURNAMES = [
    "Abdullayev", "Karimov", "Tursunov", "Ismoilov", "Yusupov",
    "Rahimov", "Saidov", "Qodirov", "Aliyev", "Nazarov",
    "Usmonov", "Ergashev", "Xolmatov", "Mamatqulov", "Sobirov",
]

CARD_PREFIXES = ["9860", "4200", "8600", "6262", "4916", "5614"]


def random_name():
    if random.choice([True, False]):
        return f"{random.choice(GIRL_NAMES)} {random.choice(FEMALE_SURNAMES)}"
    return f"{random.choice(BOY_NAMES)} {random.choice(MALE_SURNAMES)}"


def random_card():
    prefix = random.choice(CARD_PREFIXES)
    tail = "".join(str(random.randint(1, 9)) for _ in range(4))
    return f"{prefix} **** {tail}"


def uz_time():
    return datetime.now(TZ).strftime("%Y.%m.%d %H:%M")


def make_text(ch: dict):
    template = ch.get("message_text") or DEFAULT_TEXT
    text = template
    text = text.replace("{randomnik}", random_name())
    amounts = ch.get("amounts") or DEFAULT_AMOUNTS
    text = text.replace("{randomsumma}", f"{random.choice(amounts):,}".replace(",", " "))
    text = text.replace("{randomkarta}", random_card())
    text = text.replace("{vaqt}", uz_time())

    bet = random.choice([
        "📈 Narx ko‘tarilishiga tikdi 🟢",
        "📉 Narx tushishiga tikdi 🔴",
    ])
    # Ikkala yozuv ham ishlaydi: {raundrandom} va {raundrandom]
    text = text.replace("{raundrandom}", bet)
    text = text.replace("{raundrandom]", bet)

    if "demo" not in text.lower() and "test" not in text.lower():
        text = "🧪 DEMO\n" + text

    return text


# =========================
# ASOSIY (REPLY) KLAVIATURA
# =========================
def admin_keyboard():
    kb = ReplyKeyboardBuilder()

    kb.button(text="📢 Kanallarim")
    kb.button(text="➕ Kanal ulash")
    kb.button(text="📊 Statistika")
    kb.button(text="🔐 Majburiy obuna")

    kb.adjust(2, 2)
    return kb.as_markup(resize_keyboard=True)


# =========================
# INLINE TUGMA (kanal posti uchun, rangli)
# =========================
def make_inline(ch: dict):
    text = ch.get("inline_text", "")
    url = ch.get("inline_url", "")
    style = ch.get("inline_style", "")

    if not text or not url:
        return None

    if style:
        try:
            button = InlineKeyboardButton(text=text, url=url, style=style)
        except Exception:
            button = InlineKeyboardButton(text=text, url=url)
    else:
        button = InlineKeyboardButton(text=text, url=url)

    return InlineKeyboardMarkup(inline_keyboard=[[button]])


# =========================
# KANALGA YUBORISH
# =========================
async def send_one(user_id: int, cid: str):
    ch = get_channel(user_id, cid)
    if not ch:
        return False, "Kanal topilmadi."

    channel_id = ch.get("channel_id")

    if not channel_id:
        return False, "Kanal ID kiritilmagan."

    try:
        inline = make_inline(ch)
        text = make_text(ch)

        image = get_channel_image(user_id, cid)

        if not image.exists():
            return False, f"«{ch.get('name')}» uchun rasm yuklanmagan. 🖼 Rasm bo‘limidan yuklang."

        await bot.send_photo(
            chat_id=channel_id,
            photo=FSInputFile(image),
            caption=text,
            reply_markup=inline,
        )

        ch["sent_count"] = int(ch.get("sent_count", 0)) + 1
        save_profiles()
        return True, "Yuborildi."

    except Exception as e:
        return False, str(e)


# =========================
# MAJBURIY OBUNA
# =========================
def subscription_keyboard(user_settings):
    channels = user_settings.get("subscription_channels", [])

    # Eski 1-kanalli sozlamani ham qo'llab-quvvatlash.
    if not channels:
        old_id = user_settings.get("subscription_channel_id", "")
        old_link = user_settings.get("subscription_link", "")
        if old_id and old_link:
            channels = [{"id": old_id, "link": old_link}]

    if not channels:
        return None

    kb = InlineKeyboardBuilder()

    for i, channel in enumerate(channels[:5], 1):
        link = channel.get("link", "")
        if link:
            kb.button(
                text=f"📢 Kanal {i} ga obuna bo‘lish",
                url=link
            )

    kb.button(
        text="✅ Obunani tekshirish",
        callback_data="check_sub"
    )
    kb.adjust(1)

    return kb.as_markup()


async def check_subscription(user_id: int) -> bool:
    user_settings = get_settings(user_id)

    channels = user_settings.get("subscription_channels", [])

    # Eski 1-kanalli sozlamani ham qo'llab-quvvatlash.
    if not channels:
        old_id = user_settings.get("subscription_channel_id", "")
        old_link = user_settings.get("subscription_link", "")
        if old_id and old_link:
            channels = [{"id": old_id, "link": old_link}]

    if not channels:
        return True

    for channel in channels[:5]:
        channel_id = str(channel.get("id", "")).strip()

        if not channel_id:
            continue

        try:
            member = await bot.get_chat_member(channel_id, user_id)

            if member.status not in (
                "member",
                "administrator",
                "creator",
            ):
                return False

        except Exception:
            return False

    return True


# =========================
# KANAL MENYULARI (inline)
# =========================
def channels_list_kb(user_settings):
    kb = InlineKeyboardBuilder()
    for cid, ch in user_settings.get("channels", {}).items():
        mark = "🟢" if ch.get("running") else "🔴"
        kb.button(text=f"{mark} {ch.get('name', cid)}", callback_data=f"ch:{cid}")
    kb.button(text="➕ Kanal ulash", callback_data="add_ch")
    kb.adjust(1)
    return kb.as_markup()


def channel_menu_kb(cid: str, ch: dict):
    kb = InlineKeyboardBuilder()

    kb.button(text="▶️ Boshlash", callback_data=f"go:{cid}")
    kb.button(text="⏹ To‘xtatish", callback_data=f"stop:{cid}")

    kb.button(text="⚡ Birdan xabar", callback_data=f"once:{cid}")
    kb.button(text="⏰ Vaqtli yuborish", callback_data=f"sched:{cid}")

    kb.button(text="📝 Xabar matni", callback_data=f"set:{cid}:text")
    kb.button(text="🖼 Rasm joylash", callback_data=f"set:{cid}:image")

    kb.button(text="🗑 Rasmni olish", callback_data=f"delimg:{cid}")
    kb.button(text="🔘 Inline tugma", callback_data=f"set:{cid}:inline")

    kb.button(text="🎨 Tugma rangi", callback_data=f"color:{cid}")
    kb.button(text="❌ Tugmani o‘chirish", callback_data=f"delbtn:{cid}")

    kb.button(text="🔢 Xabar soni", callback_data=f"set:{cid}:limit")
    kb.button(text="⏱ Interval", callback_data=f"set:{cid}:interval")

    kb.button(text="💰 Summalar", callback_data=f"set:{cid}:amounts")
    kb.button(text="📢 Kanal ID", callback_data=f"set:{cid}:chid")

    kb.button(text="✏️ Nomi", callback_data=f"set:{cid}:name")
    kb.button(text="📊 Statistika", callback_data=f"stat:{cid}")

    kb.button(text="🗑 Kanalni o‘chirish", callback_data=f"delch:{cid}")
    kb.button(text="⬅️ Orqaga", callback_data="list")

    kb.adjust(2)
    return kb.as_markup()


def color_menu_kb(cid: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🔵 Ko‘k", callback_data=f"setcolor:{cid}:primary")
    kb.button(text="🔴 Qizil", callback_data=f"setcolor:{cid}:danger")
    kb.button(text="🟢 Yashil", callback_data=f"setcolor:{cid}:success")
    kb.button(text="⚪ Oddiy", callback_data=f"setcolor:{cid}:none")
    kb.button(text="⬅️ Orqaga", callback_data=f"ch:{cid}")
    kb.adjust(3, 1, 1)
    return kb.as_markup()


def schedule_menu_kb(cid: str, ch: dict):
    kb = InlineKeyboardBuilder()
    for i, sch in enumerate(ch.get("schedules", [])):
        kb.button(
            text=f"🗑 {sch['time']} — {sch['count']} ta",
            callback_data=f"delsch:{cid}:{i}",
        )
    kb.button(text="➕ Vaqt qo‘shish", callback_data=f"set:{cid}:schedule")
    if ch.get("schedules"):
        kb.button(text="🧹 Hammasini tozalash", callback_data=f"clrsch:{cid}")
    kb.button(text="⬅️ Orqaga", callback_data=f"ch:{cid}")
    kb.adjust(1)
    return kb.as_markup()


def schedules_text(ch: dict) -> str:
    schedules = ch.get("schedules", [])
    if not schedules:
        return "—"
    return "; ".join(f"{s['time']} — {s['count']} ta" for s in schedules)


def menu_text(user_id: int, cid: str, ch: dict) -> str:
    has_image = get_channel_image(user_id, cid).exists()
    button = "—"
    if ch.get("inline_text") and ch.get("inline_url"):
        button = (
            f"{ch['inline_text']} → {ch['inline_url']} "
            f"({COLOR_NAMES.get(ch.get('inline_style', ''), '⚪ Oddiy')})"
        )

    return (
        f"📢 {ch.get('name', cid)}\n\n"
        f"Kanal ID: {ch.get('channel_id') or '—'}\n"
        f"Avto yuborish: {'ON 🟢' if ch.get('running') else 'OFF 🔴'}\n"
        f"Yuborilgan: {ch.get('sent_count', 0)}\n"
        f"Limit: {ch.get('limit', 100)} ta\n"
        f"Interval: {ch.get('intervals')} soniya\n"
        f"Summalar: {ch.get('amounts')}\n"
        f"Rasm: {'bor ✅' if has_image else 'yo‘q ❌'}\n"
        f"Tugma: {button}\n"
        f"Vaqtli reja: {schedules_text(ch)}"
    )


async def edit_or_send(callback: CallbackQuery, text: str, kb):
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" in str(e).lower():
            return
        await callback.message.answer(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)


async def show_menu(callback: CallbackQuery, cid: str):
    ch = get_channel(callback.from_user.id, cid)
    if not ch:
        await callback.answer("Kanal topilmadi.", show_alert=True)
        return None
    await edit_or_send(
        callback,
        menu_text(callback.from_user.id, cid, ch),
        channel_menu_kb(cid, ch),
    )
    return ch


def stop_channel_task(user_id: int, cid: str):
    task = running_tasks.get((user_id, cid))
    if task:
        task.cancel()


# =========================
# /START
# =========================
@router.message(CommandStart())
async def start_handler(message: Message):
    if not await check_subscription(message.from_user.id):
        kb = subscription_keyboard(
            get_settings(message.from_user.id)
        )

        if kb:
            await message.answer(
                "🔐 Botdan foydalanish uchun barcha majburiy "
                "kanallarga obuna bo‘ling.",
                reply_markup=kb,
            )
            return

    await message.answer(
        "✅ Obuna tasdiqlandi.\nBotdan foydalanishingiz mumkin.",
    )


# =========================
# /PANEL
# =========================
@router.message(Command("panel"))
async def panel_command(message: Message):
    if not is_admin(message):
        return

    admin_waiting.pop(message.from_user.id, None)
    await message.answer(
        "👤 Sizning shaxsiy panelingiz\n\nKerakli bo‘limni tanlang:",
        reply_markup=admin_keyboard(),
    )


# =========================
# ASOSIY TUGMALAR
# =========================
@router.message(F.text == "📢 Kanallarim")
async def my_channels(message: Message):
    if not is_admin(message):
        return
    admin_waiting.pop(message.from_user.id, None)

    us = get_settings(message.from_user.id)
    if not us["channels"]:
        await message.answer(
            "Hali kanal ulanmagan.\n\n➕ Kanal ulash tugmasini bosing.",
            reply_markup=channels_list_kb(us),
        )
        return

    await message.answer(
        "📢 Kanallaringiz. Sozlash uchun birini tanlang:",
        reply_markup=channels_list_kb(us),
    )


@router.message(F.text == "➕ Kanal ulash")
async def add_channel_btn(message: Message):
    if not is_admin(message):
        return
    await ask_new_channel(message, message.from_user.id)


async def ask_new_channel(message: Message, user_id: int):
    us = get_settings(user_id)
    if len(us["channels"]) >= MAX_CHANNELS:
        await message.answer(f"❌ Eng ko‘pi bilan {MAX_CHANNELS} ta kanal ulash mumkin.")
        return

    admin_waiting[user_id] = {"action": "addch", "cid": None}
    await message.answer(
        "📢 Yangi kanal ID sini yuboring.\n"
        "Masalan: -1001234567890\n\n"
        "Bot kanalga ADMIN bo‘lishi kerak."
    )


@router.message(F.text == "📊 Statistika")
async def statistics(message: Message):
    if not is_admin(message):
        return
    admin_waiting.pop(message.from_user.id, None)

    us = get_settings(message.from_user.id)
    channels = us.get("channels", {})

    if not channels:
        await message.answer("📊 Statistika\n\nHali kanal ulanmagan.")
        return

    total = sum(int(c.get("sent_count", 0)) for c in channels.values())
    lines = ["📊 Umumiy statistika\n", f"Jami yuborilgan: {total}\n"]

    for cid, ch in channels.items():
        lines.append(
            f"📢 {ch.get('name')}: {ch.get('sent_count', 0)} ta | "
            f"{'ON 🟢' if ch.get('running') else 'OFF 🔴'} | "
            f"reja: {schedules_text(ch)}"
        )

    await message.answer("\n".join(lines))


@router.message(F.text == "🔐 Majburiy obuna")
async def ask_subscription(message: Message):
    if not is_admin(message):
        return

    get_settings(message.from_user.id)

    admin_waiting[message.from_user.id] = {"action": "subscription", "cid": None}

    await message.answer(
        "🔐 Majburiy obuna — 1 tadan 5 tagacha kanal.\n\n"
        "Har bir kanal uchun 2 qator yozing:\n"
        "1) Kanal ID\n"
        "2) Kanal havolasi\n\n"
        "Masalan, 3 ta kanal:\n\n"
        "-1001111111111\n"
        "https://t.me/kanal1\n"
        "-1002222222222\n"
        "https://t.me/kanal2\n"
        "-1003333333333\n"
        "https://t.me/kanal3\n\n"
        "Bot barcha kanallarga obunani tekshiradi."
    )


# =========================
# KANAL CALLBACKLARI
# =========================
@router.callback_query(F.data == "list")
async def cb_list(callback: CallbackQuery):
    admin_waiting.pop(callback.from_user.id, None)
    us = get_settings(callback.from_user.id)
    await edit_or_send(
        callback,
        "📢 Kanallaringiz. Sozlash uchun birini tanlang:",
        channels_list_kb(us),
    )
    await callback.answer()


@router.callback_query(F.data == "add_ch")
async def cb_add_channel(callback: CallbackQuery):
    await callback.answer()
    await ask_new_channel(callback.message, callback.from_user.id)


@router.callback_query(F.data.startswith("ch:"))
async def cb_channel(callback: CallbackQuery):
    admin_waiting.pop(callback.from_user.id, None)
    cid = callback.data.split(":")[1]
    await show_menu(callback, cid)
    await callback.answer()


@router.callback_query(F.data.startswith("go:"))
async def cb_go(callback: CallbackQuery):
    cid = callback.data.split(":")[1]
    ch = get_channel(callback.from_user.id, cid)
    if not ch:
        await callback.answer("Kanal topilmadi.", show_alert=True)
        return

    if ch.get("running"):
        await callback.answer("⚠️ Avtomatik yuborish allaqachon ishlayapti.", show_alert=True)
        return

    if not ch.get("channel_id"):
        await callback.answer("❌ Avval kanal ID kiriting.", show_alert=True)
        return

    ch["running"] = True
    ch["start_time"] = uz_time()
    save_profiles()

    await callback.answer(
        f"▶️ Boshlandi. Limit: {ch['limit']} ta. Birinchi xabar darhol yuboriladi.",
        show_alert=True,
    )
    await show_menu(callback, cid)


@router.callback_query(F.data.startswith("stop:"))
async def cb_stop(callback: CallbackQuery):
    cid = callback.data.split(":")[1]
    ch = get_channel(callback.from_user.id, cid)
    if not ch:
        await callback.answer("Kanal topilmadi.", show_alert=True)
        return

    ch["running"] = False
    save_profiles()
    stop_channel_task(callback.from_user.id, cid)

    await callback.answer("⏹ To‘xtatildi.")
    await show_menu(callback, cid)


@router.callback_query(F.data.startswith("once:"))
async def cb_once(callback: CallbackQuery):
    cid = callback.data.split(":")[1]
    await callback.answer("⏳ Yuborilmoqda...")
    ok, info = await send_one(callback.from_user.id, cid)
    if ok:
        await callback.message.answer("⚡ DEMO xabar kanalga yuborildi.")
        await show_menu(callback, cid)
    else:
        await callback.message.answer(f"❌ Yuborilmadi:\n{info}")


@router.callback_query(F.data.startswith("stat:"))
async def cb_stat(callback: CallbackQuery):
    cid = callback.data.split(":")[1]
    ch = get_channel(callback.from_user.id, cid)
    if not ch:
        await callback.answer("Kanal topilmadi.", show_alert=True)
        return

    await callback.message.answer(
        f"📊 {ch.get('name')}\n\n"
        f"Yuborilgan xabarlar: {ch.get('sent_count', 0)}\n"
        f"Limit: {ch.get('limit', 100)}\n"
        f"Interval: {ch.get('intervals')}\n"
        f"Avto yuborish: {'ON 🟢' if ch.get('running') else 'OFF 🔴'}\n"
        f"Boshlangan vaqt: {ch.get('start_time') or '—'}\n"
        f"Vaqtli reja: {schedules_text(ch)}"
    )
    await callback.answer()


PROMPTS = {
    "text": (
        "📝 Shu kanal uchun xabar matnini yuboring.\n\n"
        "Ishlatish mumkin:\n"
        "{randomnik}\n"
        "{randomsumma}\n"
        "{randomkarta}\n"
        "{vaqt}\n"
        "{raundrandom}\n\n"
        "Xabar DEMO/TEST deb ko‘rsatiladi."
    ),
    "image": "🖼 Shu kanal uchun yangi rasmni yuboring (rasm sifatida).",
    "inline": (
        "🔘 Inline tugma uchun 2 qator yuboring:\n\n"
        "1-qator: tugma nomi\n"
        "2-qator: URL\n\n"
        "Masalan:\n"
        "📲 Kanalga kirish\n"
        "https://t.me/kanal\n\n"
        "Rangini keyin 🎨 Tugma rangi orqali tanlang."
    ),
    "limit": "🔢 Nechta xabar yuborilsin?\n\nFaqat son yuboring. Masalan: 100",
    "interval": (
        "⏱ Har bir xabar orasidagi vaqtni soniyada kiriting.\n\n"
        "Bitta qiymat: 10\n"
        "Yoki bir nechta: 10 20 30"
    ),
    "amounts": (
        "💰 Summalarni bo‘sh joy bilan yuboring.\n"
        "Masalan:\n"
        "50000 100000 150000 250000 900000"
    ),
    "chid": (
        "📢 Post yuboriladigan kanal ID sini yuboring.\n"
        "Masalan: -1001234567890\n\n"
        "Bot kanalga ADMIN bo‘lishi kerak."
    ),
    "name": "✏️ Kanal uchun nom yuboring (masalan: Kanal 2 yoki Asosiy).",
    "schedule": (
        "⏰ Vaqtli yuborish. Har qatorda: HH:MM SON\n\n"
        "Bir nechta vaqtni birdan yozishingiz mumkin:\n"
        "20:00 20\n"
        "22:00 10\n\n"
        "Bu har kuni 20:00 da 20 ta, 22:00 da 10 ta DEMO xabar yuboradi.\n"
        "Mavjud rejaga qo‘shiladi (bir xil vaqt bo‘lsa yangilanadi)."
    ),
}


@router.callback_query(F.data.startswith("set:"))
async def cb_set(callback: CallbackQuery):
    _, cid, action = callback.data.split(":")
    if not get_channel(callback.from_user.id, cid):
        await callback.answer("Kanal topilmadi.", show_alert=True)
        return

    admin_waiting[callback.from_user.id] = {"action": action, "cid": cid}
    await callback.answer()
    await callback.message.answer(PROMPTS[action])


@router.callback_query(F.data.startswith("delimg:"))
async def cb_delimg(callback: CallbackQuery):
    cid = callback.data.split(":")[1]
    img = get_channel_image(callback.from_user.id, cid)
    if img.exists():
        try:
            img.unlink()
        except Exception as e:
            await callback.answer(f"Xato: {e}", show_alert=True)
            return
        await callback.answer("🗑 Rasm olib tashlandi.")
    else:
        await callback.answer("Rasm yo‘q edi.")
    await show_menu(callback, cid)


@router.callback_query(F.data.startswith("delbtn:"))
async def cb_delbtn(callback: CallbackQuery):
    cid = callback.data.split(":")[1]
    ch = get_channel(callback.from_user.id, cid)
    if not ch:
        await callback.answer("Kanal topilmadi.", show_alert=True)
        return

    ch["inline_text"] = ""
    ch["inline_url"] = ""
    ch["inline_style"] = ""
    save_profiles()
    await callback.answer("❌ Inline tugma o‘chirildi.")
    await show_menu(callback, cid)


@router.callback_query(F.data.startswith("color:"))
async def cb_color(callback: CallbackQuery):
    cid = callback.data.split(":")[1]
    ch = get_channel(callback.from_user.id, cid)
    if not ch:
        await callback.answer("Kanal topilmadi.", show_alert=True)
        return

    if not ch.get("inline_text"):
        await callback.answer("Avval 🔘 Inline tugma qo‘ying.", show_alert=True)
        return

    await edit_or_send(
        callback,
        f"🎨 Tugma rangini tanlang.\n\n"
        f"Hozirgi: {COLOR_NAMES.get(ch.get('inline_style', ''), '⚪ Oddiy')}",
        color_menu_kb(cid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("setcolor:"))
async def cb_setcolor(callback: CallbackQuery):
    _, cid, color = callback.data.split(":")
    ch = get_channel(callback.from_user.id, cid)
    if not ch:
        await callback.answer("Kanal topilmadi.", show_alert=True)
        return

    ch["inline_style"] = "" if color == "none" else color
    save_profiles()
    await callback.answer("🎨 Rang saqlandi.")
    await show_menu(callback, cid)


@router.callback_query(F.data.startswith("sched:"))
async def cb_sched(callback: CallbackQuery):
    cid = callback.data.split(":")[1]
    ch = get_channel(callback.from_user.id, cid)
    if not ch:
        await callback.answer("Kanal topilmadi.", show_alert=True)
        return

    await edit_or_send(
        callback,
        f"⏰ {ch.get('name')} — vaqtli yuborish\n\n"
        f"Reja: {schedules_text(ch)}\n\n"
        "Vaqtni o‘chirish uchun 🗑 tugmasini bosing.",
        schedule_menu_kb(cid, ch),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delsch:"))
async def cb_delsch(callback: CallbackQuery):
    _, cid, idx = callback.data.split(":")
    ch = get_channel(callback.from_user.id, cid)
    if not ch:
        await callback.answer("Kanal topilmadi.", show_alert=True)
        return

    try:
        ch["schedules"].pop(int(idx))
        save_profiles()
    except Exception:
        pass

    await callback.answer("🗑 O‘chirildi.")
    await edit_or_send(
        callback,
        f"⏰ {ch.get('name')} — vaqtli yuborish\n\nReja: {schedules_text(ch)}",
        schedule_menu_kb(cid, ch),
    )


@router.callback_query(F.data.startswith("clrsch:"))
async def cb_clrsch(callback: CallbackQuery):
    cid = callback.data.split(":")[1]
    ch = get_channel(callback.from_user.id, cid)
    if not ch:
        await callback.answer("Kanal topilmadi.", show_alert=True)
        return

    ch["schedules"] = []
    save_profiles()
    await callback.answer("🧹 Reja tozalandi.")
    await edit_or_send(
        callback,
        f"⏰ {ch.get('name')} — vaqtli yuborish\n\nReja: —",
        schedule_menu_kb(cid, ch),
    )


@router.callback_query(F.data.startswith("delch:"))
async def cb_delch(callback: CallbackQuery):
    cid = callback.data.split(":")[1]
    ch = get_channel(callback.from_user.id, cid)
    if not ch:
        await callback.answer("Kanal topilmadi.", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Ha, o‘chirish", callback_data=f"delch_yes:{cid}")
    kb.button(text="⬅️ Yo‘q", callback_data=f"ch:{cid}")
    kb.adjust(2)

    await edit_or_send(
        callback,
        f"🗑 «{ch.get('name')}» kanalini butunlay o‘chirasizmi?\n"
        "Matn, rasm, tugma va reja o‘chib ketadi.",
        kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delch_yes:"))
async def cb_delch_yes(callback: CallbackQuery):
    cid = callback.data.split(":")[1]
    us = get_settings(callback.from_user.id)

    if cid in us["channels"]:
        stop_channel_task(callback.from_user.id, cid)
        us["channels"].pop(cid, None)
        save_profiles()

        img = get_channel_image(callback.from_user.id, cid)
        if img.exists():
            try:
                img.unlink()
            except Exception:
                pass

    await callback.answer("🗑 Kanal o‘chirildi.")
    await edit_or_send(
        callback,
        "📢 Kanallaringiz. Sozlash uchun birini tanlang:",
        channels_list_kb(us),
    )


# =========================
# RASM QABUL QILISH
# =========================
@router.message(F.photo)
async def upload_image(message: Message):
    if not is_admin(message):
        return

    state = admin_waiting.get(message.from_user.id)
    if not state or state.get("action") != "image":
        return

    cid = state.get("cid")
    ch = get_channel(message.from_user.id, cid)
    if not ch:
        admin_waiting.pop(message.from_user.id, None)
        return

    try:
        photo = message.photo[-1]
        image = get_channel_image(message.from_user.id, cid)
        await bot.download(photo, destination=image)
        admin_waiting.pop(message.from_user.id, None)
        await message.answer(
            f"🖼 «{ch.get('name')}» uchun rasm saqlandi.\n"
            "Bu rasm boshqa kanallarga o‘tmaydi."
        )
        await message.answer(
            menu_text(message.from_user.id, cid, ch),
            reply_markup=channel_menu_kb(cid, ch),
        )
    except Exception as e:
        await message.answer(f"❌ Rasm saqlanmadi:\n{e}")


# =========================
# KIRITILGAN MA'LUMOTLARNI QABUL QILISH
# =========================
async def finish(message: Message, cid: str, text: str):
    admin_waiting.pop(message.from_user.id, None)
    await message.answer(text)
    ch = get_channel(message.from_user.id, cid)
    if ch:
        await message.answer(
            menu_text(message.from_user.id, cid, ch),
            reply_markup=channel_menu_kb(cid, ch),
        )


@router.message(F.text)
async def admin_input(message: Message):
    if not is_admin(message):
        return

    if message.text.startswith("/"):
        return

    state = admin_waiting.get(message.from_user.id)
    if not state:
        return

    action = state.get("action")
    cid = state.get("cid")

    user_id = message.from_user.id
    us = get_settings(user_id)
    value = message.text.strip()

    ch = us["channels"].get(cid) if cid else None

    try:
        # ---------- yangi kanal ulash ----------
        if action == "addch":
            if not value.startswith("-100"):
                await message.answer("❌ Kanal ID -100 bilan boshlanishi kerak.\nMasalan: -1001234567890")
                return

            us["channel_counter"] = int(us.get("channel_counter", 0)) + 1
            new_cid = f"c{us['channel_counter']}"
            name = f"Kanal {len(us['channels']) + 1}"
            us["channels"][new_cid] = default_channel(value, name)
            save_profiles()

            await finish(
                message,
                new_cid,
                f"✅ {name} ulandi.\n\n"
                "Endi shu kanal uchun matn, rasm, tugma va rejani sozlang.",
            )
            return

        # ---------- majburiy obuna ----------
        if action == "subscription":
            lines = [x.strip() for x in value.splitlines() if x.strip()]

            # 2, 4, 6, 8 yoki 10 qator = 1..5 kanal
            if len(lines) < 2 or len(lines) > 10 or len(lines) % 2 != 0:
                raise ValueError

            channels = []

            for i in range(0, len(lines), 2):
                channel_id = lines[i]
                link = lines[i + 1]

                if not channel_id.startswith("-100"):
                    raise ValueError

                if not link.startswith(("https://t.me/", "http://t.me/")):
                    raise ValueError

                channels.append({
                    "id": channel_id,
                    "link": link,
                })

            us["subscription_channels"] = channels

            # Eski format bilan ham moslik saqlanadi.
            us["subscription_channel_id"] = channels[0]["id"]
            us["subscription_link"] = channels[0]["link"]

            save_profiles()

            await message.answer(
                f"✅ {len(channels)} ta majburiy kanal saqlandi.\n\n"
                "Har bir foydalanuvchi barcha kanallarga "
                "obuna bo‘lgandan keyin botga kira oladi."
            )

            admin_waiting.pop(user_id, None)
            return

        # Qolganlari aniq kanalga tegishli
        if not ch:
            admin_waiting.pop(user_id, None)
            await message.answer("❌ Kanal topilmadi.")
            return

        if action == "limit":
            n = int(value)
            if n < 1:
                raise ValueError
            ch["limit"] = n
            save_profiles()
            await finish(message, cid, f"✅ Xabar limiti: {n}")

        elif action == "interval":
            vals = [int(x) for x in value.split()]
            if not vals or any(x < 1 for x in vals):
                raise ValueError
            ch["intervals"] = vals
            save_profiles()
            await finish(message, cid, f"✅ Interval saqlandi: {vals} soniya")

        elif action == "amounts":
            vals = [int(x) for x in value.split()]
            if not vals or any(x < 0 for x in vals):
                raise ValueError
            ch["amounts"] = vals
            save_profiles()
            await finish(message, cid, f"✅ Summalar saqlandi: {vals}")

        elif action == "chid":
            ch["channel_id"] = value
            save_profiles()
            await finish(message, cid, f"✅ Kanal ID saqlandi.\nKanal: {value}")

        elif action == "name":
            ch["name"] = value[:30]
            save_profiles()
            await finish(message, cid, f"✅ Nom saqlandi: {ch['name']}")

        elif action == "text":
            ch["message_text"] = value
            save_profiles()
            await finish(
                message,
                cid,
                "✅ Shu kanal uchun xabar matni saqlandi.\n\n"
                "Eslatma: xabar DEMO/TEST belgisisiz yuborilmaydi.",
            )

        elif action == "schedule":
            parsed = []
            for line in value.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) != 2:
                    raise ValueError
                time_value = parts[0]
                count = int(parts[1])
                datetime.strptime(time_value, "%H:%M")
                if count < 1:
                    raise ValueError
                parsed.append((time_value, count))

            if not parsed:
                raise ValueError

            schedules = ch.setdefault("schedules", [])
            for time_value, count in parsed:
                # Bir xil vaqt bo'lsa — yangilanadi
                schedules[:] = [s for s in schedules if s["time"] != time_value]
                schedules.append({
                    "time": time_value,
                    "count": count,
                    "last_date": "",
                })
            schedules.sort(key=lambda s: s["time"])
            save_profiles()

            await finish(
                message,
                cid,
                "✅ Vaqtli yuborish saqlandi:\n"
                + "\n".join(f"⏰ {t} — {c} ta DEMO xabar" for t, c in parsed),
            )

        elif action == "inline":
            lines = value.splitlines()
            if len(lines) < 2:
                raise ValueError

            button_text = lines[0].strip()
            url = lines[1].strip()

            if not url.startswith(("http://", "https://", "tg://")):
                await message.answer("❌ URL http:// yoki https:// bilan boshlansin.")
                return

            ch["inline_text"] = button_text
            ch["inline_url"] = url
            save_profiles()

            await finish(
                message,
                cid,
                "✅ Inline tugma shu kanal uchun saqlandi.\n\n"
                f"🔘 {button_text}\n"
                f"🔗 {url}\n\n"
                "Rang berish: 🎨 Tugma rangi.",
            )

        elif action == "image":
            await message.answer("🖼 Iltimos, rasm yuboring (matn emas).")

    except Exception:
        await message.answer(
            "❌ Format xato.\n"
            "Qaytadan to‘g‘ri formatda yuboring."
        )


# =========================
# OBUNA TEKSHIRISH
# =========================
@router.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    if await check_subscription(callback.from_user.id):
        await callback.answer(
            "✅ Barcha majburiy kanallarga obuna tasdiqlandi.",
            show_alert=True,
        )

        try:
            await callback.message.edit_text(
                "✅ Obuna tasdiqlandi.\n"
                "Botdan foydalanishingiz mumkin."
            )
        except Exception:
            pass
    else:
        await callback.answer(
            "❌ Barcha majburiy kanallarga obuna bo‘ling.",
            show_alert=True,
        )


# =========================
# AVTO YUBORISH (har bir kanal alohida)
# =========================
async def run_channel_sender(user_id: int, cid: str):
    """Faqat bitta kanalning avtomatik yuborish jarayoni."""
    ch = get_channel(user_id, cid)
    if not ch:
        running_tasks.pop((user_id, cid), None)
        return

    limit = max(1, int(ch.get("limit", 100)))
    intervals = [int(x) for x in (ch.get("intervals") or [180])]
    intervals = [x for x in intervals if x > 0] or [180]

    try:
        for index in range(limit):
            ch = get_channel(user_id, cid)

            if not ch or not ch.get("running"):
                break

            ok, info = await send_one(user_id, cid)

            if not ok:
                ch["running"] = False
                save_profiles()
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text=f"❌ «{ch.get('name')}» yuborish to‘xtadi.\n\n{info}"
                    )
                except Exception:
                    pass
                break

            # Oxirgi xabardan keyin kutish shart emas.
            if index < limit - 1:
                await asyncio.sleep(random.choice(intervals))

    except asyncio.CancelledError:
        pass
    finally:
        ch = get_channel(user_id, cid)
        if ch:
            ch["running"] = False
            save_profiles()
        running_tasks.pop((user_id, cid), None)


async def automatic_sender():
    """Barcha profillardagi barcha kanallarni mustaqil kuzatadi."""
    while True:
        try:
            for user_id_str, user_settings in list(profiles.items()):
                user_id = int(user_id_str)

                for cid, ch in list((user_settings.get("channels") or {}).items()):
                    if ch.get("running") and (user_id, cid) not in running_tasks:
                        running_tasks[(user_id, cid)] = asyncio.create_task(
                            run_channel_sender(user_id, cid)
                        )

            await asyncio.sleep(1)

        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(5)


# =========================
# VAQTLI YUBORISH (har bir kanal, bir nechta vaqt)
# =========================
async def run_scheduled_channel(user_id: int, cid: str, count: int):
    for index in range(count):
        ok, info = await send_one(user_id, cid)
        if not ok:
            ch = get_channel(user_id, cid)
            name = ch.get("name") if ch else cid
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=f"❌ «{name}» vaqtli yuborish to‘xtadi.\n\n{info}"
                )
            except Exception:
                pass
            break

        if index < count - 1:
            await asyncio.sleep(1)


async def scheduled_sender():
    while True:
        try:
            now = datetime.now(TZ)
            current = now.strftime("%H:%M")
            today = now.strftime("%Y-%m-%d")

            for user_id_str, user_settings in list(profiles.items()):
                user_id = int(user_id_str)

                for cid, ch in list((user_settings.get("channels") or {}).items()):
                    for sch in ch.get("schedules", []):
                        count = int(sch.get("count", 0))

                        if (
                            count > 0
                            and sch.get("time") == current
                            and sch.get("last_date") != today
                        ):
                            sch["last_date"] = today
                            save_profiles()

                            asyncio.create_task(
                                run_scheduled_channel(user_id, cid, count)
                            )

            await asyncio.sleep(1)

        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(5)


# =========================
# START
# =========================
async def main():
    print("BOT ISHLAYAPTI...")
    print("Panel: /panel (hamma foydalanuvchi uchun ochiq)")

    await asyncio.gather(
        dp.start_polling(bot),
        automatic_sender(),
        scheduled_sender(),
    )


if __name__ == "__main__":
    asyncio.run(main())
