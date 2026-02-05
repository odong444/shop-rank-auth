"""
Claude API 유틸리티
- 서브키워드 선별
- 키워드 전략 분석
"""
import os
import requests
import json

# API 키 (환경변수에서 가져옴 - 서버에서 CLAUDE_API_KEY 환경변수 설정 필요)
CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY', '')
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-20250514"


def call_claude(prompt, max_tokens=2000):
    """Claude API 호출"""
    if not CLAUDE_API_KEY:
        return {
            "success": False,
            "error": "CLAUDE_API_KEY 환경변수가 설정되지 않았습니다."
        }

    headers = {
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    try:
        response = requests.post(CLAUDE_API_URL, headers=headers, json=payload, timeout=60)
        if response.status_code == 200:
            data = response.json()
            return {
                "success": True,
                "content": data["content"][0]["text"]
            }
        else:
            return {
                "success": False,
                "error": f"API 오류: {response.status_code} - {response.text}"
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def analyze_sub_keywords(main_keyword, related_keywords, keyword_data):
    """
    서브키워드 분석 및 전략 제안

    Args:
        main_keyword: 메인 키워드 (예: "사과")
        related_keywords: 연관 키워드 목록 [{keyword, volume, competition}, ...]
        keyword_data: 각 키워드별 상세 데이터 {keyword: {search_volume, product_count, top_sales}, ...}

    Returns:
        AI 분석 결과
    """

    # 키워드 데이터 정리
    keyword_info = []
    for kw in related_keywords[:20]:  # 상위 20개만
        kw_name = kw.get('keyword', '')
        data = keyword_data.get(kw_name, {})
        keyword_info.append({
            "keyword": kw_name,
            "search_volume": kw.get('volume', 0),
            "competition": kw.get('competition', '-'),
            "product_count": data.get('product_count', 0),
            "top_monthly_sales": data.get('top_sales', 0)
        })

    prompt = f"""당신은 네이버 쇼핑 키워드 분석 전문가입니다.

메인 키워드: {main_keyword}

연관 키워드 데이터:
{json.dumps(keyword_info, ensure_ascii=False, indent=2)}

위 데이터를 분석하여 다음을 JSON 형식으로 응답해주세요:

**중요: 반드시 "{main_keyword}"와 직접 관련된 키워드만 선별하세요!**

1. **서브키워드 추천** (최대 5개)
   - "{main_keyword}"를 포함하거나 "{main_keyword}"의 세부 종류/브랜드인 키워드만 선별
   - 다른 카테고리 상품 키워드는 반드시 제외

   예시 (메인: "사과"):
   - ✅ 포함: "부사사과", "안동사과", "꿀사과", "사과 선물세트", "가정용 사과"
   - ❌ 제외: "멜론", "천혜향", "귤", "배" (다른 과일)
   - ❌ 제외: "사과 효능", "사과 칼로리" (정보 검색용)

2. **각 서브키워드별 분석**
   - 추천 이유 (왜 이 키워드가 "{main_keyword}" 판매에 도움이 되는지)
   - 경쟁 강도 평가
   - 예상 진입 난이도 (상/중/하)

3. **종합 전략 제안**
   - 메인 키워드 vs 서브키워드 활용 전략
   - 우선 공략 추천 키워드

JSON 형식:
{{
  "recommended_keywords": [
    {{
      "keyword": "키워드명",
      "search_volume": 검색량,
      "product_count": 상품수,
      "top_monthly_sales": 상위매출,
      "reason": "추천 이유",
      "competition_level": "높음/보통/낮음",
      "entry_difficulty": "상/중/하"
    }}
  ],
  "strategy": {{
    "main_keyword_usage": "메인 키워드 활용 방안",
    "sub_keyword_usage": "서브 키워드 활용 방안",
    "priority_keyword": "우선 공략 추천 키워드",
    "priority_reason": "우선 공략 이유"
  }},
  "summary": "2-3문장 요약"
}}

반드시 위 JSON 형식만 응답하세요. 다른 텍스트 없이 JSON만 반환하세요."""

    result = call_claude(prompt)

    if result["success"]:
        try:
            # JSON 파싱 시도
            content = result["content"].strip()
            # ```json ... ``` 형식 처리
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            analysis = json.loads(content)
            return {
                "success": True,
                "analysis": analysis
            }
        except json.JSONDecodeError as e:
            return {
                "success": True,
                "analysis": None,
                "raw_content": result["content"],
                "parse_error": str(e)
            }
    else:
        return result


def generate_report_summary(report_data):
    """
    보고서 전체 요약 생성

    Args:
        report_data: 전체 보고서 데이터

    Returns:
        AI가 생성한 요약
    """

    prompt = f"""당신은 네이버 쇼핑 키워드 분석 전문가입니다.

다음 키워드 분석 데이터를 바탕으로 고객에게 전달할 핵심 인사이트를 작성해주세요.

키워드: {report_data.get('keyword', '')}
월간 검색량: {report_data.get('search_volume', {}).get('total', 0):,}
경쟁 강도: {report_data.get('search_volume', {}).get('competition', '-')}
등록 상품 수: {report_data.get('content_counts', {}).get('shop', 0):,}

상위 상품 매출 (월간):
{json.dumps(report_data.get('monthly_sales', [])[:5], ensure_ascii=False, indent=2)}

서브키워드 분석:
{json.dumps(report_data.get('sub_keyword_analysis', {}), ensure_ascii=False, indent=2)}

다음 형식으로 응답해주세요:

1. **시장 현황** (2-3문장)
2. **기회 요인** (2-3문장)
3. **추천 전략** (2-3문장)
4. **주의 사항** (1-2문장)

전문적이지만 이해하기 쉽게 작성하세요."""

    result = call_claude(prompt, max_tokens=1000)

    if result["success"]:
        return {
            "success": True,
            "summary": result["content"]
        }
    else:
        return result
