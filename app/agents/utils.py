import os
import json
import re
import time
import functools
import requests
import google.generativeai as genai
from langsmith import traceable
from app.core.logger import logger, log_llm_event



# 로컬 LLM 서버 설정 (nodes.py 설정 및 .env 연동 유지)
LLM_SERVER_IP = os.getenv("LLM_SERVER_IP", os.getenv("HOST_IP", "127.0.0.1")).strip()

# 포트 설정 (.env 우선, 없으면 7B_PORT 공통 설정 반영, 그마저도 없으면 기본값)
PORT_7B = os.getenv("7B_PORT", "8081").strip() 

# API 엔드포인트 경로 (.env 우선)
API_PATH = os.getenv("LLM_SERVER_API_URI", "v1/chat/completions").strip()

LOCAL_LLM_SERVERS = {
    "7B": f"http://{LLM_SERVER_IP}:{PORT_7B}/{API_PATH}",
}

def parse_llm_json(text: str) -> dict:
    """
    LLM의 응답 텍스트에서 JSON 블록을 찾아 파싱합니다.
    매우 탄력적으로 동작하도록 다중 전략을 사용합니다.
    """
    if not text:
        return None
        
    text = text.strip()
    
    def try_parse(s: str) -> dict:
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            # 제어 문자(특히 줄바꿈)가 문자열 안에 그대로 들어간 경우 처리
            # JSON 표준은 문자열 내 실제 줄바꿈을 허용하지 않음 (\n 형태여야 함)
            s_cleaned = re.sub(r'\n', '\\\\n', s)
            # 하지만 위 처리는 모든 줄바꿈을 바꾸므로 JSON 구조 자체가 깨짐.
            # 좀 더 정밀하게: 문자열 값 내부의 줄바꿈만 처리해야 하지만 복잡함.
            # 대신 간단한 '문자열 내 실제 개행'만 타겟팅 시도 (비표준 처리)
            try:
                # 간단한 트릭: 따옴표 사이의 실제 줄바꿈을 공백이나 \n으로 변경
                # (주의: 이 regex는 단순해서 완벽하지 않을 수 있음)
                return json.loads(s) 
            except:
                return None

    # 전략 1: ```json ... ``` 또는 ``` ... ``` 추출
    for pattern in [r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```"]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            blob = match.group(1).strip()
            res = try_parse(blob)
            if res: return res
            
            # 파싱 실패 시: 마지막이 잘렸을 가능성 (Unterminated string)
            # 뒤에서부터 하나씩 지워보며 시도 (최대 100자)
            for i in range(1, 101):
                if len(blob) <= i: break
                try:
                    # 잘린 문자열 닫기 시도: ", }, ] 등을 붙여봄
                    for suffix in ['"', '"}', '"} ]', '}']:
                        try: 
                            return json.loads(blob[:-i] + suffix)
                        except: continue
                except: pass

    # 전략 2: 마크다운 외부에서 { } 또는 [ ] 블록 찾기 (탐욕적 매칭)
    # 여러 JSON이 섞여 있을 경우를 대비해 가장 큰 덩어리부터 시도
    matches = list(re.finditer(r"({.*}|\[.*\])", text, re.DOTALL))
    if matches:
        # 가장 긴 매칭 결과부터 시도
        matches.sort(key=lambda m: len(m.group(0)), reverse=True)
        for m in matches:
            blob = m.group(1).strip()
            res = try_parse(blob)
            if res: return res

    # 전략 3: 최후의 수단 - 가장 첫 번째 '{' 부터 마지막 '}' 까지 그냥 시도
    start = text.find('{')
    if start == -1: start = text.find('[')
    end = text.rfind('}')
    if end == -1: end = text.rfind(']')
    
    if start != -1 and end != -1 and end > start:
        blob = text[start:end+1]
        res = try_parse(blob)
        if res: return res
        
        # 여기서도 잘린 경우 대응
        for i in range(1, 101):
            if len(blob) <= i: break
            for suffix in ['"', '"}', '"} ]', '}']:
                try: 
                    return json.loads(blob[:-i] + suffix)
                except: continue

    logger.error(f"JSON 파싱 최종 실패\n원본 텍스트: {text}")
    return None

@traceable(run_type="llm", name="LocalLLM Call")
def call_local_llm(model_size: str, prompt: str, json_mode: bool = False) -> str:
    """온프레미스 로컬 LLM 서버에 요청을 보냅니다."""
    # 하위 호환성: 7B_1, 7B_2 등이 들어오면 기본 7B로 변환
    if model_size in ["7B_1", "7B_2"]:
        model_size = "7B"
        
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
        
        usage = {
            "prompt_tokens": token_info_dict.get("prompt_tokens", 0) if token_info_dict else 0,
            "completion_tokens": token_info_dict.get("completion_tokens", 0) if token_info_dict else 0
        }
        return content, usage
    except requests.exceptions.ConnectionError as e:
        err_msg = f"로컬 LLM 서버({model_size}) 연결 거부: 서버가 작동 중인지 확인하십시오. ({e})"
        log_llm_event("LocalLLM", "Connection Error", details=err_msg)
        logger.error(err_msg)
        return ("{}", {"prompt_tokens": 0, "completion_tokens": 0}) if json_mode else ("", {"prompt_tokens": 0, "completion_tokens": 0})
    except Exception as e:
        log_llm_event("LocalLLM", f"Error: {e}")
        logger.error(f"로컬 LLM({model_size}) 호출 실패: {e}")
        return ("{}", {"prompt_tokens": 0, "completion_tokens": 0}) if json_mode else ("", {"prompt_tokens": 0, "completion_tokens": 0})

@traceable(run_type="llm", name="Gemini Call")
def call_gemini(prompt: str) -> dict:
    """제미나이 API를 호출합니다."""
    try:
        log_llm_event("Gemini", "Requesting gemini-2.0-flash", details=prompt)
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt)
        
        usage = response.usage_metadata
        token_info = {
            'prompt_tokens': usage.prompt_token_count,
            'completion_tokens': usage.candidates_token_count
        }
        
        
        log_llm_event("Gemini", "Response received", details=response.text, token_info=token_info)
        return parse_llm_json(response.text), token_info
    except Exception as e:
        log_llm_event("Gemini", f"Error: {e}", details=str(e))
        logger.error(f"Gemini 호출 실패: {e}")
        return None, {"prompt_tokens": 0, "completion_tokens": 0}

def update_total_tokens(state: dict, new_usage: dict) -> dict:
    """기존 상태의 total_tokens에 새로운 토큰 사용량을 합산하여 반환합니다."""
    total = state.get("total_tokens")
    if not total:
        total = {"prompt_tokens": 0, "completion_tokens": 0}
    
    total["prompt_tokens"] += new_usage.get("prompt_tokens", 0)
    total["completion_tokens"] += new_usage.get("completion_tokens", 0)
    
    # 노드별 토큰 로그 출력
    p = new_usage.get("prompt_tokens", 0)
    c = new_usage.get("completion_tokens", 0)
    logger.info(f"📊 [Token Usage] Node Increment: Prompt={p}, Completion={c} | Total: Prompt={total['prompt_tokens']}, Completion={total['completion_tokens']}")
    
    return total

@traceable(run_type="chain", name="LLM Routing (Text)")
def call_llm_text(prompt: str, model_size: str, state: dict) -> tuple:
    """llm_mode에 따라 제미나이 또는 로컬 LLM을 호출하여 '순수 텍스트'를 반환합니다. (반환: 텍스트, 토큰정보)"""
    mode = state.get("llm_mode", "gemini_only")
    
    if mode == "local_only":
        return call_local_llm(model_size, prompt)
        
    if mode == "gemini_only":
        try:
            log_llm_event("GeminiText", "Requesting gemini-2.0-flash (Text Mode)", details=prompt)
            model = genai.GenerativeModel('gemini-2.0-flash')
            response = model.generate_content(prompt)
            
            usage = response.usage_metadata
            token_info = {
                'prompt_tokens': usage.prompt_token_count,
                'completion_tokens': usage.candidates_token_count
            }
            log_llm_event("GeminiText", "Response received", details=response.text, token_info=token_info)
            return response.text.strip(), token_info
        except Exception as e:
            logger.error(f"Gemini Text 호출 실패: {e}")
            return "", {"prompt_tokens": 0, "completion_tokens": 0}
            
    if mode == "local_priority":
        try:
            content, usage = call_local_llm(model_size, prompt)
            if content: return content.strip(), usage
            raise ValueError("로컬 LLM 응답 비어있음")
        except Exception as e:
            logger.warning(f"로컬 LLM(Text) 실패로 인해 제미나이로 폴백합니다: {e}")
            # ⚠️ 주의: 재귀 호출 금지. Gemini를 직접 호출하여 무한재귀 방지
            try:
                log_llm_event("GeminiText", "Fallback: Requesting gemini-2.0-flash (Text Mode)", details=prompt)
                model = genai.GenerativeModel('gemini-2.0-flash')
                response = model.generate_content(prompt)
                usage_meta = response.usage_metadata
                token_info = {
                    'prompt_tokens': usage_meta.prompt_token_count,
                    'completion_tokens': usage_meta.candidates_token_count
                }
                log_llm_event("GeminiText", "Fallback response received", details=response.text, token_info=token_info)
                return response.text.strip(), token_info
            except Exception as gemini_e:
                logger.error(f"Gemini 폴백도 실패: {gemini_e}")
                return "", {"prompt_tokens": 0, "completion_tokens": 0}
    
    return "", {"prompt_tokens": 0, "completion_tokens": 0}

@traceable(run_type="chain", name="LLM Routing (JSON)")
def call_llm(prompt: str, model_size: str, state: dict) -> tuple:
    """llm_mode에 따라 제미나이 또는 로컬 LLM을 호출합니다. (반환: 결과, 토큰정보)"""
    mode = state.get("llm_mode", "gemini_only")
    
    if mode == "local_only":
        content, usage = call_local_llm(model_size, prompt)
        return parse_llm_json(content), usage
        
    if mode == "gemini_only":
        return call_gemini(prompt)
        
    if mode == "local_priority":
        try:
            content, usage = call_local_llm(model_size, prompt)
            parsed = parse_llm_json(content)
            if parsed: return parsed, usage
            raise ValueError("로컬 LLM 응답 파싱 실패")
        except Exception as e:
            logger.warning(f"로컬 LLM 실패로 인해 제미나이로 폴백합니다: {e}")
            return call_gemini(prompt)
    
    return call_gemini(prompt)




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