from flask import Blueprint, request, jsonify, session, redirect, render_template
from functools import wraps
import os

from utils.db import get_db, get_user_usage, increment_usage

brand_sales_bp = Blueprint('brand_sales', __name__)

# 로컬 서버 URL
RANK_API_URL = os.environ.get('RANK_API_URL', '')

# 일반 등급 무료 사용 횟수
FREE_LIMIT = 30


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated


@brand_sales_bp.route('/brand-sales')
@login_required
def brand_sales_page():
    return render_template('brand_sales.html', 
                           active_menu='brand-sales', 
                           rank_api_url=RANK_API_URL)


@brand_sales_bp.route('/api/brand-sales/check-usage')
@login_required
def check_brand_sales_usage():
    """매출조회 사용 가능 여부 확인"""
    user_id = session['user_id']
    usage = get_user_usage(user_id)
    
    if not usage:
        return jsonify({'success': False, 'message': '사용자 정보를 찾을 수 없습니다.'})
    
    role = usage['role']
    used = usage['brand_sales_used']
    
    # 고객/관리자는 무제한
    if role in ['customer', 'admin']:
        return jsonify({
            'success': True,
            'canUse': True,
            'role': role,
            'used': used,
            'limit': -1,  # 무제한
            'remaining': -1
        })
    
    # 일반 등급은 30회 제한
    can_use = used < FREE_LIMIT
    remaining = FREE_LIMIT - used
    
    return jsonify({
        'success': True,
        'canUse': can_use,
        'role': role,
        'used': used,
        'limit': FREE_LIMIT,
        'remaining': max(0, remaining)
    })


@brand_sales_bp.route('/api/brand-sales/use', methods=['POST'])
@login_required
def use_brand_sales():
    """매출조회 사용 (횟수 차감)"""
    user_id = session['user_id']
    usage = get_user_usage(user_id)
    
    if not usage:
        return jsonify({'success': False, 'message': '사용자 정보를 찾을 수 없습니다.'})
    
    role = usage['role']
    used = usage['brand_sales_used']
    
    # 고객/관리자는 무제한
    if role in ['customer', 'admin']:
        increment_usage(user_id, 'brand_sales')
        return jsonify({'success': True, 'remaining': -1})
    
    # 일반 등급 횟수 체크
    if used >= FREE_LIMIT:
        return jsonify({
            'success': False, 
            'message': f'무료 사용 횟수({FREE_LIMIT}회)를 모두 사용했습니다. 등급 업그레이드가 필요합니다.'
        })
    
    increment_usage(user_id, 'brand_sales')
    remaining = FREE_LIMIT - used - 1
    
    return jsonify({
        'success': True,
        'remaining': remaining,
        'message': f'남은 횟수: {remaining}회'
    })
