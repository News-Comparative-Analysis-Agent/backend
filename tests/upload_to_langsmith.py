import os
import json
from langsmith import Client
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

def upload_dataset():
    """
    로컬의 full_test_data.json을 랭스미스 Dataset으로 업로드합니다.
    """
    client = Client()
    dataset_name = "News-Comparative-Analysis-Dataset"
    
    # 1. 로컬 데이터 로드
    data_path = "tests/full_test_data.json"
    if not os.path.exists(data_path):
        print(f"❌ '{data_path}' 파일을 찾을 수 없습니다.")
        return

    with open(data_path, "r", encoding="utf-8") as f:
        articles = json.load(f)
    
    # 2. 데이터셋 생성 또는 조회
    try:
        if not client.has_dataset(dataset_name=dataset_name):
            dataset = client.create_dataset(
                dataset_name=dataset_name,
                description="멀티에이전트 뉴스 분석 및 평가지표 측정을 위한 벤치마킹 데이터셋"
            )
            print(f"✨ 새로운 데이터셋 생성 완료: {dataset_name}")
        else:
            dataset = client.read_dataset(dataset_name=dataset_name)
            print(f"📚 기존 데이터셋 조회 완료: {dataset_name}")
        
        # 3. 예시(Example) 추가
        # 입력 구조: {"articles": [...]}
        # 중복 업로드 방지를 위해 기존 예시 확인 로직은 생략하거나 별도 처리 가능
        client.create_example(
            inputs={"articles": articles},
            outputs=None, # 아직 기준 정답(Golden Answer)은 없음
            dataset_id=dataset.id,
            metadata={"issue_id": 32, "topic": "김부겸 대구시장 출마"}
        )
        print(f"✅ LangSmith 데이터셋 '{dataset_name}'에 테스트 케이스(Issue 32) 업로드 완료!")
        print(f"🔗 LangSmith UI에서 '{dataset_name}'을 확인하여 벤치마킹 실험을 준비하세요.")

    except Exception as e:
        print(f"❌ 업로드 중 오류 발생: {e}")

if __name__ == "__main__":
    upload_dataset()
