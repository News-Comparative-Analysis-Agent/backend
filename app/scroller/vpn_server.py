import requests
import json
from prompts import PROMPT_POLITICAL_BIAS_1_5B, PROMPT_SUMMARIZATION_3B, PROMPT_ARTICLE_GENERATION_7B

# Configuration
SERVERS = {
    "1.5B": {"port": 8082, "api_url": "http://100.76.232.55:8082/v1/chat/completions"},
    "3B":   {"port": 8081, "api_url": "http://100.76.232.55:8081/v1/chat/completions"},
    "7B":   {"port": 8083, "api_url": "http://100.76.232.55:8083/v1/chat/completions"},
}

def query_llm(model_name, system_prompt, user_message, max_tokens=2048, temperature=0.7):
    url = SERVERS[model_name]["api_url"]
    headers = {"Content-Type": "application/json"}
    data = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    
    try:
        print(f"Sending request to {model_name} model at {url}...")
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content'].strip()
    except Exception as e:
        return f"Error: {str(e)}"

# --- Test Data ---

# 1. Test Data for 1.5B (Political Bias)
SAMPLE_ARTICLE_BIAS = """
(가상 기사)
정부는 오늘 새로운 부동산 정책을 발표했습니다. 이번 정책은 다주택자에 대한 세금을 강화하고, 서민 주거 안정을 위한 공공임대주택 공급을 확대하는 내용을 담고 있습니다. 야당은 이에 대해 "시장 경제를 위축시키는 과도한 규제"라고 비판했습니다.
"""

# 2. Test Data for 3B (Summarization)
# We need to simulate a news article from a specific source.
SAMPLE_ARTICLE_SUMMARY = """
(조선일보 기사라고 가정)
최근 경제 지표가 악화되면서 기업들의 투자가 위축되고 있습니다. 
대기업 A사 관계자는 "정부의 규제 일변도 정책으로 인해 신규 사업 진출이 어려운 상황"이라며 
"과감한 규제 혁파 없이는 경제 성장을 기대하기 어렵다"고 토로했습니다.
전문가들은 노동 시장의 유연성을 확보하고 기업하기 좋은 환경을 만들어야 한다고 입을 모으고 있습니다.
"""

# 3. Test Data for 7B (Article Generation)
# We need a list of summaries.
SAMPLE_SUMMARIES = [
    "- 조선일보는 정부의 규제 강화로 인해 기업 투자가 위축되고 있다고 보도했다.",
    "- 한겨레는 대기업 중심의 경제 구조가 불평등을 심화시키고 있다고 주장했다.",
    "- 중앙일보는 노동 시장의 경직성이 청년 실업의 원인이라고 지적했다.",
    "- 경향신문은 사회 안전망 확충이 시급하며, 정부의 적극적인 재정 역할을 강조했다."
]
SAMPLE_SUMMARIES_TEXT = "\n".join(SAMPLE_SUMMARIES)

# --- Execution ---

def run_tests():
    print("=== 1. 1.5B 모델 테스트 (정치 성향 분석) ===")
    bias_result = query_llm("1.5B", PROMPT_POLITICAL_BIAS_1_5B, SAMPLE_ARTICLE_BIAS, max_tokens=10)
    print(f"결과 (예상치: -5 ~ 5 사이의 정수): {bias_result}\n")

    print("=== 2. 3B 모델 테스트 (기사 요약) ===")
    summary_result = query_llm("3B", PROMPT_SUMMARIZATION_3B, f"(출처: 조선일보)\n{SAMPLE_ARTICLE_SUMMARY}")
    print(f"결과 (예상치: 조선일보 인용 3-5줄 요약):\n{summary_result}\n")

    print("=== 3. 7B 모델 테스트 (비평 기사 생성) ===")
    article_result = query_llm("7B", PROMPT_ARTICLE_GENERATION_7B, f"다음은 각 언론사의 보도 요약입니다:\n{SAMPLE_SUMMARIES_TEXT}")
    print(f"결과 (예상치: 종합 비평 기사):\n{article_result}\n")

if __name__ == "__main__":
    run_tests()
