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

class ComparisonState(TypedDict): # 주장 카드 생성 파이프라인 전역 상태 state
    """
    언론사별 주장 비교 분석 파이프라인 전역 상태 데이터
    """
    llm_mode: str                             # "gemini_only", "local_priority", "local_only"
    issue_id: int                             # 분석 대상 이슈 ID
    articles: List[Dict[str, Any]]            # 이슈에 속한 기사 리스트
    extracted_claims: List[Dict[str, Any]]    # 에이전트1이 추출한 언론사별 주장/근거 (JSON 리스트)
    final_analysis: str                       # 에이전트2가 생성한 최종 비평 보고서
    messages: Annotated[List[str], operator.add] # 로그 메시지 수집용
    error: str                                 # 에러 발생 시 에러 메시지 저장

