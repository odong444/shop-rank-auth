from flask import Blueprint, request, jsonify, session, redirect, render_template
import random
import urllib.request
import urllib.parse
import json

from utils.db import get_db, get_user_withdrawals, create_withdrawal

auth_bp = Blueprint('auth', __name__)

# 알리고 SMS 설정
ALIGO_API_KEY = "3xj66vap7q84cvvqfwugklcxpu7srvrf"
ALIGO_USER_ID = "odong444"
ALIGO_SENDER = "01072100210"

def send_aligo_sms(phone, message):
    try:
        url = "https://apis.aligo.in/send/"
        data = {
            'key': ALIGO_API_KEY,
            'user_id': ALIGO_USER_ID,
            'sender': ALIGO_SENDER,
            'receiver': phone.replace('-', ''),
            'msg': message
        }
        encoded_data = urllib.parse.urlencode(data).encode('utf-8')
        req = urllib.request.Request(url, data=encoded_data)
        res = urllib.request.urlopen(req, timeout=10)
        result = json.loads(res.read().decode('utf-8'))
        return result.get('result_code') == '1'
    except Exception as e:
        print(f"SMS Error: {e}")
        return False


# ===== Pages =====

@auth_bp.route('/login')
def login_page():
    return render_template('login.html')

@auth_bp.route('/register')
def register_page():
    return render_template('register.html')

@auth_bp.route('/withdrawal')
def withdrawal_page():
    if not session.get('user_id'):
        return redirect('/login')
    return render_template('withdrawal.html', active_menu='withdrawal')


# ===== API =====

@auth_bp.route('/api/login', methods=['POST'])
def api_login():
    d = request.json

    # 테스트 계정 (하드코딩) - 개발/테스트용
    if d.get('userId') == 'test' and d.get('password') == 'test':
        session['user_id'] = 'test'
        session['name'] = '테스트유저'
        session['role'] = 'admin'
        return jsonify({'success': True, 'name': '테스트유저'})

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT user_id,password,name,approved,role FROM users WHERE user_id=%s', (d.get('userId'),))
        u = cur.fetchone()
        cur.close()
        conn.close()

        if not u:
            return jsonify({'success': False, 'message': '존재하지 않는 아이디입니다.'})
        if u[1] != d.get('password'):
            return jsonify({'success': False, 'message': '비밀번호가 일치하지 않습니다.'})
        if u[3] != 'Y':
            return jsonify({'success': False, 'message': '관리자 승인 대기 중입니다.\n승인 문의: 카카오톡 odong4444'})

        session['user_id'] = d.get('userId')
        session['name'] = u[2]
        session['role'] = u[4] or 'normal'
        return jsonify({'success': True, 'name': u[2]})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@auth_bp.route('/api/register', methods=['POST'])
def api_register():
    d = request.json
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT user_id FROM users WHERE user_id=%s', (d.get('userId'),))
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': '이미 사용 중인 아이디입니다.'})
        
        phone = d.get('phone', '').replace('-', '')
        cur.execute('INSERT INTO users (user_id,password,name,phone,approved) VALUES (%s,%s,%s,%s,%s)',
                    (d.get('userId'), d.get('password'), d.get('name'), phone, 'Y'))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@auth_bp.route('/api/logout')
def api_logout():
    session.clear()
    return redirect('/login')

@auth_bp.route('/api/send-sms', methods=['POST'])
def api_send_sms():
    d = request.json
    phone = d.get('phone', '').replace('-', '')
    if not phone:
        return jsonify({'success': False, 'message': '전화번호를 입력해주세요.'})
    
    code = str(random.randint(100000, 999999))
    
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('DELETE FROM sms_verify WHERE phone=%s', (phone,))
        cur.execute('INSERT INTO sms_verify (phone, code) VALUES (%s, %s)', (phone, code))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    
    message = f"[BW-rank] 인증번호는 [{code}] 입니다."
    if send_aligo_sms(phone, message):
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': 'SMS 발송에 실패했습니다.'})

@auth_bp.route('/api/verify-sms', methods=['POST'])
def api_verify_sms():
    d = request.json
    phone = d.get('phone', '').replace('-', '')
    code = d.get('code', '')
    
    if not phone or not code:
        return jsonify({'success': False, 'message': '전화번호와 인증번호를 입력해주세요.'})
    
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''SELECT id, code FROM sms_verify 
                      WHERE phone=%s AND created_at > NOW() - INTERVAL '3 minutes' 
                      ORDER BY created_at DESC LIMIT 1''', (phone,))
        row = cur.fetchone()
        
        if not row:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': '인증번호가 만료되었습니다. 다시 요청해주세요.'})
        
        if row[1] != code:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': '인증번호가 일치하지 않습니다.'})
        
        cur.execute('UPDATE sms_verify SET verified=TRUE WHERE id=%s', (row[0],))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# 기존 클라이언트 호환
@auth_bp.route('/register', methods=['POST'])
def register_compat():
    return api_register()

@auth_bp.route('/login', methods=['POST'])
def login_compat():
    d = request.json
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT user_id,password,name,approved FROM users WHERE user_id=%s', (d.get('userId'),))
        u = cur.fetchone()
        cur.close()
        conn.close()

        if not u:
            return jsonify({'success': False, 'message': '존재하지 않는 아이디입니다.'})
        if u[1] != d.get('password'):
            return jsonify({'success': False, 'message': '비밀번호가 일치하지 않습니다.'})
        if u[3] != 'Y':
            return jsonify({'success': False, 'message': '관리자 승인 대기 중입니다.\n승인 문의: 카카오톡 odong4444'})

        return jsonify({'success': True, 'name': u[2]})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# ===== 출금 API =====

@auth_bp.route('/api/withdrawals', methods=['GET'])
def get_my_withdrawals():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': '로그인이 필요합니다.'})

    try:
        rows = get_user_withdrawals(user_id)
        withdrawals = []
        for r in rows:
            status_text = {'pending': '대기중', 'approved': '승인', 'rejected': '거절'}.get(r[5], r[5])
            withdrawals.append({
                'id': r[0],
                'amount': r[1],
                'bankName': r[2],
                'accountNumber': r[3],
                'accountHolder': r[4],
                'status': r[5],
                'statusText': status_text,
                'requestedAt': r[6].strftime('%Y-%m-%d %H:%M') if r[6] else '',
                'processedAt': r[7].strftime('%Y-%m-%d %H:%M') if r[7] else '',
                'memo': r[8] or ''
            })
        return jsonify({'success': True, 'withdrawals': withdrawals})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@auth_bp.route('/api/withdrawals', methods=['POST'])
def request_withdrawal():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': '로그인이 필요합니다.'})

    d = request.json
    amount = d.get('amount')
    bank_name = d.get('bankName')
    account_number = d.get('accountNumber')
    account_holder = d.get('accountHolder')

    if not all([amount, bank_name, account_number, account_holder]):
        return jsonify({'success': False, 'message': '모든 필드를 입력해주세요.'})

    try:
        amount = int(amount)
        if amount <= 0:
            return jsonify({'success': False, 'message': '출금 금액은 0보다 커야 합니다.'})
    except ValueError:
        return jsonify({'success': False, 'message': '올바른 금액을 입력해주세요.'})

    try:
        withdrawal_id = create_withdrawal(user_id, amount, bank_name, account_number, account_holder)
        return jsonify({'success': True, 'id': withdrawal_id})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
