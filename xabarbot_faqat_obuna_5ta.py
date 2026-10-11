import os
import asyncio
import sqlite3
import time
import secrets
import base64
import binascii
import json
from contextlib import closing

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, WebAppInfo, FSInputFile,
    InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile,
)
from dotenv import load_dotenv

load_dotenv()
BASE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.getenv('BOT_TOKEN', '').strip()
WEBAPP_URL = os.getenv('WEBAPP_URL', '').strip()
ADMIN_ID_RAW = os.getenv('ADMIN_ID', '').strip()
DATA_DIR = '/data' if os.path.isdir('/data') else BASE
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, 'trend_linya_demo.db')
try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except (TypeError, ValueError):
    ADMIN_ID = 0

PORT = int(os.getenv('PORT', '8080'))

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DATA_DIR, 'trend_linya_demo.db')
BET_SECONDS = 15
RUN_SECONDS = 30  # 30 soniya narx harakati: 15 soniya odatiy, keyin strategiya
RESULT_SECONDS = 5
ROUND_SECONDS = BET_SECONDS + RUN_SECONDS + RESULT_SECONDS
START_BALANCE = 0
app = FastAPI(title='Trend Linya Demo', docs_url=None, redoc_url=None)
BOT_INSTANCE = None
app.mount('/static', StaticFiles(directory=os.path.join(BASE, 'static'), check_dir=False), name='static')


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with closing(db()) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, balance INTEGER NOT NULL)''')
        con.execute('''CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, round_id INTEGER NOT NULL, side TEXT NOT NULL, amount INTEGER NOT NULL, settled INTEGER NOT NULL DEFAULT 0)''')
        con.execute('''CREATE TABLE IF NOT EXISTS wallet_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('topup','withdraw')), amount INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, receipt_data BLOB, receipt_name TEXT, withdraw_phone TEXT, withdraw_card TEXT, withdraw_full_name TEXT, telegram_username TEXT, balance_snapshot INTEGER, total_deposited INTEGER)''')
        con.execute('''CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)''')
        con.execute('''CREATE TABLE IF NOT EXISTS online_sessions (user_id TEXT PRIMARY KEY, last_seen REAL NOT NULL)''')
        con.execute('''CREATE TABLE IF NOT EXISTS referrals (invited_id TEXT PRIMARY KEY, referrer_id TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        con.execute('''CREATE TABLE IF NOT EXISTS referral_rewards (id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER NOT NULL UNIQUE, referrer_id TEXT NOT NULL, invited_id TEXT NOT NULL, amount INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        # Migrate an existing DB created by earlier builds.
        cols = {row[1] for row in con.execute('PRAGMA table_info(wallet_requests)').fetchall()}
        if 'receipt_data' not in cols:
            con.execute('ALTER TABLE wallet_requests ADD COLUMN receipt_data BLOB')
        if 'receipt_name' not in cols:
            con.execute('ALTER TABLE wallet_requests ADD COLUMN receipt_name TEXT')
        for column, declaration in [('withdraw_card','TEXT'),('withdraw_full_name','TEXT'),('telegram_username','TEXT'),('balance_snapshot','INTEGER'),('total_deposited','INTEGER'),('approved_at','TEXT')]:
            if column not in cols:
                con.execute(f'ALTER TABLE wallet_requests ADD COLUMN {column} {declaration}')
        con.commit()
init_db()

def get_setting(key: str, default: str = '') -> str:
    with closing(db()) as con:
        row = con.execute('SELECT value FROM app_settings WHERE key=?', (key,)).fetchone()
        return str(row['value']) if row else default


def set_setting(key: str, value: str) -> None:
    with closing(db()) as con:
        con.execute('INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value.strip()))
        con.commit()


class UserIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=80)
class BetIn(UserIn):
    side: str
    amount: int = Field(gt=0, le=1_000_000)


def ensure_user(user_id: str):
    with closing(db()) as con:
        con.execute('INSERT OR IGNORE INTO users(user_id,balance) VALUES(?,?)', (user_id, START_BALANCE))
        con.commit()
        row = con.execute('SELECT balance FROM users WHERE user_id=?', (user_id,)).fetchone()
        return int(row['balance'])


def current_round():
    now = time.time()
    cycle_id = int(now // ROUND_SECONDS)
    elapsed = now % ROUND_SECONDS
    if elapsed < BET_SECONDS:
        left = BET_SECONDS - elapsed
        return {'round_id': cycle_id, 'remaining': max(1, int(left)), 'phase': 'betting',
                'phase_remaining': max(1, int(left)), 'elapsed': int(elapsed)}
    if elapsed < BET_SECONDS + RUN_SECONDS:
        left = BET_SECONDS + RUN_SECONDS - elapsed
        return {'round_id': cycle_id, 'remaining': max(1, int(left)), 'phase': 'running',
                'phase_remaining': max(1, int(left)), 'elapsed': int(elapsed)}
    left = ROUND_SECONDS - elapsed
    return {'round_id': cycle_id, 'remaining': max(1, int(left)), 'phase': 'result',
            'phase_remaining': max(1, int(left)), 'elapsed': int(elapsed)}


def winner_for(round_id: int):
    """Demo raund natijasi: summalar 5.88% ichida farq qilsa durang."""
    with closing(db()) as con:
        rows = con.execute(
            'SELECT side, COALESCE(SUM(amount),0) AS total FROM bets '
            'WHERE round_id=? GROUP BY side',
            (round_id,)
        ).fetchall()
    totals = {row['side']: int(row['total'] or 0) for row in rows}
    with closing(db()) as con:
        player_count = con.execute(
            'SELECT COUNT(DISTINCT user_id) FROM bets WHERE round_id=?',
            (round_id,)
        ).fetchone()[0]
    if 0 < player_count < 2:
        return 'few_players'
    up_total = totals.get('up', 0)
    down_total = totals.get('down', 0)
    total = up_total + down_total
    if total > 0:
        difference_percent = round(abs(up_total - down_total) / total * 100, 2)
        if difference_percent <= 5.88:
            return 'draw'
    if up_total > down_total:
        return 'down'
    if down_total > up_total:
        return 'up'
    # Tikish yo'q bo'lsa, mavjud demo xulqi saqlanadi.
    return 'up' if round_id % 2 == 0 else 'down'


@app.get('/')
def index():
    index_path = os.path.join(BASE, 'index.html')
    if not os.path.isfile(index_path):
        raise HTTPException(503, 'index.html topilmadi. Trend Linya frontend faylini main.py yoniga joylang.')
    return FileResponse(index_path)

@app.get('/api/state')
def state(user_id: str = 'demo-user'):
    user_id = user_id[:80] or 'demo-user'
    balance = ensure_user(user_id)
    rnd = current_round()
    with closing(db()) as con:
        rows = con.execute('SELECT side, amount FROM bets WHERE user_id=? AND round_id=?', (user_id, rnd['round_id'])).fetchall()
    return {'user_id': user_id, 'balance': balance, **rnd, 'direction': (winner_for(rnd['round_id']) if rnd['phase'] in ('running', 'result') else None), 'my_bets': [{'side': r['side'], 'amount': r['amount']} for r in rows], 'mode': 'DEMO'}


@app.post('/api/online/ping')
def online_ping(body: UserIn):
    # Faol Mini App sessiyalari: oxirgi 35 soniyada ping yuborgan noyob user_id lar.
    user_id = body.user_id[:80]
    if not user_id:
        raise HTTPException(400, 'Foydalanuvchi ID topilmadi')
    now = time.time()
    with closing(db()) as con:
        con.execute(
            'INSERT INTO online_sessions(user_id,last_seen) VALUES(?,?) '
            'ON CONFLICT(user_id) DO UPDATE SET last_seen=excluded.last_seen',
            (user_id, now)
        )
        con.execute('DELETE FROM online_sessions WHERE last_seen < ?', (now - 35,))
        count = con.execute(
            'SELECT COUNT(*) FROM online_sessions WHERE last_seen >= ?', (now - 35,)
        ).fetchone()[0]
        con.commit()
    return {'ok': True, 'online': int(count)}

@app.get('/api/my-bets')
def my_bets(user_id: str = 'demo-user'):
    user_id = user_id[:80] or 'demo-user'
    result_dir = os.path.join(BASE, 'round_results')
    with closing(db()) as con:
        rows = con.execute(
            'SELECT id, round_id, side, amount, settled FROM bets WHERE user_id=? ORDER BY id DESC LIMIT 200',
            (user_id,)
        ).fetchall()
        totals = con.execute(
            'SELECT COALESCE(SUM(amount),0) AS wagered FROM bets WHERE user_id=?', (user_id,)
        ).fetchone()
        all_rows = con.execute(
            'SELECT round_id, side, amount, settled FROM bets WHERE user_id=?', (user_id,)
        ).fetchall()
    lost_total = 0
    rendered = []
    for row in rows:
        winner = None
        result_path = os.path.join(result_dir, f"{int(row['round_id'])}.txt")
        try:
            with open(result_path, 'r', encoding='utf-8') as result_file:
                winner = result_file.read().strip()
        except OSError:
            pass
        if not int(row['settled']):
            status = 'Kutilmoqda'
        elif winner == 'draw':
            status = 'Durang (50% qaytdi)'
        elif winner == 'few_players':
            status = 'O‘yinchilar kam — pul qaytdi'
        elif winner in ('up', 'down') and row['side'] == winner:
            status = 'Yutdi'
        elif winner in ('up', 'down'):
            status = 'Yutqazdi'
        else:
            status = 'Yakunlangan'
        rendered.append({'id': int(row['id']), 'round_id': int(row['round_id']),
                         'side': row['side'], 'amount': int(row['amount']),
                         'settled': bool(row['settled']), 'status': status})
    # Cumulative loss total is calculated over all stored bets, not just the displayed 200.
    for row in all_rows:
        if not int(row['settled']):
            continue
        result_path = os.path.join(result_dir, f"{int(row['round_id'])}.txt")
        try:
            with open(result_path, 'r', encoding='utf-8') as result_file:
                winner = result_file.read().strip()
        except OSError:
            continue
        if winner == 'draw':
            lost_total += int(row['amount']) - (int(row['amount']) // 2)
        elif winner in ('up', 'down') and row['side'] != winner:
            lost_total += int(row['amount'])
    return {'total_wagered': int(totals['wagered'] or 0),
            'total_lost': lost_total, 'bets': rendered}


@app.post('/api/bet')
def place_bet(body: BetIn):
    if body.side not in ('up', 'down'):
        raise HTTPException(400, 'Yo‘nalish noto‘g‘ri')
    rnd = current_round()
    if rnd['phase'] != 'betting':
        raise HTTPException(409, 'Hozir tikish yopiq. Keyingi 15 soniyalik tikish oynasini kuting.')
    balance = ensure_user(body.user_id)
    if body.amount > balance:
        raise HTTPException(400, 'Demo balans yetarli emas')
    with closing(db()) as con:
        con.execute('UPDATE users SET balance=balance-? WHERE user_id=?', (body.amount, body.user_id))
        con.execute('INSERT INTO bets(user_id,round_id,side,amount) VALUES(?,?,?,?)', (body.user_id, rnd['round_id'], body.side, body.amount))
        con.commit()
        new_balance = con.execute('SELECT balance FROM users WHERE user_id=?', (body.user_id,)).fetchone()['balance']
    return {'ok': True, 'balance': int(new_balance), 'round_id': rnd['round_id']}

@app.get('/api/result')
def result(round_id: int, user_id: str = 'demo-user'):
    # Results are cached per round so all users see the same outcome.
    result_file = os.path.join(BASE, 'round_results')
    os.makedirs(result_file, exist_ok=True)
    path = os.path.join(result_file, f'{round_id}.txt')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f: winner = f.read().strip()
    else:
        now = time.time()
        cycle_id = int(now // ROUND_SECONDS)
        elapsed = now % ROUND_SECONDS
        # Natija tikish oynasi va 30 soniyalik harakat tugagandan keyin beriladi.
        if round_id > cycle_id or (round_id == cycle_id and elapsed < BET_SECONDS + RUN_SECONDS):
            raise HTTPException(409, 'Raund hali tugamadi')
        winner = winner_for(round_id)
        with open(path, 'w', encoding='utf-8') as f: f.write(winner)
    with closing(db()) as con:
        bets = con.execute('SELECT id,side,amount FROM bets WHERE user_id=? AND round_id=? AND settled=0', (user_id, round_id)).fetchall()
        wagered = sum(int(b['amount']) for b in bets)
        if winner == 'draw':
            # Durangda har bir foydalanuvchiga jami tikkan pulining 50% qaytariladi.
            payout = wagered // 2
        elif winner == 'few_players':
            # Raundda faqat bitta o‘yinchi qatnashsa, uning tikkan puli to‘liq qaytariladi.
            payout = wagered
        else:
            payout = sum(int(b['amount']) * 2 for b in bets if b['side'] == winner)
        profit = payout - wagered
        con.execute('UPDATE users SET balance=balance+? WHERE user_id=?', (payout, user_id))
        con.execute('UPDATE bets SET settled=1 WHERE user_id=? AND round_id=?', (user_id, round_id))
        con.commit()
        balance = con.execute('SELECT balance FROM users WHERE user_id=?', (user_id,)).fetchone()
    return {'round_id': round_id, 'winner': winner, 'payout': payout, 'wagered': wagered, 'profit': profit, 'balance': int(balance['balance']) if balance else ensure_user(user_id)}

@app.post('/api/demo-reset')
def reset(body: UserIn):
    with closing(db()) as con:
        con.execute('INSERT INTO users(user_id,balance) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET balance=?', (body.user_id, START_BALANCE, START_BALANCE))
        con.commit()
    return {'ok': True, 'balance': START_BALANCE}



class WalletRequestIn(UserIn):
    kind: str
    amount: int = Field(gt=0, le=100_000_000)
    receipt_data: str | None = Field(default=None, max_length=1_500_000)
    receipt_name: str | None = Field(default='chek.jpg', max_length=160)
    username: str | None = Field(default='', max_length=64)
    card_number: str | None = Field(default='', max_length=24)
    full_name: str | None = Field(default='', max_length=100)


@app.get('/api/wallet/config')
def wallet_config():
    return {'card_number': get_setting('card_number', ''), 'bank_name': get_setting('bank_name', '')}


@app.get('/api/referrals')
async def referral_info(user_id: str = 'demo-user'):
    user_id = user_id[:80]
    if not user_id.isdigit():
        raise HTTPException(400, 'Taklif havolasi uchun Mini App’ni Telegram ichidan oching')
    bot_username = ''
    if BOT_INSTANCE:
        try:
            me = await BOT_INSTANCE.get_me()
            bot_username = me.username or ''
        except Exception:
            pass
    invite_link = f'https://t.me/{bot_username}?start=ref_{user_id}' if bot_username else ''
    with closing(db()) as con:
        total = con.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id=?', (user_id,)).fetchone()[0]
        earned = con.execute('SELECT COALESCE(SUM(amount),0) FROM referral_rewards WHERE referrer_id=?', (user_id,)).fetchone()[0]
        rows = con.execute(
            """SELECT r.invited_id,
                      COALESCE((SELECT SUM(w.amount) FROM wallet_requests w
                                WHERE w.user_id=r.invited_id AND w.kind='topup' AND w.status='approved'),0) AS deposited,
                      COALESCE((SELECT SUM(rr.amount) FROM referral_rewards rr
                                WHERE rr.invited_id=r.invited_id AND rr.referrer_id=r.referrer_id),0) AS reward
               FROM referrals r WHERE r.referrer_id=?
               ORDER BY deposited DESC, reward DESC, r.created_at ASC LIMIT 20""",
            (user_id,)
        ).fetchall()
    friends = [{'user_id': str(row['invited_id']), 'deposited': int(row['deposited'] or 0),
                'reward': int(row['reward'] or 0)} for row in rows]
    return {'invite_link': invite_link, 'count': int(total), 'earned': int(earned),
            'friends': friends, 'remaining_count': max(0, int(total) - len(friends)),
            'demo': True}


@app.get('/api/evidence')
def evidence_links():
    try:
        links = json.loads(get_setting('evidence_links', '[]'))
        if not isinstance(links, list):
            links = []
    except (ValueError, TypeError):
        links = []
    return {'links': [item for item in links if isinstance(item, dict) and item.get('title') and item.get('url')]}


@app.post('/api/wallet/request')
async def create_wallet_request(body: WalletRequestIn):
    if body.kind not in ('topup', 'withdraw'):
        raise HTTPException(400, 'So‘rov turi noto‘g‘ri')
    if body.kind == 'topup' and body.amount < 50000:
        raise HTTPException(400, 'Minimal balans to‘ldirish miqdori 50 000 so‘m')
    if body.kind == 'withdraw' and body.amount < 20000:
        raise HTTPException(400, 'Pul chiqarish uchun eng kam summa 20 000 so‘m')
    # Wallet requests need a real Telegram numeric ID so admin decisions can be sent to the correct user.
    if not body.user_id.isdigit():
        raise HTTPException(400, 'Telegram ID olinmadi. Mini App’ni Telegram bot ichidan oching.')
    receipt_bytes = None
    if body.kind == 'withdraw':
        card_digits = ''.join(ch for ch in (body.card_number or '') if ch.isdigit())
        full_name = (body.full_name or '').strip()
        if not 12 <= len(card_digits) <= 20:
            raise HTTPException(400, 'Karta raqami 12–20 ta raqam bo‘lishi kerak')
        if len(full_name) < 5 or len(full_name) > 100:
            raise HTTPException(400, 'Karta egasining to‘liq ismini kiriting')
        if not get_setting('withdraw_group_id'):
            raise HTTPException(409, 'Admin pul chiqarish guruhini sozlamagan')
    if body.kind == 'topup':
        if not body.receipt_data or not body.receipt_data.startswith('data:image/') or ',' not in body.receipt_data:
            raise HTTPException(400, 'Chek skrinshotini tanlang')
        if not get_setting('card_number') or not get_setting('bank_name'):
            raise HTTPException(409, 'Admin hali karta raqami va bank nomini sozlamagan')
        if not get_setting('requests_group_id'):
            raise HTTPException(409, 'Admin hali arizalar guruhini sozlamagan')
        try:
            encoded = body.receipt_data.split(',', 1)[1]
            receipt_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(400, 'Chek rasmi noto‘g‘ri formatda')
        if len(receipt_bytes) > 900_000:
            raise HTTPException(413, 'Chek rasmi hajmi katta. Kichikroq rasm yuboring.')
    balance = ensure_user(body.user_id)
    with closing(db()) as con:
        pending = con.execute("SELECT id FROM wallet_requests WHERE user_id=? AND kind=? AND status='pending' LIMIT 1", (body.user_id, body.kind)).fetchone()
        if pending:
            raise HTTPException(409, 'Shu turdagi kutayotgan arizangiz bor')
        total_deposited = int(con.execute("SELECT COALESCE(SUM(amount),0) FROM wallet_requests WHERE user_id=? AND kind='topup' AND status='approved'", (body.user_id,)).fetchone()[0])
        if body.kind == 'withdraw':
            if body.amount > balance:
                raise HTTPException(400, 'Balans yetarli emas. Pul chiqarish uchun balansingizda yetarli mablag‘ bo‘lishi kerak.')
            cur_update = con.execute('UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?', (body.amount, body.user_id, body.amount))
            if cur_update.rowcount == 0:
                raise HTTPException(400, 'Demo balans yetarli emas')
        cur = con.execute('''INSERT INTO wallet_requests(user_id,kind,amount,status,receipt_data,receipt_name,withdraw_card,withdraw_full_name,telegram_username,balance_snapshot,total_deposited) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                           (body.user_id, body.kind, body.amount, 'pending', receipt_bytes, body.receipt_name if receipt_bytes else None, ''.join(ch for ch in (body.card_number or '') if ch.isdigit()) if body.kind == 'withdraw' else None, (body.full_name or '').strip() if body.kind == 'withdraw' else None, (body.username or '').strip().lstrip('@') if body.kind == 'withdraw' else None, int(balance) - (body.amount if body.kind == 'withdraw' else 0), total_deposited))
        request_id = cur.lastrowid
        con.commit()
        row = con.execute('SELECT balance FROM users WHERE user_id=?', (body.user_id,)).fetchone()
    # The Telegram group receives the demo request and a decision keyboard.
    group_id = get_setting('requests_group_id')
    if body.kind == 'topup' and BOT_INSTANCE and group_id:
        kind_label = 'DEMO balansni to‘ldirish'
        caption = (f'🧾 <b>{kind_label} arizasi #{request_id}</b>\n'
                   f'👤 Foydalanuvchi: <b>{("@" + body.username.lstrip("@")).strip() if (body.username or "").strip() else "username yo‘q"}</b>\n'
                   f'🆔 Telegram ID: <code>{body.user_id}</code>\n'
                   f'💵 Summa: <b>{body.amount:,} demo so‘m</b>\n'
                   f'📌 Holat: <b>JARAYONDA</b>\n\n'
                   '⚠️ Bu test arizasi. Tasdiqlash faqat virtual balansni o‘zgartiradi.')
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text='✅ Tasdiqlash (demo)', callback_data=f'wreq:ok:{request_id}'),
            InlineKeyboardButton(text='❌ Rad etish', callback_data=f'wreq:no:{request_id}')
        ], [InlineKeyboardButton(text='📩 Xabar yuborish', callback_data=f'wreq:msg:{request_id}')]])
        try:
            await BOT_INSTANCE.send_photo(chat_id=group_id,
                photo=BufferedInputFile(receipt_bytes, filename=(body.receipt_name or 'chek.jpg')),
                caption=caption, reply_markup=kb, parse_mode='HTML')
        except Exception as e:
            # Keep the request visible in admin queue even if group delivery failed.
            print(f'Wallet request #{request_id} group send failed: {e}')
    elif body.kind == 'withdraw' and BOT_INSTANCE and get_setting('withdraw_group_id'):
        group_id = get_setting('withdraw_group_id')
        username_label = '@' + (body.username or '').strip().lstrip('@') if (body.username or '').strip() else 'username yo‘q'
        with closing(db()) as con:
            req = con.execute('SELECT balance_snapshot,total_deposited FROM wallet_requests WHERE id=?', (request_id,)).fetchone()
        caption = (f'🧾 <b>PUL CHIQARISH ARIZASI #{request_id}</b>\n'
                   f'👤 Foydalanuvchi: <b>{username_label}</b>\n'
                   f'🆔 Telegram ID: <code>{body.user_id}</code>\n'
                   f'💳 Karta raqami: <code>{body.card_number}</code>\n'
                   f'🪪 Karta egasi: <b>{body.full_name}</b>\n'
                   f'💵 Yechish summasi: <b>{body.amount:,} so‘m</b>\n'
                   f'💰 Arizadan keyingi balans: <b>{int(req["balance_snapshot"] or 0):,} so‘m</b>\n'
                   f'📥 O‘yin balansiga jami tasdiqlangan tushum: <b>{int(req["total_deposited"] or 0):,} so‘m</b>\n'
                   f'📌 Holat: <b>JARAYONDA</b>\n\n⚠️ Bu demo ariza. Bot haqiqiy pul o‘tkazmasini bajarmaydi.')
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text='✅ Tasdiqlash (demo)', callback_data=f'wreq:ok:{request_id}'),
            InlineKeyboardButton(text='❌ Rad etish', callback_data=f'wreq:no:{request_id}')
        ], [InlineKeyboardButton(text='📩 Xabar yuborish', callback_data=f'wreq:msg:{request_id}')]])
        try:
            await BOT_INSTANCE.send_message(chat_id=group_id, text=caption, reply_markup=kb, parse_mode='HTML')
        except Exception as e:
            print(f'Wallet request #{request_id} group send failed: {e}')
    return {'ok': True, 'request_id': request_id, 'balance': int(row['balance'])}


@app.get('/api/wallet/requests')
def wallet_requests(user_id: str = 'demo-user'):
    with closing(db()) as con:
        rows = con.execute('SELECT id,kind,amount,status,created_at FROM wallet_requests WHERE user_id=? ORDER BY id DESC LIMIT 20', (user_id[:80],)).fetchall()
    labels = {'pending': 'Ko‘rib chiqilmoqda', 'approved': 'Tasdiqlandi (demo)', 'rejected': 'Rad etildi'}
    return {'requests': [{'id': int(r['id']), 'kind': r['kind'], 'amount': int(r['amount']), 'status': r['status'], 'status_label': labels.get(r['status'], r['status']), 'created_at': r['created_at']} for r in rows]}


# Admin states are intentionally simple and in-memory for this demo project.
ADMIN_STATES: dict[int, str] = {}


def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📊 Statistika', callback_data='adm:stats')],
        [InlineKeyboardButton(text='👥 Foydalanuvchilar', callback_data='adm:users')],
        [InlineKeyboardButton(text='📢 Reklama yuborish', callback_data='adm:broadcast')],
        [InlineKeyboardButton(text='💰 Demo balansni o‘zgartirish', callback_data='adm:setbalance')],
        [InlineKeyboardButton(text='🧾 Demo arizalar', callback_data='adm:requests')],
        [InlineKeyboardButton(text='💳 Karta raqamini sozlash', callback_data='adm:card')],
        [InlineKeyboardButton(text='🏦 Bank nomini sozlash', callback_data='adm:bank')],
        [InlineKeyboardButton(text='👥 To‘ldirish arizalari guruhi', callback_data='adm:group')],
        [InlineKeyboardButton(text='↗ Pul chiqarish guruhi', callback_data='adm:withdraw_group')],
        [InlineKeyboardButton(text='🌐 Mini App manzili', callback_data='adm:url')],
        [InlineKeyboardButton(text='🔗 Isbotlar havolalarini boshqarish', callback_data='adm:evidence')],
        [InlineKeyboardButton(text='🟢 Start xabariga tugma qo‘shish', callback_data='adm:start_button')],
        [InlineKeyboardButton(text='🗑 Start tugmasini olib tashlash', callback_data='adm:start_button_remove')],
    ])


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


async def bot_main():
    if not TOKEN:
        raise RuntimeError('BOT_TOKEN .env faylida kiritilmagan')
    global BOT_INSTANCE
    bot = Bot(TOKEN)
    BOT_INSTANCE = bot
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def start(message: Message):
        # Deep-link orqali taklif qilgan do‘stni bir marta bog‘laymiz.
        try:
            payload = (message.text or '').split(maxsplit=1)[1].strip()
            if payload.startswith('ref_') and message.from_user:
                referrer_id = payload[4:]
                invited_id = str(message.from_user.id)
                if referrer_id.isdigit() and referrer_id != invited_id:
                    with closing(db()) as con:
                        con.execute('INSERT OR IGNORE INTO referrals(invited_id,referrer_id) VALUES(?,?)',
                                    (invited_id, referrer_id))
                        con.commit()
        except (IndexError, ValueError):
            pass
        rows = []
        if WEBAPP_URL.startswith('https://') and '.example' not in WEBAPP_URL:
            rows.append([InlineKeyboardButton(text='🟢 O‘yinni boshlash', web_app=WebAppInfo(url=WEBAPP_URL))])
        extra_text = get_setting('start_button_text', '').strip()
        extra_url = get_setting('start_button_url', '').strip()
        if extra_text and extra_url.startswith('https://'):
            rows.append([InlineKeyboardButton(text=extra_text[:64], url=extra_url)])
        kb = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
        banner_path = os.path.join(BASE, 'static', 'start_banner.png')
        if not os.path.isfile(banner_path):
            banner_path = os.path.join(BASE, 'start_banner.png')
        caption = 'Trend Linya bilan pul ishlang, o‘yinni boshlang!'
        if os.path.isfile(banner_path):
            await message.answer_photo(
                photo=FSInputFile(banner_path),
                caption=caption,
                reply_markup=kb,
            )
        else:
            await message.answer(caption + '\n\nRasm topilmadi: static/start_banner.png', reply_markup=kb)

    @dp.message(Command('admin'))
    async def admin(message: Message):
        if not message.from_user or message.from_user.id != ADMIN_ID or not ADMIN_ID:
            await message.answer('⛔ Bu buyruq faqat administrator uchun.')
            return
        await message.answer('🛠 <b>Trend Linya — admin panel</b>\n\nBu panel demo ma’lumotlarini boshqaradi.', reply_markup=admin_keyboard(), parse_mode='HTML')

    @dp.callback_query(F.data.startswith('wreq:msg:'))
    async def wallet_request_message_start(callback: CallbackQuery):
        if not callback.from_user or callback.from_user.id != ADMIN_ID or not ADMIN_ID:
            await callback.answer('Ruxsat yo‘q.', show_alert=True)
            return
        try:
            request_id = int(callback.data.rsplit(':', 1)[1])
        except (ValueError, IndexError):
            await callback.answer('Ariza raqami noto‘g‘ri.', show_alert=True)
            return
        with closing(db()) as con:
            row = con.execute('SELECT user_id, status FROM wallet_requests WHERE id=?', (request_id,)).fetchone()
        if not row:
            await callback.answer('Ariza topilmadi.', show_alert=True)
            return
        ADMIN_STATES[callback.from_user.id] = f'wallet_message:{request_id}'
        await callback.answer()
        await callback.message.answer(
            f'📩 Ariza #{request_id} egasiga yuboriladigan xabar matnini yozing. Bekor qilish uchun /cancel yuboring.'
        )

    @dp.message(Command('cancel'))
    async def cancel_admin_action(message: Message):
        if message.from_user and message.from_user.id == ADMIN_ID:
            ADMIN_STATES.pop(message.from_user.id, None)
            await message.answer('Bekor qilindi.')

    @dp.callback_query(F.data.startswith('wreq:'))
    async def wallet_request_admin(callback: CallbackQuery):
        if not callback.from_user or callback.from_user.id != ADMIN_ID or not ADMIN_ID:
            await callback.answer('Ruxsat yo‘q.', show_alert=True)
            return
        parts = callback.data.split(':')
        if len(parts) != 3 or parts[1] not in ('ok', 'no'):
            await callback.answer('So‘rov noto‘g‘ri.', show_alert=True)
            return
        request_id = int(parts[2])
        with closing(db()) as con:
            row = con.execute("SELECT * FROM wallet_requests WHERE id=?", (request_id,)).fetchone()
            if not row or row['status'] != 'pending':
                await callback.answer('Ariza allaqachon ko‘rib chiqilgan.', show_alert=True)
                return
            status = 'approved' if parts[1] == 'ok' else 'rejected'
            bonus = 0
            if row['kind'] == 'topup' and status == 'approved':
                amount = int(row['amount'])
                bonus = 50000 if amount >= 300000 else 20000 if amount >= 200000 else 0
                con.execute('UPDATE users SET balance=balance+? WHERE user_id=?', (amount + bonus, row['user_id']))
                ref = con.execute('SELECT referrer_id FROM referrals WHERE invited_id=?', (str(row['user_id']),)).fetchone()
                if ref and str(ref['referrer_id']) != str(row['user_id']):
                    referral_bonus = amount // 5
                    if referral_bonus > 0:
                        con.execute('INSERT OR IGNORE INTO users(user_id,balance) VALUES(?,?)',
                                    (str(ref['referrer_id']), START_BALANCE))
                        con.execute('UPDATE users SET balance=balance+? WHERE user_id=?',
                                    (referral_bonus, str(ref['referrer_id'])))
                        con.execute('INSERT OR IGNORE INTO referral_rewards(request_id,referrer_id,invited_id,amount) VALUES(?,?,?,?)',
                                    (request_id, str(ref['referrer_id']), str(row['user_id']), referral_bonus))
                con.execute("UPDATE wallet_requests SET approved_at=datetime('now','localtime') WHERE id=?", (request_id,))
            changed = con.execute("UPDATE wallet_requests SET status=? WHERE id=? AND status='pending'", (status, request_id)).rowcount
            if changed != 1:
                con.rollback()
                await callback.answer('Ariza allaqachon ko‘rib chiqilgan.', show_alert=True)
                return
            con.commit()
        # Xabarnoma: tasdiqlangan ariza turi va summasini aniq ko‘rsatadi.
        # Ushbu loyiha demo: haqiqiy bank/karta pul o‘tkazmasi bajarilmaydi.
        try:
            amount = int(row['amount'])
            if status == 'approved' and row['kind'] == 'topup':
                credited = amount + bonus
                notice = f'✅ Arizangiz tasdiqlandi. Balansingizga {credited:,} so‘m qo‘shildi. /start berib tekshiring.' + '\n\n⚠️ Bu demo balans; haqiqiy pul o‘tkazilmadi.'
            elif status == 'approved' and row['kind'] == 'withdraw':
                notice = f'✅ Pul yechish arizangiz tasdiqlandi. Bu demo tizimida karta hisobiga haqiqiy pul o‘tkazilmaydi.'
            else:
                notice = f'❌ So‘rovingiz #{request_id} rad etildi.'
            await bot.send_message(int(row['user_id']), notice)
        except Exception:
            pass
        # Guruhdagi asl ariza xabarini o‘zgartirmaymiz: karta, summa va boshqa
        # ma’lumotlar saqlanib qoladi. Faqat tugmalar olib tashlanadi va holat
        # alohida xabar sifatida yuboriladi.
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        try:
            group_status = (
                f'✅ <b>ARIZA #{request_id} TASDIQLANDI (DEMO)</b>'
                if status == 'approved'
                else f'❌ <b>ARIZA #{request_id} RAD ETILDI</b>'
            )
            await callback.message.answer(group_status, parse_mode='HTML')
        except Exception as e:
            print(f'Wallet request #{request_id} status send failed: {e}')
        await callback.answer('Ariza holati yangilandi.')

    @dp.callback_query(F.data.startswith('evidence:del:'))
    async def evidence_delete(callback: CallbackQuery):
        if not callback.from_user or callback.from_user.id != ADMIN_ID or not ADMIN_ID:
            await callback.answer('Ruxsat yo‘q.', show_alert=True)
            return
        try:
            index = int(callback.data.rsplit(':', 1)[1])
            links = json.loads(get_setting('evidence_links', '[]'))
            if not isinstance(links, list) or not 0 <= index < len(links):
                raise ValueError
            links.pop(index)
            set_setting('evidence_links', json.dumps(links, ensure_ascii=False))
            await callback.answer('Havola olib tashlandi.')
            lines = ['🔗 <b>Isbotlar — kanal va guruh havolalari</b>']
            if links:
                lines.extend(f'{i+1}. {item.get("title", "Havola")} — {item.get("url", "")}' for i, item in enumerate(links))
            else:
                lines.append('Hozircha havolalar yo‘q.')
            kb_rows = [[InlineKeyboardButton(text='➕ Havola qo‘shish', callback_data='adm:evidence_add')]]
            kb_rows.extend([[InlineKeyboardButton(text=f'🗑 {item.get("title", "Havola")[:35]}', callback_data=f'evidence:del:{i}')] for i, item in enumerate(links)])
            kb_rows.append([InlineKeyboardButton(text='⬅️ Admin panel', callback_data='adm:back')])
            await callback.message.edit_text('\n'.join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode='HTML', disable_web_page_preview=True)
        except (ValueError, TypeError, json.JSONDecodeError):
            await callback.answer('Havola topilmadi.', show_alert=True)

    @dp.callback_query(F.data.startswith('adm:'))
    async def admin_actions(callback: CallbackQuery):
        if not callback.from_user or callback.from_user.id != ADMIN_ID or not ADMIN_ID:
            await callback.answer('Ruxsat yo‘q.', show_alert=True)
            return
        action = callback.data.split(':', 1)[1]
        if action == 'stats':
            try:
                with closing(db()) as con:
                    users = con.execute('SELECT COUNT(*) n FROM users').fetchone()['n']
                    balance = con.execute('SELECT COALESCE(SUM(balance),0) n FROM users').fetchone()['n']
                    bets = con.execute('SELECT COUNT(*) n FROM bets').fetchone()['n']
                    wagered = con.execute('SELECT COALESCE(SUM(amount),0) n FROM bets').fetchone()['n']
                text = (f'📊 <b>Demo statistika</b>\n\n👥 Foydalanuvchilar: <b>{users}</b>\n'
                        f'💰 Jami virtual balans: <b>{int(balance):,} so‘m</b>\n'
                        f'🎲 Demo stavkalar: <b>{bets}</b>\n📉 Jami demo stavka: <b>{int(wagered):,} so‘m</b>')
            except sqlite3.Error:
                text = 'Ma’lumotlar bazasi hali yaratilmagan. Avval run.py ni ishga tushiring.'
            await callback.message.edit_text(text, reply_markup=admin_keyboard(), parse_mode='HTML')
        elif action == 'users':
            try:
                with closing(db()) as con:
                    rows = con.execute('SELECT user_id,balance FROM users ORDER BY balance DESC, user_id ASC LIMIT 20').fetchall()
                    total = con.execute('SELECT COUNT(*) FROM users').fetchone()[0]
                lines = [f'{i}. ID: <code>{r["user_id"]}</code> — <b>{int(r["balance"]):,} so‘m</b>' for i, r in enumerate(rows, 1)]
                text = f'👥 <b>Eng ko‘p balansga ega 20 foydalanuvchi</b>\nJami foydalanuvchilar: {total}\n\n' + ('\n'.join(lines) if lines else 'Hozircha foydalanuvchilar yo‘q.')
            except sqlite3.Error:
                text = 'Ma’lumotlar bazasi hali yaratilmagan. Avval botni ishga tushiring.'
            await callback.message.edit_text(text, reply_markup=admin_keyboard(), parse_mode='HTML')
        elif action == 'broadcast':
            ADMIN_STATES[callback.from_user.id] = 'broadcast_message'
            await callback.message.answer('📢 Reklama uchun yubormoqchi bo‘lgan xabaringizni yuboring. Matn, rasm, video yoki boshqa Telegram xabar turi qabul qilinadi. Bekor qilish: /cancel')
        elif action == 'requests':
            with closing(db()) as con:
                rows = con.execute("SELECT id,user_id,kind,amount,created_at FROM wallet_requests WHERE status='pending' ORDER BY id LIMIT 10").fetchall()
            if not rows:
                await callback.message.edit_text('🧾 <b>Kutayotgan demo arizalar yo‘q.</b>', reply_markup=admin_keyboard(), parse_mode='HTML')
            else:
                for r in rows:
                    kind = 'Balansni to‘ldirish' if r['kind'] == 'topup' else 'Demo balansdan yechish'
                    kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text='✅ Tasdiqlash', callback_data=f'wreq:ok:{r["id"]}'),
                        InlineKeyboardButton(text='❌ Rad etish', callback_data=f'wreq:no:{r["id"]}')
                    ]])
                    await callback.message.answer(
                        f'🧾 <b>Demo ariza #{r["id"]}</b>\nTuri: {kind}\nFoydalanuvchi ID: <code>{r["user_id"]}</code>\nSumma: <b>{int(r["amount"]):,} so‘m</b>\nSana: {r["created_at"]}\n\nFaqat virtual balans. Haqiqiy pul o‘tkazilmaydi.',
                        reply_markup=kb, parse_mode='HTML')
                await callback.message.answer('Admin panel:', reply_markup=admin_keyboard())
        elif action == 'card':
            ADMIN_STATES[callback.from_user.id] = 'setting:card_number'
            await callback.message.answer('Karta raqamini yuboring (demo interfeysida ko‘rsatiladi):')
        elif action == 'bank':
            ADMIN_STATES[callback.from_user.id] = 'setting:bank_name'
            await callback.message.answer('Bank nomini yuboring:')
        elif action == 'group':
            ADMIN_STATES[callback.from_user.id] = 'setting:requests_group_id'
            await callback.message.answer('Balans to‘ldirish arizalari guruh ID sini yuboring (masalan, -1001234567890). Bot guruhda bo‘lishi va xabar yubora olishi kerak.')
        elif action == 'withdraw_group':
            ADMIN_STATES[callback.from_user.id] = 'setting:withdraw_group_id'
            await callback.message.answer('Pul chiqarish arizalari tushadigan alohida Telegram guruh ID sini yuboring (masalan, -1001234567890). Bot guruhda bo‘lishi kerak.')
        elif action == 'setbalance':
            ADMIN_STATES[callback.from_user.id] = 'setbalance_user'
            await callback.message.answer('Demo balansini o‘zgartirish uchun foydalanuvchining Telegram ID sini yuboring. Faqat demo balans o‘zgaradi.')
        elif action == 'evidence':
            try:
                links = json.loads(get_setting('evidence_links', '[]'))
                if not isinstance(links, list): links = []
            except (ValueError, TypeError):
                links = []
            lines = ['🔗 <b>Isbotlar — kanal va guruh havolalari</b>']
            if links:
                lines.extend(f'{i+1}. {item.get("title", "Havola")} — {item.get("url", "")}' for i, item in enumerate(links))
            else:
                lines.append('Hozircha havolalar yo‘q.')
            kb_rows = [[InlineKeyboardButton(text='➕ Havola qo‘shish', callback_data='adm:evidence_add')]]
            kb_rows.extend([[InlineKeyboardButton(text=f'🗑 {item.get("title", "Havola")[:35]}', callback_data=f'evidence:del:{i}')] for i, item in enumerate(links)])
            kb_rows.append([InlineKeyboardButton(text='⬅️ Admin panel', callback_data='adm:back')])
            await callback.message.edit_text('\n'.join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode='HTML', disable_web_page_preview=True)
        elif action == 'evidence_add':
            ADMIN_STATES[callback.from_user.id] = 'evidence_name'
            await callback.message.answer('Tugma nomini yuboring (masalan: Admin):')
        elif action == 'back':
            await callback.message.edit_text('🛠 <b>Trend Linya — admin panel</b>\n\nBu panel demo ma’lumotlarini boshqaradi.', reply_markup=admin_keyboard(), parse_mode='HTML')
        elif action == 'start_button':
            ADMIN_STATES[callback.from_user.id] = 'start_button_text'
            await callback.message.answer('Start xabariga qo‘shiladigan qo‘shimcha inline tugma nomini yuboring (1–64 belgi). Bekor qilish: /cancel')
        elif action == 'start_button_remove':
            set_setting('start_button_text', '')
            set_setting('start_button_url', '')
            await callback.message.answer('✅ Start xabaridagi qo‘shimcha tugma olib tashlandi.', reply_markup=admin_keyboard())
        elif action == 'url':
            await callback.message.answer(f'WEBAPP_URL: <code>{WEBAPP_URL or "kiritilmagan"}</code>', parse_mode='HTML')
        await callback.answer()

    @dp.message()
    async def admin_text_input(message: Message):
        if not message.from_user or message.from_user.id != ADMIN_ID or not ADMIN_ID:
            return
        state = ADMIN_STATES.get(message.from_user.id)
        if not state:
            return
        if state == 'broadcast_message':
            with closing(db()) as con:
                recipients = [str(row['user_id']) for row in con.execute('SELECT user_id FROM users ORDER BY rowid ASC').fetchall() if str(row['user_id']).isdigit()]
            if not recipients:
                ADMIN_STATES.pop(message.from_user.id, None)
                await message.answer('Yuborish uchun foydalanuvchilar topilmadi.', reply_markup=admin_keyboard())
                return
            ADMIN_STATES.pop(message.from_user.id, None)
            await message.answer(f'📢 Reklama yuborish boshlandi. Qabul qiluvchilar: {len(recipients)} ta.')
            sent = 0
            failed = 0
            for recipient in recipients:
                try:
                    await bot.copy_message(chat_id=int(recipient), from_chat_id=message.chat.id, message_id=message.message_id)
                    sent += 1
                except Exception:
                    failed += 1
                if sent % 25 == 0:
                    await asyncio.sleep(0.05)
            await message.answer(f'✅ Reklama yuborish yakunlandi.\n📨 Yuborildi: {sent} ta\n⚠️ Yuborilmadi: {failed} ta', reply_markup=admin_keyboard())
            return
        if not message.text:
            return
        if state.startswith('wallet_message:'):
            request_id = int(state.split(':', 1)[1])
            text_to_send = (message.text or '').strip()
            if not text_to_send:
                await message.answer('Xabar matnini kiriting.')
                return
            with closing(db()) as con:
                request_row = con.execute('SELECT user_id FROM wallet_requests WHERE id=?', (request_id,)).fetchone()
            if not request_row:
                ADMIN_STATES.pop(message.from_user.id, None)
                await message.answer('Ariza topilmadi.')
                return
            try:
                await bot.send_message(int(request_row['user_id']), '📩 Administratordan xabar:\\n\\n' + text_to_send)
                await message.answer(f'✅ Xabar #{request_id} foydalanuvchiga yuborildi. Tasdiqlash/rad etish tugmalari o‘zgarishsiz qoldi.')
            except Exception as e:
                await message.answer(f'❌ Xabar yuborilmadi: {e}')
            finally:
                ADMIN_STATES.pop(message.from_user.id, None)
            return
        if state == 'start_button_text':
            title = (message.text or '').strip()
            if not title or len(title) > 64:
                await message.answer('Tugma nomi 1–64 belgi bo‘lsin. Qayta yuboring:')
                return
            ADMIN_STATES[message.from_user.id] = 'start_button_url:' + title
            await message.answer('Endi tugma bosilganda ochiladigan HTTPS havolani yuboring:')
            return
        if state.startswith('start_button_url:'):
            title = state.split(':', 1)[1]
            url = (message.text or '').strip()
            if not url.startswith('https://'):
                await message.answer('Havola https:// bilan boshlanishi kerak. Qayta yuboring:')
                return
            set_setting('start_button_text', title)
            set_setting('start_button_url', url)
            ADMIN_STATES.pop(message.from_user.id, None)
            await message.answer(f'✅ Start xabariga “{title}” tugmasi qo‘shildi.', reply_markup=admin_keyboard())
            return
        if state == 'evidence_name':
            title = (message.text or '').strip()
            if not title or len(title) > 60:
                await message.answer('Tugma nomi 1–60 ta belgidan iborat bo‘lsin. Qayta yuboring:')
                return
            ADMIN_STATES[message.from_user.id] = 'evidence_url:' + title
            await message.answer('Endi Telegram kanal/guruh havolasini yuboring (https://t.me/...):')
            return
        if state.startswith('evidence_url:'):
            title = state.split(':', 1)[1]
            url = (message.text or '').strip()
            if not (url.startswith('https://t.me/') or url.startswith('https://telegram.me/')):
                await message.answer('Havola https://t.me/... ko‘rinishida bo‘lsin. Qayta yuboring:')
                return
            try:
                links = json.loads(get_setting('evidence_links', '[]'))
                if not isinstance(links, list): links = []
            except (ValueError, TypeError):
                links = []
            links.append({'title': title, 'url': url})
            set_setting('evidence_links', json.dumps(links, ensure_ascii=False))
            ADMIN_STATES.pop(message.from_user.id, None)
            await message.answer(f'✅ “{title}” havolasi saqlandi. Profilning Isbotlar oynasida ko‘rinadi.', reply_markup=admin_keyboard())
            return
        if state.startswith('setting:'):
            setting_key = state.split(':', 1)[1]
            value = (message.text or '').strip()
            if not value:
                await message.answer('Qiymat bo‘sh bo‘lmasin. Qayta yuboring:')
                return
            if setting_key in ('requests_group_id', 'withdraw_group_id') and not (value.startswith('@') or value.lstrip('-').isdigit()):
                await message.answer('Guruh ID sini -100... formatida yoki @username ko‘rinishida yuboring.')
                return
            if setting_key == 'card_number':
                digits = ''.join(ch for ch in value if ch.isdigit())
                if len(digits) < 12 or len(digits) > 20:
                    await message.answer('Karta raqami 12–20 ta raqam bo‘lishi kerak. Qayta yuboring:')
                    return
                value = digits
            if setting_key == 'bank_name' and len(value) > 80:
                await message.answer('Bank nomi juda uzun. Qayta yuboring:')
                return
            set_setting(setting_key, value)
            ADMIN_STATES.pop(message.from_user.id, None)
            await message.answer('✅ Sozlama saqlandi. Faqat demo arizalari/virtual balans uchun ishlaydi.', reply_markup=admin_keyboard())
            return
        if state == 'setbalance_user':
            user_id = (message.text or '').strip()
            if not user_id.isdigit():
                await message.answer('Telegram ID faqat raqamlardan iborat bo‘lsin. Qayta yuboring:')
                return
            ADMIN_STATES[message.from_user.id] = f'setbalance_amount:{user_id}'
            await message.answer('Yangi demo balansini so‘mda yuboring (0 dan 1000000000 gacha):')
            return
        if state.startswith('setbalance_amount:'):
            user_id = state.split(':', 1)[1]
            try:
                amount = int((message.text or '').replace(' ', '').replace(',', ''))
            except ValueError:
                await message.answer('Summani butun son qilib yuboring.')
                return
            if not 0 <= amount <= 1_000_000_000:
                await message.answer('Summa 0 va 1 000 000 000 orasida bo‘lishi kerak.')
                return
            try:
                with closing(db()) as con:
                    con.execute('INSERT INTO users(user_id,balance) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET balance=excluded.balance', (user_id, amount))
                    con.commit()
                await message.answer(f'✅ Demo balans yangilandi. ID: {user_id}; balans: {amount:,} so‘m.', reply_markup=admin_keyboard())
            except sqlite3.Error as e:
                await message.answer(f'DB xatosi: {e}')
            finally:
                ADMIN_STATES.pop(message.from_user.id, None)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()



async def run_all():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN .env faylida kiritilmagan")
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    web_server = uvicorn.Server(config)
    web_task = asyncio.create_task(web_server.serve())
    try:
        await bot_main()
    finally:
        web_server.should_exit = True
        await web_task

if __name__ == "__main__":
    asyncio.run(run_all())

