"""
네이버 플레이스 순위 체크 유틸리티
"""

import requests
from urllib.parse import quote
import re
from datetime import datetime
import urllib.request
import urllib.parse
import json
import random

# 네이버 API 키
NAVER_CLIENT_ID = "UrlniCJoGZ_jfgk5tlkN"
NAVER_CLIENT_SECRET = "x3z9b1CM2F"

# Decodo 프록시 설정
PROXY_HOST = "gate.decodo.com"
PROXY_USER = "spa2rm7ar7"
PROXY_PASS = "~oAEv1Dd5wt0goGg4h"
PROXY_PORT_MIN = 10001
PROXY_PORT_MAX = 10010


def get_proxy():
    """랜덤 프록시 설정 반환 (포트 로테이션)"""
    port = random.randint(PROXY_PORT_MIN, PROXY_PORT_MAX)
    proxy_url = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{port}"
    return {
        'http': proxy_url,
        'https': proxy_url
    }


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


def save_keyword_snapshot(keyword, place_data_list):
    """
    키워드 검색 결과를 스냅샷으로 저장
    
    Args:
        keyword: 검색 키워드
        place_data_list: [(place_id, rank, title), ...] 리스트
    """
    try:
        from utils.db import get_db
        conn = get_db()
        cur = conn.cursor()
        
        for place_id, rank, title in place_data_list:
            cur.execute('''
                INSERT INTO place_keyword_snapshots (keyword, place_id, rank, title)
                VALUES (%s, %s, %s, %s)
            ''', (keyword, place_id, rank, title or ''))
        
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Snapshot save error: {e}")


def check_place_rank(keyword, place_id, max_results=200):
    """
    네이버 플레이스 순위 체크
    
    Args:
        keyword: 검색 키워드
        place_id: 찾을 플레이스 ID
        max_results: 최대 체크 순위 (기본 300)
    
    Returns:
        tuple: (순위, 업체명) - 못 찾으면 (None, None)
    """
    
    # 프록시 설정
    proxies = get_proxy()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9',
        'Referer': 'https://m.map.naver.com/'
    }
    
    place_data = {}  # place_id: title 매핑
    place_ids = []
    
    # 1. 네이버 로컬 API로 업체명 가져오기
    local_places = get_place_names_from_local_api(keyword, max_results=max_results)
    
    # 2. 모바일 지도 검색
    try:
        url = f"https://m.map.naver.com/search2/search.naver?query={quote(keyword)}"
        response = requests.get(url, headers=headers, proxies=proxies, timeout=10)
        
        if response.status_code == 200:
            response.encoding = 'utf-8'
            html = response.text
            
            # place_id와 업체명 함께 추출 시도
            pattern = r'data-cid="(\d+)"[^>]*>.*?<span[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)</span>'
            matches = re.findall(pattern, html, re.DOTALL)
            
            for pid, title in matches:
                if pid not in place_data:
                    place_data[pid] = title.strip()
                    place_ids.append(pid)
            
            # data-cid가 없는 경우 기존 방식으로 place_id 추출
            if not place_ids:
                ids = extract_place_ids_from_html(html)
                place_ids.extend(ids)
                
                # place_id는 있지만 업체명이 없으면 로컬 API 결과로 매칭 시도
                # 순서가 비슷하다고 가정하고 인덱스로 매칭
                for idx, pid in enumerate(place_ids):
                    if pid not in place_data and idx < len(local_places):
                        place_data[pid] = local_places[idx]['title']
    except Exception as e:
        print(f"Mobile search error: {e}")
    
    # PC 지도 검색 (추가 결과)
    try:
        url = f"https://map.naver.com/v5/search/{quote(keyword)}"
        headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        response = requests.get(url, headers=headers, proxies=proxies, timeout=10)
        
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
    
    # 스냅샷 저장용 데이터 준비
    snapshot_data = []
    for rank, pid in enumerate(place_ids, start=1):
        title = place_data.get(pid, '')
        snapshot_data.append((pid, rank, title))
    
    # 키워드 검색 결과 스냅샷 저장 (비동기로 저장)
    if snapshot_data:
        try:
            save_keyword_snapshot(keyword, snapshot_data)
        except Exception as e:
            print(f"Snapshot save failed: {e}")
    
    # 순위 찾기
    for rank, pid in enumerate(place_ids, start=1):
        if pid == place_id:
            # 검색 결과에서 가져온 업체명 사용
            title = place_data.get(pid)
            
            # 없으면 로컬 API 결과에서 순위로 가져오기
            if not title and rank <= len(local_places):
                title = local_places[rank - 1]['title']
                print(f"Using local API result for rank {rank}: {title}")
            
            # 그래도 없으면 fallback (작동 안 할 가능성 높음)
            if not title:
                title = get_place_title(place_id)
                print(f"Trying fallback for place_id {place_id}: {title}")
            
            return (rank, title)
    
    return (None, None)


def get_place_names_from_local_api(keyword, max_results=50):
    """
    네이버 로컬 검색 API로 업체명 리스트 가져오기
    
    Returns:
        list: [{'title': '업체명', 'address': '주소'}, ...]
    """
    try:
        enc = urllib.parse.quote(keyword)
        url = f"https://openapi.naver.com/v1/search/local.json?query={enc}&display={max_results}&sort=sim"
        
        req = urllib.request.Request(url)
        req.add_header("X-Naver-Client-Id", NAVER_CLIENT_ID)
        req.add_header("X-Naver-Client-Secret", NAVER_CLIENT_SECRET)
        
        response = urllib.request.urlopen(req, timeout=10)
        data = json.loads(response.read().decode('utf-8'))
        
        results = []
        for item in data.get('items', []):
            title = item['title'].replace('<b>', '').replace('</b>', '')
            results.append({
                'title': title,
                'address': item.get('address', ''),
                'category': item.get('category', '')
            })
        
        return results
    except Exception as e:
        print(f"Local API error: {e}")
        return []


def get_place_title(place_id):
    """플레이스 ID로 업체명 조회 (fallback)"""
    try:
        proxies = get_proxy()
        url = f"https://m.place.naver.com/restaurant/{place_id}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9'
        }
        response = requests.get(url, headers=headers, proxies=proxies, timeout=10)
        
        if response.status_code == 200:
            response.encoding = 'utf-8'
            
            # <title> 태그에서 업체명 추출
            match = re.search(r'<title>([^<]+)</title>', response.text)
            if match:
                title = match.group(1)
                # "- 네이버 플레이스" 제거
                title = title.replace(' - 네이버 플레이스', '').strip()
                if title and title != '네이버 플레이스':
                    return title
    except Exception as e:
        print(f"Title fetch error: {e}")
    
    return None
