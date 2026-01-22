"""
전체 상품 순위 업데이트 스케줄러
Railway Cron Job으로 매일 오후 1시(KST)에 실행

Railway 설정:
  - Cron Expression: 0 4 * * * (UTC 기준 = KST 13:00)
  - Command: python scheduler.py
"""

import time
from datetime import datetime
import pytz

from utils.db import get_db
from utils.naver_api import get_naver_search_results, get_cached_results, save_cache, update_all_products_with_keyword

KST = pytz.timezone('Asia/Seoul')


def log(message):
    """타임스탬프와 함께 로그 출력"""
    now = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {message}")


def get_all_keywords():
    """등록된 모든 키워드 조회 (중복 제거)"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT DISTINCT keyword FROM products WHERE keyword IS NOT NULL AND keyword != \'\'')
    keywords = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return keywords


def main():
    """메인 실행 함수 - refresh_ranks()의 전체 버전"""
    log("=" * 50)
    log("전체 상품 순위 업데이트 시작")
    log("=" * 50)
    
    start_time = time.time()
    
    # 모든 키워드 가져오기
    keywords = get_all_keywords()
    log(f"총 {len(keywords)}개 키워드 발견")
    
    if not keywords:
        log("업데이트할 키워드가 없습니다.")
        return
    
    total_updated = 0
    
    for i, kw in enumerate(keywords, 1):
        try:
            log(f"[{i}/{len(keywords)}] '{kw}' 처리 중...")
            
            # 캐시 확인 후 없으면 API 호출 (기존 로직 그대로)
            results = get_cached_results(kw)
            if not results:
                results = get_naver_search_results(kw)
                if results:
                    save_cache(kw, results)
                time.sleep(0.5)  # API 호출 간격
            
            # 순위 업데이트
            if results:
                updated = update_all_products_with_keyword(kw, results)
                total_updated += updated
                log(f"  → {updated}개 상품 업데이트")
            else:
                log(f"  → 검색 결과 없음")
            
        except Exception as e:
            log(f"  → 에러: {e}")
    
    elapsed = time.time() - start_time
    
    log("=" * 50)
    log(f"완료! 총 {total_updated}개 상품 업데이트 ({elapsed:.1f}초)")
    log("=" * 50)


if __name__ == '__main__':
    main()
