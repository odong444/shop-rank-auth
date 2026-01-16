import urllib.request
import urllib.parse
import json
import time
from datetime import datetime, timedelta
import pytz

from utils.db import get_db

NAVER_CLIENT_ID = "UrlniCJoGZ_jfgk5tlkN"
NAVER_CLIENT_SECRET = "x3z9b1CM2F"
CACHE_DURATION_MINUTES = 60

def get_naver_search_results(keyword):
    """네이버 API로 300위까지 검색 결과 가져오기"""
    results = []
    try:
        enc = urllib.parse.quote(keyword)
        for start in range(1, 301, 100):
            url = f"https://openapi.naver.com/v1/search/shop.json?query={enc}&display=100&start={start}&sort=sim"
            req = urllib.request.Request(url)
            req.add_header("X-Naver-Client-Id", NAVER_CLIENT_ID)
            req.add_header("X-Naver-Client-Secret", NAVER_CLIENT_SECRET)
            res = urllib.request.urlopen(req, timeout=10)
            data = json.loads(res.read().decode('utf-8'))
            if not data['items']:
                break
            for idx, item in enumerate(data['items']):
                rank = (start - 1) + (idx + 1)
                results.append({
                    'rank': rank,
                    'mid': str(item['productId']),
                    'title': item['title'].replace('<b>', '').replace('</b>', ''),
                    'mall': item['mallName']
                })
            time.sleep(0.1)
    except Exception as e:
        print(f"API Error: {e}")
    return results

def get_cached_results(keyword):
    """캐시된 검색 결과 가져오기 (1시간 이내)"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT search_results, cached_at FROM keyword_cache WHERE keyword=%s', (keyword,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    
    if row:
        cached_at = row[1]
        if cached_at.tzinfo is None:
            cached_at = pytz.utc.localize(cached_at)
        now = datetime.now(pytz.utc)
        if now - cached_at < timedelta(minutes=CACHE_DURATION_MINUTES):
            return json.loads(row[0]) if row[0] else None
    return None

def save_cache(keyword, results):
    """검색 결과 캐시 저장"""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('''INSERT INTO keyword_cache (keyword, search_results, cached_at) 
                      VALUES (%s, %s, NOW()) 
                      ON CONFLICT (keyword) DO UPDATE SET search_results=%s, cached_at=NOW()''',
                   (keyword, json.dumps(results), json.dumps(results)))
        conn.commit()
    except Exception as e:
        print(f"Cache save error: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

def update_all_products_with_keyword(keyword, results):
    """해당 키워드를 가진 모든 사용자의 상품 순위 업데이트"""
    if not results:
        return 0
    
    mid_map = {r['mid']: r for r in results}
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute('SELECT id, mid, first_rank FROM products WHERE keyword=%s', (keyword,))
    products = cur.fetchall()
    
    updated = 0
    for pid, mid, first_rank in products:
        if mid in mid_map:
            r = mid_map[mid]
            rank_str = str(r['rank'])
            new_first = first_rank if first_rank != '-' else rank_str
            cur.execute('''UPDATE products SET prev_rank=current_rank, current_rank=%s, 
                          title=COALESCE(NULLIF(%s,''),title), mall=COALESCE(NULLIF(%s,''),mall),
                          first_rank=%s, last_checked=NOW() WHERE id=%s''',
                       (rank_str, r['title'], r['mall'], new_first, pid))
            cur.execute('INSERT INTO rank_history (product_id, rank) VALUES (%s, %s)', (pid, rank_str))
            updated += 1
        else:
            cur.execute('''UPDATE products SET prev_rank=current_rank, current_rank=%s, last_checked=NOW() WHERE id=%s''',
                       ('300위 밖', pid))
            cur.execute('INSERT INTO rank_history (product_id, rank) VALUES (%s, %s)', (pid, '300위 밖'))
            updated += 1
    
    conn.commit()
    cur.close()
    conn.close()
    return updated

def get_naver_rank(keyword, target_mid):
    """단일 상품 순위 조회 (캐시 활용)"""
    results = get_cached_results(keyword)
    
    if not results:
        results = get_naver_search_results(keyword)
        if results:
            save_cache(keyword, results)
            update_all_products_with_keyword(keyword, results)
    
    for r in results:
        if r['mid'] == str(target_mid):
            return r['rank'], r['title'], r['mall']
    
    return None, None, None
