from langgraph.graph import StateGraph, START, END
from app.scroller.state import CrawlState, ClusterState
from app.scroller.nodes import ScrollerNodes
from sqlalchemy.orm import Session

def create_crawl_graph(db: Session):
    """
    뉴스 크롤링 파이프라인 그래프 (LangGraph) 생성
    과거 삭제 -> 뉴스 크롤링 -> AI 분석 및 DB 저장
    """
    nodes = ScrollerNodes(db)
    workflow = StateGraph(CrawlState)
    
    workflow.add_node("crawl", nodes.node_crawl_news)
    workflow.add_node("analyze_save", nodes.node_analyze_and_save)
    
    workflow.add_edge(START, "crawl")
    workflow.add_edge("crawl", "analyze_save")
    workflow.add_edge("analyze_save", END)
    
    return workflow.compile()

def create_cluster_graph(db: Session):
    """
    이슈 클러스터링 파이프라인 그래프 (LangGraph) 생성
    미분류 불러오기 -> BERTopic 군집화 -> AI 명명 및 통합 저장
    """
    nodes = ScrollerNodes(db)
    workflow = StateGraph(ClusterState)
    
    workflow.add_node("fetch", nodes.node_fetch_unclustered)
    workflow.add_node("cluster", nodes.node_bertopic_cluster)
    workflow.add_node("name_and_save", nodes.node_name_and_save_issues)
    
    workflow.add_edge(START, "fetch")
    workflow.add_edge("fetch", "cluster")
    workflow.add_edge("cluster", "name_and_save")
    workflow.add_edge("name_and_save", END)
    
    return workflow.compile()
