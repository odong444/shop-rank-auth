"""
키워드 리포트 - 간단 버전
"""
from flask import Blueprint, request, jsonify, session, redirect, render_template
from functools import wraps
import requests
import hashlib
import hmac
import base64
import time
import os

keyword_report_bp = Blueprint('keyword_report', __name__)

# API 설정
CUSTOMER_ID = os.environ.get('NAVER_AD_CUSTOMER_ID', '2453515')
AD_API_KEY = os.environ.get('NAVER_AD_API_KEY', '01000000006162454519ef4e8d97852a2ad5eb9b397beef455f126cace2f790f5c6b7bccff')
AD_SECRET_KEY = os.environ.get('NAVER_AD_SECRET_KEY', 'AQAAAABhYkVFGe9OjZeFKirV65s5Ke25zkTefku4HBEbYMqJ+Q==')
AD_BASE_URL = 'https://api.naver.com'

NAVER_CLIENT_ID = os.environ.get('NAVER_CLIENT_ID', 'UrlniCJoGZ_jfgk5tlkN')
NAVER_CLIENT_SECRET = os.environ.get('NAVER_CLIENT_SECRET', 'x3z9b1CM2F')

RANK_API_URL = os.environ.get('RANK_API_URL', 'https://api.bw-rank.kr')


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated


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


def parse_count(value):
    if isinstance(value, str) and '<' in value:
        return 5
    try:
        return int(value)
    except:
        return 0


@keyword_report_bp.route('/keyword-report')
@login_required
def keyword_report_page():
    return render_template('keyword_report.html', 
                           active_menu='keyword-report',
                           rank_api_url=RANK_API_URL)


@keyword_report_bp.route('/api/keyword-report/analyze', methods=['POST'])
@login_required
def analyze_keyword():
    try:
        data = request.get_json()
        keyword = data.get('keyword', '').strip()
        
        if not keyword:
            return jsonify({"success": False, "error": "키워드를 입력하세요"}), 400
        
        result = {
            "keyword": keyword,
            "search_volume": {},
            "content_counts": {},
            "related_keywords": [],
            "top_products": []
        }
        
        # 1. 검색량 + 연관키워드
        uri = '/keywordstool'
        method = 'GET'
        params = {'hintKeywords': keyword, 'showDetail': '1'}
        headers = get_ad_header(method, uri)
        
        try:
            response = requests.get(AD_BASE_URL + uri, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                stats = response.json()
                keywords_list = stats.get('keywordList', [])
                
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
                    if keyword not in rel_keyword:
                        continue
                    
                    pc = parse_count(kw.get('monthlyPcQcCnt', 0))
                    mobile = parse_count(kw.get('monthlyMobileQcCnt', 0))
                    volume = pc + mobile
                    
                    related.append({
                        'keyword': rel_keyword,
                        'volume': volume,
                        'competition': kw.get('compIdx', '-'),
                        'blog': 0,
                        'cafe': 0,
                        'shop': 0
                    })
                
                related.sort(key=lambda x: x['volume'], reverse=True)
                result['related_keywords'] = related[:5]
        except Exception as e:
            print(f"[Keyword API Error] {e}")
        
        # 2. 콘텐츠 수
        for search_type, api_type in [('blog', 'blog'), ('cafe', 'cafearticle'), ('shop', 'shop')]:
            url = f"https://openapi.naver.com/v1/search/{api_type}.json"
            headers = {
                "X-Naver-Client-Id": NAVER_CLIENT_ID,
                "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
            }
            try:
                response = requests.get(url, headers=headers, params={"query": keyword, "display": 1}, timeout=10)
                if response.status_code == 200:
                    result['content_counts'][search_type] = response.json().get('total', 0)
                else:
                    result['content_counts'][search_type] = 0
            except:
                result['content_counts'][search_type] = 0
        
        # 3. 상품지수
        try:
            response = requests.get(
                f"{RANK_API_URL}/api/product-score",
                params={"keyword": keyword},
                timeout=30
            )
            
            if response.status_code == 200:
                score_data = response.json()
                products = score_data.get('result', {}).get('products', [])
                
                for i, p in enumerate(products[:5], 1):
                    result['top_products'].append({
                        'rank': i,
                        'nvmid': str(p.get('nvmid', '')),
                        'mallSeq': p.get('mallSeq', ''),
                        'title': p.get('productTitle', ''),
                        'mall': p.get('mallName', ''),
                        'price': p.get('lowPrice', 0),
                        'image': p.get('imageUrl', ''),
                        'review_cnt': p.get('reviewCount', 0),
                        'keep_cnt': p.get('keepCnt', 0),
                        'purchase_cnt': p.get('purchaseCnt', 0),
                        'relevance': p.get('relevanceStarScore', 0),
                        'hit': p.get('hitStarScore', 0),
                        'sale': p.get('saleStarScore', 0),
                        'review_score': p.get('reviewCountStarScore', 0),
                    })
        except Exception as e:
            print(f"[Product Score Error] {e}")
        
        return jsonify({"success": True, "data": result})
        
    except Exception as e:
        print(f"[Analyze Error] {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@keyword_report_bp.route('/api/keyword-report/sales', methods=['POST'])
@login_required
def fetch_sales():
    try:
        data = request.get_json()
        products = data.get('products', [])
        period = data.get('period', 'monthly')
        
        if not products:
            return jsonify({"success": False, "error": "상품 데이터가 필요합니다"}), 400
        
        sales_result = []
        
        for product in products:
            mall_seq = product.get('mallSeq')
            nvmid = product.get('nvmid', '')
            mall_name = product.get('mall', '-')
            product_title = product.get('title', '')
            
            # ★ 가격비교 상품: mallSeq가 없으면(0) catalog-seller로 찾기
            if not mall_seq or str(mall_seq) == '0':
                try:
                    seller_resp = requests.get(
                        f"{RANK_API_URL}/api/catalog-seller",
                        params={"title": product_title},
                        timeout=15
                    )
                    if seller_resp.status_code == 200:
                        seller_data = seller_resp.json()
                        if seller_data.get('success'):
                            mall_seq = seller_data['mall_seq']
                            mall_name = seller_data.get('mall_name', mall_name)
                            # ★ 개별 상품 ID로 매출 필터링
                            nvmid = seller_data.get('mall_product_id', '')
                except Exception as e:
                    print(f"[Catalog Seller Error] {product_title}: {e}")
            
            if not mall_seq or str(mall_seq) == '0':
                continue
            
            try:
                url = f"{RANK_API_URL}/api/brand-sales?mall_seq={mall_seq}&period={period}&product_id={nvmid}"
                response = requests.get(url, timeout=30)
                
                if response.status_code == 200:
                    sales_data = response.json()
                    products_data = sales_data.get('products', [])
                    
                    matched = None
                    if nvmid and products_data:
                        for p in products_data:
                            if str(p.get('product_id', '')) == nvmid:
                                matched = p
                                break
                    
                    if matched:
                        sales_result.append({
                            'mall': mall_name,
                            'title': product_title,
                            'amount': matched.get('amount', 0),
                            'count': matched.get('count', 0),
                            'match_type': 'product'
                        })
                    else:
                        summary = sales_data.get('summary', {})
                        if summary.get('total_amount', 0) > 0:
                            sales_result.append({
                                'mall': mall_name,
                                'title': product_title,
                                'amount': summary['total_amount'],
                                'count': summary.get('total_count', 0),
                                'match_type': 'store_total'
                            })
            except Exception as e:
                print(f"[Sales Error] {mall_name}: {e}")
                continue
        
        return jsonify({"success": True, "sales": sales_result})
        
    except Exception as e:
        print(f"[Fetch Sales Error] {e}")
        return jsonify({"success": False, "error": str(e)}), 500
