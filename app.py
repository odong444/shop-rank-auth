from flask import Flask, request, jsonify, session, redirect, Response
from flask_cors import CORS
import psycopg
import os
import urllib.request
import urllib.parse
import json
import time
from datetime import datetime
import pytz
from functools import wraps
import csv
import io

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')
CORS(app)

DATABASE_URL = os.environ.get('DATABASE_URL')
NAVER_CLIENT_ID = "UrlniCJoGZ_jfgk5tlkN"
NAVER_CLIENT_SECRET = "x3z9b1CM2F"
KST = pytz.timezone('Asia/Seoul')

ADMIN_PASSWORD = "02100210"

def get_db():
    return psycopg.connect(DATABASE_URL)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY, user_id VARCHAR(50) UNIQUE NOT NULL,
        password VARCHAR(100) NOT NULL, name VARCHAR(50) NOT NULL,
        phone VARCHAR(20) NOT NULL, reg_date DATE DEFAULT CURRENT_DATE,
        approved CHAR(1) DEFAULT 'N')''')
    cur.execute('''CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY, user_id VARCHAR(50) NOT NULL,
        mid VARCHAR(50) NOT NULL, keyword VARCHAR(100) NOT NULL,
        title VARCHAR(500) DEFAULT '', mall VARCHAR(100) DEFAULT '',
        current_rank VARCHAR(20) DEFAULT '-',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, mid, keyword))''')
    cur.execute('''CREATE TABLE IF NOT EXISTS rank_history (
        id SERIAL PRIMARY KEY, product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
        rank VARCHAR(20) NOT NULL, checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    
    # 기존 테이블에 새 컬럼 추가 (각각 별도 트랜잭션)
    for col in [("first_rank", "VARCHAR(20) DEFAULT '-'"), ("prev_rank", "VARCHAR(20) DEFAULT '-'"), ("last_checked", "TIMESTAMP")]:
        try:
            cur.execute(f"ALTER TABLE products ADD COLUMN {col[0]} {col[1]}")
            conn.commit()
        except Exception:
            conn.rollback()
    
    cur.close()
    conn.close()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

def get_naver_rank(keyword, target_mid):
    try:
        enc = urllib.parse.quote(keyword)
        for start in range(1, 301, 100):
            url = f"https://openapi.naver.com/v1/search/shop.json?query={enc}&display=100&start={start}&sort=sim"
            req = urllib.request.Request(url)
            req.add_header("X-Naver-Client-Id", NAVER_CLIENT_ID)
            req.add_header("X-Naver-Client-Secret", NAVER_CLIENT_SECRET)
            res = urllib.request.urlopen(req, timeout=10)
            data = json.loads(res.read().decode('utf-8'))
            if not data['items']: break
            for idx, item in enumerate(data['items']):
                if str(item['productId']) == str(target_mid):
                    rank = (start - 1) + (idx + 1)
                    title = item['title'].replace('<b>', '').replace('</b>', '')
                    return rank, title, item['mallName']
            time.sleep(0.1)
        return None, None, None
    except Exception as e:
        print(f"API Error: {e}")
        return None, None, None

# ===== HTML PAGES =====

@app.route('/')
def index():
    return redirect('/dashboard' if 'user_id' in session else '/login')

@app.route('/login')
def login_page():
    return '''<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>로그인</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Malgun Gothic',sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);min-height:100vh;display:flex;align-items:center;justify-content:center}
.container{background:#fff;padding:40px;border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.3);width:90%;max-width:400px}h1{text-align:center;margin-bottom:30px;font-size:24px}
.form-group{margin-bottom:20px}.form-group label{display:block;margin-bottom:8px;font-weight:bold}.form-group input{width:100%;padding:15px;border:2px solid #e0e0e0;border-radius:10px;font-size:16px}
.form-group input:focus{outline:none;border-color:#667eea}.btn{width:100%;padding:15px;border:none;border-radius:10px;font-size:16px;font-weight:bold;cursor:pointer;margin-bottom:10px}
.btn-primary{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff}.btn-secondary{background:#f0f0f0;color:#333}.notice{text-align:center;margin-top:20px;color:#888;font-size:14px}
.error{background:#ffe0e0;color:#c00;padding:10px;border-radius:10px;margin-bottom:20px;text-align:center;display:none}</style></head>
<body><div class="container"><h1>🛒 순위 관리 시스템</h1><div class="error" id="error"></div>
<div class="form-group"><label>아이디</label><input type="text" id="userId" placeholder="아이디 입력"></div>
<div class="form-group"><label>비밀번호</label><input type="password" id="password" placeholder="비밀번호 입력"></div>
<button class="btn btn-primary" onclick="doLogin()">로그인</button>
<button class="btn btn-secondary" onclick="location.href='/register'">회원가입</button>
<p class="notice">문의: 카카오톡 odong4444</p></div>
<script>async function doLogin(){const u=document.getElementById('userId').value,p=document.getElementById('password').value,e=document.getElementById('error');
if(!u||!p){e.textContent='아이디와 비밀번호를 입력해주세요.';e.style.display='block';return}
try{const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({userId:u,password:p})});const d=await r.json();
if(d.success)location.href='/dashboard';else{e.textContent=d.message;e.style.display='block'}}catch(x){e.textContent='서버 연결 실패';e.style.display='block'}}
document.getElementById('password').addEventListener('keypress',e=>{if(e.key==='Enter')doLogin()})</script></body></html>'''

@app.route('/register')
def register_page():
    return '''<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>회원가입</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Malgun Gothic',sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.container{background:#fff;padding:40px;border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.3);width:90%;max-width:400px}h1{text-align:center;margin-bottom:30px}
.form-group{margin-bottom:15px}.form-group label{display:block;margin-bottom:5px;font-weight:bold;font-size:14px}.form-group input{width:100%;padding:12px;border:2px solid #e0e0e0;border-radius:10px;font-size:14px}
.btn{width:100%;padding:15px;border:none;border-radius:10px;font-size:16px;font-weight:bold;cursor:pointer;margin-bottom:10px}.btn-primary{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff}.btn-secondary{background:#f0f0f0}
.error,.success{padding:10px;border-radius:10px;margin-bottom:15px;text-align:center;display:none}.error{background:#ffe0e0;color:#c00}.success{background:#e0ffe0;color:#060}</style></head>
<body><div class="container"><h1>📝 회원가입</h1><div class="error" id="error"></div><div class="success" id="success"></div>
<div class="form-group"><label>아이디</label><input type="text" id="userId"></div>
<div class="form-group"><label>비밀번호</label><input type="password" id="password"></div>
<div class="form-group"><label>비밀번호 확인</label><input type="password" id="password2"></div>
<div class="form-group"><label>이름</label><input type="text" id="name"></div>
<div class="form-group"><label>연락처</label><input type="text" id="phone"></div>
<button class="btn btn-primary" onclick="doRegister()">가입하기</button>
<button class="btn btn-secondary" onclick="location.href='/login'">로그인으로</button></div>
<script>async function doRegister(){const u=document.getElementById('userId').value,p=document.getElementById('password').value,p2=document.getElementById('password2').value,
n=document.getElementById('name').value,ph=document.getElementById('phone').value,err=document.getElementById('error'),suc=document.getElementById('success');
err.style.display='none';suc.style.display='none';if(!u||!p||!p2||!n||!ph){err.textContent='모든 항목을 입력해주세요.';err.style.display='block';return}
if(p!==p2){err.textContent='비밀번호가 일치하지 않습니다.';err.style.display='block';return}
try{const r=await fetch('/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({userId:u,password:p,name:n,phone:ph})});const d=await r.json();
if(d.success){suc.innerHTML='회원가입 완료!<br>관리자 승인 후 사용 가능합니다.<br>문의: 카카오톡 odong4444';suc.style.display='block'}else{err.textContent=d.message;err.style.display='block'}}
catch(x){err.textContent='서버 연결 실패';err.style.display='block'}}</script></body></html>'''

@app.route('/dashboard')
@login_required
def dashboard_page():
    name = session.get('name', '')
    return f'''<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>대시보드</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:'Malgun Gothic',sans-serif;background:#f5f7fa;min-height:100vh}}
.layout{{display:flex;min-height:100vh}}.sidebar{{width:250px;background:linear-gradient(180deg,#2c3e50,#1a252f);color:#fff;padding:20px 0;flex-shrink:0}}
.sidebar-header{{padding:20px;border-bottom:1px solid rgba(255,255,255,.1);margin-bottom:20px}}.sidebar-header h1{{font-size:18px}}.sidebar-header p{{font-size:12px;color:#888}}
.sidebar-menu{{list-style:none}}.sidebar-menu li{{margin:5px 10px}}.sidebar-menu a{{display:flex;align-items:center;padding:12px 15px;color:#ccc;text-decoration:none;border-radius:8px;font-size:14px}}
.sidebar-menu a:hover{{background:rgba(255,255,255,.1);color:#fff}}.sidebar-menu a.active{{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff}}
.sidebar-menu .icon{{margin-right:10px;font-size:18px}}.sidebar-menu .soon{{margin-left:auto;font-size:11px;color:#666}}
.sidebar-footer{{position:fixed;bottom:20px;left:0;width:250px;padding:20px;border-top:1px solid rgba(255,255,255,.1)}}.sidebar-footer a{{color:#888;text-decoration:none;font-size:13px}}
.main{{flex:1;display:flex;flex-direction:column}}.header{{background:#fff;padding:15px 25px;display:flex;justify-content:space-between;align-items:center;box-shadow:0 2px 10px rgba(0,0,0,.05)}}
.header h2{{font-size:18px}}.content{{flex:1;padding:25px;overflow-y:auto}}
.card{{background:#fff;border-radius:12px;box-shadow:0 2px 15px rgba(0,0,0,.05);margin-bottom:20px}}.card-header{{padding:20px;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px}}
.card-header h3{{font-size:16px}}.card-body{{padding:20px}}.form-row{{display:flex;gap:10px;flex-wrap:wrap;align-items:center}}
.form-row input{{padding:10px 15px;border:2px solid #e0e0e0;border-radius:8px;font-size:14px;min-width:150px}}.form-row input:focus{{outline:none;border-color:#667eea}}
.form-row button{{padding:10px 20px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border:none;border-radius:8px;font-weight:bold;cursor:pointer}}
.form-row button:disabled{{background:#ccc;cursor:not-allowed}}.btn-group{{display:flex;gap:10px;flex-wrap:wrap}}
.btn{{padding:8px 16px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:500}}.btn-primary{{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff}}
.btn-success{{background:#28a745;color:#fff}}.btn-info{{background:#17a2b8;color:#fff}}.btn-danger{{background:#dc3545;color:#fff}}
.table-container{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:12px 10px;text-align:center;border-bottom:1px solid #eee}}
th{{background:#f8f9fa;color:#555;font-weight:600;white-space:nowrap}}.rank-up{{color:#dc3545;font-weight:bold}}.rank-down{{color:#28a745;font-weight:bold}}
.empty{{text-align:center;padding:60px 20px;color:#888}}.empty-icon{{font-size:50px;margin-bottom:15px}}.loading{{text-align:center;padding:40px;color:#666}}
.spinner{{display:inline-block;width:30px;height:30px;border:3px solid #f3f3f3;border-top:3px solid #667eea;border-radius:50%;animation:spin 1s linear infinite}}
@keyframes spin{{0%{{transform:rotate(0deg)}}100%{{transform:rotate(360deg)}}}}
.modal{{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);align-items:center;justify-content:center;z-index:1000}}
.modal-content{{background:#fff;padding:25px;border-radius:15px;max-width:600px;width:90%;max-height:80vh;overflow-y:auto}}
.modal-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding-bottom:15px;border-bottom:1px solid #eee}}
.modal-close{{background:none;border:none;font-size:28px;cursor:pointer;color:#888}}
@media(max-width:768px){{.sidebar{{display:none}}.layout{{flex-direction:column}}th,td{{padding:8px 5px;font-size:11px}}.form-row{{flex-direction:column}}.form-row input,.form-row button{{width:100%}}}}</style></head>
<body><div class="layout">
<nav class="sidebar"><div class="sidebar-header"><h1>🛒 순위 관리</h1><p>Rank Tracker</p></div>
<ul class="sidebar-menu">
<li><a href="/dashboard" class="active"><span class="icon">🛍️</span>네이버 쇼핑 순위체크</a></li>
<li><a href="#" style="opacity:.5;cursor:not-allowed"><span class="icon">🚀</span>쿠팡 순위체크<span class="soon">준비중</span></a></li>
<li><a href="#" style="opacity:.5;cursor:not-allowed"><span class="icon">📍</span>네이버 플레이스<span class="soon">준비중</span></a></li>
<li style="margin-top:30px"><a href="/admin"><span class="icon">⚙️</span>회원 관리</a></li>
</ul><div class="sidebar-footer"><a href="/api/logout">🚪 로그아웃</a></div></nav>
<main class="main">
<header class="header"><h2>🛍️ 네이버 쇼핑 순위체크</h2><div style="font-size:14px;color:#666">👤 {name}님</div></header>
<div class="content">
<div class="card"><div class="card-header"><h3>➕ 상품 등록</h3></div>
<div class="card-body"><div class="form-row">
<input type="text" id="mid" placeholder="MID (상품번호)">
<input type="text" id="keyword" placeholder="검색 키워드">
<button onclick="addProduct()" id="addBtn">등록하기</button>
</div><p style="margin-top:10px;font-size:12px;color:#888">* 등록 시 자동으로 순위가 조회됩니다</p></div></div>
<div class="card"><div class="card-header"><h3>📋 내 상품 목록 <span id="productCount" style="color:#667eea"></span></h3>
<div class="btn-group">
<button class="btn btn-success" onclick="exportExcel()">📥 엑셀 다운로드</button>
<button class="btn btn-primary" onclick="refreshAll()" id="refreshBtn">🔄 전체 새로고침</button>
</div></div>
<div class="card-body">
<div id="loading" class="loading"><div class="spinner"></div><p>로딩 중...</p></div>
<div class="table-container" id="tableContainer" style="display:none">
<table><thead><tr><th>스토어명</th><th>상품명</th><th>MID</th><th>키워드</th><th>최초순위</th><th>이전순위</th><th>오늘순위</th><th>관리</th></tr></thead>
<tbody id="productBody"></tbody></table></div>
<div id="empty" class="empty" style="display:none"><div class="empty-icon">📦</div><p>등록된 상품이 없습니다.<br>상품을 등록해보세요!</p></div>
</div></div></div>
<div class="modal" id="historyModal"><div class="modal-content">
<div class="modal-header"><h3>📊 순위 변동 이력</h3><button class="modal-close" onclick="closeModal()">&times;</button></div>
<p id="historyTitle" style="margin-bottom:15px;color:#666"></p>
<div class="table-container"><table><thead><tr><th>날짜/시간</th><th>순위</th></tr></thead><tbody id="historyBody"></tbody></table></div>
</div></div>
</main></div>
<script>
let products=[];
async function loadProducts(){{try{{const r=await fetch('/api/products');const d=await r.json();document.getElementById('loading').style.display='none';
if(d.success&&d.products.length>0){{products=d.products;document.getElementById('tableContainer').style.display='block';document.getElementById('empty').style.display='none';
document.getElementById('productCount').textContent=`(${{d.products.length}}개)`;const tbody=document.getElementById('productBody');tbody.innerHTML='';
d.products.forEach(p=>{{const tr=document.createElement('tr');let todayHtml=formatRank(p.current_rank);
if(p.prev_rank&&p.prev_rank!=='-'&&p.current_rank&&p.current_rank!=='-'&&p.current_rank!=='300위 밖'){{
const prev=parseInt(p.prev_rank),curr=parseInt(p.current_rank);if(!isNaN(prev)&&!isNaN(curr)){{const diff=prev-curr;
if(diff>0)todayHtml+=` <span class="rank-down">▲${{diff}}</span>`;else if(diff<0)todayHtml+=` <span class="rank-up">▼${{Math.abs(diff)}}</span>`;}}}}
tr.innerHTML=`<td>${{p.mall||'-'}}</td><td style="text-align:left;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${{p.title||''}}">${{p.title||'-'}}</td>
<td>${{p.mid}}</td><td>${{p.keyword}}</td><td>${{formatRank(p.first_rank)}}</td><td>${{formatRank(p.prev_rank)}}</td><td>${{todayHtml}}</td>
<td><button class="btn btn-info" style="padding:4px 8px;font-size:11px" onclick="showHistory(${{p.id}},'${{p.keyword}}')">이력</button>
<button class="btn btn-danger" style="padding:4px 8px;font-size:11px" onclick="deleteProduct(${{p.id}})">삭제</button></td>`;
tbody.appendChild(tr);}});}}else{{products=[];document.getElementById('tableContainer').style.display='none';document.getElementById('empty').style.display='block';
document.getElementById('productCount').textContent='(0개)';}}}}catch(e){{document.getElementById('loading').innerHTML='<p style="color:#c00">데이터 로드 실패</p>';}}}}
function formatRank(r){{if(!r||r==='-')return'-';if(r==='300위 밖')return'<span style="color:#888">300위 밖</span>';return r+'위';}}
async function addProduct(){{const mid=document.getElementById('mid').value.trim(),kw=document.getElementById('keyword').value.trim(),btn=document.getElementById('addBtn');
if(!mid||!kw){{alert('MID와 키워드를 입력해주세요.');return;}}btn.disabled=true;btn.textContent='조회 중...';
try{{const r=await fetch('/api/products',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{mid,keyword:kw}})}});const d=await r.json();
if(d.success){{document.getElementById('mid').value='';document.getElementById('keyword').value='';loadProducts();}}else alert(d.message);}}
catch(e){{alert('서버 연결 실패');}}finally{{btn.disabled=false;btn.textContent='등록하기';}}}}
async function deleteProduct(id){{if(!confirm('정말 삭제하시겠습니까?'))return;try{{const r=await fetch('/api/products/'+id,{{method:'DELETE'}});const d=await r.json();if(d.success)loadProducts();else alert(d.message);}}catch(e){{alert('서버 연결 실패');}}}}
async function refreshAll(){{if(!confirm('전체 순위를 새로고침하시겠습니까?\\n(시간이 걸릴 수 있습니다)'))return;const btn=document.getElementById('refreshBtn');btn.disabled=true;btn.textContent='조회 중...';
try{{const r=await fetch('/api/refresh',{{method:'POST'}});const d=await r.json();if(d.success){{alert(`순위 조회 완료! (${{d.updated}}개 상품)`);loadProducts();}}else alert(d.message);}}
catch(e){{alert('서버 연결 실패');}}finally{{btn.disabled=false;btn.textContent='🔄 전체 새로고침';}}}}
async function showHistory(pid,kw){{try{{const r=await fetch('/api/history/'+pid);const d=await r.json();document.getElementById('historyTitle').textContent='키워드: '+kw;
const tbody=document.getElementById('historyBody');tbody.innerHTML='';if(d.success&&d.history.length>0){{d.history.forEach(h=>{{const tr=document.createElement('tr');
tr.innerHTML=`<td>${{h.checked_at}}</td><td>${{formatRank(h.rank)}}</td>`;tbody.appendChild(tr);}});}}else tbody.innerHTML='<tr><td colspan="2">이력이 없습니다.</td></tr>';
document.getElementById('historyModal').style.display='flex';}}catch(e){{alert('이력 조회 실패');}}}}
function closeModal(){{document.getElementById('historyModal').style.display='none';}}
function exportExcel(){{if(products.length===0){{alert('다운로드할 데이터가 없습니다.');return;}}window.location.href='/api/export';}}
document.getElementById('historyModal').addEventListener('click',function(e){{if(e.target===this)closeModal();}});
document.getElementById('keyword').addEventListener('keypress',function(e){{if(e.key==='Enter')addProduct();}});
loadProducts();
</script></body></html>'''

@app.route('/admin')
def admin_page():
    if not session.get('admin_logged_in'):
        return redirect('/admin/login')
    return '''<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>회원 관리</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Malgun Gothic',sans-serif;background:#f5f5f5;padding:20px}
.container{max-width:1000px;margin:0 auto;background:#fff;padding:20px;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.1)}
h1{text-align:center;margin-bottom:20px}table{width:100%;border-collapse:collapse}th,td{padding:12px;text-align:center;border-bottom:1px solid #ddd}
th{background:#4a90d9;color:#fff}tr:hover{background:#f9f9f9}.btn{padding:6px 12px;border:none;border-radius:5px;cursor:pointer;font-size:12px}
.btn-approve{background:#28a745;color:#fff}.btn-reject{background:#ffc107}.btn-delete{background:#dc3545;color:#fff}
.refresh-btn{display:block;margin:20px auto;padding:10px 30px;background:#4a90d9;color:#fff;border:none;border-radius:5px;cursor:pointer}
.back-btn{display:inline-block;margin-bottom:20px;padding:8px 16px;background:#667eea;color:#fff;text-decoration:none;border-radius:5px}
.logout-btn{display:inline-block;margin-left:10px;padding:8px 16px;background:#dc3545;color:#fff;text-decoration:none;border-radius:5px}</style></head>
<body><div class="container"><a href="/dashboard" class="back-btn">← 대시보드로</a><a href="/admin/logout" class="logout-btn">관리자 로그아웃</a><h1>🔐 회원 관리</h1>
<button class="refresh-btn" onclick="loadUsers()">새로고침</button>
<table><thead><tr><th>아이디</th><th>이름</th><th>전화번호</th><th>가입일</th><th>승인</th><th>관리</th></tr></thead><tbody id="userTable"></tbody></table></div>
<script>async function loadUsers(){try{const r=await fetch('/admin/users');const d=await r.json();if(d.success){const tbody=document.getElementById('userTable');tbody.innerHTML='';
d.users.forEach(u=>{const tr=document.createElement('tr');tr.innerHTML=`<td>${u.userId}</td><td>${u.name}</td><td>${u.phone}</td><td>${u.regDate}</td>
<td style="color:${u.approved==='Y'?'#28a745':'#dc3545'};font-weight:bold">${u.approved==='Y'?'승인됨':'대기중'}</td>
<td>${u.approved==='Y'?`<button class="btn btn-reject" onclick="setApproval('${u.userId}','N')">승인취소</button>`:`<button class="btn btn-approve" onclick="setApproval('${u.userId}','Y')">승인</button>`}
<button class="btn btn-delete" onclick="deleteUser('${u.userId}')">삭제</button></td>`;tbody.appendChild(tr);});}}catch(e){alert('로드 실패');}}
async function setApproval(id,ap){const r=await fetch('/admin/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({userId:id,approved:ap})});const d=await r.json();if(d.success)loadUsers();else alert(d.message);}
async function deleteUser(id){if(!confirm(id+' 회원을 삭제하시겠습니까?'))return;const r=await fetch('/admin/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({userId:id})});const d=await r.json();if(d.success)loadUsers();else alert(d.message);}
loadUsers();</script></body></html>'''

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect('/admin')
        else:
            return '''<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>관리자 로그인</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Malgun Gothic',sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);min-height:100vh;display:flex;align-items:center;justify-content:center}
.container{background:#fff;padding:40px;border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.3);width:90%;max-width:350px;text-align:center}
h1{margin-bottom:20px;font-size:20px}input{width:100%;padding:15px;border:2px solid #e0e0e0;border-radius:10px;font-size:16px;margin-bottom:15px}
input:focus{outline:none;border-color:#667eea}button{width:100%;padding:15px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border:none;border-radius:10px;font-size:16px;font-weight:bold;cursor:pointer}
.error{color:#c00;margin-bottom:15px}</style></head>
<body><div class="container"><h1>🔐 관리자 로그인</h1><p class="error">비밀번호가 틀렸습니다.</p>
<form method="POST"><input type="password" name="password" placeholder="관리자 비밀번호"><button type="submit">로그인</button></form></div></body></html>'''
    
    return '''<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>관리자 로그인</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Malgun Gothic',sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);min-height:100vh;display:flex;align-items:center;justify-content:center}
.container{background:#fff;padding:40px;border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.3);width:90%;max-width:350px;text-align:center}
h1{margin-bottom:20px;font-size:20px}input{width:100%;padding:15px;border:2px solid #e0e0e0;border-radius:10px;font-size:16px;margin-bottom:15px}
input:focus{outline:none;border-color:#667eea}button{width:100%;padding:15px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border:none;border-radius:10px;font-size:16px;font-weight:bold;cursor:pointer}</style></head>
<body><div class="container"><h1>🔐 관리자 로그인</h1>
<form method="POST"><input type="password" name="password" placeholder="관리자 비밀번호"><button type="submit">로그인</button></form></div></body></html>'''

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect('/admin/login')

# ===== API =====

@app.route('/api/login', methods=['POST'])
def api_login():
    d = request.json
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT user_id,password,name,approved FROM users WHERE user_id=%s', (d.get('userId'),))
        u = cur.fetchone()
        cur.close()
        conn.close()
        if not u: return jsonify({'success': False, 'message': '존재하지 않는 아이디입니다.'})
        if u[1] != d.get('password'): return jsonify({'success': False, 'message': '비밀번호가 일치하지 않습니다.'})
        if u[3] != 'Y': return jsonify({'success': False, 'message': '관리자 승인 대기 중입니다.\n승인 문의: 카카오톡 odong4444'})
        session['user_id'] = d.get('userId')
        session['name'] = u[2]
        return jsonify({'success': True, 'name': u[2]})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/register', methods=['POST'])
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
        cur.execute('INSERT INTO users (user_id,password,name,phone) VALUES (%s,%s,%s,%s)', (d.get('userId'), d.get('password'), d.get('name'), d.get('phone')))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/logout')
def api_logout():
    session.clear()
    return redirect('/login')

@app.route('/api/products', methods=['GET'])
@login_required
def get_products():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT id,mid,keyword,title,mall,first_rank,prev_rank,current_rank FROM products WHERE user_id=%s ORDER BY id DESC', (session['user_id'],))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'products': [{'id': r[0], 'mid': r[1], 'keyword': r[2], 'title': r[3], 'mall': r[4], 'first_rank': r[5], 'prev_rank': r[6], 'current_rank': r[7]} for r in rows]})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/products', methods=['POST'])
@login_required
def add_product():
    d = request.json
    mid, kw = d.get('mid'), d.get('keyword')
    try:
        rank, title, mall = get_naver_rank(kw, mid)
        rank_str = str(rank) if rank else '300위 밖'
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT id FROM products WHERE user_id=%s AND mid=%s AND keyword=%s', (session['user_id'], mid, kw))
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': '이미 등록된 상품입니다.'})
        cur.execute('INSERT INTO products (user_id,mid,keyword,title,mall,first_rank,prev_rank,current_rank,last_checked) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())',
                    (session['user_id'], mid, kw, title or '', mall or '', rank_str, '-', rank_str))
        conn.commit()
        cur.execute('SELECT id FROM products WHERE user_id=%s AND mid=%s AND keyword=%s', (session['user_id'], mid, kw))
        pid = cur.fetchone()[0]
        cur.execute('INSERT INTO rank_history (product_id,rank) VALUES (%s,%s)', (pid, rank_str))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/products/<int:pid>', methods=['DELETE'])
@login_required
def delete_product(pid):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('DELETE FROM products WHERE id=%s AND user_id=%s', (pid, session['user_id']))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/history/<int:pid>', methods=['GET'])
@login_required
def get_history(pid):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT rank,checked_at FROM rank_history WHERE product_id=%s ORDER BY checked_at DESC LIMIT 50', (pid,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        result = []
        for r in rows:
            t = r[1]
            if t:
                if t.tzinfo is None:
                    t = pytz.utc.localize(t)
                t = t.astimezone(KST).strftime('%Y-%m-%d %H:%M')
            else:
                t = ''
            result.append({'rank': r[0], 'checked_at': t})
        return jsonify({'success': True, 'history': result})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/refresh', methods=['POST'])
@login_required
def refresh_ranks():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT id,mid,keyword FROM products WHERE user_id=%s', (session['user_id'],))
        rows = cur.fetchall()
        updated = 0
        for r in rows:
            pid, mid, kw = r
            rank, title, mall = get_naver_rank(kw, mid)
            rank_str = str(rank) if rank else '300위 밖'
            cur.execute('UPDATE products SET prev_rank=current_rank,current_rank=%s,title=COALESCE(NULLIF(%s,\'\'),title),mall=COALESCE(NULLIF(%s,\'\'),mall),last_checked=NOW() WHERE id=%s',
                        (rank_str, title or '', mall or '', pid))
            cur.execute('INSERT INTO rank_history (product_id,rank) VALUES (%s,%s)', (pid, rank_str))
            updated += 1
            time.sleep(0.2)
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'updated': updated})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/export')
@login_required
def export_excel():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT mall,title,mid,keyword,first_rank,prev_rank,current_rank FROM products WHERE user_id=%s ORDER BY id DESC', (session['user_id'],))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        output = io.StringIO()
        w = csv.writer(output)
        w.writerow(['스토어명', '상품명', 'MID', '키워드', '최초순위', '이전순위', '오늘순위'])
        for r in rows:
            w.writerow([r[0] or '', r[1] or '', r[2], r[3], r[4] or '-', r[5] or '-', r[6] or '-'])
        output.seek(0)
        now = datetime.now(KST).strftime('%Y%m%d_%H%M')
        return Response('\ufeff' + output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=rank_{now}.csv'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/admin/users', methods=['GET'])
def get_users():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT id,user_id,name,phone,reg_date,approved FROM users ORDER BY id DESC')
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'users': [{'id': r[0], 'userId': r[1], 'name': r[2], 'phone': r[3], 'regDate': str(r[4]) if r[4] else '', 'approved': r[5]} for r in rows]})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/admin/approve', methods=['POST'])
def approve_user():
    d = request.json
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('UPDATE users SET approved=%s WHERE user_id=%s', (d.get('approved', 'Y'), d.get('userId')))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/admin/delete', methods=['POST'])
def delete_user():
    d = request.json
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('DELETE FROM products WHERE user_id=%s', (d.get('userId'),))
        cur.execute('DELETE FROM users WHERE user_id=%s', (d.get('userId'),))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# 기존 클라이언트 호환
@app.route('/register', methods=['POST'])
def register_compat():
    return api_register()

@app.route('/login', methods=['POST'])
def login_compat():
    d = request.json
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT user_id,password,name,approved FROM users WHERE user_id=%s', (d.get('userId'),))
        u = cur.fetchone()
        cur.close()
        conn.close()
        if not u: return jsonify({'success': False, 'message': '존재하지 않는 아이디입니다.'})
        if u[1] != d.get('password'): return jsonify({'success': False, 'message': '비밀번호가 일치하지 않습니다.'})
        if u[3] != 'Y': return jsonify({'success': False, 'message': '관리자 승인 대기 중입니다.\n승인 문의: 카카오톡 odong4444'})
        return jsonify({'success': True, 'name': u[2]})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

with app.app_context():
    try:
        init_db()
    except:
        pass

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
