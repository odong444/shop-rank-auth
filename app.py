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

@app.route('/admin', methods=['GET'])
def admin_page():
    return '''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>회원 관리</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Malgun Gothic', sans-serif; background: #f5f5f5; padding: 20px; }
        .container { max-width: 900px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { text-align: center; margin-bottom: 20px; color: #333; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: center; border-bottom: 1px solid #ddd; }
        th { background: #4a90d9; color: white; }
        tr:hover { background: #f9f9f9; }
        .btn { padding: 6px 12px; border: none; border-radius: 5px; cursor: pointer; font-size: 12px; }
        .btn-approve { background: #28a745; color: white; }
        .btn-reject { background: #ffc107; color: black; }
        .btn-delete { background: #dc3545; color: white; }
        .status-y { color: #28a745; font-weight: bold; }
        .status-n { color: #dc3545; font-weight: bold; }
        .refresh-btn { display: block; margin: 20px auto; padding: 10px 30px; background: #4a90d9; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 14px; }
        @media (max-width: 600px) {
            th, td { padding: 8px; font-size: 12px; }
            .btn { padding: 4px 8px; font-size: 10px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 회원 관리</h1>
        <button class="refresh-btn" onclick="loadUsers()">새로고침</button>
        <table>
            <thead>
                <tr>
                    <th>아이디</th>
                    <th>이름</th>
                    <th>전화번호</th>
                    <th>가입일</th>
                    <th>승인</th>
                    <th>관리</th>
                </tr>
            </thead>
            <tbody id="userTable"></tbody>
        </table>
    </div>
    <script>
        const API_URL = window.location.origin;
        async function loadUsers() {
            try {
                const res = await fetch(API_URL + '/admin/users');
                const data = await res.json();
                if (data.success) {
                    const tbody = document.getElementById('userTable');
                    tbody.innerHTML = '';
                    data.users.forEach(user => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td>${user.userId}</td>
                            <td>${user.name}</td>
                            <td>${user.phone}</td>
                            <td>${user.regDate}</td>
                            <td class="${user.approved === 'Y' ? 'status-y' : 'status-n'}">
                                ${user.approved === 'Y' ? '승인됨' : '대기중'}
                            </td>
                            <td>
                                ${user.approved === 'Y' 
                                    ? `<button class="btn btn-reject" onclick="setApproval('${user.userId}', 'N')">승인취소</button>`
                                    : `<button class="btn btn-approve" onclick="setApproval('${user.userId}', 'Y')">승인</button>`
                                }
                                <button class="btn btn-delete" onclick="deleteUser('${user.userId}')">삭제</button>
                            </td>
                        `;
                        tbody.appendChild(tr);
                    });
                }
            } catch (e) {
                alert('서버 연결 실패: ' + e.message);
            }
        }
        async function setApproval(userId, approved) {
            try {
                const res = await fetch(API_URL + '/admin/approve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ userId, approved })
                });
                const data = await res.json();
                if (data.success) loadUsers();
                else alert(data.message);
            } catch (e) { alert('오류: ' + e.message); }
        }
        async function deleteUser(userId) {
            if (!confirm(userId + ' 회원을 삭제하시겠습니까?')) return;
            try {
                const res = await fetch(API_URL + '/admin/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ userId })
                });
                const data = await res.json();
                if (data.success) loadUsers();
                else alert(data.message);
            } catch (e) { alert('오류: ' + e.message); }
        }
        loadUsers();
    </script>
</body>
</html>'''

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
            'message': '회원가입 완료! 관리자 승인 후 사용 가능합니다.'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'서버 오류: {str(e)}'
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
            'SELECT user_id, password, name, approved FROM users WHERE user_id = %s',
            (user_id,)
        )
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        if not user:
            return jsonify({
                'success': False,
                'message': '존재하지 않는 아이디입니다.'
            })
        
        if user[1] != password:
            return jsonify({
                'success': False,
                'message': '비밀번호가 일치하지 않습니다.'
            })
        
        if user[3] != 'Y':
            return jsonify({
                'success': False,
                'message': '관리자 승인 대기 중입니다.\n승인 문의: 카카오톡 odong4444'
            })
        
        return jsonify({
            'success': True,
            'message': '로그인 성공!',
            'name': user[2]
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'서버 오류: {str(e)}'
        })

# 관리자용 API - 전체 회원 조회
@app.route('/admin/users', methods=['GET'])
def get_users():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT id, user_id, name, phone, reg_date, approved FROM users ORDER BY id DESC')
        users = cur.fetchall()
        cur.close()
        conn.close()
        
        result = []
        for u in users:
            result.append({
                'id': u[0],
                'userId': u[1],
                'name': u[2],
                'phone': u[3],
                'regDate': str(u[4]) if u[4] else '',
                'approved': u[5]
            })
        
        return jsonify({'success': True, 'users': result})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# 관리자용 API - 승인 처리
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
        
        return jsonify({'success': True, 'message': '승인 처리 완료'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# 관리자용 API - 회원 삭제
@app.route('/admin/delete', methods=['POST'])
def delete_user():
    data = request.json
    user_id = data.get('userId')
    
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('DELETE FROM users WHERE user_id = %s', (user_id,))
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({'success': True, 'message': '삭제 완료'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# 서버 시작 시 테이블 생성
with app.app_context():
    try:
        init_db()
    except:
        pass

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
