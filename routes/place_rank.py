from flask import Blueprint, request, jsonify, session, redirect, render_template, Response
from functools import wraps
from datetime import datetime
import pytz
import csv
import io

from utils.db import get_db

place_rank_bp = Blueprint('place_rank', __name__)
KST = pytz.timezone('Asia/Seoul')

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        if not request.path.startswith('/api/') and not session.get('terms_agreed'):
            return redirect('/terms')
        return f(*args, **kwargs)
    return decorated


# ===== Pages =====

@place_rank_bp.route('/place-rank')
@login_required
def place_rank_page():
    return render_template('place_rank.html', active_menu='place-rank')


# ===== API =====

@place_rank_bp.route('/api/place-rank/places', methods=['GET'])
@login_required
def get_places():
    """등록된 플레이스 목록 조회"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            SELECT id, place_id, keyword, title, first_rank, prev_rank, current_rank 
            FROM place_ranks 
            WHERE user_id=%s 
            ORDER BY id DESC
        ''', (session['user_id'],))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        places = []
        for r in rows:
            places.append({
                'id': r[0],
                'place_id': r[1],
                'keyword': r[2],
                'title': r[3] or '',
                'first_rank': r[4] or '-',
                'prev_rank': r[5] or '-',
                'current_rank': r[6] or '-'
            })
        
        return jsonify({'success': True, 'places': places})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@place_rank_bp.route('/api/place-rank/places', methods=['POST'])
@login_required
def add_place():
    """플레이스 등록"""
    d = request.json
    keyword = d.get('keyword', '').strip()
    place_id = d.get('place_id', '').strip()
    title = d.get('title', '').strip()
    
    if not keyword or not place_id:
        return jsonify({'success': False, 'message': '키워드와 플레이스 ID를 입력해주세요.'})
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # 중복 체크
        cur.execute('''
            SELECT id FROM place_ranks 
            WHERE user_id=%s AND place_id=%s AND keyword=%s
        ''', (session['user_id'], place_id, keyword))
        
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': '이미 등록된 플레이스입니다.'})
        
        # 등록 (업체명 포함)
        cur.execute('''
            INSERT INTO place_ranks (user_id, place_id, keyword, title, first_rank, prev_rank, current_rank)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (session['user_id'], place_id, keyword, title, '-', '-', '-'))
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@place_rank_bp.route('/api/place-rank/places/<int:pid>', methods=['DELETE'])
@login_required
def delete_place(pid):
    """플레이스 삭제"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('DELETE FROM place_ranks WHERE id=%s AND user_id=%s', (pid, session['user_id']))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@place_rank_bp.route('/api/place-rank/bulk-delete', methods=['POST'])
@login_required
def bulk_delete_places():
    """플레이스 대량 삭제"""
    d = request.json
    ids = d.get('ids', [])
    if not ids:
        return jsonify({'success': False, 'message': '삭제할 항목이 없습니다.'})
    
    try:
        conn = get_db()
        cur = conn.cursor()
        deleted = 0
        for pid in ids:
            cur.execute('DELETE FROM place_ranks WHERE id=%s AND user_id=%s', (pid, session['user_id']))
            deleted += cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'deleted': deleted})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@place_rank_bp.route('/api/place-rank/check/<int:pid>', methods=['POST'])
@login_required
def check_single_rank(pid):
    """단일 플레이스 순위 조회"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            SELECT place_id, keyword, first_rank, title 
            FROM place_ranks 
            WHERE id=%s AND user_id=%s
        ''', (pid, session['user_id']))
        row = cur.fetchone()
        
        if not row:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': '플레이스를 찾을 수 없습니다.'})
        
        place_id, keyword, first_rank, existing_title = row
        
        # 순위 체크 로직 (Python 스크립트 호출)
        from utils.naver_place import check_place_rank
        rank, title = check_place_rank(keyword, place_id, max_results=200)
        
        rank_str = str(rank) if rank else '200위 밖'
        
        # 최초 순위 설정
        if first_rank == '-':
            first_rank = rank_str
        
        # 업체명: 기존 값이 있으면 유지, 없으면 새로 가져온 값 사용
        final_title = existing_title if existing_title else (title or '')
        
        # DB 업데이트
        cur.execute('''
            UPDATE place_ranks 
            SET title=%s, first_rank=%s, current_rank=%s, last_checked=NOW()
            WHERE id=%s
        ''', (final_title, first_rank, rank_str, pid))
        
        # 이력 저장
        cur.execute('''
            INSERT INTO place_rank_history (place_rank_id, rank)
            VALUES (%s, %s)
        ''', (pid, rank_str))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'rank': rank_str,
            'first_rank': first_rank,
            'title': title or ''
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@place_rank_bp.route('/api/place-rank/refresh', methods=['POST'])
@login_required
def refresh_ranks():
    """전체 플레이스 순위 새로고침"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            SELECT id, place_id, keyword
            FROM place_ranks
            WHERE user_id=%s
        ''', (session['user_id'],))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        from utils.naver_place import check_place_rank
        updated = 0
        
        for pid, place_id, keyword in rows:
            try:
                rank, title = check_place_rank(keyword, place_id, max_results=200)
                rank_str = str(rank) if rank else '200위 밖'
                
                conn = get_db()
                cur = conn.cursor()
                
                # 현재 순위 및 기존 업체명 가져오기
                cur.execute('SELECT first_rank, current_rank, title FROM place_ranks WHERE id=%s', (pid,))
                first_rank, prev_rank, existing_title = cur.fetchone()
                
                # 최초 순위 설정
                if first_rank == '-':
                    first_rank = rank_str
                
                # 업체명: 기존 값이 있으면 유지, 없으면 새로 가져온 값 사용
                final_title = existing_title if existing_title else (title or '')
                
                # 업데이트
                cur.execute('''
                    UPDATE place_ranks
                    SET title=%s, first_rank=%s, prev_rank=%s, current_rank=%s, last_checked=NOW()
                    WHERE id=%s
                ''', (final_title, first_rank, prev_rank, rank_str, pid))
                
                # 이력 저장
                cur.execute('''
                    INSERT INTO place_rank_history (place_rank_id, rank)
                    VALUES (%s, %s)
                ''', (pid, rank_str))
                
                conn.commit()
                cur.close()
                conn.close()
                
                updated += 1
            except Exception as e:
                print(f"Error checking place {pid}: {e}")
                continue
        
        return jsonify({'success': True, 'updated': updated})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@place_rank_bp.route('/api/place-rank/history/<int:pid>', methods=['GET'])
@login_required
def get_history(pid):
    """순위 변동 이력 조회"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            SELECT rank, checked_at 
            FROM place_rank_history 
            WHERE place_rank_id=%s 
            ORDER BY checked_at DESC 
            LIMIT 50
        ''', (pid,))
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


@place_rank_bp.route('/api/place-rank/bulk-upload', methods=['POST'])
@login_required
def bulk_upload():
    """대량 등록"""
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
            keyword = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''
            place_id = str(row.iloc[1]).strip() if len(row) > 1 and pd.notna(row.iloc[1]) else ''
            title = str(row.iloc[2]).strip() if len(row) > 2 and pd.notna(row.iloc[2]) else ''
            
            if keyword and place_id and keyword != '키워드':
                cur.execute('''
                    SELECT id FROM place_ranks 
                    WHERE user_id=%s AND place_id=%s AND keyword=%s
                ''', (session['user_id'], place_id, keyword))
                
                if not cur.fetchone():
                    cur.execute('''
                        INSERT INTO place_ranks (user_id, place_id, keyword, title, first_rank, prev_rank, current_rank)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ''', (session['user_id'], place_id, keyword, title, '-', '-', '-'))
                    count += 1
        
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@place_rank_bp.route('/api/place-rank/sample-excel')
@login_required
def sample_excel():
    """샘플 엑셀 다운로드"""
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(['키워드', '플레이스ID', '업체명'])
    w.writerow(['강남역 카페', '12948226', '스타벅스 강남역점'])
    w.writerow(['홍대 맛집', '37420517', '홍대 맛집'])
    w.writerow(['신촌 치킨', '11111111', '치킨집'])
    output.seek(0)
    return Response('\ufeff' + output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=place_rank_sample.csv'})


@place_rank_bp.route('/api/place-rank/export')
@login_required
def export_excel():
    """엑셀 내보내기"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            SELECT title, place_id, keyword, first_rank, prev_rank, current_rank
            FROM place_ranks
            WHERE user_id=%s
            ORDER BY id DESC
        ''', (session['user_id'],))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        output = io.StringIO()
        w = csv.writer(output)
        w.writerow(['업체명', '플레이스ID', '키워드', '최초순위', '이전순위', '현재순위'])
        for r in rows:
            w.writerow([
                r[0] or '',
                r[1],
                r[2],
                r[3] or '-',
                r[4] or '-',
                r[5] or '-'
            ])
        output.seek(0)
        
        now = datetime.now(KST).strftime('%Y%m%d_%H%M')
        return Response('\ufeff' + output.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename=place_rank_{now}.csv'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
