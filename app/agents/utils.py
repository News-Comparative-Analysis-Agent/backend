import os
import json
import re
import time
import functools
import requests
import threading
from google import genai
from langsmith import traceable
from app.core.logger import logger, log_llm_event

# 로컬 LLM 서버 부하 방지를 위해 요청을 1개씩 직렬화
llm_semaphore = threading.Semaphore(1)



# 로컬 LLM 서버 설정 (nodes.py 설정 및 .env 연동 유지)
LLM_SERVER_IP = os.getenv("LLM_SERVER_IP", os.getenv("HOST_IP", "127.0.0.1")).strip()

# 포트 설정 (.env 우선, 없으면 LOCAL_PORT 공통 설정 반영, 그마저도 없으면 기본값)
LOCAL_PORT = 8081

# API 엔드포인트 경로 (.env 우선)
API_PATH = os.getenv("LLM_SERVER_API_URI", "v1/chat/completions").strip()

LOCAL_LLM_SERVERS = {
    "local": f"http://{LLM_SERVER_IP}:{LOCAL_PORT}/{API_PATH}",
}

def get_local_model_name() -> str:
    """
    로컬 LLM 서버에서 현재 활성화된 모델의 ID 또는 이름을 조회합니다.
    (OpenAI, Ollama, llama.cpp 등 다양한 응답 구조 대응)
    """
    try:
        url = f"http://{LLM_SERVER_IP}:{LOCAL_PORT}/v1/models"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            # 1. 표준 OpenAI 포맷 (data[0].id)
            if "data" in data and len(data["data"]) > 0:
                return data["data"][0].get("id", "Unknown-Local-Model")
            # 2. Ollama/llama.cpp 변형 포맷 (models[0].name)
            elif "models" in data and len(data["models"]) > 0:
                model_info = data["models"][0]
                return model_info.get("name") or model_info.get("id") or "Unknown-Local-Model"
    except Exception as e:
        logger.warning(f"⚠️ 로컬 모델명 조회실제 실패 (IP: {LLM_SERVER_IP}): {e}")
    
    return os.getenv("LLM_MODEL_NAME", "Qwen/Qwen2.5-7B-Instruct").strip()

# 로컬 모델 이름 설정
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "Qwen/Qwen2.5-7B-Instruct").strip()

def parse_llm_json(text: str) -> any:
    """
    LLM의 응답 텍스트에서 JSON 블록을 찾아 파싱합니다.
    다중 시작점 탐색 및 부분 복구(force-close)를 통해 매우 높은 복구율을 가집니다.
    """
    if not text: return None
    
    def force_close_json(s: str) -> any:
        s = s.strip()
        # 끝부분에서부터 잘린 지점을 찾아 닫는 괄호들을 조합하여 시도
        # 최대 1000자까지 뒤로 가며 시도 (이전 300자에서 확장)
        for i in range(len(s), max(0, len(s)-1000), -1):
            sub = s[:i]
            # 다양한 닫는 패턴 시도
            for suffix in ['"', '"}', '"]', '}', ']', '"}]', '"}]}', '"}]} ]']:
                try:
                    return json.loads(sub + suffix)
                except:
                    continue
        return None

    def try_parse(s: str) -> any:
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return force_close_json(s)

    # 1. 마크다운 코드 블록 우선 처리
    for pattern in [r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```"]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            blob = match.group(1).strip()
            res = try_parse(blob)
            if res: return res

    # 2. 다중 시작점 탐색 및 스키마 점수화 (Phase 2)
    results = []
    # 모든 { 또는 [ 위치를 찾음
    for m in re.finditer(r"\{|\[", text):
        start_idx = m.start()
        blob = text[start_idx:].strip()
        
        # 기호에 맞는 닫는 문자 탐색
        end_char = '}' if text[start_idx] == '{' else ']'
        for end_m in re.finditer(re.escape(end_char), blob):
            end_idx = end_m.start() + 1
            sub_blob = blob[:end_idx]
            res = try_parse(sub_blob)
            if res: results.append(res)
        
        # 전체 덩어리(잘린 경우 대비) 시도
        res = try_parse(blob)
        if res: results.append(res)

    if not results:
        logger.error(f"JSON 파싱 최종 실패\n원본 텍스트: {text[:500]}...")
        return None

    # 3. 결과 채점 (가장 신뢰도 높은 객체 선택)
    def score_object(obj):
        if obj is None: return -1
        score = 0
        # 리스트인 경우 내부 요소 확인
        if isinstance(obj, list):
            score += len(obj) * 2
            if len(obj) > 0 and isinstance(obj[0], dict):
                first = obj[0]
                if 'contention_title' in first: score += 50
                if 'press' in first: score += 10
        # 딕셔너리인 경우 키 확인
        elif isinstance(obj, dict):
            score += len(obj.keys())
            if 'claim' in obj: score += 20
            if 'title' in obj: score += 10
            if 'conflict_summary' in obj: score += 50
            if 'media_narratives' in obj: score += 30
            if 'contention_title' in obj: score += 10 # 과거 버전 호환성 유지 (점수 낮춤)
            if 'metrics' in obj: score += 50
            if 'details' in obj: score += 50
            if 'ai_opinion' in obj: score += 50
        return score

    results.sort(key=score_object, reverse=True)
    return results[0]

@traceable(run_type="llm", name="LocalLLM Call")
def call_local_llm(model_size: str, prompt: str, json_mode: bool = False, schema: dict = None) -> str:
    """온프레미스 로컬 LLM 서버에 요청을 보냅니다 (재시도 및 예외 전파 포함)."""
        
    url = LOCAL_LLM_SERVERS.get(model_size)
    if not url:
        raise ValueError(f"정의되지 않은 LLM 크기입니다: {model_size}")

    actual_model = get_local_model_name()
    # 랭스미스 트레이싱용 메타데이터 태깅
    metadata = {"model_name": actual_model, "server_ip": LLM_SERVER_IP}
    
    payload = {
        "model": actual_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 8192  # 기사 잘림 방지를 위해 출력 한도 대폭 상향
    }
    
    # JSON 모드 혹은 스키마가 제공된 경우 response_format 추가 지원 (vLLM, Ollama, MLX 등 OpenAI 호환 서버 대응)
    if json_mode or schema:
        payload["response_format"] = {"type": "json_object"}

    max_retries = 3
    for attempt in range(max_retries):
        try:
            # log_llm_event("LocalLLM", f"Requesting {actual_model} (Attempt {attempt+1})", details=f"URL: {url}\nPayload: {json.dumps(payload, ensure_ascii=False)}")
            
            # 랭스미스 태그 및 메타데이터 동적 주입을 위해 log_llm_event에 tags 정보 전달 가능 여부 확인 후 업데이트
            res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=300)
            res.raise_for_status()
            
            response_data = res.json()
            content = response_data['choices'][0]['message']['content']
            
            # Raw Response 로깅 추가 (디버깅 시에만 사용)
            # log_llm_event("LocalLLM", f"Response received from {actual_model}", details=content)
            
            token_info_dict = response_data.get('usage')
            usage = {
                "prompt_tokens": token_info_dict.get("prompt_tokens", 0) if token_info_dict else 0,
                "completion_tokens": token_info_dict.get("completion_tokens", 0) if token_info_dict else 0
            }
            return content, usage
            
        except (requests.exceptions.RequestException, Exception) as e:
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) + 0.5 # Exponential backoff with simple jitter
                logger.warning(f"로컬 LLM({actual_model}) 호출 실패 (시도 {attempt+1}): {e}. {wait_time}초 후 재시도...")
                time.sleep(wait_time)
            else:
                log_llm_event("LocalLLM", f"Error after {max_retries} attempts: {e}")
                logger.error(f"로컬 LLM({actual_model}) 최종 호출 실패: {e}")
                raise e # 최종 실패 시 예외를 던져서 상위(Gemini Fallback)에서 처리하게 함

# Gemini 클라이언트 초기화 코드 (지연 로딩)
_gemini_client = None

def get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("GOOGLE_API_KEY가 설정되지 않았습니다.")
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client

@traceable(run_type="llm", name="Gemini Call")
def call_gemini(prompt: str, schema: dict = None) -> dict:
    """제미나이 API를 호출합니다."""
    # 랭스미스 트레이싱용 메타데이터 태깅
    metadata = {"model_name": "gemini-2.0-flash", "provider": "google"}
    
    try:
        # log_llm_event("Gemini", "Requesting gemini-2.0-flash", details=prompt)
        client = get_gemini_client()
        
        generate_kwargs = {
            "model": 'gemini-2.0-flash',
            "contents": prompt
        }
        
        if schema:
            generate_kwargs["config"] = {
                "response_mime_type": "application/json",
                "response_schema": schema
            }

        response = client.models.generate_content(**generate_kwargs)
        
        usage = response.usage_metadata
        token_info = {
            'prompt_tokens': usage.prompt_token_count,
            'completion_tokens': usage.candidates_token_count
        }
        
        # log_llm_event("Gemini", "Response received", details=response.text, token_info=token_info)
        return parse_llm_json(response.text), token_info
    except Exception as e:
        log_llm_event("Gemini", f"Error: {e}", details=str(e))
        logger.error(f"Gemini 호출 실패: {e}")
        return None, {"prompt_tokens": 0, "completion_tokens": 0}

def update_total_tokens(state: dict, new_usage: dict, agent_name: str = "Unknown") -> dict:
    """기존 상태의 total_tokens에 새로운 토큰 사용량을 합산하여 반환합니다."""
    total = state.get("total_tokens")
    if not total:
        total = {"prompt_tokens": 0, "completion_tokens": 0}
    
    total["prompt_tokens"] += new_usage.get("prompt_tokens", 0)
    total["completion_tokens"] += new_usage.get("completion_tokens", 0)
    
    # 노드별 토큰 로그 출력
    p = new_usage.get("prompt_tokens", 0)
    c = new_usage.get("completion_tokens", 0)
    logger.info(f"📊 [{agent_name}] Token Usage: Prompt={p}, Completion={c} | Total: Prompt={total['prompt_tokens']}, Completion={total['completion_tokens']}")
    
    return total

@traceable(run_type="chain", name="LLM Routing (Text)")
def call_llm_text(prompt: str, model_size: str, state: dict) -> tuple:
    """llm_mode에 따라 제미나이 또는 로컬 LLM을 호출하여 '순수 텍스트'를 반환합니다. (반환: 텍스트, 토큰정보)"""
    mode = state.get("llm_mode", "gemini_only")
    
    if mode == "local_only":
        with llm_semaphore:
            return call_local_llm(model_size, prompt)
            
    if mode == "gemini_only":
        try:
            # log_llm_event("GeminiText", "Requesting gemini-2.0-flash (Text Mode)", details=prompt)
            client = get_gemini_client()
            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt
            )
            
            usage = response.usage_metadata
            token_info = {
                'prompt_tokens': usage.prompt_token_count,
                'completion_tokens': usage.candidates_token_count
            }
            # log_llm_event("GeminiText", "Response received", details=response.text, token_info=token_info)
            return response.text.strip(), token_info
        except Exception as e:
            logger.error(f"Gemini Text 호출 실패: {e}")
            return "", {"prompt_tokens": 0, "completion_tokens": 0}
            
    if mode == "local_priority":
        try:
            with llm_semaphore:
                content, usage = call_local_llm(model_size, prompt)
            if content: return content.strip(), usage
            raise ValueError("로컬 LLM 응답 비어있음")
        except Exception as e:
            logger.warning(f"로컬 LLM(Text) 실패로 인해 제미나이로 폴백합니다: {e}")
            try:
                # log_llm_event("GeminiText", "Fallback: Requesting gemini-2.0-flash (Text Mode)", details=prompt)
                client = get_gemini_client()
                response = client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=prompt
                )
                usage_meta = response.usage_metadata
                token_info = {
                    'prompt_tokens': usage_meta.prompt_token_count,
                    'completion_tokens': usage_meta.candidates_token_count
                }
                # log_llm_event("GeminiText", "Fallback response received", details=response.text, token_info=token_info)
                return response.text.strip(), token_info
            except Exception as gemini_e:
                logger.error(f"Gemini 폴백도 실패: {gemini_e}")
                return "", {"prompt_tokens": 0, "completion_tokens": 0}
    
    return "", {"prompt_tokens": 0, "completion_tokens": 0}

@traceable(run_type="chain", name="LLM Routing (JSON)")
def call_llm(prompt: str, model_size: str, state: dict, schema: dict = None) -> tuple:
    """llm_mode에 따라 제미나이 또는 로컬 LLM을 호출합니다. (반환: 결과, 토큰정보)"""
    mode = state.get("llm_mode", "gemini_only")
    
    if mode == "local_only":
        with llm_semaphore:
            content, usage = call_local_llm(model_size, prompt, schema=schema)
        return parse_llm_json(content), usage
        
    if mode == "gemini_only":
        return call_gemini(prompt, schema=schema)
        
    if mode == "local_priority":
        try:
            with llm_semaphore:
                content, usage = call_local_llm(model_size, prompt, schema=schema)
            parsed = parse_llm_json(content)
            if parsed: return parsed, usage
            raise ValueError("로컬 LLM 응답 파싱 실패")
        except Exception as e:
            logger.warning(f"로컬 LLM 실패로 인해 제미나이로 폴백합니다: {e}")
            return call_gemini(prompt, schema=schema)
    
    return call_gemini(prompt, schema=schema)




def log_execution_time(node_name: str):
    """노드의 실행 시간을 측정하여 로깅하는 데코레이터"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            logger.info(f"⏱️ [{node_name}] 실행 시작...")
            result = func(*args, **kwargs)
            end_time = time.perf_counter()
            duration = end_time - start_time
            logger.info(f"⏱️ [{node_name}] 실행 완료 (소요 시간: {duration:.2f}초)")
            # 상태 메시지에도 시간 정보 추가 (선택 사항)
            if isinstance(result, dict) and "messages" in result:
                result["messages"].append(f"{node_name} 소요 시간: {duration:.2f}s")
            return result
        return wrapper
    return decorator