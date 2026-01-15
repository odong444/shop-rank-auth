from flask import Flask, request, jsonify, session, redirect, Response
from flask_cors import CORS
import psycopg
import os
import urllib.request
import urllib.parse
import json
import time
from datetime import datetime, timedelta
import pytz
from functools import wraps
import csv
import io
import random
import hashlib
import hmac

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')
CORS(app)

DATABASE_URL = os.environ.get('DATABASE_URL')
NAVER_CLIENT_ID = "UrlniCJoGZ_jfgk5tlkN"
NAVER_CLIENT_SECRET = "x3z9b1CM2F"
KST = pytz.timezone('Asia/Seoul')

ADMIN_PASSWORD = "02100210"
CACHE_DURATION_MINUTES = 60

# 알리고 SMS 설정
ALIGO_API_KEY = "3xj66vap7q84cvvqfwugklcxpu7srvrf"
ALIGO_USER_ID = "odong444"
ALIGO_SENDER = "01072100210"

# [신규] 윈도우 로컬 서버 (상세 점수 조회 담당)
RANK_API_URL = 'https://bat-loved-independence-attachments.trycloudflare.com'

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
    
    cur.execute('''CREATE TABLE IF NOT EXISTS keyword_cache (
        id SERIAL PRIMARY KEY,
        keyword VARCHAR(100) UNIQUE NOT NULL,
        search_results TEXT,
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    cur.execute('''CREATE TABLE IF NOT EXISTS sms_verify (
        id SERIAL PRIMARY KEY,
        phone VARCHAR(20) NOT NULL,
        code VARCHAR(6) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        verified BOOLEAN DEFAULT FALSE)''')
    conn.commit()
    
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

def get_naver_search_results(keyword):
    results = []
    try:
        enc = urllib.parse.quote(keyword)
        for start in range(1, 301, 100):
            url = f"https://openapi.naver.com/v1/search/shop.json?query={enc}&display=100&start={start}&sort=sim"
            req = urllib.request.Request(url)
            req.add_header("X-Naver-Client-Id", NAVER_CLIENT_ID)
            req.add_header("X-Naver-Client-Secret", NAVER_CLIENT_SECRET)
            res = urllib.request.urlopen(req, timeout=10)
            data = json.loads(res.read().decode('utf-8'))
            if not data['items']:
                break
            for idx, item in enumerate(data['items']):
                rank = (start - 1) + (idx + 1)
                results.append({
                    'rank': rank,
                    'mid': str(item['productId']),
                    'title': item['title'].replace('<b>', '').replace('</b>', ''),
                    'mall': item['mallName']
                })
            time.sleep(0.1)
    except Exception as e:
        print(f"API Error: {e}")
    return results

def get_cached_results(keyword):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT search_results, cached_at FROM keyword_cache WHERE keyword=%s', (keyword,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    
    if row:
        cached_at = row[1]
        if cached_at.tzinfo is None:
            cached_at = pytz.utc.localize(cached_at)
        now = datetime.now(pytz.utc)
        if now - cached_at < timedelta(minutes=CACHE_DURATION_MINUTES):
            return json.loads(row[0]) if row[0] else None
    return None

def save_cache(keyword, results):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('''INSERT INTO keyword_cache (keyword, search_results, cached_at) 
                      VALUES (%s, %s, NOW()) 
                      ON CONFLICT (keyword) DO UPDATE SET search_results=%s, cached_at=NOW()''',
                   (keyword, json.dumps(results), json.dumps(results)))
        conn.commit()
    except Exception as e:
        print(f"Cache save error: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

def update_all_products_with_keyword(keyword, results):
    if not results:
        return 0
    
    mid_map = {r['mid']: r for r in results}
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute('SELECT id, mid, first_rank FROM products WHERE keyword=%s', (keyword,))
    products = cur.fetchall()
    
    updated = 0
    for pid, mid, first_rank in products:
        if mid in mid_map:
            r = mid_map[mid]
            rank_str = str(r['rank'])
            new_first = first_rank if first_rank != '-' else rank_str
            cur.execute('''UPDATE products SET prev_rank=current_rank, current_rank=%s, 
                          title=COALESCE(NULLIF(%s,''),title), mall=COALESCE(NULLIF(%s,''),mall),
                          first_rank=%s, last_checked=NOW() WHERE id=%s''',
                       (rank_str, r['title'], r['mall'], new_first, pid))
            cur.execute('INSERT INTO rank_history (product_id, rank) VALUES (%s, %s)', (pid, rank_str))
            updated += 1
        else:
            cur.execute('''UPDATE products SET prev_rank=current_rank, current_rank=%s, last_checked=NOW() WHERE id=%s''',
                       ('300위 밖', pid))
            cur.execute('INSERT INTO rank_history (product_id, rank) VALUES (%s, %s)', (pid, '300위 밖'))
            updated += 1
    
    conn.commit()
    cur.close()
    conn.close()
    return updated

def get_naver_rank(keyword, target_mid):
    results = get_cached_results(keyword)
    
    if not results:
        results = get_naver_search_results(keyword)
        if results:
            save_cache(keyword, results)
            update_all_products_with_keyword(keyword, results)
    
    for r in results:
        if r['mid'] == str(target_mid):
            return r['rank'], r['title'], r['mall']
    
    return None, None, None


# ===== 사이드바 공통 HTML =====
def get_sidebar_html(active_menu='dashboard'):
    name = session.get('name', '')
    menus = [
        ('dashboard', '/dashboard', '🛍️', '네이버 쇼핑 순위체크', False),
        ('product-score', '/product-score', '📊', '상품지수 조회', False),
        ('coupang', '#', '🚀', '쿠팡 순위체크', True),
        ('place', '#', '📍', '네이버 플레이스', True),
    ]
    
    menu_html = ''
    for key, href, icon, label, disabled in menus:
        if disabled:
            menu_html += f'<li><a href="#" style="opacity:.5;cursor:not-allowed"><span class="icon">{icon}</span>{label}<span class="soon">준비중</span></a></li>'
        else:
            active_class = ' class="active"' if key == active_menu else ''
            menu_html += f'<li><a href="{href}"{active_class}><span class="icon">{icon}</span>{label}</a></li>'
    
    return f'''<button class="menu-toggle" onclick="toggleSidebar()">☰</button>
<div class="sidebar-overlay" id="sidebarOverlay" onclick="toggleSidebar()"></div>
<nav class="sidebar" id="sidebar"><div class="sidebar-header"><h1>🛒 순위 관리</h1><p>Rank Tracker</p></div>
<ul class="sidebar-menu">{menu_html}</ul>
<div class="sidebar-contact">
<p style="color:#888;font-size:12px;margin-bottom:10px;padding:0 15px">📞 문의하기</p>
<a href="http://pf.kakao.com/_HcdEn" target="_blank" class="contact-btn"><img src="https://developers.kakao.com/assets/img/about/logos/kakaotalksharing/kakaotalk_sharing_btn_small.png" alt="카카오">리뷰작업 문의</a>
<a href="http://pf.kakao.com/_xkKUnxj" target="_blank" class="contact-btn"><img src="https://developers.kakao.com/assets/img/about/logos/kakaotalksharing/kakaotalk_sharing_btn_small.png" alt="카카오">네이버 트래픽 문의</a>
<a href="http://pf.kakao.com/_xayNxjG" target="_blank" class="contact-btn"><img src="https://developers.kakao.com/assets/img/about/logos/kakaotalksharing/kakaotalk_sharing_btn_small.png" alt="카카오">쿠팡 트래픽 문의</a>
<a href="http://pf.kakao.com/_NxfIxfxj" target="_blank" class="contact-btn"><img src="https://developers.kakao.com/assets/img/about/logos/kakaotalksharing/kakaotalk_sharing_btn_small.png" alt="카카오">체험단 문의</a>
</div>
<div class="sidebar-footer"><a href="/api/logout">🚪 로그아웃</a></div></nav>'''


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
.error,.success{padding:10px;border-radius:10px;margin-bottom:15px;text-align:center;display:none}.error{background:#ffe0e0;color:#c00}.success{background:#e0ffe0;color:#060}
.notice-box{background:#fff3cd;color:#856404;padding:12px;border-radius:10px;margin-bottom:20px;font-size:13px;line-height:1.6;border:1px solid #ffc107}</style></head>
<body><div class="container"><h1>📝 회원가입</h1>
<div class="notice-box">⚠️ 이름과 연락처는 정확하게 입력해주세요.<br>허위 정보 입력 시 사전 안내 없이 계정이 삭제될 수 있습니다.</div>
<div class="error" id="error"></div><div class="success" id="success"></div>
<div class="form-group"><label>아이디</label><input type="text" id="userId"></div>
<div class="form-group"><label>비밀번호</label><input type="password" id="password"></div>
<div class="form-group"><label>비밀번호 확인</label><input type="password" id="password2"></div>
<div class="form-group"><label>이름</label><input type="text" id="name"></div>
<div class="form-group"><label>연락처</label><input type="text" id="phone" placeholder="01012345678"></div>
<button class="btn btn-primary" onclick="doRegister()">가입하기</button>
<button class="btn btn-secondary" onclick="location.href='/login'">로그인으로</button></div>
<script>
async function doRegister(){
const u=document.getElementById('userId').value,p=document.getElementById('password').value,p2=document.getElementById('password2').value,
n=document.getElementById('name').value,ph=document.getElementById('phone').value.replace(/-/g,''),err=document.getElementById('error'),suc=document.getElementById('success');
err.style.display='none';suc.style.display='none';
if(!u||!p||!p2||!n||!ph){err.textContent='모든 항목을 입력해주세요.';err.style.display='block';return}
if(p!==p2){err.textContent='비밀번호가 일치하지 않습니다.';err.style.display='block';return}
try{const r=await fetch('/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({userId:u,password:p,name:n,phone:ph})});const d=await r.json();
if(d.success){suc.innerHTML='회원가입 완료!<br>로그인해주세요.';suc.style.display='block';setTimeout(()=>location.href='/login',1500)}else{err.textContent=d.message;err.style.display='block'}}
catch(x){err.textContent='서버 연결 실패';err.style.display='block'}}
</script></body></html>'''

@app.route('/dashboard')
@login_required
def dashboard_page():
    name = session.get('name', '')
    sidebar = get_sidebar_html('dashboard')
    return f'''<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>대시보드</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:'Malgun Gothic',sans-serif;background:#f5f7fa;min-height:100vh}}
.layout{{display:flex;min-height:100vh}}.sidebar{{width:250px;background:linear-gradient(180deg,#2c3e50,#1a252f);color:#fff;padding:20px 0;flex-shrink:0;display:flex;flex-direction:column}}
.sidebar-header{{padding:20px;border-bottom:1px solid rgba(255,255,255,.1);margin-bottom:20px}}.sidebar-header h1{{font-size:18px}}.sidebar-header p{{font-size:12px;color:#888}}
.sidebar-menu{{list-style:none}}.sidebar-menu li{{margin:5px 10px}}.sidebar-menu a{{display:flex;align-items:center;padding:12px 15px;color:#ccc;text-decoration:none;border-radius:8px;font-size:14px}}
.sidebar-menu a:hover{{background:rgba(255,255,255,.1);color:#fff}}.sidebar-menu a.active{{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff}}
.sidebar-menu .icon{{margin-right:10px;font-size:18px}}.sidebar-menu .soon{{margin-left:auto;font-size:11px;color:#666}}
.sidebar-footer{{padding:20px;border-top:1px solid rgba(255,255,255,.1)}}.sidebar-footer a{{color:#888;text-decoration:none;font-size:13px}}
.sidebar-contact{{padding:10px;margin-top:auto;border-top:1px solid rgba(255,255,255,.1)}}.contact-btn{{display:flex;align-items:center;padding:8px 15px;margin:5px 10px;background:rgba(255,255,255,.05);border-radius:8px;color:#ccc;text-decoration:none;font-size:12px;transition:all .2s}}.contact-btn:hover{{background:#fee500;color:#000}}.contact-btn img{{width:20px;height:20px;margin-right:8px;border-radius:4px}}
.main{{flex:1;display:flex;flex-direction:column}}.header{{background:#fff;padding:15px 25px;display:flex;justify-content:space-between;align-items:center;box-shadow:0 2px 10px rgba(0,0,0,.05)}}
.header h2{{font-size:18px}}.content{{flex:1;padding:25px;overflow-y:auto}}
.card{{background:#fff;border-radius:12px;box-shadow:0 2px 15px rgba(0,0,0,.05);margin-bottom:20px}}.card-header{{padding:20px;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px}}
.card-header h3{{font-size:16px}}.card-body{{padding:20px}}.form-row{{display:flex;gap:10px;flex-wrap:wrap;align-items:center}}
.form-row input{{padding:10px 15px;border:2px solid #e0e0e0;border-radius:8px;font-size:14px;min-width:150px}}.form-row input:focus{{outline:none;border-color:#667eea}}
.form-row button{{padding:10px 20px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border:none;border-radius:8px;font-weight:bold;cursor:pointer}}
.form-row button:disabled{{background:#ccc;cursor:not-allowed}}.btn-group{{display:flex;gap:10px;flex-wrap:wrap}}
.btn{{padding:8px 16px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:500}}.btn-primary{{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff}}
.btn-success{{background:#28a745;color:#fff}}.btn-info{{background:#17a2b8;color:#fff}}.btn-danger{{background:#dc3545;color:#fff}}.btn-warning{{background:#ffc107;color:#000}}
.table-container{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:12px 10px;text-align:center;border-bottom:1px solid #eee}}
th{{background:#f8f9fa;color:#555;font-weight:600;white-space:nowrap}}.rank-up{{color:#dc3545;font-weight:bold}}.rank-down{{color:#28a745;font-weight:bold}}
.empty{{text-align:center;padding:60px 20px;color:#888}}.empty-icon{{font-size:50px;margin-bottom:15px}}.loading{{text-align:center;padding:40px;color:#666}}
.spinner{{display:inline-block;width:30px;height:30px;border:3px solid #f3f3f3;border-top:3px solid #667eea;border-radius:50%;animation:spin 1s linear infinite}}
.spinner-small{{display:inline-block;width:16px;height:16px;border:2px solid #f3f3f3;border-top:2px solid #667eea;border-radius:50%;animation:spin 1s linear infinite}}
@keyframes spin{{0%{{transform:rotate(0deg)}}100%{{transform:rotate(360deg)}}}}
.modal{{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);align-items:center;justify-content:center;z-index:1000}}
.modal-content{{background:#fff;padding:25px;border-radius:15px;max-width:600px;width:90%;max-height:80vh;overflow-y:auto}}
.modal-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding-bottom:15px;border-bottom:1px solid #eee}}
.modal-close{{background:none;border:none;font-size:28px;cursor:pointer;color:#888}}
.checkbox-col{{width:40px}}input[type="checkbox"]{{width:18px;height:18px;cursor:pointer}}
.selected-info{{display:none;padding:10px 15px;background:#fff3cd;border-radius:8px;margin-bottom:15px;align-items:center;justify-content:space-between}}
.selected-info.show{{display:flex}}
.menu-toggle{{display:none}}
@media(max-width:768px){{.sidebar{{display:none;position:fixed;top:0;left:0;height:100%;z-index:1000;transform:translateX(-100%);transition:transform .3s}}.sidebar.open{{display:flex;transform:translateX(0)}}
.menu-toggle{{display:block!important;position:fixed;top:15px;left:15px;z-index:999;background:#667eea;color:#fff;border:none;padding:10px 12px;border-radius:8px;font-size:20px;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.2)}}
.sidebar-overlay{{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);z-index:999}}.sidebar-overlay.open{{display:block}}
.header{{padding-left:60px}}.layout{{flex-direction:column}}
.table-container table,.table-container thead,.table-container tbody,.table-container th,.table-container td,.table-container tr{{display:block}}
.table-container thead tr{{position:absolute;top:-9999px;left:-9999px}}
.table-container tr{{background:#fff;border:1px solid #eee;border-radius:10px;margin-bottom:15px;padding:10px;box-shadow:0 2px 8px rgba(0,0,0,.05)}}
.table-container td{{border:none;padding:8px 10px;position:relative;padding-left:40%;white-space:normal!important;overflow:visible!important;text-overflow:clip!important;max-width:none!important}}
.table-container td:before{{content:attr(data-label);position:absolute;left:10px;width:35%;font-weight:600;color:#666;font-size:12px}}
.table-container td:last-child{{text-align:right;padding-left:10px}}.table-container td:last-child:before{{display:none}}
.checkbox-col{{display:none}}.form-row{{flex-direction:column}}.form-row input,.form-row button{{width:100%}}.btn-group{{width:100%}}.btn-group .btn{{flex:1}}
.card-header{{flex-direction:column;align-items:flex-start}}.card-header h3{{margin-bottom:10px}}}}</style></head>
<body><div class="layout">
{sidebar}
<main class="main">
<header class="header"><h2>🛍️ 네이버 쇼핑 순위체크</h2><div style="font-size:14px;color:#666">👤 {name}님</div></header>
<div class="content">
<div class="card"><div class="card-header"><h3>➕ 상품 등록</h3></div>
<div class="card-body">
<div class="form-row" style="margin-bottom:15px">
<input type="text" id="mid" placeholder="MID (상품번호)">
<input type="text" id="keyword" placeholder="검색 키워드">
<button onclick="addProduct()" id="addBtn">등록하기</button>
</div>
<div class="form-row">
<input type="file" id="excelFile" accept=".xlsx,.xls,.csv" style="padding:8px">
<button onclick="bulkUpload()" id="bulkBtn" class="btn-secondary" style="background:#FF9800;color:#fff">📁 대량등록</button>
<button onclick="downloadSample()" style="background:#6c757d;color:#fff">📥 샘플파일</button>
</div>
<p style="margin-top:10px;font-size:12px;color:#888">* 등록 후 순위가 자동으로 조회됩니다 (개별 로딩)</p>
</div></div>

<div class="selected-info" id="selectedInfo">
<span><strong id="selectedCount">0</strong>개 선택됨</span>
<button class="btn btn-danger" onclick="deleteSelected()">🗑️ 선택 삭제</button>
</div>

<div class="card"><div class="card-header"><h3>📋 내 상품 목록 <span id="productCount" style="color:#667eea"></span></h3>
<div class="btn-group">
<button class="btn btn-success" onclick="exportExcel()">📥 엑셀 다운로드</button>
<button class="btn btn-primary" onclick="refreshAll()" id="refreshBtn">🔄 전체 새로고침</button>
</div></div>
<div class="card-body">
<div id="loading" class="loading"><div class="spinner"></div><p>로딩 중...</p></div>
<div class="table-container" id="tableContainer" style="display:none">
<table><thead><tr>
<th class="checkbox-col"><input type="checkbox" id="selectAll" onchange="toggleSelectAll()"></th>
<th>스토어명</th><th>상품명</th><th>MID</th><th>키워드</th><th>최초순위</th><th>이전순위</th><th>오늘순위</th><th>관리</th></tr></thead>
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
let selectedIds=new Set();

async function loadProducts(){{try{{const r=await fetch('/api/products');const d=await r.json();document.getElementById('loading').style.display='none';
if(d.success&&d.products.length>0){{products=d.products;document.getElementById('tableContainer').style.display='block';document.getElementById('empty').style.display='none';
document.getElementById('productCount').textContent=`(${{d.products.length}}개)`;selectedIds.clear();updateSelectedInfo();renderTable();checkPendingRanks();}}
else{{products=[];document.getElementById('tableContainer').style.display='none';document.getElementById('empty').style.display='block';
document.getElementById('productCount').textContent='(0개)';}}}}catch(e){{document.getElementById('loading').innerHTML='<p style="color:#c00">데이터 로드 실패</p>';}}}}

function renderTable(){{const tbody=document.getElementById('productBody');tbody.innerHTML='';
products.forEach(p=>{{const tr=document.createElement('tr');tr.id='row-'+p.id;
const isChecked=selectedIds.has(p.id)?'checked':'';
let todayHtml=p.current_rank==='-'||p.current_rank==='loading'?'<div class="spinner-small"></div>':formatRank(p.current_rank);
if(p.prev_rank&&p.prev_rank!=='-'&&p.current_rank&&p.current_rank!=='-'&&p.current_rank!=='300위 밖'&&p.current_rank!=='loading'){{
const prev=parseInt(p.prev_rank),curr=parseInt(p.current_rank);if(!isNaN(prev)&&!isNaN(curr)){{const diff=prev-curr;
if(diff>0)todayHtml+=` <span class="rank-down">▲${{diff}}</span>`;else if(diff<0)todayHtml+=` <span class="rank-up">▼${{Math.abs(diff)}}</span>`;}}}}
let firstHtml=p.first_rank==='-'||p.first_rank==='loading'?'<div class="spinner-small"></div>':formatRank(p.first_rank);
tr.innerHTML=`<td class="checkbox-col"><input type="checkbox" ${{isChecked}} onchange="toggleSelect(${{p.id}})"></td>
<td data-label="스토어명">${{p.mall||'-'}}</td><td data-label="상품명" style="text-align:left;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${{p.title||''}}">${{p.title||'-'}}</td>
<td data-label="MID">${{p.mid}}</td><td data-label="키워드">${{p.keyword}}</td><td data-label="최초순위" id="first-${{p.id}}">${{firstHtml}}</td><td data-label="이전순위">${{formatRank(p.prev_rank)}}</td><td data-label="오늘순위" id="rank-${{p.id}}">${{todayHtml}}</td>
<td><button class="btn btn-info" style="padding:4px 8px;font-size:11px" onclick="showHistory(${{p.id}},'${{p.keyword}}')">이력</button>
<button class="btn btn-danger" style="padding:4px 8px;font-size:11px" onclick="deleteProduct(${{p.id}})">삭제</button></td>`;
tbody.appendChild(tr);}});
document.getElementById('selectAll').checked=selectedIds.size===products.length&&products.length>0;}}

function toggleSelect(id){{if(selectedIds.has(id))selectedIds.delete(id);else selectedIds.add(id);updateSelectedInfo();
document.getElementById('selectAll').checked=selectedIds.size===products.length&&products.length>0;}}

function toggleSelectAll(){{const checked=document.getElementById('selectAll').checked;
if(checked)products.forEach(p=>selectedIds.add(p.id));else selectedIds.clear();updateSelectedInfo();renderTable();}}

function updateSelectedInfo(){{const info=document.getElementById('selectedInfo');const count=document.getElementById('selectedCount');
count.textContent=selectedIds.size;if(selectedIds.size>0)info.classList.add('show');else info.classList.remove('show');}}

async function deleteSelected(){{if(selectedIds.size===0)return;if(!confirm(`${{selectedIds.size}}개 상품을 삭제하시겠습니까?`))return;
try{{const r=await fetch('/api/products/bulk-delete',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{ids:Array.from(selectedIds)}})}});
const d=await r.json();if(d.success){{alert(`${{d.deleted}}개 삭제 완료`);selectedIds.clear();loadProducts();}}else alert(d.message);}}catch(e){{alert('서버 연결 실패');}}}}

async function checkPendingRanks(){{for(const p of products){{if(p.current_rank==='-'||p.current_rank==='loading'){{await checkSingleRank(p.id);await new Promise(r=>setTimeout(r,300));}}}}}}

async function checkSingleRank(pid){{try{{const r=await fetch('/api/check-rank/'+pid,{{method:'POST'}});const d=await r.json();
if(d.success){{const p=products.find(x=>x.id===pid);if(p){{p.current_rank=d.rank;p.first_rank=d.first_rank;p.title=d.title||p.title;p.mall=d.mall||p.mall;}}
const rankCell=document.getElementById('rank-'+pid);const firstCell=document.getElementById('first-'+pid);
if(rankCell)rankCell.innerHTML=formatRank(d.rank);if(firstCell)firstCell.innerHTML=formatRank(d.first_rank);
const row=document.getElementById('row-'+pid);if(row){{row.cells[1].textContent=d.mall||'-';row.cells[2].textContent=d.title||'-';row.cells[2].title=d.title||'';}}}}}}catch(e){{console.error(e);}}}}

function formatRank(r){{if(!r||r==='-'||r==='loading')return'-';if(r==='300위 밖')return'<span style="color:#888">300위 밖</span>';return r+'위';}}

async function addProduct(){{const mid=document.getElementById('mid').value.trim(),kw=document.getElementById('keyword').value.trim(),btn=document.getElementById('addBtn');
if(!mid||!kw){{alert('MID와 키워드를 입력해주세요.');return;}}btn.disabled=true;btn.textContent='등록 중...';
try{{const r=await fetch('/api/products/quick',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{mid,keyword:kw}})}});const d=await r.json();
if(d.success){{document.getElementById('mid').value='';document.getElementById('keyword').value='';await loadProducts();}}else alert(d.message);}}
catch(e){{alert('서버 연결 실패');}}finally{{btn.disabled=false;btn.textContent='등록하기';}}}}

async function bulkUpload(){{const fileInput=document.getElementById('excelFile');const btn=document.getElementById('bulkBtn');
if(!fileInput.files[0]){{alert('엑셀 파일을 선택해주세요.');return;}}
const formData=new FormData();formData.append('file',fileInput.files[0]);btn.disabled=true;btn.textContent='업로드 중...';
try{{const r=await fetch('/api/bulk-upload',{{method:'POST',body:formData}});const d=await r.json();
if(d.success){{alert(`${{d.count}}개 상품이 등록되었습니다.\\n순위 조회가 시작됩니다.`);fileInput.value='';await loadProducts();}}else alert(d.message);}}
catch(e){{alert('업로드 실패');}}finally{{btn.disabled=false;btn.textContent='📁 대량등록';}}}}

function downloadSample(){{window.location.href='/api/sample-excel';}}

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
function toggleSidebar(){{const sidebar=document.getElementById('sidebar');const overlay=document.getElementById('sidebarOverlay');sidebar.classList.toggle('open');overlay.classList.toggle('open');}}
</script></body></html>'''


# ===== 상품지수 조회 페이지 =====
@app.route('/product-score')
@login_required
def product_score_page():
    name = session.get('name', '')
    sidebar = get_sidebar_html('product-score')
    return f'''<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>상품지수 조회</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:'Malgun Gothic',sans-serif;background:#f5f7fa;min-height:100vh}}
.layout{{display:flex;min-height:100vh}}.sidebar{{width:250px;background:linear-gradient(180deg,#2c3e50,#1a252f);color:#fff;padding:20px 0;flex-shrink:0;display:flex;flex-direction:column}}
.sidebar-header{{padding:20px;border-bottom:1px solid rgba(255,255,255,.1);margin-bottom:20px}}.sidebar-header h1{{font-size:18px}}.sidebar-header p{{font-size:12px;color:#888}}
.sidebar-menu{{list-style:none}}.sidebar-menu li{{margin:5px 10px}}.sidebar-menu a{{display:flex;align-items:center;padding:12px 15px;color:#ccc;text-decoration:none;border-radius:8px;font-size:14px}}
.sidebar-menu a:hover{{background:rgba(255,255,255,.1);color:#fff}}.sidebar-menu a.active{{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff}}
.sidebar-menu .icon{{margin-right:10px;font-size:18px}}.sidebar-menu .soon{{margin-left:auto;font-size:11px;color:#666}}
.sidebar-footer{{padding:20px;border-top:1px solid rgba(255,255,255,.1)}}.sidebar-footer a{{color:#888;text-decoration:none;font-size:13px}}
.sidebar-contact{{padding:10px;margin-top:auto;border-top:1px solid rgba(255,255,255,.1)}}.contact-btn{{display:flex;align-items:center;padding:8px 15px;margin:5px 10px;background:rgba(255,255,255,.05);border-radius:8px;color:#ccc;text-decoration:none;font-size:12px;transition:all .2s}}.contact-btn:hover{{background:#fee500;color:#000}}.contact-btn img{{width:20px;height:20px;margin-right:8px;border-radius:4px}}
.main{{flex:1;display:flex;flex-direction:column}}.header{{background:#fff;padding:15px 25px;display:flex;justify-content:space-between;align-items:center;box-shadow:0 2px 10px rgba(0,0,0,.05)}}
.header h2{{font-size:18px}}.content{{flex:1;padding:25px;overflow-y:auto}}
.card{{background:#fff;border-radius:12px;box-shadow:0 2px 15px rgba(0,0,0,.05);margin-bottom:20px}}.card-header{{padding:20px;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px}}
.card-header h3{{font-size:16px}}.card-body{{padding:20px}}
.search-box{{display:flex;gap:0;align-items:center}}
.search-box input{{width:250px;padding:10px 12px;border:2px solid #e0e0e0;border-radius:8px 0 0 8px;font-size:14px;border-right:none}}
.search-box input:focus{{outline:none;border-color:#667eea}}
.search-box button{{padding:10px 20px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border:none;border-radius:0 8px 8px 0;font-weight:bold;cursor:pointer;font-size:14px}}
.search-box button:disabled{{background:#ccc;cursor:not-allowed}}
.result-info{{margin:15px 0;font-size:14px;color:#666}}
.score-table{{width:100%;border-collapse:collapse;font-size:12px}}
.score-table th,.score-table td{{padding:8px 6px;text-align:center;border:1px solid #e0e0e0}}
.score-table th{{background:#f8f9fa;font-weight:600;white-space:nowrap;position:sticky;top:0}}
.score-table .product-row{{background:#f0f4ff}}
.score-table .product-row td{{text-align:left;font-size:11px;color:#555}}
.score-table .data-row td{{font-size:12px}}
.score-table .img-cell{{text-align:center;vertical-align:middle}}
.score-table .product-img{{width:50px;height:50px;object-fit:cover;border-radius:4px}}
.score-table .product-title{{max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.score-red{{border:2px solid #dc3545!important;background:#fff5f5}}
.score-yellow{{background:#fff9e6}}
.score-good{{color:#28a745;font-weight:bold}}
.score-bad{{color:#dc3545;font-weight:bold}}
.loading{{text-align:center;padding:60px 20px;color:#666}}
.spinner{{display:inline-block;width:40px;height:40px;border:4px solid #f3f3f3;border-top:4px solid #667eea;border-radius:50%;animation:spin 1s linear infinite}}
@keyframes spin{{0%{{transform:rotate(0deg)}}100%{{transform:rotate(360deg)}}}}
.empty{{text-align:center;padding:60px 20px;color:#888}}.empty-icon{{font-size:50px;margin-bottom:15px}}
.table-scroll{{max-height:70vh;overflow:auto}}
.server-status{{display:inline-flex;align-items:center;gap:5px;padding:5px 10px;border-radius:15px;font-size:12px}}
.server-status.online{{background:#d4edda;color:#155724}}
.server-status.offline{{background:#f8d7da;color:#721c24}}
.menu-toggle{{display:none}}
@media(max-width:768px){{.sidebar{{display:none;position:fixed;top:0;left:0;height:100%;z-index:1000;transform:translateX(-100%);transition:transform .3s}}.sidebar.open{{display:flex;transform:translateX(0)}}
.menu-toggle{{display:block!important;position:fixed;top:15px;left:15px;z-index:999;background:#667eea;color:#fff;border:none;padding:10px 12px;border-radius:8px;font-size:20px;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.2)}}
.sidebar-overlay{{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);z-index:999}}.sidebar-overlay.open{{display:block}}
.header{{padding-left:60px}}.search-box input{{width:100%;border-radius:8px;border-right:2px solid #e0e0e0}}.search-box button{{width:100%;border-radius:8px;margin-top:10px}}.search-box{{flex-wrap:wrap}}}}</style></head>
<body><div class="layout">
{sidebar}
<main class="main">
<header class="header"><h2>📊 상품지수 조회</h2><div style="display:flex;align-items:center;gap:15px"><span id="serverStatus" class="server-status offline">● 서버 확인중</span><span style="font-size:14px;color:#666">👤 {name}님</span></div></header>
<div class="content">
<div class="card"><div class="card-header"><h3>🔍 키워드 검색</h3></div>
<div class="card-body">
<div class="search-box">
<input type="text" id="searchKeyword" placeholder="검색할 키워드를 입력하세요 (예: 물티슈)">
<button onclick="searchProducts()" id="searchBtn">검색</button>
</div>
<p style="margin-top:10px;font-size:12px;color:#888">* 작동하지 않으면 좌측 하단의 채널들 중 한곳으로 문의 주세요.</p>
</div></div>

<div class="card">
<div class="card-header"><h3>📋 검색 결과 <span id="resultCount" style="color:#667eea"></span></h3></div>
<div class="card-body">
<div id="loading" class="loading" style="display:none"><div class="spinner"></div><p>검색 중...</p></div>
<div id="resultArea">
<div class="empty"><div class="empty-icon">🔍</div><p>키워드를 입력하고 검색하세요.<br>상품별 상세 점수를 확인할 수 있습니다.</p></div>
</div>
</div></div>
</div>
</main></div>
<script>
const RANK_API_URL = 'https://bat-loved-independence-attachments.trycloudflare.com';

// 서버 상태 체크
async function checkServer() {{
    const status = document.getElementById('serverStatus');
    try {{
        const r = await fetch(RANK_API_URL + '/health', {{method:'GET',mode:'cors'}});
        if(r.ok) {{
            status.className = 'server-status online';
            status.textContent = '● 서버 연결됨';
            return true;
        }}
    }} catch(e) {{}}
    status.className = 'server-status offline';
    status.textContent = '● 서버 오프라인';
    return false;
}}

async function searchProducts() {{
    const keyword = document.getElementById('searchKeyword').value.trim();
    const btn = document.getElementById('searchBtn');
    const loading = document.getElementById('loading');
    const resultArea = document.getElementById('resultArea');
    const resultCount = document.getElementById('resultCount');
    
    if(!keyword) {{
        alert('검색 키워드를 입력해주세요.');
        return;
    }}
    
    // 서버 체크
    const serverOk = await checkServer();
    if(!serverOk) {{
        alert('로컬 서버에 연결할 수 없습니다.\\n윈도우 서버가 실행 중인지 확인해주세요.');
        return;
    }}
    
    btn.disabled = true;
    btn.textContent = '검색 중...';
    loading.style.display = 'block';
    resultArea.innerHTML = '';
    resultCount.textContent = '';
    
    try {{
        const r = await fetch(RANK_API_URL + '/api/product-score?keyword=' + encodeURIComponent(keyword), {{
            method: 'GET',
            mode: 'cors',
            headers: {{'Accept': 'application/json'}}
        }});
        const d = await r.json();
        
        if(d.result && d.result.products && d.result.products.length > 0) {{
            resultCount.textContent = `(${{d.result.products.length}}개)`;
            renderScoreTable(d.result.products);
        }} else {{
            resultArea.innerHTML = '<div class="empty"><div class="empty-icon">📭</div><p>검색 결과가 없습니다.</p></div>';
        }}
    }} catch(e) {{
        console.error(e);
        resultArea.innerHTML = '<div class="empty" style="color:#c00"><div class="empty-icon">⚠️</div><p>검색 중 오류가 발생했습니다.<br>서버 연결을 확인해주세요.</p></div>';
    }} finally {{
        btn.disabled = false;
        btn.textContent = '검색';
        loading.style.display = 'none';
    }}
}}

function renderScoreTable(products) {{
    const resultArea = document.getElementById('resultArea');
    
    let html = `<div class="table-scroll"><table class="score-table">
    <thead><tr>
        <th rowspan="2">이미지</th>
        <th rowspan="2">순위</th>
        <th rowspan="2">판매처수</th>
        <th rowspan="2">가격</th>
        <th rowspan="2">찜수</th>
        <th rowspan="2">리뷰수</th>
        <th rowspan="2">구매건수</th>
        <th class="score-red">종합점수</th>
        <th>적합도</th>
        <th class="score-yellow">인기도</th>
        <th>클릭점수</th>
        <th>판매점수</th>
        <th>리뷰점수</th>
        <th>최신성</th>
        <th>신뢰성</th>
        <th>패널티등급</th>
    </tr></thead><tbody>`;
    
    products.forEach(p => {{
        // 상품정보 행
        html += `<tr class="product-row">
            <td rowspan="2" class="img-cell"><img src="${{p.imageUrl || ''}}" class="product-img" onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 50 50%22><rect fill=%22%23eee%22 width=%2250%22 height=%2250%22/><text x=%2225%22 y=%2230%22 text-anchor=%22middle%22 fill=%22%23999%22 font-size=%2210%22>No IMG</text></svg>'"></td>
            <td colspan="15" style="text-align:left;padding:10px">
                <div><strong>상품명:</strong> <span class="product-title" title="${{p.productTitle || ''}}">${{p.productTitle || '-'}}</span></div>
                <div style="margin-top:3px"><strong>카테고리:</strong> ${{p.category || '-'}} &nbsp;&nbsp; <strong>판매처명:</strong> ${{p.mallName || '-'}}</div>
            </td>
        </tr>`;
        
        // 데이터 행
        html += `<tr class="data-row">
            <td>${{p.rank || '-'}}</td>
            <td>${{p.mallCount || 0}}</td>
            <td>${{formatNumber(p.lowPrice)}}</td>
            <td>${{formatNumber(p.keepCnt)}}</td>
            <td>${{formatNumber(p.reviewCount)}}</td>
            <td>${{formatNumber(p.purchaseCnt)}}</td>
            <td class="score-red">${{p.relevanceStarScore || 0}}</td>
            <td>${{p.similarityStarScore || 0}}</td>
            <td class="score-yellow">${{p.hitStarScore || 0}}</td>
            <td>${{p.qualityStarScore || 0}}</td>
            <td>${{p.saleStarScore || 0}}</td>
            <td>${{p.reviewCountStarScore || 0}}</td>
            <td>${{p.recentStarScore || 0}}</td>
            <td class="${{p.reliabilityType === 'GOOD' ? 'score-good' : ''}}">${{p.reliabilityType || '-'}}</td>
            <td class="${{p.rankDownScoreType === 'GOOD' ? 'score-good' : (p.rankDownScoreType === 'BAD' ? 'score-bad' : '')}}">${{p.rankDownScoreType || '-'}}</td>
        </tr>`;
    }});
    
    html += '</tbody></table></div>';
    resultArea.innerHTML = html;
}}

function formatNumber(num) {{
    if(num === undefined || num === null) return '-';
    return Number(num).toLocaleString();
}}

// 엔터키 검색
document.getElementById('searchKeyword').addEventListener('keypress', function(e) {{
    if(e.key === 'Enter') searchProducts();
}});

// 페이지 로드시 서버 상태 체크
checkServer();
setInterval(checkServer, 30000); // 30초마다 체크

function toggleSidebar(){{const sidebar=document.getElementById('sidebar');const overlay=document.getElementById('sidebarOverlay');sidebar.classList.toggle('open');overlay.classList.toggle('open');}}
</script></body></html>'''


@app.route('/admin')
def admin_page():
    if not session.get('admin_logged_in'):
        return redirect('/admin/login')
    return '''<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>관리자</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Malgun Gothic',sans-serif;background:#f5f5f5;padding:20px}
.container{max-width:1200px;margin:0 auto;background:#fff;padding:20px;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.1)}
h1{text-align:center;margin-bottom:20px}table{width:100%;border-collapse:collapse}th,td{padding:12px;text-align:center;border-bottom:1px solid #ddd}
th{background:#4a90d9;color:#fff}tr:hover{background:#f9f9f9}.btn{padding:6px 12px;border:none;border-radius:5px;cursor:pointer;font-size:12px}
.btn-approve{background:#28a745;color:#fff}.btn-reject{background:#ffc107}.btn-delete{background:#dc3545;color:#fff}
.refresh-btn{display:block;margin:20px auto;padding:10px 30px;background:#4a90d9;color:#fff;border:none;border-radius:5px;cursor:pointer}
.top-btns{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap;justify-content:center}
.top-btns a,.top-btns button{padding:8px 16px;border-radius:5px;text-decoration:none;font-size:14px;border:none;cursor:pointer}
.back-btn{background:#667eea;color:#fff}.logout-btn{background:#dc3545;color:#fff}
.tabs{display:flex;border-bottom:2px solid #eee;margin-bottom:20px}.tab{padding:12px 24px;cursor:pointer;border:none;background:none;font-size:14px;color:#666}
.tab.active{color:#4a90d9;border-bottom:2px solid #4a90d9;margin-bottom:-2px;font-weight:bold}
.tab-content{display:none}.tab-content.active{display:block}
.search-box{margin-bottom:15px;display:flex;gap:10px;flex-wrap:wrap}.search-box input,.search-box select{padding:8px 12px;border:1px solid #ddd;border-radius:5px}
.search-box input{flex:1;min-width:200px}.product-title{max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left}
.stats{display:flex;gap:20px;margin-bottom:20px;flex-wrap:wrap}.stat-box{background:#f8f9fa;padding:15px 25px;border-radius:8px;text-align:center}
.stat-box .num{font-size:24px;font-weight:bold;color:#4a90d9}.stat-box .label{font-size:12px;color:#666}</style></head>
<body><div class="container">
<div class="top-btns"><a href="/dashboard" class="back-btn">← 대시보드</a><a href="/admin/logout" class="logout-btn">로그아웃</a></div>
<h1>🔐 관리자 페이지</h1>
<div class="stats" id="stats"></div>
<div class="tabs"><button class="tab active" onclick="showTab('users')">👥 회원 관리</button><button class="tab" onclick="showTab('products')">📦 전체 상품</button></div>
<div class="tab-content active" id="tab-users">
<button class="refresh-btn" onclick="loadUsers()">새로고침</button>
<table><thead><tr><th>아이디</th><th>이름</th><th>전화번호</th><th>가입일</th><th>상품수</th><th>승인</th><th>관리</th></tr></thead><tbody id="userTable"></tbody></table>
</div>
<div class="tab-content" id="tab-products">
<div class="search-box"><input type="text" id="searchKeyword" placeholder="키워드 또는 스토어명 검색"><select id="filterUser"><option value="">전체 사용자</option></select>
<button class="btn btn-approve" onclick="loadAllProducts()">검색</button></div>
<table><thead><tr><th>사용자</th><th>스토어명</th><th>상품명</th><th>MID</th><th>키워드</th><th>현재순위</th><th>등록일</th></tr></thead><tbody id="productTable"></tbody></table>
</div></div>
<script>
function showTab(tab){document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
document.querySelector(`.tab-content#tab-${tab}`).classList.add('active');event.target.classList.add('active');if(tab==='products')loadAllProducts();}

async function loadStats(){try{const r=await fetch('/admin/stats');const d=await r.json();if(d.success){
document.getElementById('stats').innerHTML=`<div class="stat-box"><div class="num">${d.totalUsers}</div><div class="label">전체 회원</div></div>
<div class="stat-box"><div class="num">${d.approvedUsers}</div><div class="label">승인 회원</div></div>
<div class="stat-box"><div class="num">${d.totalProducts}</div><div class="label">전체 상품</div></div>
<div class="stat-box"><div class="num">${d.todayProducts}</div><div class="label">오늘 등록</div></div>`;}}catch(e){}}

async function loadUsers(){try{const r=await fetch('/admin/users');const d=await r.json();if(d.success){const tbody=document.getElementById('userTable');tbody.innerHTML='';
const select=document.getElementById('filterUser');select.innerHTML='<option value="">전체 사용자</option>';
d.users.forEach(u=>{select.innerHTML+=`<option value="${u.userId}">${u.userId} (${u.name})</option>`;
const tr=document.createElement('tr');tr.innerHTML=`<td>${u.userId}</td><td>${u.name}</td><td>${u.phone}</td><td>${u.regDate}</td><td>${u.productCount||0}개</td>
<td style="color:${u.approved==='Y'?'#28a745':'#dc3545'};font-weight:bold">${u.approved==='Y'?'승인됨':'대기중'}</td>
<td>${u.approved==='Y'?`<button class="btn btn-reject" onclick="setApproval('${u.userId}','N')">승인취소</button>`:`<button class="btn btn-approve" onclick="setApproval('${u.userId}','Y')">승인</button>`}
<button class="btn btn-delete" onclick="deleteUser('${u.userId}')">삭제</button></td>`;tbody.appendChild(tr);});}}catch(e){alert('로드 실패');}}

async function loadAllProducts(){try{const kw=document.getElementById('searchKeyword').value;const user=document.getElementById('filterUser').value;
const r=await fetch(`/admin/all-products?keyword=${encodeURIComponent(kw)}&user=${encodeURIComponent(user)}`);const d=await r.json();
if(d.success){const tbody=document.getElementById('productTable');tbody.innerHTML='';
d.products.forEach(p=>{const tr=document.createElement('tr');tr.innerHTML=`<td>${p.userId}</td><td>${p.mall||'-'}</td>
<td class="product-title" title="${p.title||''}">${p.title||'-'}</td><td>${p.mid}</td><td>${p.keyword}</td>
<td>${p.currentRank||'-'}</td><td>${p.createdAt||'-'}</td>`;tbody.appendChild(tr);});
if(d.products.length===0)tbody.innerHTML='<tr><td colspan="7">등록된 상품이 없습니다.</td></tr>';}}catch(e){alert('로드 실패');}}

async function setApproval(id,ap){const r=await fetch('/admin/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({userId:id,approved:ap})});const d=await r.json();if(d.success)loadUsers();else alert(d.message);}
async function deleteUser(id){if(!confirm(id+' 회원을 삭제하시겠습니까?'))return;const r=await fetch('/admin/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({userId:id})});const d=await r.json();if(d.success){loadUsers();loadStats();}else alert(d.message);}
document.getElementById('searchKeyword').addEventListener('keypress',e=>{if(e.key==='Enter')loadAllProducts();});
loadStats();loadUsers();
</script></body></html>'''

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
        phone = d.get('phone', '').replace('-', '')
        cur.execute('INSERT INTO users (user_id,password,name,phone,approved) VALUES (%s,%s,%s,%s,%s)', (d.get('userId'), d.get('password'), d.get('name'), phone, 'Y'))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/send-sms', methods=['POST'])
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

@app.route('/api/verify-sms', methods=['POST'])
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

@app.route('/api/products/quick', methods=['POST'])
@login_required
def add_product_quick():
    d = request.json
    mid, kw = d.get('mid'), d.get('keyword')
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT id FROM products WHERE user_id=%s AND mid=%s AND keyword=%s', (session['user_id'], mid, kw))
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': '이미 등록된 상품입니다.'})
        cur.execute('INSERT INTO products (user_id,mid,keyword,title,mall,first_rank,prev_rank,current_rank) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                    (session['user_id'], mid, kw, '', '', '-', '-', '-'))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/products/bulk-delete', methods=['POST'])
@login_required
def bulk_delete_products():
    d = request.json
    ids = d.get('ids', [])
    if not ids:
        return jsonify({'success': False, 'message': '삭제할 항목이 없습니다.'})
    try:
        conn = get_db()
        cur = conn.cursor()
        deleted = 0
        for pid in ids:
            cur.execute('DELETE FROM products WHERE id=%s AND user_id=%s', (pid, session['user_id']))
            deleted += cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'deleted': deleted})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/bulk-upload', methods=['POST'])
@login_required
def bulk_upload():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '파일이 없습니다.'})
    file = request.files['file']
    if not file.filename:
        return jsonify({'success': False, 'message': '파일이 선택되지 않았습니다.'})
    
    try:
        import pandas as pd
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)
        
        conn = get_db()
        cur = conn.cursor()
        count = 0
        
        for _, row in df.iterrows():
            mid = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''
            kw = str(row.iloc[1]).strip() if len(row) > 1 and pd.notna(row.iloc[1]) else ''
            if mid and kw and mid != 'MID' and mid != 'mid':
                cur.execute('SELECT id FROM products WHERE user_id=%s AND mid=%s AND keyword=%s', (session['user_id'], mid, kw))
                if not cur.fetchone():
                    cur.execute('INSERT INTO products (user_id,mid,keyword,title,mall,first_rank,prev_rank,current_rank) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                                (session['user_id'], mid, kw, '', '', '-', '-', '-'))
                    count += 1
        
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/check-rank/<int:pid>', methods=['POST'])
@login_required
def check_single_rank(pid):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT mid,keyword,first_rank FROM products WHERE id=%s AND user_id=%s', (pid, session['user_id']))
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': '상품을 찾을 수 없습니다.'})
        
        mid, kw, first_rank = row
        rank, title, mall = get_naver_rank(kw, mid)
        rank_str = str(rank) if rank else '300위 밖'
        
        if first_rank == '-':
            first_rank = rank_str
        
        cur.execute('UPDATE products SET title=%s,mall=%s,first_rank=%s,current_rank=%s,last_checked=NOW() WHERE id=%s',
                    (title or '', mall or '', first_rank, rank_str, pid))
        cur.execute('INSERT INTO rank_history (product_id,rank) VALUES (%s,%s)', (pid, rank_str))
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({'success': True, 'rank': rank_str, 'first_rank': first_rank, 'title': title or '', 'mall': mall or ''})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/sample-excel')
@login_required
def sample_excel():
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(['MID', '키워드'])
    w.writerow(['11111111111', '검색키워드1'])
    w.writerow(['22222222222', '검색키워드2'])
    w.writerow(['33333333333', '검색키워드3'])
    output.seek(0)
    return Response('\ufeff' + output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=sample_bulk.csv'})

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
        cur.close()
        conn.close()
        
        keyword_products = {}
        for r in rows:
            pid, mid, kw = r
            if kw not in keyword_products:
                keyword_products[kw] = []
            keyword_products[kw].append({'id': pid, 'mid': mid})
        
        updated = 0
        for kw, prods in keyword_products.items():
            results = get_cached_results(kw)
            if not results:
                results = get_naver_search_results(kw)
                if results:
                    save_cache(kw, results)
                time.sleep(0.2)
            
            updated += update_all_products_with_keyword(kw, results)
        
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
        cur.execute('''SELECT u.id, u.user_id, u.name, u.phone, u.reg_date, u.approved,
                      (SELECT COUNT(*) FROM products p WHERE p.user_id = u.user_id) as product_count
                      FROM users u ORDER BY u.id DESC''')
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'users': [{'id': r[0], 'userId': r[1], 'name': r[2], 'phone': r[3], 'regDate': str(r[4]) if r[4] else '', 'approved': r[5], 'productCount': r[6]} for r in rows]})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/admin/stats', methods=['GET'])
def get_admin_stats():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM users')
        total_users = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM users WHERE approved='Y'")
        approved_users = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM products')
        total_products = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM products WHERE DATE(created_at) = CURRENT_DATE")
        today_products = cur.fetchone()[0]
        cur.close()
        conn.close()
        return jsonify({'success': True, 'totalUsers': total_users, 'approvedUsers': approved_users, 'totalProducts': total_products, 'todayProducts': today_products})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/admin/all-products', methods=['GET'])
def get_all_products():
    try:
        keyword = request.args.get('keyword', '')
        user_filter = request.args.get('user', '')
        conn = get_db()
        cur = conn.cursor()
        query = '''SELECT user_id, mall, title, mid, keyword, current_rank, created_at FROM products WHERE 1=1'''
        params = []
        if keyword:
            query += ' AND (keyword ILIKE %s OR mall ILIKE %s OR title ILIKE %s)'
            params.extend([f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'])
        if user_filter:
            query += ' AND user_id = %s'
            params.append(user_filter)
        query += ' ORDER BY created_at DESC LIMIT 500'
        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        products = []
        for r in rows:
            created = r[6].strftime('%Y-%m-%d %H:%M') if r[6] else ''
            products.append({'userId': r[0], 'mall': r[1], 'title': r[2], 'mid': r[3], 'keyword': r[4], 'currentRank': r[5], 'createdAt': created})
        return jsonify({'success': True, 'products': products})
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
