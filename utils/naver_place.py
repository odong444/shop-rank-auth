"""
네이버 플레이스 순위 체크 유틸리티
"""

import requests
from urllib.parse import quote
import re


def extract_place_ids_from_html(html):
    """HTML에서 플레이스 ID 추출 (순서 유지, 중복 제거)"""
    
    # 패턴 1: place.naver.com/restaurant/숫자
    pattern1 = r'place\.naver\.com/restaurant/(\d+)'
    matches1 = re.findall(pattern1, html)
    
    # 패턴 2: place.naver.com/숫자
    pattern2 = r'place\.naver\.com/(\d+)'
    matches2 = re.findall(pattern2, html)
    
    # 패턴 3: /place/ 뒤의 숫자
    pattern3 = r'/place/(\d{8,})'
    matches3 = re.findall(pattern3, html)
    
    # 모든 매치 합치기 (순서 유지)
    all_matches = matches1 + matches2 + matches3
    
    # 중복 제거하면서 순서 유지
    seen = set()
    unique_ids = []
    for pid in all_matches:
        if pid not in seen:
            seen.add(pid)
            unique_ids.append(pid)
    
    return unique_ids


def check_place_rank(keyword, place_id, max_results=300):
    """
    네이버 플레이스 순위 체크
    
    Args:
        keyword: 검색 키워드
        place_id: 찾을 플레이스 ID
        max_results: 최대 체크 순위 (기본 300)
    
    Returns:
        tuple: (순위, 업체명) - 못 찾으면 (None, None)
    """
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9',
        'Referer': 'https://m.map.naver.com/'
    }
    
    place_data = {}  # place_id: title 매핑
    place_ids = []
    
    # 모바일 지도 검색
    try:
        url = f"https://m.map.naver.com/search2/search.naver?query={quote(keyword)}"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            response.encoding = 'utf-8'
            html = response.text
            
            # place_id와 업체명 함께 추출
            # 패턴: data-cid="플레이스ID" ... <span class="title">업체명</span>
            pattern = r'data-cid="(\d+)"[^>]*>.*?<span[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)</span>'
            matches = re.findall(pattern, html, re.DOTALL)
            
            for pid, title in matches:
                if pid not in place_data:
                    place_data[pid] = title.strip()
                    place_ids.append(pid)
            
            # data-cid가 없는 경우 기존 방식
            if not place_ids:
                ids = extract_place_ids_from_html(html)
                place_ids.extend(ids)
    except Exception as e:
        print(f"Mobile search error: {e}")
    
    # PC 지도 검색 (추가 결과)
    try:
        url = f"https://map.naver.com/v5/search/{quote(keyword)}"
        headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            response.encoding = 'utf-8'
            ids = extract_place_ids_from_html(response.text)
            
            # 중복 제거하면서 추가
            for pid in ids:
                if pid not in place_ids:
                    place_ids.append(pid)
    except Exception as e:
        print(f"PC search error: {e}")
    
    # 중복 최종 제거
    seen = set()
    unique_place_ids = []
    for pid in place_ids:
        if pid not in seen:
            seen.add(pid)
            unique_place_ids.append(pid)
    
    place_ids = unique_place_ids[:max_results]
    
    # 순위 찾기
    for rank, pid in enumerate(place_ids, start=1):
        if pid == place_id:
            # 검색 결과에서 가져온 업체명 사용
            title = place_data.get(pid)
            
            # 없으면 별도 조회 (fallback)
            if not title:
                title = get_place_title(place_id)
            
            return (rank, title)
    
    return (None, None)


def get_place_title(place_id):
    """플레이스 ID로 업체명 조회"""
    try:
        url = f"https://m.place.naver.com/restaurant/{place_id}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9'
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            # UTF-8 인코딩 명시
            response.encoding = 'utf-8'
            
            # <title> 태그에서 업체명 추출
            match = re.search(r'<title>([^<]+)</title>', response.text)
            if match:
                title = match.group(1)
                # "- 네이버 플레이스" 제거
                title = title.replace(' - 네이버 플레이스', '').strip()
                return title
    except Exception as e:
        print(f"Title fetch error: {e}")
    
    return None
