from flask import Blueprint, request, jsonify, session, redirect, render_template

from utils.db import (get_db, reset_user_usage, reset_all_usage,
                      get_pending_withdrawals_count, get_all_withdrawals,
                      update_withdrawal_status, get_user_logs, get_log_stats,
                      get_notices, get_notice, create_notice, update_notice, delete_notice)

admin_bp = Blueprint('admin', __name__)

ADMIN_PASSWORD = "02100210"


@admin_bp.route('/admin')
def admin_page():
    if not session.get('admin_logged_in'):
        return redirect('/admin/login')
    return render_template('admin.html')

@admin_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect('/admin')
        else:
            return render_template('admin_login.html', error=True)
    return render_template('admin_login.html', error=False)

@admin_bp.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect('/admin/login')

@admin_bp.route('/admin/users', methods=['GET'])
def get_users():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''SELECT u.id, u.user_id, u.name, u.phone, u.reg_date, u.approved, u.role,
                      (SELECT COUNT(*) FROM products p WHERE p.user_id = u.user_id) as product_count,
                      u.product_score_used, u.brand_sales_used, u.marketing_agreed, u.coupang_sales_used
                      FROM users u ORDER BY u.id DESC''')
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({
            'success': True,
            'users': [{
                'id': r[0], 'userId': r[1], 'name': r[2], 'phone': r[3],
                'regDate': str(r[4]) if r[4] else '', 'approved': r[5],
                'role': r[6] or 'normal', 'productCount': r[7],
                'productScoreUsed': r[8] or 0, 'brandSalesUsed': r[9] or 0,
                'marketingAgreed': r[10] or False, 'coupangSalesUsed': r[11] or 0
            } for r in rows]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/admin/stats', methods=['GET'])
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
        return jsonify({
            'success': True, 
            'totalUsers': total_users, 
            'approvedUsers': approved_users, 
            'totalProducts': total_products, 
            'todayProducts': today_products
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/admin/all-products', methods=['GET'])
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
            products.append({
                'userId': r[0], 'mall': r[1], 'title': r[2], 'mid': r[3], 
                'keyword': r[4], 'currentRank': r[5], 'createdAt': created
            })
        
        return jsonify({'success': True, 'products': products})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/admin/approve', methods=['POST'])
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

@admin_bp.route('/admin/role', methods=['POST'])
def change_role():
    d = request.json
    user_id = d.get('userId')
    new_role = d.get('role')
    
    if new_role not in ['normal', 'customer', 'admin']:
        return jsonify({'success': False, 'message': '유효하지 않은 등급입니다.'})
    
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('UPDATE users SET role=%s WHERE user_id=%s', (new_role, user_id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/admin/delete', methods=['POST'])
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

@admin_bp.route('/admin/reset-usage', methods=['POST'])
def reset_usage():
    d = request.json
    user_id = d.get('userId')
    if not user_id:
        return jsonify({'success': False, 'message': '사용자 ID가 필요합니다.'})
    try:
        reset_user_usage(user_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/admin/reset-all-usage', methods=['POST'])
def reset_all_usage_route():
    try:
        reset_all_usage()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/admin/withdrawals/pending-count', methods=['GET'])
def get_pending_count():
    try:
        count = get_pending_withdrawals_count()
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/admin/withdrawals', methods=['GET'])
def get_withdrawals():
    try:
        rows = get_all_withdrawals()
        withdrawals = []
        for r in rows:
            withdrawals.append({
                'id': r[0],
                'userId': r[1],
                'userName': r[2] or r[1],
                'amount': r[3],
                'bankName': r[4],
                'accountNumber': r[5],
                'accountHolder': r[6],
                'status': r[7],
                'requestedAt': r[8].strftime('%Y-%m-%d %H:%M') if r[8] else '',
                'processedAt': r[9].strftime('%Y-%m-%d %H:%M') if r[9] else '',
                'memo': r[10] or ''
            })
        return jsonify({'success': True, 'withdrawals': withdrawals})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/admin/withdrawals/process', methods=['POST'])
def process_withdrawal():
    d = request.json
    withdrawal_id = d.get('id')
    status = d.get('status')  # 'approved' or 'rejected'
    memo = d.get('memo', '')

    if status not in ['approved', 'rejected']:
        return jsonify({'success': False, 'message': '유효하지 않은 상태입니다.'})

    try:
        update_withdrawal_status(withdrawal_id, status, memo)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# ===== 사용자 로그 관리 =====

@admin_bp.route('/admin/logs', methods=['GET'])
def get_logs():
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '관리자 권한이 필요합니다.'})

    try:
        limit = request.args.get('limit', 100, type=int)
        user_id = request.args.get('user_id', '')
        action = request.args.get('action', '')

        rows = get_user_logs(limit, user_id or None, action or None)
        logs = []
        for r in rows:
            logs.append({
                'id': r[0],
                'userId': r[1],
                'userName': r[2] or r[1],
                'action': r[3],
                'detail': r[4] or '',
                'ipAddress': r[5] or '',
                'createdAt': r[6].strftime('%Y-%m-%d %H:%M:%S') if r[6] else ''
            })
        return jsonify({'success': True, 'logs': logs})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@admin_bp.route('/admin/logs/stats', methods=['GET'])
def get_logs_stats():
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '관리자 권한이 필요합니다.'})

    try:
        stats = get_log_stats()
        return jsonify({
            'success': True,
            'todayLogins': stats['today_logins'],
            'todayActions': [{'action': a[0], 'count': a[1]} for a in stats['today_actions']]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# ===== 공지사항 관리 =====

@admin_bp.route('/admin/notices', methods=['GET'])
def get_notices_list():
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '관리자 권한이 필요합니다.'})

    try:
        rows = get_notices()
        notices = []
        for r in rows:
            notices.append({
                'id': r[0],
                'title': r[1],
                'content': r[2] or '',
                'isPopup': r[3],
                'isActive': r[4],
                'createdAt': r[5].strftime('%Y-%m-%d %H:%M') if r[5] else ''
            })
        return jsonify({'success': True, 'notices': notices})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@admin_bp.route('/admin/notices', methods=['POST'])
def create_notice_api():
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '관리자 권한이 필요합니다.'})

    d = request.json
    title = d.get('title', '').strip()
    content = d.get('content', '').strip()
    is_popup = d.get('isPopup', False)

    if not title:
        return jsonify({'success': False, 'message': '제목을 입력해주세요.'})

    try:
        notice_id = create_notice(title, content, is_popup)
        return jsonify({'success': True, 'id': notice_id})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@admin_bp.route('/admin/notices/<int:notice_id>', methods=['PUT'])
def update_notice_api(notice_id):
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '관리자 권한이 필요합니다.'})

    d = request.json
    title = d.get('title', '').strip()
    content = d.get('content', '').strip()
    is_popup = d.get('isPopup', False)
    is_active = d.get('isActive', True)

    if not title:
        return jsonify({'success': False, 'message': '제목을 입력해주세요.'})

    try:
        update_notice(notice_id, title, content, is_popup, is_active)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@admin_bp.route('/admin/notices/<int:notice_id>', methods=['DELETE'])
def delete_notice_api(notice_id):
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '관리자 권한이 필요합니다.'})

    try:
        delete_notice(notice_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# ===== 사용자용 공지사항 API (로그인 필요 없음) =====

@admin_bp.route('/api/notices/popup', methods=['GET'])
def get_popup_notices_api():
    """팝업 공지사항 조회 (사용자용)"""
    from utils.db import get_popup_notices
    try:
        rows = get_popup_notices()
        notices = [{'id': r[0], 'title': r[1], 'content': r[2]} for r in rows]
        return jsonify({'success': True, 'notices': notices})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@admin_bp.route('/api/notices', methods=['GET'])
def get_active_notices_api():
    """활성화된 공지사항 목록 (사용자용)"""
    try:
        rows = get_notices(active_only=True)
        notices = []
        for r in rows:
            notices.append({
                'id': r[0],
                'title': r[1],
                'content': r[2] or '',
                'createdAt': r[5].strftime('%Y-%m-%d') if r[5] else ''
            })
        return jsonify({'success': True, 'notices': notices})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
