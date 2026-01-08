from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Railway PostgreSQL 연결
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db():
    conn = psycopg.connect(DATABASE_URL)
    return conn

# 테이블 생성 (최초 1회)
def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(50) UNIQUE NOT NULL,
            password VARCHAR(100) NOT NULL,
            name VARCHAR(50) NOT NULL,
            phone VARCHAR(20) NOT NULL,
            reg_date DATE DEFAULT CURRENT_DATE,
            approved CHAR(1) DEFAULT 'N'
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

@app.route('/', methods=['GET'])
def index():
    return jsonify({'status': 'API 정상 작동 중'})

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    user_id = data.get('userId')
    password = data.get('password')
    name = data.get('name')
    phone = data.get('phone')
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # 아이디 중복 체크
        cur.execute('SELECT user_id FROM users WHERE user_id = %s', (user_id,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({
                'success': False,
                'message': '이미 사용 중인 아이디입니다.'
            })
        
        # 신규 등록
        cur.execute(
            'INSERT INTO users (user_id, password, name, phone) VALUES (%s, %s, %s, %s)',
            (user_id, password, name, phone)
        )
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': '회원가입 완료!'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'오류 발생: {str(e)}'
        })

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    user_id = data.get('userId')
    password = data.get('password')
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute(
            'SELECT name, approved FROM users WHERE user_id = %s AND password = %s',
            (user_id, password)
        )
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if result:
            name, approved = result
            if approved == 'Y':
                return jsonify({
                    'success': True,
                    'approved': True,
                    'name': name,
                    'message': '로그인 성공!'
                })
            else:
                return jsonify({
                    'success': True,
                    'approved': False,
                    'message': '관리자 승인 대기 중입니다.\n문의: 카카오톡 odong4444'
                })
        else:
            return jsonify({
                'success': False,
                'message': '아이디 또는 비밀번호가 틀렸습니다.'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'오류 발생: {str(e)}'
        })

# 관리자용: 사용자 목록 조회
@app.route('/admin/users', methods=['GET'])
def get_users():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT user_id, name, phone, reg_date, approved FROM users ORDER BY id DESC')
        users = cur.fetchall()
        cur.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'users': [
                {
                    'userId': u[0],
                    'name': u[1],
                    'phone': u[2],
                    'regDate': str(u[3]),
                    'approved': u[4]
                } for u in users
            ]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# 관리자용: 승인 처리
@app.route('/admin/approve', methods=['POST'])
def approve_user():
    data = request.json
    user_id = data.get('userId')
    approved = data.get('approved', 'Y')
    
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('UPDATE users SET approved = %s WHERE user_id = %s', (approved, user_id))
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({'success': True, 'message': '처리 완료'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
