from flask import Blueprint, request, jsonify, session, redirect, render_template

from utils.db import get_db

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
                      (SELECT COUNT(*) FROM products p WHERE p.user_id = u.user_id) as product_count
                      FROM users u ORDER BY u.id DESC''')
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({
            'success': True, 
            'users': [{'id': r[0], 'userId': r[1], 'name': r[2], 'phone': r[3], 'regDate': str(r[4]) if r[4] else '', 'approved': r[5], 'role': r[6] or 'normal', 'productCount': r[7]} for r in rows]
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
