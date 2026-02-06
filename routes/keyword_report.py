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
def _match_store_url(url):
    """URL에서 스마트스토어/브랜드 URL 추출 (헬퍼), /main 제외"""
    import re
    match = re.search(r'(https?://smartstore\.naver\.com/[^/\?&\s]+)', url)
    if match:
        store_url = match.group(1)
        # /main은 공용 경로이므로 실제 스토어가 아님
        if store_url.endswith('/main'):
            return None
        return store_url
    match = re.search(r'(https?://brand\.naver\.com/[^/\?&\s]+)', url)
    if match:
        return match.group(1)
    return None


def _follow_redirect(url):
    """URL 리다이렉트를 따라가서 최종 URL 반환"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, allow_redirects=True, timeout=5, stream=True)
        final_url = response.url
        response.close()
        return final_url
    except Exception as e:
        print(f"[Extract URL] Redirect error: {e}")
        return None


def extract_store_url(product_link):
    """상품 링크에서 스토어 URL 추출 (리다이렉트 따라감)"""
    from urllib.parse import unquote

    # 1) 원본 링크에서 직접 추출 (/main 아닌 경우)
    result = _match_store_url(product_link)
    if result:
        return result

    # 2) URL 인코딩된 트래킹 링크 처리
    decoded = unquote(product_link)
    if decoded != product_link:
        result = _match_store_url(decoded)
        if result:
            return result

    # 3) smartstore.naver.com/main/products/XXX → 리다이렉트로 실제 스토어 URL 획득
    #    네이버 쇼핑 API가 /main/ 공용 경로로 반환하므로 반드시 리다이렉트 필요
    print(f"[Extract URL] Following redirect for: {product_link[:100]}")
    final_url = _follow_redirect(product_link)
    if final_url:
        print(f"[Extract URL] Redirected to: {final_url[:100]}")
        result = _match_store_url(final_url)
        if result:
            return result

        decoded_final = unquote(final_url)
        if decoded_final != final_url:
            result = _match_store_url(decoded_final)
            if result:
                return result

    return None


def get_brand_sales_by_url(store_url, period='monthly'):
    """스토어 URL로 매출 조회 (로컬 API)"""
    try:
        from urllib.parse import quote
        url = f"{RANK_API_URL}/api/brand-sales?store_url={quote(store_url, safe='')}&period={period}"
        print(f"[BrandSales] Calling: {url[:120]}")
        response = requests.get(url, timeout=30)
        print(f"[BrandSales] Status: {response.status_code}")
        if response.status_code == 200:
            return response.json()
        else:
            print(f"[BrandSales] Error body: {response.text[:200]}")
    except requests.exceptions.Timeout:
        print(f"[BrandSales] Timeout for: {store_url}")
    except Exception as e:
        print(f"[BrandSales] Error: {e}")
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
            for p in result['top_products'][:10]:
                try:
                    link = p.get('link', '')
                    mall = p.get('mall', '-')
                    print(f"[Sales] Product link for {mall}: {link[:100]}")

                    store_url = extract_store_url(link)
                    print(f"[Sales] Extracted store URL for {mall}: {store_url}")

                    if store_url and store_url not in seen_stores:
                        seen_stores.add(store_url)
                        print(f"[Sales] Fetching sales for: {store_url}")
                        sales = get_brand_sales_by_url(store_url, 'monthly')
                        print(f"[Sales] API response for {mall}: success={sales.get('success') if sales else 'None'}")
                        if sales and sales.get('success'):
                            total_amount = sales.get('summary', {}).get('total_amount', 0)
                            result['monthly_sales'].append({
                                'mall': mall,
                                'store_url': store_url,
                                'total_amount': total_amount
                            })
                            print(f"[Sales] Got sales for {mall}: {total_amount}")
                        else:
                            error_msg = sales.get('error', 'unknown') if sales else 'no response'
                            print(f"[Sales] No sales data for {mall}: {error_msg}")
                        if len(result['monthly_sales']) >= 3:
                            break
                except Exception as e:
                    print(f"[Analyze] Sales error for {p.get('mall')}: {e}")
            print(f"[Analyze] Step 4 done: {len(result['monthly_sales'])} sales")

        # AI 분석은 별도 API로 분리 (타임아웃 방지)
        # include_ai 플래그는 프론트엔드에서 별도 호출 여부 결정용
        result['ai_available'] = include_ai and len(result['related_keywords']) > 0

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
