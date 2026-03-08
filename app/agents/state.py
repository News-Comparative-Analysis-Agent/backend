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

class ComparisonState(TypedDict):
    """
    5단계 멀티 에이전트 하이브리드 파이프라인 전역 상태 데이터 
    (Evidence ➡️ Issue ➡️ Writer ➡️ Editor ➡️ Judge)
    """
    llm_mode: str                             # "gemini_only", "local_priority", "local_only"
    issue_id: int                             # 분석 대상 이슈 ID
    
    # 통합 파이프라인 중간 단계 데이터
    raw_articles: List[Dict[str, Any]]        # 크롤링된 기사 리스트
    unclustered_articles: List[Dict[str, Any]] # 이슈 미배정 기사 리스트
    clustered_topics: List[Dict[str, Any]]     # 군집화된 토픽 상세 리스트
    
    articles: List[Dict[str, Any]]            # 최종 분석 대상 이슈에 속한 기사 리스트
    
    # 1. Evidence Agent 출력
    claim_cards: List[Dict[str, Any]]         # 매체별 주장 카드 (주장 1문장, 원문 인용 근거, 기사 URL/매체)
    
    # 2. Issue Agent 출력
    structured_issues: List[Dict[str, Any]]   # 구조화된 쟁점 리스트 (쟁점 제목, 매체별 차이, 근거 claim_id)
    
    # 3. Writer Agent 출력
    draft_article: str                        # 비평 기사 초안 (마크다운)
    
    # 4. Editor Agent 출력
    edited_article: str                       # 수정/톤 정제된 비평 기사
    edit_log: str                             # 에디터 수정 로그
    
    # 5. Judge Agent 출력 및 라우팅 상태
    judge_status: str                         # "PASS", "FAIL_WRITER", "FAIL_EDITOR"
    judge_feedback: str                       # 재판관의 피드백 코멘트
    retry_count: int                          # 현재 루프 재시도 횟수
    
    messages: Annotated[List[str], operator.add] # 로그 메시지 수집용
    error: str                                 # 에러 발생 시 에러 메시지 저장
