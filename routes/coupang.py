from flask import Blueprint, request, jsonify, session, redirect, render_template
from functools import wraps
import os
import requests

from utils.db import get_db, get_user_usage, increment_usage, add_user_log

coupang_bp = Blueprint('coupang', __name__)

# 로컬 쿠팡 API 서버 URL
COUPANG_API_URL = os.environ.get('COUPANG_API_URL', '')

# 쿠팡 매출조회 무료 횟수 (하루 1회)
COUPANG_SALES_FREE_LIMIT = 1


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated


# ===== 페이지 =====

@coupang_bp.route('/coupang-rank')
@login_required
def coupang_rank_page():
    return render_template('coupang_rank.html',
                           active_menu='coupang-rank',
                           coupang_api_url=COUPANG_API_URL)


@coupang_bp.route('/coupang-sales')
@login_required
def coupang_sales_page():
    return render_template('coupang_sales.html',
                           active_menu='coupang-sales',
                           coupang_api_url=COUPANG_API_URL)


# ===== API: 순위검색 (무료 무제한) =====

@coupang_bp.route('/api/coupang/search')
@login_required
def coupang_search():
    """쿠팡 키워드 순위 검색 (무료)"""
    keyword = request.args.get('keyword', '')
    if not keyword:
        return jsonify({'success': False, 'message': '키워드를 입력해주세요.'})

    if not COUPANG_API_URL:
        return jsonify({'success': False, 'message': '쿠팡 API가 설정되지 않았습니다.'})

    try:
        resp = requests.get(
            f"{COUPANG_API_URL}/api/coupang/search",
            params={'keyword': keyword},
            timeout=30
        )
        data = resp.json()

        # 로그 기록
        user_id = session['user_id']
        add_user_log(user_id, 'coupang_search', f'키워드: {keyword[:50]}')

        return jsonify(data)
    except requests.exceptions.RequestException as e:
        return jsonify({'success': False, 'message': f'API 연결 실패: {str(e)}'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# ===== API: 매출조회 (하루 1회) =====

@coupang_bp.route('/api/coupang/sales/check-usage')
@login_required
def check_coupang_sales_usage():
    """쿠팡 매출조회 사용 가능 여부 확인"""
    user_id = session['user_id']
    usage = get_user_usage(user_id)

    if not usage:
        return jsonify({'success': False, 'message': '사용자 정보를 찾을 수 없습니다.'})

    role = usage['role']
    used = usage.get('coupang_sales_used', 0)

    # 고객/관리자는 무제한
    if role in ['customer', 'admin']:
        return jsonify({
            'success': True,
            'canUse': True,
            'role': role,
            'used': used,
            'limit': -1,
            'remaining': -1
        })

    # 일반 등급: 하루 1회
    can_use = used < COUPANG_SALES_FREE_LIMIT
    remaining = COUPANG_SALES_FREE_LIMIT - used

    return jsonify({
        'success': True,
        'canUse': can_use,
        'role': role,
        'used': used,
        'limit': COUPANG_SALES_FREE_LIMIT,
        'remaining': max(0, remaining)
    })


@coupang_bp.route('/api/coupang/product/<product_id>')
@login_required
def coupang_product_sales(product_id):
    """쿠팡 특정 상품 매출 조회 (하루 1회 제한)"""
    user_id = session['user_id']
    usage = get_user_usage(user_id)

    if not usage:
        return jsonify({'success': False, 'message': '사용자 정보를 찾을 수 없습니다.'})

    role = usage['role']
    used = usage.get('coupang_sales_used', 0)

    # 일반 등급은 하루 1회 제한
    if role not in ['customer', 'admin']:
        if used >= COUPANG_SALES_FREE_LIMIT:
            return jsonify({
                'success': False,
                'message': f'무료 사용 횟수({COUPANG_SALES_FREE_LIMIT}회/일)를 모두 사용했습니다.'
            })

    if not COUPANG_API_URL:
        return jsonify({'success': False, 'message': '쿠팡 API가 설정되지 않았습니다.'})

    try:
        resp = requests.get(
            f"{COUPANG_API_URL}/api/coupang/product/{product_id}",
            timeout=30
        )
        data = resp.json()

        # 성공 시 사용량 증가
        if data.get('success', False):
            increment_usage(user_id, 'coupang_sales')
            add_user_log(user_id, 'coupang_sales', f'상품ID: {product_id}')

        return jsonify(data)
    except requests.exceptions.RequestException as e:
        return jsonify({'success': False, 'message': f'API 연결 실패: {str(e)}'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# ===== API: 상태 확인 =====

@coupang_bp.route('/api/coupang/health')
@login_required
def coupang_health():
    """쿠팡 API 서버 상태 확인"""
    if not COUPANG_API_URL:
        return jsonify({'success': False, 'status': 'not_configured'})

    try:
        resp = requests.get(f"{COUPANG_API_URL}/health", timeout=5)
        if resp.status_code == 200:
            return jsonify({'success': True, 'status': 'online'})
        else:
            return jsonify({'success': False, 'status': 'error'})
    except:
        return jsonify({'success': False, 'status': 'offline'})
