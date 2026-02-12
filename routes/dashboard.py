from flask import Blueprint, request, jsonify, session, redirect, render_template, Response
from functools import wraps
from datetime import datetime
import pytz
import time
import csv
import io
import os

from utils.db import get_db
from utils.naver_api import get_naver_rank, get_naver_search_results, get_cached_results, save_cache, update_all_products_with_keyword

dashboard_bp = Blueprint('dashboard', __name__)
KST = pytz.timezone('Asia/Seoul')

# 로컬 서버 URL
RANK_API_URL = os.environ.get('RANK_API_URL', '')

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        # 약관 동의 체크 (API가 아닌 페이지 요청에만 적용)
        if not request.path.startswith('/api/') and not session.get('terms_agreed'):
            return redirect('/terms')
        return f(*args, **kwargs)
    return decorated


# ===== Pages =====

@dashboard_bp.route('/naver-shop')
@login_required
def naver_shop_page():
    return render_template('dashboard.html', active_menu='naver-shop', rank_api_url=RANK_API_URL)

@dashboard_bp.route('/dashboard')
@login_required
def dashboard_page():
    # 기존 URL 호환성 - naver-shop으로 리다이렉트
    return redirect('/naver-shop')


# ===== API =====

@dashboard_bp.route('/api/products', methods=['GET'])
@login_required
def get_products():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT id,mid,keyword,title,mall,first_rank,prev_rank,current_rank FROM products WHERE user_id=%s ORDER BY id DESC', (session['user_id'],))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({
            'success': True, 
            'products': [{'id': r[0], 'mid': r[1], 'keyword': r[2], 'title': r[3], 'mall': r[4], 'first_rank': r[5], 'prev_rank': r[6], 'current_rank': r[7]} for r in rows]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@dashboard_bp.route('/api/products', methods=['POST'])
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

@dashboard_bp.route('/api/products/quick', methods=['POST'])
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

@dashboard_bp.route('/api/products/bulk-delete', methods=['POST'])
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

@dashboard_bp.route('/api/bulk-upload', methods=['POST'])
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

@dashboard_bp.route('/api/check-rank/<int:pid>', methods=['POST'])
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

@dashboard_bp.route('/api/sample-excel')
@login_required
def sample_excel():
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(['MID', '키워드'])
    w.writerow(['11111111111', '검색키워드1'])
    w.writerow(['22222222222', '검색키워드2'])
    w.writerow(['33333333333', '검색키워드3'])
    output.seek(0)
    return Response('\ufeff' + output.getvalue(), mimetype='text/csv', 
                    headers={'Content-Disposition': 'attachment; filename=sample_bulk.csv'})

@dashboard_bp.route('/api/products/<int:pid>', methods=['DELETE'])
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

@dashboard_bp.route('/api/history/<int:pid>', methods=['GET'])
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

@dashboard_bp.route('/api/refresh', methods=['POST'])
@login_required
def refresh_ranks():
    try:
        import concurrent.futures
        
        start_time = time.time()
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT id,mid,keyword FROM products WHERE user_id=%s', (session['user_id'],))
        rows = cur.fetchall()
        total_count = len(rows)
        cur.close()
        conn.close()
        
        db_time = time.time() - start_time
        print(f"[Refresh] DB query: {db_time:.2f}s")
        
        keyword_products = {}
        for r in rows:
            pid, mid, kw = r
            if kw not in keyword_products:
                keyword_products[kw] = []
            keyword_products[kw].append({'id': pid, 'mid': mid})
        
        print(f"[Refresh] Total keywords: {len(keyword_products)}, products: {total_count}")
        
        # 병렬 처리 함수
        def process_keyword(kw):
            kw_start = time.time()
            
            results = get_cached_results(kw)
            cache_hit = results is not None
            
            if not results:
                api_start = time.time()
                results = get_naver_search_results(kw)
                api_time = time.time() - api_start
                print(f"[Refresh] '{kw}': API call {api_time:.2f}s")
                
                if results:
                    save_cache(kw, results)
            else:
                print(f"[Refresh] '{kw}': Cache hit")
            
            update_start = time.time()
            count = update_all_products_with_keyword(kw, results, user_id=session['user_id'])
            update_time = time.time() - update_start
            
            kw_total = time.time() - kw_start
            print(f"[Refresh] '{kw}': update {update_time:.2f}s, total {kw_total:.2f}s (cache: {cache_hit})")
            
            return count
        
        # 키워드 리스트
        keywords = list(keyword_products.keys())
        updated = 0
        
        # 병렬 처리 (5개씩 배치)
        batch_size = 5
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
            for i in range(0, len(keywords), batch_size):
                batch = keywords[i:i + batch_size]
                print(f"[Refresh] Processing batch {i//batch_size + 1}/{(len(keywords) + batch_size - 1)//batch_size}: {batch}")
                
                futures = {executor.submit(process_keyword, kw): kw for kw in batch}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        count = future.result()
                        updated += count
                    except Exception as e:
                        kw = futures[future]
                        print(f"[Refresh Error] Keyword '{kw}': {e}")
                
                # 배치 간 딜레이 (마지막 배치 제외)
                if i + batch_size < len(keywords):
                    time.sleep(0.3)
        
        total_time = time.time() - start_time
        print(f"[Refresh] DONE: {updated} products in {total_time:.2f}s")
        
        return jsonify({'success': True, 'updated': updated, 'total': total_count, 'time': f'{total_time:.2f}s'})
    except Exception as e:
        import traceback
        print(f"[Refresh Error] {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)})

@dashboard_bp.route('/api/export')
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
        return Response('\ufeff' + output.getvalue(), mimetype='text/csv', 
                        headers={'Content-Disposition': f'attachment; filename=rank_{now}.csv'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
