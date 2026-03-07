from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import RetryPolicy
from sqlalchemy.orm import Session

# 새로운 agents 상태 임포트
from app.agents.state import CrawlState, ClusterState, ComparisonState
from app.scroller.nodes import ScrollerNodes

# 자동 재시도 정책 정의
# 외부 API(네이버, 제미나이, 로컬 LLM) 통신 오류 시 최대 3회 재시도 (지수 백오프 적용)
RETRY_POLICY = RetryPolicy(max_attempts=3)

def create_crawl_graph(db: Session):
    """
    뉴스 크롤링 및 AI 분석 파이프라인 그래프 (LangGraph) 생성
    - RetryPolicy: 크롤링 및 분석 노드에 적용
    - Checkpointer: 장애 복구를 위한 상태 저장소 적용
    """
    from app.agents.scout import ScoutAgent
    nodes = ScrollerNodes(db)
    scout = ScoutAgent(db)
    
    # 1. 상태(State) 정의와 함께 그래프 초기화
    workflow = StateGraph(CrawlState)
    
    # 노드 등록 (재시도 정책 적용)
    workflow.add_node("cleanup", nodes.node_clean_old_data) # 과거 데이터 정리 노드
    workflow.add_node("crawl", scout.node_crawl, retry=RETRY_POLICY) # 비동기 뉴스 수집 (ScoutAgent)
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

def create_comparison_graph(db: Session):
    """
    언론사별 주장을 비교 분석 파이프라인 그래프 (LangGraph) 생성
    [5-Step Multi-Agent Hybrid Architecture]
    - Agent 1 (Evidence): 각 기사별 주장/근거 추출 (JSON 카드)
    - Agent 2 (Issue): 추출된 역량 쟁점화 (JSON 구조)
    - Agent 3 (Writer): 고정 템플릿 기반 초안 작성
    - Agent 4 (Editor): 표현 다듬기 및 톤앤매너 교정
    - Agent 5 (Judge): 품질 검수 및 라우팅 판별 (PASS / FAIL_WRITER / FAIL_EDITOR)
    """
    from app.agents.evidence import EvidenceAgent
    from app.agents.issue import IssueAgent
    from app.agents.writer import WriterAgent
    from app.agents.editor import EditorAgent
    from app.agents.judge import JudgeAgent
    
    evidence_agent = EvidenceAgent(db)
    issue_agent = IssueAgent()
    writer_agent = WriterAgent()
    editor_agent = EditorAgent()
    judge_agent = JudgeAgent()
    
    # 1. 상태(State) 정의와 함께 그래프 초기화
    workflow = StateGraph(ComparisonState)
    
    # 노드 등록
    workflow.add_node("fetch", evidence_agent.node_fetch_articles)             # 원문 로드
    workflow.add_node("evidence", evidence_agent.node_extract_claims, retry=RETRY_POLICY) # 주장 카드 추출
    workflow.add_node("issue", issue_agent.node_structure_issues, retry=RETRY_POLICY)     # 쟁점 구조화
    workflow.add_node("writer", writer_agent.node_write_draft, retry=RETRY_POLICY)        # 초안 생성
    workflow.add_node("editor", editor_agent.node_edit_draft, retry=RETRY_POLICY)         # 데스크 교정
    workflow.add_node("judge", judge_agent.node_evaluate_draft, retry=RETRY_POLICY)       # 최종 검수
    
    # 엣지 정의 (선형 흐름)
    workflow.add_edge(START, "fetch")
    workflow.add_edge("fetch", "evidence")
    workflow.add_edge("evidence", "issue")
    workflow.add_edge("issue", "writer")
    workflow.add_edge("writer", "editor")
    workflow.add_edge("editor", "judge")
    
    # 순환 라우팅 함수 (재시도 및 패스 체크)
    def route_from_judge(state) -> str:
        status = state.get("judge_status", "")
        retry = state.get("retry_count", 0)
        
        # 최대 3번까지만 반려 허용
        if retry >= 3:
            return END
            
        if status == "FAIL_WRITER":
            return "writer"  # 기사 내용 자체가 부실하면 기자가 다시 씀
        elif status == "FAIL_EDITOR":
            return "editor"  # 톤이나 반복 문제면 데스크가 다시 수정
        else:
            return END       # PASS면 종료

    # Judge 결과에 따른 조건부 엣지 매핑
    workflow.add_conditional_edges(
        "judge",
        route_from_judge,
        {
            "writer": "writer",
            "editor": "editor",
            END: END
        }
    )
    
    # 메모리 기반 체크포인터 적용하여 컴파일
    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)
