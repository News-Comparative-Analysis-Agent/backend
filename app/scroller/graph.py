from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Send, RetryPolicy
from sqlalchemy.orm import Session

# 새로운 agents 상태 임포트
from app.agents.state import CrawlState, ClusterState, OverallState, ComparisonState
from app.core.logger import logger
from app.agents.utils import log_execution_time

# 자동 재시도 정책 정의
RETRY_POLICY = RetryPolicy(max_attempts=3)

def create_crawl_graph(db: Session):
    """뉴스 크롤링 및 AI 분석 파이프라인 그래프 (LangGraph) 생성"""
    from app.agents.scout import ScoutAgent
    scout = ScoutAgent(db)
    workflow = StateGraph(CrawlState)
    workflow.add_node("cleanup", scout.cleanup_old_data)
    workflow.add_node("crawl", scout.node_crawl, retry=RETRY_POLICY)
    workflow.add_node("analyze_save", scout.node_save_articles, retry=RETRY_POLICY)
    workflow.add_edge(START, "cleanup")
    workflow.add_edge("cleanup", "crawl")
    workflow.add_edge("crawl", "analyze_save")
    workflow.add_edge("analyze_save", END)
    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)

def create_cluster_graph(db: Session):
    """이슈 클러스터링 및 명명 파이프라인 그래프 (LangGraph) 생성"""
    from app.agents.cluster import ClusterAgent
    cluster = ClusterAgent(db)
    workflow = StateGraph(ClusterState)
    workflow.add_node("fetch", cluster.node_fetch_unclustered)
    workflow.add_node("cluster", cluster.node_lexical_cluster, retry=RETRY_POLICY)
    workflow.add_node("name_and_save", cluster.node_name_and_save_issues, retry=RETRY_POLICY)
    workflow.add_node("cleanup_unclustered", cluster.node_cleanup_unclustered)
    workflow.add_edge(START, "fetch")
    workflow.add_edge("fetch", "cluster")
    workflow.add_edge("cluster", "name_and_save")
    workflow.add_edge("name_and_save", "cleanup_unclustered")
    workflow.add_edge("cleanup_unclustered", END)
    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)

def create_analysis_subgraph():
    """단일 이슈 분석을 위한 내부 서브 그래프 (ComparisonState 사용) - 병렬 처리를 위해 노드별 독립 DB 세션 사용"""
    from app.agents.evidence import EvidenceAgent
    from app.agents.issue import IssueAgent
    from app.agents.writer import WriterAgent
    from app.agents.editor import EditorAgent
    from app.agents.judge import JudgeAgent
    from app.core.database import SessionLocal
    
    workflow = StateGraph(ComparisonState)
    
    # 병렬 스레드에서 DB 충돌(TransactionClosedError)을 막기 위해 노드 래퍼 함수 정의
    def fetch_wrapper(state):
        with SessionLocal() as db:
            return EvidenceAgent(db).node_fetch_articles(state)
            
    def evidence_wrapper(state):
        with SessionLocal() as db:
            return EvidenceAgent(db).node_extract_claims(state)
            
    def issue_wrapper(state):
        with SessionLocal() as db:
            return IssueAgent(db).node_structure_issues(state)
            
    def writer_wrapper(state):
        return WriterAgent().node_write_draft(state)
        
    def editor_wrapper(state):
        with SessionLocal() as db:
            return EditorAgent(db).node_edit_draft(state)
        
    def judge_wrapper(state):
        with SessionLocal() as db:
            return JudgeAgent(db).node_evaluate_draft(state)
    
    # 노드 등록 (래퍼 함수 사용)
    workflow.add_node("fetch", fetch_wrapper)
    workflow.add_node("evidence", evidence_wrapper, retry=RETRY_POLICY)
    workflow.add_node("issue", issue_wrapper, retry=RETRY_POLICY)
    workflow.add_node("writer", writer_wrapper, retry=RETRY_POLICY)
    workflow.add_node("judge", judge_wrapper, retry=RETRY_POLICY)
    
    # 엣지 정의
    workflow.add_edge(START, "fetch")
    workflow.add_edge("fetch", "evidence")
    workflow.add_edge("evidence", "issue")
    workflow.add_edge("issue", "writer")
    workflow.add_edge("writer", "judge")
    
    # 순환 라우팅 (재작성/재교정)
    def route_from_judge(state: ComparisonState) -> str:
        status = state.get("judge_status", "")
        retry = state.get("retry_count", 0)
        if retry >= 3 or status == "PASS":
            return END
        return "writer"

    workflow.add_conditional_edges("judge", route_from_judge, {"writer": "writer", END: END})
    
    return workflow.compile()

@log_execution_time("issue_generation_pipeline")
def create_comparison_graph(db: Session):
    """전체 메인 파이프라인 (OverallState 사용)"""
    from app.agents.scout import ScoutAgent
    from app.agents.cluster import ClusterAgent
    
    scout_agent = ScoutAgent(db)
    cluster_agent = ClusterAgent(db)
    
    # 분석 서브 그래프 컴파일 (db 세션 의존성 제거됨)
    analysis_subgraph = create_analysis_subgraph()
    
    workflow = StateGraph(OverallState)
    
    # 1. 시퀀셜 공통 노드
    workflow.add_node("crawl", scout_agent.node_crawl)
    workflow.add_node("save", scout_agent.node_save_articles)
    workflow.add_node("cluster_fetch", cluster_agent.node_fetch_unclustered)
    workflow.add_node("cluster", cluster_agent.node_lexical_cluster)
    workflow.add_node("cluster_save", cluster_agent.node_name_and_save_issues)
    workflow.add_node("cluster_cleanup", cluster_agent.node_cleanup_unclustered)
    
    # 2. 병렬 분석 노드 (서브 그래프 호출용 래퍼)
    def run_analysis_worker(state: OverallState):
        """서브 그래프를 독립적으로 실행하고 결과만 반환합니다."""
        from app.core.database import SessionLocal
        # state는 Send()로부터 전달받은 단일 이슈 처리용 데이터
        issue_id = state.get("issue_id")
        llm_mode = state.get("llm_mode")
        
        # ✅ DB에서 해당 이슈의 '진짜' 상세 정보를 로드 (OverallState는 이를 들고 있지 않음)
        with SessionLocal() as db:
            from app.scroller.repository import ScrollerRepository
            repo = ScrollerRepository(db)
            issue = repo.get_issue_by_id(issue_id)
            
            # 서브 그래프 실행 (초기 상태 설정 - DB에서 로드한 메타데이터 주입)
            sub_initial_state = {
                "issue_id": issue_id,
                "llm_mode": llm_mode,
                "title": issue.name if issue else "",
                "description": issue.description if issue else "",
                "background": issue.background if issue else "",
                "messages": [],
                "total_tokens": {"prompt_tokens": 0, "completion_tokens": 0}
            }
        
        # invoke로 개별 스레드/프로세스 환경에서 실행
        final_state = analysis_subgraph.invoke(sub_initial_state)
        
        # ✅ 메인 그래프(OverallState)로 돌려보낼 데이터 추출 (저장 및 후속 처리를 위해 필드 확장)
        return {
            "conflict_summary": final_state.get("conflict_summary", ""),
            "messages": final_state.get("messages", []),
            "total_tokens": final_state.get("total_tokens", {"prompt_tokens": 0, "completion_tokens": 0})
        }
        
    workflow.add_node("analysis_worker", run_analysis_worker)
    
    # 라우팅 1: 시작 시점
    def route_start(state: OverallState) -> str:
        if state.get("issue_id"): return "analysis_worker"
        if state.get("unclustered_articles") and len(state["unclustered_articles"]) > 0:
            return "cluster"
        return "crawl"

    workflow.add_conditional_edges(START, route_start, {"crawl": "crawl", "analysis_worker": "analysis_worker", "cluster": "cluster"})
    
    # 공통 흐름
    workflow.add_edge("crawl", "save")
    workflow.add_edge("save", "cluster_fetch")
    workflow.add_edge("cluster_fetch", "cluster")
    workflow.add_edge("cluster", "cluster_save")
    workflow.add_edge("cluster_save", "cluster_cleanup")
    
    # 라우팅 2: Map (Send)
    def map_analysis_tasks(state: OverallState):
        issue_ids = state.get("all_issue_ids", [])
        if not issue_ids:
            logger.info("🏁 [Graph] 분석할 이슈가 없어 파이프라인을 종료합니다.")
            return END
        
        logger.info(f"🗺️ [Graph] 총 {len(issue_ids)}개 이슈에 대한 병렬 분석 분기 시작 (Map)")
        # 서브 그래프로 작업 분배
        return [Send("analysis_worker", {"issue_id": iid, "llm_mode": state.get("llm_mode")}) for iid in issue_ids]

    workflow.add_conditional_edges("cluster_cleanup", map_analysis_tasks, ["analysis_worker", END])
    
    # 분석 완료 후 종료
    workflow.add_edge("analysis_worker", END)
    
    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)


@log_execution_time("review_pipeline")
def create_review_graph(db: Session):
    """
    최종 품질 검토 파이프라인 그래프 (LangGraph) 생성
    [Chain: Fetch -> Analysis]
    """
    from app.agents.state import ReviewState
    from app.agents.review import ReviewAgent
    
    agent = ReviewAgent(db)
    
    # 1. 상태(State) 정의와 함께 그래프 초기화
    workflow = StateGraph(ReviewState)
    
    # 노드 등록
    workflow.add_node("fetch", agent.node_fetch_articles)
    workflow.add_node("analyze", agent.node_analyze_and_opine)
    
    # 순차적 엣지 정의
    workflow.add_edge(START, "fetch")
    workflow.add_edge("fetch", "analyze")
    workflow.add_edge("analyze", END)
    
    # 체크포인터 없이 컴파일 (실시간 요청-응답형)
    return workflow.compile()

