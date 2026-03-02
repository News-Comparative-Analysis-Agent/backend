from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import RetryPolicy
from app.scroller.state import CrawlState, ClusterState
from app.scroller.nodes import ScrollerNodes
from sqlalchemy.orm import Session

# 자동 재시도 정책 정의
# 외부 API(네이버, 제미나이, 로컬 LLM) 통신 오류 시 최대 3회 재시도 (지수 백오프 적용)
RETRY_POLICY = RetryPolicy(max_attempts=3)

def create_crawl_graph(db: Session):
    """
    뉴스 크롤링 및 AI 분석 파이프라인 그래프 (LangGraph) 생성
    - RetryPolicy: 크롤링 및 분석 노드에 적용
    - Checkpointer: 장애 복구를 위한 상태 저장소 적용
    """
    nodes = ScrollerNodes(db)
    
    # 1. 상태(State) 정의와 함께 그래프 초기화
    workflow = StateGraph(CrawlState)
    
    # 노드 등록 (재시도 정책 적용)
    workflow.add_node("cleanup", nodes.node_clean_old_data) # 과거 데이터 정리 노드
    workflow.add_node("crawl", nodes.node_crawl_news, retry=RETRY_POLICY) # 뉴스 수집 노드
    workflow.add_node("analyze_save", nodes.node_analyze_and_save, retry=RETRY_POLICY) # AI 분석 및 저장 노드
    
    # 엣지 정의
    workflow.add_edge(START, "cleanup") # 시작 시 바로 정리 작업 진입
    workflow.add_edge("cleanup", "crawl") # 정리 후 크롤링 시작
    workflow.add_edge("crawl", "analyze_save") # 크롤링 완료 후 분석 및 저장 수행
    workflow.add_edge("analyze_save", END) # 모든 작업 완료 후 종료
    
    # 메모리 기반 체크포인터 적용하여 컴파일
    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)

def create_cluster_graph(db: Session):
    """
    이슈 클러스터링 및 명명 파이프라인 그래프 (LangGraph) 생성
    - RetryPolicy: 군집화 및 명명 노드에 적용
    - Checkpointer: 장애 복구를 위한 상태 저장소 적용
    """
    nodes = ScrollerNodes(db)
    
    # 1. 상태(State) 정의와 함께 그래프 초기화
    workflow = StateGraph(ClusterState)
    
    # 노드 등록 (재시도 정책 적용)
    workflow.add_node("fetch", nodes.node_fetch_unclustered) # 미분류 데이터 로드 노드
    workflow.add_node("cluster", nodes.node_bertopic_cluster, retry=RETRY_POLICY) # AI 군집화 노드
    workflow.add_node("name_and_save", nodes.node_name_and_save_issues, retry=RETRY_POLICY) # 이슈 명명 및 통합 저장 노드
    
    # 엣지 정의
    workflow.add_edge(START, "fetch") # 시작 시 데이터 로드 진입
    workflow.add_edge("fetch", "cluster") # 로드 완료 후 군집화 수행
    workflow.add_edge("cluster", "name_and_save") # 군집화 완료 후 이슈 이름 작성 및 저장
    workflow.add_edge("name_and_save", END) # 모든 작업 완료 후 종료
    
    # 메모리 기반 체크포인터 적용하여 컴파일
    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)
