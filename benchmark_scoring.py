import os
import sys
import json

# 프로젝트 경로 설정
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.agents.review import ReviewAgent

def run_benchmark():
    agent = ReviewAgent(db=None)  # DB에 접근하지 않으므로 None
    
    # 벤치마크용 임의의 상태 데이터 (원문 기사 및 이슈 기본 정보)
    base_state = {
        "issue_name": "의료계 파업 갈등",
        "issue_background": "정부의 의대 증원 정책에 반발하여 의료계가 파업을 선언함.",
        "core_contentions": "정부는 필수 의료 인력 부족을 이유로 증원 주장, 의료계는 수가 문제 해결을 우선 주장.",
        "conflict_summary": "정부와 의료계의 입장이 팽팽해 협상이 지연 중.",
        "articles_meta": [
            {
                "title": "의협, 파업 장기화 우려...",
                "content": "의사협회는 정부의 일방적인 의대 정원 확대에 반발하며 무기한 파업에 돌입할 수 있다고 경고했다. 정부는 법과 원칙에 따라 대응하겠다는 입장이다."
            }
        ],
        "total_tokens": {"prompt_tokens": 0, "completion_tokens": 0}
    }
    
    print("====================================================================")
    print(" [벤치마크 1] 공정하고 충실하게 작성된 '정상 초안'")
    print("====================================================================")
    clean_draft = """
정부의 의대 증원 발표 이후 의료계와 정부 간의 대립이 격화되고 있다.
정부 측은 지역과 필수 의료 인력을 확보하기 위해 증원이 불가피하다는 입장이다. 반면 대한의사협회는 현재의 교육 인프라로는 늘어난 인원을 감당하기 어렵고, 근본적인 의료 수가 개선이 선행되어야 한다고 반박하고 있다.
환자 단체들은 양측의 조속한 대화와 합의를 통해 진료 공백이 최소화되기를 촉구하고 있다.
    """
    state_clean = base_state.copy()
    state_clean["pre_generated_draft"] = clean_draft
    
    result_clean = agent.node_analyze_and_opine(state_clean)
    print(json.dumps(result_clean["scores"], indent=2, ensure_ascii=False))
    print("\n[AI 에디터 의견]:", result_clean["ai_opinion"])
    print("\n\n")

    print("====================================================================")
    print(" [벤치마크 2] 욕설, 극단적 감정어, 수치 왜곡(5만명 등)이 포함된 '불량 초안'")
    print("====================================================================")
    toxic_draft = """
아니 진짜 정부 이 버러지 같은 XX들 제정신인가? 지들 맘대로 의대생을 5만명이나 쳐늘린다고 개소리를 지껄이고 있다.
의협은 이런 미친 소리에 아주 기가 막혀서 다 때려부술 기세다.
우리 멍청하고 역겨운 정치인들은 아무 생각 없이 이 쓰레기 정책에 찬성만 누르고 앉아있고.
애초에 의사가 모자란다는 건 좌파 집단들이 꾸며낸 완전한 거짓말이다. 환자들은 알아서 병원 안 가면 그만이지 맨날 징징대고 자빠졌다.
의사들 다 굶어 죽게 만들고 아주 혐오스러운 정책이 아닐 수 없다.
    """
    state_toxic = base_state.copy()
    state_toxic["pre_generated_draft"] = toxic_draft
    
    result_toxic = agent.node_analyze_and_opine(state_toxic)
    print(json.dumps(result_toxic["scores"], indent=2, ensure_ascii=False))
    print("\n[AI 에디터 의견]:", result_toxic["ai_opinion"])

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv() # .env에서 GOOGLE_API_KEY 로드
    run_benchmark()
