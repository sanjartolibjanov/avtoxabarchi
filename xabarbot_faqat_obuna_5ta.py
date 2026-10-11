import asyncio
import json
import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder


# =========================
# ASOSIY SOZLAMALAR
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")

BASE_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = BASE_DIR / "settings.json"
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

DEFAULT_SETTINGS = {
    "channel_id": "",
    "subscription_channel_id": "",
    "subscription_link": "",
    "limit": 100,
    "intervals": [180, 240],
    "amounts": [50000, 100000, 150000, 250000, 900000],
    "message_text": DEFAULT_TEXT,
    "inline_text": "",
    "inline_url": "",
    "running": False,
    "schedule_time": "",
    "schedule_count": 0,
    "last_schedule_date": "",
    "sent_count": 0,
    "start_time": "",
}


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


def default_settings():
    return {
        "channel_id": "",
        "subscription_channel_id": "",
        "subscription_link": "",
        "subscription_channels": [],
        "limit": 100,
        "intervals": [180, 240],
        "amounts": [50000, 100000, 150000, 250000, 900000],
        "message_text": DEFAULT_TEXT,
        "inline_text": "",
        "inline_url": "",
        "running": False,
        "schedule_time": "",
        "schedule_count": 0,
        "last_schedule_date": "",
        "sent_count": 0,
        "start_time": "",
    }


def get_settings(user_id: int):
    key = str(user_id)

    if key not in profiles or not isinstance(profiles[key], dict):
        profiles[key] = default_settings()
        save_profiles()

    # Kelajakdagi yangi sozlamalar uchun ham default qiymatlar qo'shiladi.
    defaults = default_settings()
    changed = False
    for k, v in defaults.items():
        if k not in profiles[key]:
            profiles[key][k] = v
            changed = True

    if changed:
        save_profiles()

    return profiles[key]


def get_user_image(user_id: int) -> Path:
    """Har bir Telegram profilining o'z rasmi."""
    user_dir = PROFILE_MEDIA_DIR / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / "promo.png"


def save_profiles():
    PROFILES_FILE.write_text(
        json.dumps(profiles, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# =========================
# ADMIN HOLATINI SAQLASH
# =========================
admin_waiting = {}


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


def random_amount(user_settings=None):
    amounts = (user_settings or default_settings()).get("amounts") or default_settings()["amounts"]
    return f"{random.choice(amounts):,}".replace(",", " ")


def uz_time():
    return datetime.now(TZ).strftime("%Y.%m.%d %H:%M")


def make_text(user_settings):
    template = user_settings.get("message_text") or DEFAULT_TEXT
    text = template
    text = text.replace("{randomnik}", random_name())
    amounts = user_settings.get("amounts") or DEFAULT_SETTINGS["amounts"]
    text = text.replace("{randomsumma}", f"{random.choice(amounts):,}".replace(",", " "))
    text = text.replace("{randomkarta}", random_card())
    text = text.replace("{vaqt}", uz_time())
    text = text.replace("{raundrandom]", random.choice([
        "📈 Narx ko‘tarilishiga tikdi 🟢",
        "📉 Narx tushishiga tikdi 🔴",
    ]))

    if "demo" not in text.lower() and "test" not in text.lower():
        text = "🧪 DEMO\n" + text

    return text


# =========================
# ADMIN KLAVIATURASI
# =========================
def admin_keyboard():
    kb = ReplyKeyboardBuilder()

    kb.button(text="▶️ Boshlash")
    kb.button(text="⏹ To‘xtatish")
    kb.button(text="⚡ Birdan xabar")
    kb.button(text="⏰ Vaqtli yuborish")

    kb.button(text="📊 Statistika")
    kb.button(text="🔢 Xabar soni")
    kb.button(text="⏱ Interval")
    kb.button(text="💰 Summalar")

    kb.button(text="📢 Kanal")
    kb.button(text="📝 Xabar matni")
    kb.button(text="🖼 Rasm")
    kb.button(text="🔘 Inline tugma")

    kb.button(text="❌ Tugmani o‘chirish")
    kb.button(text="🔐 Majburiy obuna")

    kb.adjust(2, 2, 2, 2, 2, 2, 2)
    return kb.as_markup(resize_keyboard=True)


# =========================
# INLINE TUGMA
# =========================
def make_inline(user_settings):
    text = user_settings.get("inline_text", "")
    url = user_settings.get("inline_url", "")

    if not text or not url:
        return None

    kb = InlineKeyboardBuilder()
    kb.button(text=text, url=url)
    return kb.as_markup()


# =========================
# KANALGA YUBORISH
# =========================
async def send_one(user_id: int):
    user_settings = get_settings(user_id)
    channel_id = user_settings.get("channel_id")

    if not channel_id:
        return False, "Kanal ID kiritilmagan."

    try:
        inline = make_inline(user_settings)
        text = make_text(user_settings)

        user_image = get_user_image(user_id)

        if not user_image.exists():
            return False, "Siz hali 🖼 Rasm bo‘limidan shaxsiy rasmingizni yuklamagansiz."

        await bot.send_photo(
            chat_id=channel_id,
            photo=FSInputFile(user_image),
            caption=text,
            reply_markup=inline,
        )

        user_settings["sent_count"] = int(user_settings.get("sent_count", 0)) + 1
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
# /ADMIN
# =========================
@router.message(Command("panel"))
async def panel_command(message: Message):
    if not is_admin(message):
        return

    await message.answer(
        "👤 Sizning shaxsiy panelingiz\n\nKerakli bo‘limni tanlang:",
        reply_markup=admin_keyboard(),
    )


# =========================
# ADMIN MATN BUYRUQLARI
# =========================
# =========================
@router.message(F.text == "▶️ Boshlash")
async def start_sending(message: Message):
    if not is_admin(message):
        return
    user_settings = get_settings(message.from_user.id)

    if user_settings.get("running"):
        await message.answer("⚠️ Avtomatik yuborish allaqachon ishlayapti.")
        return

    user_settings["running"] = True
    user_settings["start_time"] = uz_time()
    save_profiles()

    await message.answer(
        f"▶️ Avtomatik yuborish boshlandi.\n"
        f"🔢 Limit: {user_settings['limit']} ta\n"
        f"⏱ Interval: {user_settings['intervals']} soniya\n\n"
        f"⚡ Birinchi DEMO xabar darhol yuboriladi."
    )


@router.message(F.text == "⏹ To‘xtatish")
async def stop_sending(message: Message):
    if not is_admin(message):
        return
    user_settings = get_settings(message.from_user.id)

    user_settings["running"] = False
    save_profiles()

    task = running_tasks.get(message.from_user.id)
    if task:
        task.cancel()

    await message.answer("⏹ Avtomatik yuborish to‘xtatildi.")


@router.message(F.text == "⚡ Birdan xabar")
async def one_message(message: Message):
    if not is_admin(message):
        return
    user_settings = get_settings(message.from_user.id)

    ok, info = await send_one(message.from_user.id)

    if ok:
        await message.answer("⚡ DEMO xabar kanalga yuborildi.")
    else:
        await message.answer(f"❌ Yuborilmadi:\n{info}")


@router.message(F.text == "📊 Statistika")
async def statistics(message: Message):
    if not is_admin(message):
        return
    user_settings = get_settings(message.from_user.id)

    await message.answer(
        "📊 Statistika\n\n"
        f"Yuborilgan xabarlar: {user_settings.get('sent_count', 0)}\n"
        f"Limit: {user_settings.get('limit', 100)}\n"
        f"Interval: {user_settings.get('intervals')}\n"
        f"Avto yuborish: {'ON 🟢' if user_settings.get('running') else 'OFF 🔴'}\n"
        f"Boshlangan vaqt: {user_settings.get('start_time') or '—'}\n"
        f"Reja: {user_settings.get('schedule_time') or '—'} / "
        f"{user_settings.get('schedule_count', 0)} ta"
    )


@router.message(F.text == "🔢 Xabar soni")
async def ask_limit(message: Message):
    global admin_waiting

    if not is_admin(message):
        return
    user_settings = get_settings(message.from_user.id)

    admin_waiting[message.from_user.id] = "limit"
    await message.answer(
        "🔢 Nechta xabar yuborilsin?\n\n"
        "Faqat son yuboring. Masalan: 100"
    )


@router.message(F.text == "⏱ Interval")
async def ask_interval(message: Message):
    global admin_waiting

    if not is_admin(message):
        return
    user_settings = get_settings(message.from_user.id)

    admin_waiting[message.from_user.id] = "interval"
    await message.answer(
        "⏱ Har bir xabar orasidagi vaqtni soniyada kiriting.\n\n"
        "Bitta qiymat: 10\n"
        "Yoki bir nechta: 10 20 30"
    )


@router.message(F.text == "💰 Summalar")
async def ask_amounts(message: Message):
    global admin_waiting

    if not is_admin(message):
        return
    user_settings = get_settings(message.from_user.id)

    admin_waiting[message.from_user.id] = "amounts"
    await message.answer(
        "💰 Summalarni bo‘sh joy bilan yuboring.\n"
        "Masalan:\n"
        "50000 100000 150000 250000 900000"
    )


@router.message(F.text == "📢 Kanal")
async def ask_channel(message: Message):
    global admin_waiting

    if not is_admin(message):
        return
    user_settings = get_settings(message.from_user.id)

    admin_waiting[message.from_user.id] = "channel"
    await message.answer(
        "📢 Post yuboriladigan kanal ID sini yuboring.\n"
        "Masalan: -1001234567890\n\n"
        "Bot kanalga ADMIN bo‘lishi kerak."
    )


@router.message(F.text == "🔐 Majburiy obuna")
async def ask_subscription(message: Message):
    global admin_waiting

    if not is_admin(message):
        return

    user_settings = get_settings(message.from_user.id)

    admin_waiting[message.from_user.id] = "subscription"

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


@router.message(F.text == "📝 Xabar matni")
async def ask_text(message: Message):
    global admin_waiting

    if not is_admin(message):
        return
    user_settings = get_settings(message.from_user.id)

    admin_waiting[message.from_user.id] = "message_text"
    await message.answer(
        "📝 Xabar matnini yuboring.\n\n"
        "Ishlatish mumkin:\n"
        "{randomnik}\n"
        "{randomsumma}\n"
        "{randomkarta}\n"
        "{vaqt}\n"
        "{raundrandom]\n\n"
        "Xabar DEMO/TEST deb ko‘rsatiladi."
    )


@router.message(F.text == "⏰ Vaqtli yuborish")
async def ask_schedule(message: Message):
    global admin_waiting

    if not is_admin(message):
        return
    user_settings = get_settings(message.from_user.id)

    admin_waiting[message.from_user.id] = "schedule"
    await message.answer(
        "⏰ Vaqtli yuborish formatini yuboring:\n\n"
        "HH:MM COUNT\n\n"
        "Masalan:\n"
        "20:30 20\n\n"
        "Bu vaqtda 20 ta DEMO xabar yuboriladi."
    )


@router.message(F.text == "🔘 Inline tugma")
async def ask_inline(message: Message):
    global admin_waiting

    if not is_admin(message):
        return
    user_settings = get_settings(message.from_user.id)

    admin_waiting[message.from_user.id] = "inline"
    await message.answer(
        "🔘 Inline tugma uchun 2 qator yuboring:\n\n"
        "1-qator: tugma nomi\n"
        "2-qator: URL\n\n"
        "Masalan:\n"
        "📲 Kanalga kirish\n"
        "https://t.me/kanal"
    )


@router.message(F.text == "❌ Tugmani o‘chirish")
async def remove_inline(message: Message):
    if not is_admin(message):
        return
    user_settings = get_settings(message.from_user.id)

    user_settings["inline_text"] = ""
    user_settings["inline_url"] = ""
    save_profiles()
    await message.answer("❌ Inline tugma o‘chirildi.")


@router.message(F.photo)
async def upload_image(message: Message):
    global admin_waiting

    if not is_admin(message):
        return
    user_settings = get_settings(message.from_user.id)

    if admin_waiting.get(message.from_user.id) != "image":
        return

    try:
        photo = message.photo[-1]
        user_image = get_user_image(message.from_user.id)
        await bot.download(photo, destination=user_image)
        admin_waiting.pop(message.from_user.id, None)
        await message.answer(
            "🖼 Sizning shaxsiy rasmingiz saqlandi.\n"
            "Bu rasm boshqa profillarga o'tmaydi."
        )
    except Exception as e:
        await message.answer(f"❌ Rasm saqlanmadi:\n{e}")


@router.message(F.text == "🖼 Rasm")
async def ask_image(message: Message):
    global admin_waiting

    if not is_admin(message):
        return
    user_settings = get_settings(message.from_user.id)

    admin_waiting[message.from_user.id] = "image"
    await message.answer("🖼 Endi yangi rasmni yuboring.\n\nBu rasm faqat sizning profilingizda saqlanadi.")


# =========================
# ADMIN KIRITGAN MA'LUMOTLARNI QABUL QILISH
# =========================
@router.message(F.text)
async def admin_input(message: Message):
    global admin_waiting

    if not is_admin(message):
        return

    if message.text.startswith("/"):
        return

    if message.from_user.id not in admin_waiting:
        return

    # Har bir foydalanuvchi o‘zining alohida sozlamalariga ega.
    user_settings = get_settings(message.from_user.id)
    value = message.text.strip()

    try:
        if admin_waiting.get(message.from_user.id) == "limit":
            n = int(value)
            if n < 1:
                raise ValueError
            user_settings["limit"] = n
            save_profiles()
            await message.answer(f"✅ Xabar limiti: {n}")
            admin_waiting.pop(message.from_user.id, None)

        elif admin_waiting.get(message.from_user.id) == "interval":
            vals = [int(x) for x in value.split()]
            if not vals or any(x < 1 for x in vals):
                raise ValueError
            user_settings["intervals"] = vals
            save_profiles()
            await message.answer(f"✅ Interval saqlandi: {vals} soniya")
            admin_waiting.pop(message.from_user.id, None)

        elif admin_waiting.get(message.from_user.id) == "amounts":
            vals = [int(x) for x in value.split()]
            if not vals or any(x < 0 for x in vals):
                raise ValueError
            user_settings["amounts"] = vals
            save_profiles()
            await message.answer(f"✅ Summalar saqlandi: {vals}")
            admin_waiting.pop(message.from_user.id, None)

        elif admin_waiting.get(message.from_user.id) == "channel":
            user_settings["channel_id"] = value
            save_profiles()
            await message.answer(
                "✅ Kanal ID saqlandi.\n"
                f"Kanal: {value}"
            )
            admin_waiting.pop(message.from_user.id, None)

        elif admin_waiting.get(message.from_user.id) == "subscription":
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

            user_settings["subscription_channels"] = channels

            # Eski format bilan ham moslik saqlanadi.
            user_settings["subscription_channel_id"] = channels[0]["id"]
            user_settings["subscription_link"] = channels[0]["link"]

            save_profiles()

            await message.answer(
                f"✅ {len(channels)} ta majburiy kanal saqlandi.\n\n"
                "Har bir foydalanuvchi barcha kanallarga "
                "obuna bo‘lgandan keyin botga kira oladi."
            )

            admin_waiting.pop(message.from_user.id, None)

        elif admin_waiting.get(message.from_user.id) == "message_text":
            user_settings["message_text"] = value
            save_profiles()
            await message.answer(
                "✅ Xabar matni saqlandi.\n\n"
                "Eslatma: xabar DEMO/TEST belgisisiz yuborilmaydi."
            )
            admin_waiting.pop(message.from_user.id, None)

        elif admin_waiting.get(message.from_user.id) == "schedule":
            parts = value.split()
            if len(parts) != 2:
                raise ValueError

            time_value = parts[0]
            count = int(parts[1])

            datetime.strptime(time_value, "%H:%M")

            if count < 1:
                raise ValueError

            user_settings["schedule_time"] = time_value
            user_settings["schedule_count"] = count
            user_settings["last_schedule_date"] = ""
            save_profiles()

            await message.answer(
                f"✅ Vaqtli yuborish saqlandi:\n"
                f"⏰ {time_value}\n"
                f"🔢 {count} ta DEMO xabar"
            )
            admin_waiting.pop(message.from_user.id, None)

        elif admin_waiting.get(message.from_user.id) == "inline":
            lines = value.splitlines()
            if len(lines) < 2:
                raise ValueError

            button_text = lines[0].strip()
            url = lines[1].strip()

            if not url.startswith(("http://", "https://", "tg://")):
                await message.answer("❌ URL http:// yoki https:// bilan boshlansin.")
                return

            user_settings["inline_text"] = button_text
            user_settings["inline_url"] = url
            save_profiles()

            await message.answer(
                "✅ Inline tugma faqat sizning profilingizga saqlandi.\n\n"
                f"🔘 {button_text}\n"
                f"🔗 {url}"
            )
            admin_waiting.pop(message.from_user.id, None)

    except Exception:
        await message.answer(
            "❌ Format xato.\n"
            "Qaytadan to‘g‘ri formatda yuboring."
        )

    if message.from_user.id in admin_waiting:
        save_profiles()


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
# AVTO YUBORISH
# =========================
running_tasks = {}


async def run_user_sender(user_id: int):
    """Faqat bitta foydalanuvchining avtomatik yuborish jarayoni."""
    user_settings = get_settings(user_id)
    limit = max(1, int(user_settings.get("limit", 100)))
    intervals = [int(x) for x in (user_settings.get("intervals") or [180])]
    intervals = [x for x in intervals if x > 0] or [180]

    try:
        for index in range(limit):
            user_settings = get_settings(user_id)

            if not user_settings.get("running"):
                break

            ok, info = await send_one(user_id)

            if not ok:
                user_settings["running"] = False
                save_profiles()
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text=f"❌ Yuborish to‘xtadi.\n\n{info}"
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
        user_settings = get_settings(user_id)
        user_settings["running"] = False
        save_profiles()
        running_tasks.pop(user_id, None)


async def automatic_sender():
    """Barcha profillarni mustaqil kuzatadi."""
    while True:
        try:
            for user_id_str, user_settings in list(profiles.items()):
                user_id = int(user_id_str)

                if user_settings.get("running") and user_id not in running_tasks:
                    running_tasks[user_id] = asyncio.create_task(
                        run_user_sender(user_id)
                    )

            await asyncio.sleep(1)

        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(5)


# =========================
# VAQTLI YUBORISH
# =========================
async def run_scheduled_user(user_id: int, count: int):
    for index in range(count):
        ok, info = await send_one(user_id)
        if not ok:
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=f"❌ Vaqtli yuborish to‘xtadi.\n\n{info}"
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
                schedule_time = user_settings.get("schedule_time", "")
                count = int(user_settings.get("schedule_count", 0))

                if (
                    schedule_time
                    and count > 0
                    and current == schedule_time
                    and user_settings.get("last_schedule_date") != today
                ):
                    user_settings["last_schedule_date"] = today
                    save_profiles()

                    user_id = int(user_id_str)
                    asyncio.create_task(run_scheduled_user(user_id, count))

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
