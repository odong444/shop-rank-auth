from flask import Blueprint, session, redirect, render_template, jsonify, request
from functools import wraps
import os
import requests

from utils.db import get_db, get_user_usage, increment_usage, add_user_log
from utils.naver_api import get_naver_search_results, get_product_indices_from_local

product_score_bp = Blueprint('product_score', __name__)

# 로컬 서버 URL
RANK_API_URL = os.environ.get('RANK_API_URL', '')


def get_product_index(mids):
    """
    로컬 서버에서 상품지수 조회 (bulk)

    Args:
        mids: MID 목록 (리스트)

    Returns:
        상품지수 데이터 또는 None
    """
    if not RANK_API_URL or not mids:
        return None

    try:
        response = requests.post(
            f"{RANK_API_URL}/api/product-index/bulk",
            json={"mids": mids},
            timeout=60
        )
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Product index error: {e}")
    return None

# 일반 등급 무료 사용 횟수
FREE_LIMIT_MARKETING = 30  # 마케팅 동의
FREE_LIMIT_DEFAULT = 3     # 마케팅 미동의


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated


@product_score_bp.route('/product-score')
@login_required
def product_score_page():
    return render_template('product_score.html', 
                           active_menu='product-score',
                           rank_api_url=RANK_API_URL)


@product_score_bp.route('/api/product-score/check-usage')
@login_required
def check_product_score_usage():
    """상품지수 사용 가능 여부 확인"""
    user_id = session['user_id']
    usage = get_user_usage(user_id)

    if not usage:
        return jsonify({'success': False, 'message': '사용자 정보를 찾을 수 없습니다.'})

    role = usage['role']
    used = usage['product_score_used']
    marketing_agreed = usage.get('marketing_agreed', False)

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

    # 일반 등급: 마케팅 동의 여부에 따라 제한
    free_limit = FREE_LIMIT_MARKETING if marketing_agreed else FREE_LIMIT_DEFAULT
    can_use = used < free_limit
    remaining = free_limit - used

    return jsonify({
        'success': True,
        'canUse': can_use,
        'role': role,
        'used': used,
        'limit': free_limit,
        'remaining': max(0, remaining)
    })


@product_score_bp.route('/api/product-score/use', methods=['POST'])
@login_required
def use_product_score():
    """상품지수 사용 (횟수 차감)"""
    user_id = session['user_id']
    usage = get_user_usage(user_id)

    if not usage:
        return jsonify({'success': False, 'message': '사용자 정보를 찾을 수 없습니다.'})

    role = usage['role']
    used = usage['product_score_used']
    marketing_agreed = usage.get('marketing_agreed', False)

    # 고객/관리자는 무제한
    if role in ['customer', 'admin']:
        increment_usage(user_id, 'product_score')
        add_user_log(user_id, 'product_score', f'사용 (무제한)')
        return jsonify({'success': True, 'remaining': -1})

    # 일반 등급: 마케팅 동의 여부에 따라 제한
    free_limit = FREE_LIMIT_MARKETING if marketing_agreed else FREE_LIMIT_DEFAULT

    if used >= free_limit:
        return jsonify({
            'success': False,
            'message': f'무료 사용 횟수({free_limit}회)를 모두 사용했습니다. 등급 업그레이드가 필요합니다.'
        })

    increment_usage(user_id, 'product_score')
    remaining = free_limit - used - 1
    add_user_log(user_id, 'product_score', f'사용 ({used + 1}/{free_limit})')

    return jsonify({
        'success': True,
        'remaining': remaining,
        'message': f'남은 횟수: {remaining}회'
    })


@product_score_bp.route('/api/product-score/search', methods=['GET'])
@login_required
def search_product_index():
    """키워드로 상품 검색 + 상품지수 조회"""
    keyword = request.args.get('keyword')
    if not keyword:
        return jsonify({'success': False, 'message': '키워드를 입력해주세요.'})

    # 1. 네이버 API로 상품 목록 조회 (MID 포함)
    products = get_naver_search_results(keyword)
    if not products:
        return jsonify({'success': False, 'message': '검색 결과가 없습니다.'})

    # 2. MID 목록 추출 (상위 50개만)
    mids = [p['mid'] for p in products[:50]]

    # 3. 로컬 서버에서 상품지수 조회
    indices = get_product_indices_from_local(mids)

    # 4. 결과 병합
    results = []
    for p in products[:50]:
        mid = p['mid']
        item = {
            'rank': p['rank'],
            'mid': mid,
        }

        # 상품지수 데이터 병합 (로컬 서버에서 온 모든 필드)
        if indices and mid in indices:
            idx = indices[mid]
            item.update(idx)

        results.append(item)

    return jsonify({
        'success': True,
        'keyword': keyword,
        'total': len(results),
        'products': results
    })
