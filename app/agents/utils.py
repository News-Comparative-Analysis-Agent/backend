import os
import json
import re
import requests
from app.core.logger import logger, log_llm_event

# 로컬 LLM 서버 설정 (nodes.py 설정 및 .env 연동 유지)
LLM_SERVER_IP = os.getenv("LLM_SERVER_IP", os.getenv("HOST_IP", "127.0.0.1")).strip()

# 포트 설정 (.env 우선, 없으면 기본값)
# PORT_3B = os.getenv("3B_PORT", "8081").strip()
PORT_7B_1 = os.getenv("7B_PORT", "8000").strip() # 기본 추출용
PORT_7B_2 = os.getenv("7B_PORT_WRITER", "8001").strip() # 비평 작성 전용 (있을 경우)

# API 엔드포인트 경로 (.env 우선)
API_PATH = os.getenv("LLM_SERVER_API_URI", "v1/chat/completions").strip()

LOCAL_LLM_SERVERS = {
    # "3B": f"http://{LLM_SERVER_IP}:{PORT_3B}/{API_PATH}",
    "7B_1": f"http://{LLM_SERVER_IP}:{PORT_7B_1}/{API_PATH}",
    "7B_2": f"http://{LLM_SERVER_IP}:{PORT_7B_2}/{API_PATH}",
}

def parse_llm_json(text: str) -> dict:
    """LLM의 응답 텍스트에서 JSON 마크다운 블록을 찾아 파싱합니다."""
    text = text.strip()
    match = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
    else:
        json_str = text
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"JSON 파싱 실패: {e}\n원본 텍스트: {text}")
        return None

def call_local_llm(model_size: str, prompt: str, json_mode: bool = False) -> str:
    """온프레미스 로컬 LLM 서버에 요청을 보냅니다."""
    url = LOCAL_LLM_SERVERS.get(model_size)
    if not url:
        raise ValueError(f"정의되지 않은 LLM 크기입니다: {model_size}")

    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    
    try:
        log_llm_event("LocalLLM", f"Requesting {model_size}", details=f"URL: {url}\nPayload: {json.dumps(payload, ensure_ascii=False)}")
        res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=120)
        res.raise_for_status()
        
        response_data = res.json()
        content = response_data['choices'][0]['message']['content']
        
        token_info_dict = None
        if 'usage' in response_data:
            token_info_dict = response_data['usage']
            
        log_llm_event("LocalLLM", "Response received", details=content, token_info=token_info_dict)
        return content
    except Exception as e:
        log_llm_event("LocalLLM", f"Error: {e}")
        logger.error(f"로컬 LLM({model_size}) 호출 실패: {e}")
        return "{}" if json_mode else ""
