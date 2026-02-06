"""
키워드 분석 보고서 API
- 메인 키워드 분석
- 서브키워드 추출 및 분석
- AI 전략 제안
"""
from flask import Blueprint, request, jsonify, session, redirect, render_template
from functools import wraps
import requests
import hashlib
import hmac
import base64
import time
import os
import json

from utils.claude_api import analyze_sub_keywords, generate_report_summary

keyword_report_bp = Blueprint('keyword_report', __name__)

# ========== API 설정 ==========
CUSTOMER_ID = os.environ.get('NAVER_AD_CUSTOMER_ID', '2453515')
AD_API_KEY = os.environ.get('NAVER_AD_API_KEY', '01000000006162454519ef4e8d97852a2ad5eb9b397beef455f126cace2f790f5c6b7bccff')
AD_SECRET_KEY = os.environ.get('NAVER_AD_SECRET_KEY', 'AQAAAABhYkVFGe9OjZeFKirV65s5Ke25zkTefku4HBEbYMqJ+Q==')
AD_BASE_URL = 'https://api.naver.com'

NAVER_CLIENT_ID = os.environ.get('NAVER_CLIENT_ID', 'UrlniCJoGZ_jfgk5tlkN')
NAVER_CLIENT_SECRET = os.environ.get('NAVER_CLIENT_SECRET', 'x3z9b1CM2F')

# 로컬 API 서버 (매출 조회용)
RANK_API_URL = os.environ.get('RANK_API_URL', 'https://api.bw-rank.kr')


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated


# ========== 네이버 광고 API ==========
def generate_signature(timestamp, method, uri):
    message = f"{timestamp}.{method}.{uri}"
    signature = hmac.new(
        AD_SECRET_KEY.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).digest()
    return base64.b64encode(signature).decode('utf-8')


def get_ad_header(method, uri):
    timestamp = str(int(time.time() * 1000))
    signature = generate_signature(timestamp, method, uri)
    return {
        'Content-Type': 'application/json; charset=UTF-8',
        'X-Timestamp': timestamp,
        'X-API-KEY': AD_API_KEY,
        'X-Customer': CUSTOMER_ID,
        'X-Signature': signature
    }


def get_keyword_stats(keyword):
    """네이버 광고 API - 키워드 검색량 조회"""
    uri = '/keywordstool'
    method = 'GET'
    params = {'hintKeywords': keyword, 'showDetail': '1'}
    headers = get_ad_header(method, uri)
    try:
        response = requests.get(AD_BASE_URL + uri, headers=headers, params=params, timeout=10)
        print(f"[Keyword API] status={response.status_code}, keyword={keyword}")
        if response.status_code == 200:
            return response.json()
        else:
            print(f"[Keyword API] Error response: {response.text[:200]}")
    except requests.exceptions.Timeout:
        print(f"[Keyword API] Timeout for keyword: {keyword}")
    except Exception as e:
        print(f"[Keyword API] Exception: {e}")
    return None


# ========== 네이버 검색 API ==========
def get_content_counts(keyword):
    """블로그, 카페, 쇼핑 콘텐츠 수 조회"""
    results = {}
    for search_type, api_type in [('blog', 'blog'), ('cafe', 'cafearticle'), ('shop', 'shop')]:
        url = f"https://openapi.naver.com/v1/search/{api_type}.json"
        headers = {
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
        }
        try:
            response = requests.get(url, headers=headers, params={"query": keyword, "display": 1}, timeout=10)
            if response.status_code == 200:
                results[search_type] = response.json().get('total', 0)
            else:
                results[search_type] = 0
        except:
            results[search_type] = 0
    return results


def get_shopping_top_products(keyword, count=10):
    """쇼핑 상위 상품 조회"""
    url = "https://openapi.naver.com/v1/search/shop.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    params = {"query": keyword, "display": count, "sort": "sim"}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            products = []
            for idx, item in enumerate(data.get('items', []), 1):
                products.append({
                    'rank': idx,
                    'title': item.get('title', '').replace('<b>', '').replace('</b>', ''),
                    'mall': item.get('mallName', ''),
                    'price': int(item.get('lprice', '0')),
                    'link': item.get('link', '')
                })
            return products
    except Exception as e:
        print(f"Shopping search error: {e}")
    return []


# ========== 로컬 API 서버 호출 ==========
def extract_store_url(product_link):
    """상품 링크에서 스토어 URL 추출 (리다이렉트 따라감)"""
    import re

    # 이미 스토어 URL 형태인 경우
    match = re.search(r'(https?://smartstore\.naver\.com/[^/\?]+)', product_link)
    if match:
        return match.group(1)
    match = re.search(r'(https?://brand\.naver\.com/[^/\?]+)', product_link)
    if match:
        return match.group(1)

    # 리다이렉트 URL인 경우 따라가서 실제 URL 얻기
    try:
        response = requests.head(product_link, allow_redirects=True, timeout=5)
        final_url = response.url

        match = re.search(r'(https?://smartstore\.naver\.com/[^/\?]+)', final_url)
        if match:
            return match.group(1)
        match = re.search(r'(https?://brand\.naver\.com/[^/\?]+)', final_url)
        if match:
            return match.group(1)
    except Exception as e:
        print(f"[Extract URL] Error following redirect: {e}")

    return None


def get_brand_sales_by_url(store_url, period='monthly'):
    """스토어 URL로 매출 조회 (로컬 API)"""
    try:
        url = f"{RANK_API_URL}/api/brand-sales?store_url={requests.utils.quote(store_url)}&period={period}"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Brand sales by URL error: {e}")
    return None


def get_product_score(keyword):
    """상품지수 조회 (로컬 API) - 현재 네이버에서 차단됨"""
    try:
        url = f"{RANK_API_URL}/api/product-score?keyword={requests.utils.quote(keyword)}"
        response = requests.get(url, timeout=60)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Product score error: {e}")
    return None


def get_brand_sales(mall_seq, period='monthly'):
    """브랜드 매출 조회 (로컬 API)"""
    try:
        url = f"{RANK_API_URL}/api/brand-sales?mall_seq={mall_seq}&period={period}"
        response = requests.get(url, timeout=60)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Brand sales error: {e}")
    return None


# ========== 유틸 함수 ==========
def parse_count(value):
    if isinstance(value, str) and '<' in value:
        return 5
    try:
        return int(value)
    except:
        return 0


def format_number(num):
    try:
        return f"{int(num):,}"
    except:
        return str(num)


# ========== API 라우트 ==========

@keyword_report_bp.route('/keyword-report')
@login_required
def keyword_report_page():
    """키워드 보고서 페이지"""
    return render_template('keyword_report.html',
                           active_menu='keyword-report',
                           rank_api_url=RANK_API_URL)


@keyword_report_bp.route('/api/keyword-report/analyze', methods=['POST'])
@login_required
def analyze_keyword():
    """
    키워드 분석 API

    Request Body:
    {
        "keyword": "메인 키워드",
        "include_ai": true/false (AI 분석 포함 여부)
    }

    Response:
    {
        "success": true,
        "data": {
            "keyword": "메인 키워드",
            "search_volume": {...},
            "content_counts": {...},
            "related_keywords": [...],
            "top_products": [...],
            "sub_keyword_analysis": {...}  // AI 분석 결과
        }
    }
    """
    try:
        data = request.get_json()
        keyword = data.get('keyword', '').strip()
        include_ai = data.get('include_ai', True)

        if not keyword:
            return jsonify({"success": False, "error": "키워드를 입력하세요."}), 400

        result = {
            "keyword": keyword,
            "search_volume": {},
            "content_counts": {},
            "related_keywords": [],
            "top_products": [],
            "product_scores": [],
            "monthly_sales": [],
            "sub_keyword_analysis": None,
            "ai_summary": None
        }

        # 1. 검색량 + 연관 키워드
        print(f"[Analyze] Step 1: Keyword stats for '{keyword}'")
        try:
            stats = get_keyword_stats(keyword)
            if stats and 'keywordList' in stats:
                keywords_list = stats['keywordList']

                # 메인 키워드 검색량
                main_kw = next((kw for kw in keywords_list if kw.get('relKeyword', '').strip() == keyword.strip()),
                              keywords_list[0] if keywords_list else None)
                if main_kw:
                    pc = parse_count(main_kw.get('monthlyPcQcCnt', 0))
                    mobile = parse_count(main_kw.get('monthlyMobileQcCnt', 0))
                    result['search_volume'] = {
                        'total': pc + mobile,
                        'pc': pc,
                        'mobile': mobile,
                        'competition': main_kw.get('compIdx', '-')
                    }

                # 연관 키워드 (검색량 순 정렬)
                related = []
                for kw in keywords_list:
                    rel_keyword = kw.get('relKeyword', '')
                    if rel_keyword.strip() == keyword.strip():
                        continue
                    volume = parse_count(kw.get('monthlyPcQcCnt', 0)) + parse_count(kw.get('monthlyMobileQcCnt', 0))
                    related.append({
                        'keyword': rel_keyword,
                        'volume': volume,
                        'competition': kw.get('compIdx', '-')
                    })
                related.sort(key=lambda x: x['volume'], reverse=True)
                result['related_keywords'] = related[:20]
                print(f"[Analyze] Step 1 done: {len(related)} related keywords")
        except Exception as e:
            print(f"[Analyze] Step 1 error: {e}")

        # 2. 콘텐츠 수
        print(f"[Analyze] Step 2: Content counts")
        try:
            result['content_counts'] = get_content_counts(keyword)
            print(f"[Analyze] Step 2 done: {result['content_counts']}")
        except Exception as e:
            print(f"[Analyze] Step 2 error: {e}")

        # 3. 쇼핑 상위 상품
        print(f"[Analyze] Step 3: Top products")
        try:
            result['top_products'] = get_shopping_top_products(keyword, 10)
            print(f"[Analyze] Step 3 done: {len(result['top_products'])} products")
        except Exception as e:
            print(f"[Analyze] Step 3 error: {e}")

        # 4. 상위 스토어 월간 매출 (상위 3개만, 빠르게)
        print(f"[Analyze] Step 4: Monthly sales")
        if result['top_products']:
            seen_stores = set()
            for p in result['top_products'][:5]:
                try:
                    link = p.get('link', '')
                    store_url = extract_store_url(link)

                    if store_url and store_url not in seen_stores:
                        seen_stores.add(store_url)
                        sales = get_brand_sales_by_url(store_url, 'monthly')
                        if sales and sales.get('success'):
                            total_amount = sales.get('summary', {}).get('total_amount', 0)
                            result['monthly_sales'].append({
                                'mall': p.get('mall', '-'),
                                'store_url': store_url,
                                'total_amount': total_amount
                            })
                        if len(result['monthly_sales']) >= 3:
                            break
                except Exception as e:
                    print(f"[Analyze] Sales error for {p.get('mall')}: {e}")
            print(f"[Analyze] Step 4 done: {len(result['monthly_sales'])} sales")

        # 5. AI 서브키워드 분석 (간소화 - 상위 5개만, 상품수만 조회)
        if include_ai and result['related_keywords']:
            keyword_data = {}
            # 상위 5개 키워드만 상품수 조회 (타임아웃 방지)
            for kw in result['related_keywords'][:5]:
                kw_name = kw['keyword']
                try:
                    counts = get_content_counts(kw_name)
                    keyword_data[kw_name] = {
                        'product_count': counts.get('shop', 0),
                        'top_sales': 0  # 매출은 메인 키워드 데이터 참고하도록
                    }
                except:
                    keyword_data[kw_name] = {'product_count': 0, 'top_sales': 0}
                time.sleep(0.1)

            # AI 분석 호출
            print(f"[AI] Calling Claude API for {keyword}")
            ai_result = analyze_sub_keywords(keyword, result['related_keywords'], keyword_data)
            if ai_result.get('success'):
                result['sub_keyword_analysis'] = ai_result.get('analysis')

                # AI 추천 키워드로 related_keywords 대체
                ai_keywords = ai_result.get('analysis', {}).get('recommended_keywords', [])
                if ai_keywords:
                    result['related_keywords'] = [
                        {
                            'keyword': kw.get('keyword', ''),
                            'volume': kw.get('search_volume', 0),
                            'competition': kw.get('competition_level', '-'),
                            'product_count': kw.get('product_count', 0),
                            'reason': kw.get('reason', ''),
                            'entry_difficulty': kw.get('entry_difficulty', '-')
                        }
                        for kw in ai_keywords
                    ]
                    print(f"[AI] Replaced related_keywords with {len(ai_keywords)} AI recommendations")
            else:
                print(f"[AI] Error: {ai_result.get('error')}")
            #     result['ai_summary'] = summary_result.get('summary')

        return jsonify({"success": True, "data": result})

    except Exception as e:
        import traceback
        print(f"[Analyze Error] {e}")
        print(traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500


@keyword_report_bp.route('/api/keyword-report/quick', methods=['POST'])
@login_required
def quick_analyze():
    """
    빠른 키워드 분석 (AI 제외, 기본 데이터만)
    """
    try:
        data = request.get_json()
        keyword = data.get('keyword', '').strip()

        if not keyword:
            return jsonify({"success": False, "error": "키워드를 입력하세요."}), 400

        result = {
            "keyword": keyword,
            "search_volume": {},
            "content_counts": {},
            "related_keywords": []
        }

        # 검색량 + 연관 키워드
        stats = get_keyword_stats(keyword)
        if stats and 'keywordList' in stats:
            keywords_list = stats['keywordList']

            main_kw = next((kw for kw in keywords_list if kw.get('relKeyword', '').strip() == keyword.strip()),
                          keywords_list[0] if keywords_list else None)
            if main_kw:
                pc = parse_count(main_kw.get('monthlyPcQcCnt', 0))
                mobile = parse_count(main_kw.get('monthlyMobileQcCnt', 0))
                result['search_volume'] = {
                    'total': pc + mobile,
                    'pc': pc,
                    'mobile': mobile,
                    'competition': main_kw.get('compIdx', '-')
                }

            related = []
            for kw in keywords_list:
                rel_keyword = kw.get('relKeyword', '')
                if rel_keyword.strip() == keyword.strip():
                    continue
                volume = parse_count(kw.get('monthlyPcQcCnt', 0)) + parse_count(kw.get('monthlyMobileQcCnt', 0))
                related.append({
                    'keyword': rel_keyword,
                    'volume': volume,
                    'competition': kw.get('compIdx', '-')
                })
            related.sort(key=lambda x: x['volume'], reverse=True)
            result['related_keywords'] = related[:20]

        # 콘텐츠 수
        result['content_counts'] = get_content_counts(keyword)

        return jsonify({"success": True, "data": result})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@keyword_report_bp.route('/api/keyword-report/ai-analyze', methods=['POST'])
@login_required
def ai_only_analyze():
    """
    AI 분석만 수행 (이미 수집된 데이터로)
    """
    try:
        data = request.get_json()
        keyword = data.get('keyword', '').strip()
        related_keywords = data.get('related_keywords', [])
        keyword_data = data.get('keyword_data', {})

        if not keyword or not related_keywords:
            return jsonify({"success": False, "error": "키워드와 연관 키워드 데이터가 필요합니다."}), 400

        result = analyze_sub_keywords(keyword, related_keywords, keyword_data)
        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
