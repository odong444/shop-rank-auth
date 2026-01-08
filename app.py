from flask import Flask, request, jsonify, session, redirect, url_for
from flask_cors import CORS
import psycopg
import os
import urllib.request
import urllib.parse
import json
import time
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')
CORS(app)

# Railway PostgreSQL 연결
DATABASE_URL = os.environ.get('DATABASE_URL')

# 네이버 API 키
NAVER_CLIENT_ID = "UrlniCJoGZ_jfgk5tlkN"
NAVER_CLIENT_SECRET = "x3z9b1CM2F"

def get_db():
    conn = psycopg.connect(DATABASE_URL)
    return conn

# 테이블 생성
def init_db():
    conn = get_db()
    cur = conn.cursor()
    
    # 회원 테이블
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
    
    # 상품 테이블
    cur.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(50) NOT NULL,
            mid VARCHAR(50) NOT NULL,
            keyword VARCHAR(100) NOT NULL,
            title VARCHAR(500) DEFAULT '',
            mall VARCHAR(100) DEFAULT '',
            current_rank VARCHAR(20) DEFAULT '-',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, mid, keyword)
        )
    ''')
    
    # 순위 이력 테이블
    cur.execute('''
        CREATE TABLE IF NOT EXISTS rank_history (
            id SERIAL PRIMARY KEY,
            product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
            rank VARCHAR(20) NOT NULL,
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    cur.close()
    conn.close()

# 로그인 체크 데코레이터
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

# ============ 페이지 라우트 ============

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect('/dashboard')
    return redirect('/login')

@app.route('/login')
def login_page():
    return '''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>로그인 - 순위 관리</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Malgun Gothic', sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .container { background: white; padding: 40px; border-radius: 20px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); width: 90%; max-width: 400px; }
        h1 { text-align: center; color: #333; margin-bottom: 30px; font-size: 24px; }
        .form-group { margin-bottom: 20px; }
        .form-group label { display: block; margin-bottom: 8px; color: #555; font-weight: bold; }
        .form-group input { width: 100%; padding: 15px; border: 2px solid #e0e0e0; border-radius: 10px; font-size: 16px; transition: border-color 0.3s; }
        .form-group input:focus { outline: none; border-color: #667eea; }
        .btn { width: 100%; padding: 15px; border: none; border-radius: 10px; font-size: 16px; font-weight: bold; cursor: pointer; transition: transform 0.2s, box-shadow 0.2s; }
        .btn-primary { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; margin-bottom: 10px; }
        .btn-secondary { background: #f0f0f0; color: #333; }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 5px 20px rgba(0,0,0,0.2); }
        .notice { text-align: center; margin-top: 20px; color: #888; font-size: 14px; }
        .error { background: #ffe0e0; color: #c00; padding: 10px; border-radius: 10px; margin-bottom: 20px; text-align: center; display: none; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🛒 순위 관리 시스템</h1>
        <div class="error" id="error"></div>
        <div class="form-group">
            <label>아이디</label>
            <input type="text" id="userId" placeholder="아이디 입력">
        </div>
        <div class="form-group">
            <label>비밀번호</label>
            <input type="password" id="password" placeholder="비밀번호 입력">
        </div>
        <button class="btn btn-primary" onclick="doLogin()">로그인</button>
        <button class="btn btn-secondary" onclick="location.href='/register'">회원가입</button>
        <p class="notice">문의: 카카오톡 odong4444</p>
    </div>
    <script>
        async function doLogin() {
            const userId = document.getElementById('userId').value;
            const password = document.getElementById('password').value;
            const errorDiv = document.getElementById('error');
            
            if (!userId || !password) {
                errorDiv.textContent = '아이디와 비밀번호를 입력해주세요.';
                errorDiv.style.display = 'block';
                return;
            }
            
            try {
                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ userId, password })
                });
                const data = await res.json();
                
                if (data.success) {
                    location.href = '/dashboard';
                } else {
                    errorDiv.textContent = data.message;
                    errorDiv.style.display = 'block';
                }
            } catch (e) {
                errorDiv.textContent = '서버 연결 실패';
                errorDiv.style.display = 'block';
            }
        }
        
        document.getElementById('password').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') doLogin();
        });
    </script>
</body>
</html>'''

@app.route('/register')
def register_page():
    return '''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>회원가입 - 순위 관리</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Malgun Gothic', sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }
        .container { background: white; padding: 40px; border-radius: 20px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); width: 90%; max-width: 400px; }
        h1 { text-align: center; color: #333; margin-bottom: 30px; font-size: 24px; }
        .form-group { margin-bottom: 15px; }
        .form-group label { display: block; margin-bottom: 5px; color: #555; font-weight: bold; font-size: 14px; }
        .form-group input { width: 100%; padding: 12px; border: 2px solid #e0e0e0; border-radius: 10px; font-size: 14px; }
        .form-group input:focus { outline: none; border-color: #667eea; }
        .btn { width: 100%; padding: 15px; border: none; border-radius: 10px; font-size: 16px; font-weight: bold; cursor: pointer; }
        .btn-primary { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; margin-bottom: 10px; }
        .btn-secondary { background: #f0f0f0; color: #333; }
        .error { background: #ffe0e0; color: #c00; padding: 10px; border-radius: 10px; margin-bottom: 15px; text-align: center; display: none; }
        .success { background: #e0ffe0; color: #060; padding: 10px; border-radius: 10px; margin-bottom: 15px; text-align: center; display: none; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📝 회원가입</h1>
        <div class="error" id="error"></div>
        <div class="success" id="success"></div>
        <div class="form-group">
            <label>아이디</label>
            <input type="text" id="userId" placeholder="아이디 입력">
        </div>
        <div class="form-group">
            <label>비밀번호</label>
            <input type="password" id="password" placeholder="비밀번호 입력">
        </div>
        <div class="form-group">
            <label>비밀번호 확인</label>
            <input type="password" id="password2" placeholder="비밀번호 확인">
        </div>
        <div class="form-group">
            <label>이름</label>
            <input type="text" id="name" placeholder="이름 입력">
        </div>
        <div class="form-group">
            <label>연락처</label>
            <input type="text" id="phone" placeholder="연락처 입력">
        </div>
        <button class="btn btn-primary" onclick="doRegister()">가입하기</button>
        <button class="btn btn-secondary" onclick="location.href='/login'">로그인으로 돌아가기</button>
    </div>
    <script>
        async function doRegister() {
            const userId = document.getElementById('userId').value;
            const password = document.getElementById('password').value;
            const password2 = document.getElementById('password2').value;
            const name = document.getElementById('name').value;
            const phone = document.getElementById('phone').value;
            const errorDiv = document.getElementById('error');
            const successDiv = document.getElementById('success');
            
            errorDiv.style.display = 'none';
            successDiv.style.display = 'none';
            
            if (!userId || !password || !password2 || !name || !phone) {
                errorDiv.textContent = '모든 항목을 입력해주세요.';
                errorDiv.style.display = 'block';
                return;
            }
            
            if (password !== password2) {
                errorDiv.textContent = '비밀번호가 일치하지 않습니다.';
                errorDiv.style.display = 'block';
                return;
            }
            
            try {
                const res = await fetch('/api/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ userId, password, name, phone })
                });
                const data = await res.json();
                
                if (data.success) {
                    successDiv.innerHTML = '회원가입 완료!<br>관리자 승인 후 사용 가능합니다.<br>승인 문의: 카카오톡 odong4444';
                    successDiv.style.display = 'block';
                } else {
                    errorDiv.textContent = data.message;
                    errorDiv.style.display = 'block';
                }
            } catch (e) {
                errorDiv.textContent = '서버 연결 실패';
                errorDiv.style.display = 'block';
            }
        }
    </script>
</body>
</html>'''

@app.route('/dashboard')
@login_required
def dashboard_page():
    return '''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>대시보드 - 순위 관리</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Malgun Gothic', sans-serif; background: #f5f7fa; min-height: 100vh; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
        .header h1 { font-size: 20px; }
        .header-btns { display: flex; gap: 10px; }
        .header-btns button { padding: 8px 15px; border: none; border-radius: 5px; cursor: pointer; font-size: 14px; }
        .btn-logout { background: rgba(255,255,255,0.2); color: white; }
        .btn-refresh { background: #28a745; color: white; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .add-form { background: white; padding: 20px; border-radius: 15px; box-shadow: 0 5px 20px rgba(0,0,0,0.1); margin-bottom: 20px; }
        .add-form h2 { margin-bottom: 15px; color: #333; font-size: 18px; }
        .form-row { display: flex; gap: 10px; flex-wrap: wrap; }
        .form-row input { flex: 1; min-width: 150px; padding: 12px; border: 2px solid #e0e0e0; border-radius: 10px; font-size: 14px; }
        .form-row input:focus { outline: none; border-color: #667eea; }
        .form-row button { padding: 12px 25px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 10px; font-weight: bold; cursor: pointer; }
        .product-list { background: white; border-radius: 15px; box-shadow: 0 5px 20px rgba(0,0,0,0.1); overflow: hidden; }
        .product-list h2 { padding: 20px; background: #f8f9fa; border-bottom: 1px solid #e0e0e0; font-size: 18px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 15px; text-align: center; border-bottom: 1px solid #e0e0e0; }
        th { background: #667eea; color: white; font-size: 14px; }
        td { font-size: 14px; }
        .rank-up { color: #28a745; font-weight: bold; }
        .rank-down { color: #dc3545; font-weight: bold; }
        .rank-same { color: #666; }
        .btn-small { padding: 5px 10px; border: none; border-radius: 5px; cursor: pointer; font-size: 12px; margin: 2px; }
        .btn-history { background: #17a2b8; color: white; }
        .btn-delete { background: #dc3545; color: white; }
        .empty { text-align: center; padding: 50px; color: #888; }
        .loading { text-align: center; padding: 20px; color: #666; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); align-items: center; justify-content: center; z-index: 1000; }
        .modal-content { background: white; padding: 30px; border-radius: 15px; max-width: 500px; width: 90%; max-height: 80vh; overflow-y: auto; }
        .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        .modal-close { background: none; border: none; font-size: 24px; cursor: pointer; color: #888; }
        .history-table { width: 100%; border-collapse: collapse; }
        .history-table th, .history-table td { padding: 10px; border: 1px solid #e0e0e0; }
        .history-table th { background: #f8f9fa; }
        @media (max-width: 768px) {
            th, td { padding: 10px; font-size: 12px; }
            .form-row { flex-direction: column; }
            .form-row input, .form-row button { width: 100%; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🛒 네이버 쇼핑 순위 관리</h1>
        <div class="header-btns">
            <button class="btn-refresh" onclick="refreshAll()">🔄 전체 새로고침</button>
            <button class="btn-logout" onclick="logout()">로그아웃</button>
        </div>
    </div>
    
    <div class="container">
        <div class="add-form">
            <h2>➕ 상품 등록</h2>
            <div class="form-row">
                <input type="text" id="mid" placeholder="MID (상품번호)">
                <input type="text" id="keyword" placeholder="검색 키워드">
                <button onclick="addProduct()">등록하기</button>
            </div>
        </div>
        
        <div class="product-list">
            <h2>📋 내 상품 목록 <span id="productCount"></span></h2>
            <div id="loading" class="loading">로딩 중...</div>
            <table id="productTable" style="display:none;">
                <thead>
                    <tr>
                        <th>MID</th>
                        <th>키워드</th>
                        <th>상품명</th>
                        <th>판매처</th>
                        <th>현재순위</th>
                        <th>관리</th>
                    </tr>
                </thead>
                <tbody id="productBody"></tbody>
            </table>
            <div id="empty" class="empty" style="display:none;">등록된 상품이 없습니다.</div>
        </div>
    </div>
    
    <!-- 이력 모달 -->
    <div class="modal" id="historyModal">
        <div class="modal-content">
            <div class="modal-header">
                <h3>📊 순위 변동 이력</h3>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <p id="historyTitle" style="margin-bottom:15px; color:#666;"></p>
            <table class="history-table">
                <thead>
                    <tr><th>날짜/시간</th><th>순위</th></tr>
                </thead>
                <tbody id="historyBody"></tbody>
            </table>
        </div>
    </div>
    
    <script>
        async function loadProducts() {
            try {
                const res = await fetch('/api/products');
                const data = await res.json();
                
                document.getElementById('loading').style.display = 'none';
                
                if (data.success && data.products.length > 0) {
                    document.getElementById('productTable').style.display = 'table';
                    document.getElementById('empty').style.display = 'none';
                    document.getElementById('productCount').textContent = `(${data.products.length}개)`;
                    
                    const tbody = document.getElementById('productBody');
                    tbody.innerHTML = '';
                    
                    data.products.forEach(p => {
                        const tr = document.createElement('tr');
                        let rankClass = 'rank-same';
                        let rankText = p.current_rank;
                        if (rankText && rankText !== '-' && rankText !== '300위 밖') {
                            rankText += '위';
                        }
                        
                        tr.innerHTML = `
                            <td>${p.mid}</td>
                            <td>${p.keyword}</td>
                            <td>${p.title || '-'}</td>
                            <td>${p.mall || '-'}</td>
                            <td class="${rankClass}">${rankText}</td>
                            <td>
                                <button class="btn-small btn-history" onclick="showHistory(${p.id}, '${p.keyword}')">이력</button>
                                <button class="btn-small btn-delete" onclick="deleteProduct(${p.id})">삭제</button>
                            </td>
                        `;
                        tbody.appendChild(tr);
                    });
                } else {
                    document.getElementById('productTable').style.display = 'none';
                    document.getElementById('empty').style.display = 'block';
                    document.getElementById('productCount').textContent = '(0개)';
                }
            } catch (e) {
                document.getElementById('loading').textContent = '데이터 로드 실패';
            }
        }
        
        async function addProduct() {
            const mid = document.getElementById('mid').value.trim();
            const keyword = document.getElementById('keyword').value.trim();
            
            if (!mid || !keyword) {
                alert('MID와 키워드를 입력해주세요.');
                return;
            }
            
            try {
                const res = await fetch('/api/products', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ mid, keyword })
                });
                const data = await res.json();
                
                if (data.success) {
                    document.getElementById('mid').value = '';
                    document.getElementById('keyword').value = '';
                    loadProducts();
                } else {
                    alert(data.message);
                }
            } catch (e) {
                alert('서버 연결 실패');
            }
        }
        
        async function deleteProduct(id) {
            if (!confirm('정말 삭제하시겠습니까?')) return;
            
            try {
                const res = await fetch('/api/products/' + id, { method: 'DELETE' });
                const data = await res.json();
                if (data.success) loadProducts();
                else alert(data.message);
            } catch (e) {
                alert('서버 연결 실패');
            }
        }
        
        async function refreshAll() {
            if (!confirm('전체 순위를 새로고침하시겠습니까?\\n(시간이 걸릴 수 있습니다)')) return;
            
            document.querySelector('.btn-refresh').textContent = '조회 중...';
            document.querySelector('.btn-refresh').disabled = true;
            
            try {
                const res = await fetch('/api/refresh', { method: 'POST' });
                const data = await res.json();
                
                if (data.success) {
                    alert(`순위 조회 완료! (${data.updated}개 상품)`);
                    loadProducts();
                } else {
                    alert(data.message);
                }
            } catch (e) {
                alert('서버 연결 실패');
            } finally {
                document.querySelector('.btn-refresh').textContent = '🔄 전체 새로고침';
                document.querySelector('.btn-refresh').disabled = false;
            }
        }
        
        async function showHistory(productId, keyword) {
            try {
                const res = await fetch('/api/history/' + productId);
                const data = await res.json();
                
                document.getElementById('historyTitle').textContent = '키워드: ' + keyword;
                const tbody = document.getElementById('historyBody');
                tbody.innerHTML = '';
                
                if (data.success && data.history.length > 0) {
                    data.history.forEach(h => {
                        const tr = document.createElement('tr');
                        let rankText = h.rank;
                        if (rankText && rankText !== '-' && rankText !== '300위 밖') {
                            rankText += '위';
                        }
                        tr.innerHTML = `<td>${h.checked_at}</td><td>${rankText}</td>`;
                        tbody.appendChild(tr);
                    });
                } else {
                    tbody.innerHTML = '<tr><td colspan="2">이력이 없습니다.</td></tr>';
                }
                
                document.getElementById('historyModal').style.display = 'flex';
            } catch (e) {
                alert('이력 조회 실패');
            }
        }
        
        function closeModal() {
            document.getElementById('historyModal').style.display = 'none';
        }
        
        function logout() {
            location.href = '/api/logout';
        }
        
        // 모달 외부 클릭시 닫기
        document.getElementById('historyModal').addEventListener('click', function(e) {
            if (e.target === this) closeModal();
        });
        
        // 페이지 로드시 상품 목록 불러오기
        loadProducts();
    </script>
</body>
</html>'''

@app.route('/admin')
def admin_page():
    return '''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>관리자 - 회원 관리</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Malgun Gothic', sans-serif; background: #f5f5f5; padding: 20px; }
        .container { max-width: 1000px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
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
        async function loadUsers() {
            try {
                const res = await fetch('/admin/users');
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
            } catch (e) { alert('서버 연결 실패'); }
        }
        async function setApproval(userId, approved) {
            const res = await fetch('/admin/approve', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ userId, approved })
            });
            const data = await res.json();
            if (data.success) loadUsers();
            else alert(data.message);
        }
        async function deleteUser(userId) {
            if (!confirm(userId + ' 회원을 삭제하시겠습니까?')) return;
            const res = await fetch('/admin/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ userId })
            });
            const data = await res.json();
            if (data.success) loadUsers();
            else alert(data.message);
        }
        loadUsers();
    </script>
</body>
</html>'''

# ============ API 라우트 ============

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    user_id = data.get('userId')
    password = data.get('password')
    
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT user_id, password, name, approved FROM users WHERE user_id = %s', (user_id,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        if not user:
            return jsonify({'success': False, 'message': '존재하지 않는 아이디입니다.'})
        if user[1] != password:
            return jsonify({'success': False, 'message': '비밀번호가 일치하지 않습니다.'})
        if user[3] != 'Y':
            return jsonify({'success': False, 'message': '관리자 승인 대기 중입니다.\n승인 문의: 카카오톡 odong4444'})
        
        session['user_id'] = user_id
        session['name'] = user[2]
        return jsonify({'success': True, 'name': user[2]})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.json
    user_id = data.get('userId')
    password = data.get('password')
    name = data.get('name')
    phone = data.get('phone')
    
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT user_id FROM users WHERE user_id = %s', (user_id,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': '이미 사용 중인 아이디입니다.'})
        
        cur.execute('INSERT INTO users (user_id, password, name, phone) VALUES (%s, %s, %s, %s)',
                    (user_id, password, name, phone))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'message': '회원가입 완료!'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/logout')
def api_logout():
    session.clear()
    return redirect('/login')

# 상품 관련 API
@app.route('/api/products', methods=['GET'])
@login_required
def get_products():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            SELECT id, mid, keyword, title, mall, current_rank 
            FROM products WHERE user_id = %s ORDER BY id DESC
        ''', (session['user_id'],))
        products = cur.fetchall()
        cur.close()
        conn.close()
        
        result = []
        for p in products:
            result.append({
                'id': p[0], 'mid': p[1], 'keyword': p[2],
                'title': p[3], 'mall': p[4], 'current_rank': p[5]
            })
        return jsonify({'success': True, 'products': result})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/products', methods=['POST'])
@login_required
def add_product():
    data = request.json
    mid = data.get('mid')
    keyword = data.get('keyword')
    
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO products (user_id, mid, keyword) VALUES (%s, %s, %s)
            ON CONFLICT (user_id, mid, keyword) DO NOTHING
        ''', (session['user_id'], mid, keyword))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
@login_required
def delete_product(product_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('DELETE FROM products WHERE id = %s AND user_id = %s', (product_id, session['user_id']))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/history/<int:product_id>', methods=['GET'])
@login_required
def get_history(product_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            SELECT rank, checked_at FROM rank_history 
            WHERE product_id = %s ORDER BY checked_at DESC LIMIT 50
        ''', (product_id,))
        history = cur.fetchall()
        cur.close()
        conn.close()
        
        result = []
        for h in history:
            result.append({
                'rank': h[0],
                'checked_at': h[1].strftime('%Y-%m-%d %H:%M') if h[1] else ''
            })
        return jsonify({'success': True, 'history': result})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/refresh', methods=['POST'])
@login_required
def refresh_ranks():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT id, mid, keyword FROM products WHERE user_id = %s', (session['user_id'],))
        products = cur.fetchall()
        
        updated = 0
        for p in products:
            product_id, mid, keyword = p
            rank, title, mall = get_naver_rank(keyword, mid)
            
            if rank:
                cur.execute('''
                    UPDATE products SET current_rank = %s, title = %s, mall = %s WHERE id = %s
                ''', (str(rank), title or '', mall or '', product_id))
                cur.execute('''
                    INSERT INTO rank_history (product_id, rank) VALUES (%s, %s)
                ''', (product_id, str(rank)))
            else:
                cur.execute('UPDATE products SET current_rank = %s WHERE id = %s', ('300위 밖', product_id))
                cur.execute('INSERT INTO rank_history (product_id, rank) VALUES (%s, %s)', (product_id, '300위 밖'))
            
            updated += 1
            time.sleep(0.2)  # API 호출 간격
        
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'updated': updated})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# 네이버 API 순위 조회
def get_naver_rank(keyword, target_mid):
    try:
        enc_text = urllib.parse.quote(keyword)
        
        for start in range(1, 301, 100):
            url = f"https://openapi.naver.com/v1/search/shop.json?query={enc_text}&display=100&start={start}&sort=sim"
            req = urllib.request.Request(url)
            req.add_header("X-Naver-Client-Id", NAVER_CLIENT_ID)
            req.add_header("X-Naver-Client-Secret", NAVER_CLIENT_SECRET)
            
            res = urllib.request.urlopen(req, timeout=10)
            data = json.loads(res.read().decode('utf-8'))
            
            if not data['items']:
                break
            
            for idx, item in enumerate(data['items']):
                if str(item['productId']) == str(target_mid):
                    real_rank = (start - 1) + (idx + 1)
                    clean_title = item['title'].replace('<b>', '').replace('</b>', '')
                    return real_rank, clean_title, item['mallName']
            
            time.sleep(0.1)
        
        return None, None, None
    except Exception as e:
        print(f"API Error: {e}")
        return None, None, None

# 관리자 API (기존 유지)
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
                'id': u[0], 'userId': u[1], 'name': u[2], 'phone': u[3],
                'regDate': str(u[4]) if u[4] else '', 'approved': u[5]
            })
        return jsonify({'success': True, 'users': result})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/admin/approve', methods=['POST'])
def approve_user():
    data = request.json
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('UPDATE users SET approved = %s WHERE user_id = %s', (data.get('approved', 'Y'), data.get('userId')))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/admin/delete', methods=['POST'])
def delete_user():
    data = request.json
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('DELETE FROM users WHERE user_id = %s', (data.get('userId'),))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# 기존 클라이언트 호환용 API
@app.route('/register', methods=['POST'])
def register_compat():
    return api_register()

@app.route('/login', methods=['POST'])
def login_compat():
    data = request.json
    user_id = data.get('userId')
    password = data.get('password')
    
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT user_id, password, name, approved FROM users WHERE user_id = %s', (user_id,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        if not user:
            return jsonify({'success': False, 'message': '존재하지 않는 아이디입니다.'})
        if user[1] != password:
            return jsonify({'success': False, 'message': '비밀번호가 일치하지 않습니다.'})
        if user[3] != 'Y':
            return jsonify({'success': False, 'message': '관리자 승인 대기 중입니다.\n승인 문의: 카카오톡 odong4444'})
        
        return jsonify({'success': True, 'name': user[2]})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# DB 초기화
with app.app_context():
    try:
        init_db()
    except:
        pass

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
