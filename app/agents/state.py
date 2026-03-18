import operator
from typing import Annotated, TypedDict, List, Dict, Any

class CrawlState(TypedDict):
    """
    뉴스 크롤링 파이프라인 전역 상태 데이터
    """
    llm_mode: str                             # "gemini_only", "local_priority", "local_only"
    raw_articles: List[Dict[str, Any]]        # 원본 뉴스 기사 리스트
    analyzed_articles: List[Dict[str, Any]]   # AI 분석(요약, 편향성 등)이 완료된 기사 리스트
    saved_count: int                          # DB에 저장된 기사 수
    skipped_count: int                        # 이미 존재하여 스킵된 기사 수
    messages: Annotated[List[str], operator.add] # 로그 메시지 수집용
    error: str                                # 에러 발생 시 에러 메시지 저장

class ClusterState(TypedDict):
    """
    이슈 클러스터링 파이프라인 전역 상태 데이터
    """
    llm_mode: str                             # "gemini_only", "local_priority", "local_only"
    unclustered_articles: List[Dict[str, Any]] # 이슈가 배정되지 않은 기사 리스트
    clustered_topics: List[Dict[str, Any]]     # BERTopic으로 군집화되고 AI로 분석된 토픽 리스트
    saved_issue_count: int                     # DB에 저장된 이슈 라벨 수
    messages: Annotated[List[str], operator.add] # 로그 메시지 수집용
    error: str                                 # 에러 발생 시 에러 메시지 저장

def merge_tokens(left: Dict[str, int], right: Dict[str, int]) -> Dict[str, int]:
    """병럴 브랜치의 토큰 사용량을 합산하기 위한 리듀서"""
    if not left: return right
    if not right: return left
    return {
        "prompt_tokens": left.get("prompt_tokens", 0) + right.get("prompt_tokens", 0),
        "completion_tokens": left.get("completion_tokens", 0) + right.get("completion_tokens", 0)
    }

class OverallState(TypedDict):
    """
    통합 파이프라인 최상위 전역 상태 (Map-Reduce의 Reduce 단계용)
    - Subgraph에서 병렬로 상태가 반환될 때 Concurrent Update 에러를 막기 위해
      단일 값들은 operator.replace 등을 사용하여 덮어쓰도록 처리합니다.
    """
    llm_mode: str
    issue_id: int                             # (Optional)
    all_issue_ids: List[int]
    
    # 공통 데이터
    raw_articles: List[Dict[str, Any]]
    unclustered_articles: List[Dict[str, Any]]
    clustered_topics: List[Dict[str, Any]]
    
    # 집계 데이터 (Reducer 적용)
    total_tokens: Annotated[Dict[str, int], merge_tokens]
    messages: Annotated[List[str], operator.add]
    error: str

class ComparisonState(TypedDict):
    """
    개별 이슈 분석 브랜치 전용 상태 (Isolated State)
    """
    llm_mode: str
    issue_id: int
    
    # 브랜치 내부 데이터 (Conflict 방지를 위해 OverallState와 겹치지 않게 관리하거나 Reducer 미지정)
    raw_articles: List[Dict[str, Any]]
    unclustered_articles: List[Dict[str, Any]]
    clustered_topics: List[Dict[str, Any]]
    
    articles: List[Dict[str, Any]]
    claim_cards: List[Dict[str, Any]]
    structured_issues: List[Dict[str, Any]]
    draft_article: Dict[str, Any]
    edited_article: Dict[str, Any]
    edit_log: str
    
    judge_status: str
    judge_feedback: str
    retry_count: int
    
    # 이슈 메타데이터
    description: str                           # 이슈 요약 설명
    background: str                            # 이슈 배경 정보
    
    # 토큰 사용량 추적
    total_tokens: Dict[str, int]               # {"prompt_tokens": 0, "completion_tokens": 0}

class ReviewState(TypedDict):
    """
    최종 검토 파이프라인 전역 상태 데이터 (Review Graph)
    (FetchArticles ➡️ CalculateReliability ➡️ AnalyzeAndOpine)
    """
    llm_mode: str                              # "gemini_only", "local_priority", "local_only"
    issue_id: int                              # 검토 대상 이슈 ID
    user_content: str                          # 사용자가 수정한 최종 기사 텍스트

    # 이슈 메타데이터
    issue_name: str                            # 이슈명
    issue_description: str                     # 이슈 배경 설명

    # 이슈에 속한 기사 목록 (제목, URL, 언론사만 사용)
    articles_meta: List[Dict[str, Any]]        # [{"title": str, "url": str, "publisher": str, "published_at": str}]

    # 신뢰도 분석 결과
    reliability_score: int                     # 0~100 (유사도 위험도, 높을수록 위험)
    risk_level: str                            # "안전" | "주의" | "위험"
    top_sources: List[Dict[str, Any]]          # 유사 기사 소스 최대 3건

    # 가이드라인 검증 결과 (Gemini)
    guideline_checks: List[Dict[str, Any]]     # [{"label": str, "passed": bool, "detail": str}]

    # AI 종합 의견 (Gemini)
    ai_opinion: str

    messages: Annotated[List[str], operator.add]  # 로그 메시지 수집용
    error: str                                  # 에러 발생 시 에러 메시지
    
    # 토큰 사용량 추적
    total_tokens: Dict[str, int]               # {"prompt_tokens": 0, "completion_tokens": 0}

