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

# 로컬 LLM 및 Gemini 서버 부하 방지를 위해 요청을 제어
llm_semaphore = threading.Semaphore(1)
gemini_semaphore = threading.Semaphore(1) # TPM 제한이 엄격하므로 순차 처리 권장


# 로컬 LLM 서버 설정 (nodes.py 설정 및 .env 연동 유지)
LLM_SERVER_IP = os.getenv("LLM_SERVER_IP", os.getenv("HOST_IP", "127.0.0.1")).strip()

# 포트 설정 (.env 우선, 없으면 LOCAL_PORT 공통 설정 반영, 그마저도 없으면 기본값)
PORT = os.getenv("PORT", os.getenv("LOCAL_PORT", "8081")).strip() 

# API 엔드포인트 경로 (.env 우선)
API_PATH = os.getenv("LLM_SERVER_API_URI", "v1/chat/completions").strip()

LOCAL_LLM_SERVERS = {
    "local": f"http://{LLM_SERVER_IP}:{PORT}/{API_PATH}",
}

# 로컬 모델 이름 설정
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "Qwen3-8B-Instruct").strip()
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash").strip()


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
        # 4. 휴리스틱 복구: JSON 기호가 전혀 없지만 텍스트가 충분히 긴 경우 (로컬 LLM 답변 이탈 대응)
        if len(text.strip()) > 100:
            logger.warning("⚠️ JSON 기호를 찾을 수 없어 원문 텍스트를 'article_body'로 래핑하여 강제 복구합니다.")
            return {"article_body": text.strip()}
            
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
            if 'contention_title' in obj: score += 10 # 과거 버전 호환성 유지
            if 'metrics' in obj: score += 50
            if 'details' in obj: score += 50
            if 'ai_opinion' in obj: score += 50
        return score

    results.sort(key=score_object, reverse=True)
    return results[0]

@traceable(run_type="llm", name="LocalLLM Call")
def call_local_llm(model_size: str, prompt: str, json_mode: bool = False, schema: dict = None) -> str:
    """온프레미스 로컬 LLM 서버에 요청을 보냅니다 (재시도 및 예외 전파 포함)."""
        
    use_deepinfra = os.getenv("LLM_USE_DEEPINFRA", "false").lower() == "true"
    deepinfra_api_key = os.getenv("DEEPINFRA_API_KEY")

    if use_deepinfra and deepinfra_api_key:
        url = "https://api.deepinfra.com/v1/openai/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {deepinfra_api_key}"
        }
        target_name = "DeepInfra"
    else:
        url = LOCAL_LLM_SERVERS.get(model_size)
        headers = {"Content-Type": "application/json"}
        target_name = "LocalLLM"
        if not url:
            raise ValueError(f"정의되지 않은 LLM 크기입니다: {model_size}")

    payload = {
        "model": LLM_MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 32768
    }
    
    # JSON 모드 혹은 스키마가 제공된 경우 response_format 추가 지원 (vLLM, Ollama, MLX 등 OpenAI 호환 서버 대응)
    if json_mode or schema:
        payload["response_format"] = {"type": "json_object"}

    max_retries = 3
    for attempt in range(max_retries):
        try:
            log_llm_event(target_name, f"Requesting {LLM_MODEL_NAME} (Attempt {attempt+1})", details=prompt)
            res = requests.post(url, json=payload, headers=headers, timeout=300)
            
            if res.status_code == 400:
                error_detail = res.text
                logger.error(f"❌ [{target_name}] 400 Bad Request 발생: {error_detail}")
                logger.error(f"   Payload Preview: {json.dumps(payload, ensure_ascii=False)[:300]}...")
                # 400 에러는 재시도해도 의미가 없는 경우가 많음 (컨텍스트 초과 등)
                res.raise_for_status()

            res.raise_for_status()
            
            response_data = res.json()
            content = response_data['choices'][0]['message']['content']
            
            token_info_dict = response_data.get('usage')
            usage = {
                "prompt_tokens": token_info_dict.get("prompt_tokens", 0) if token_info_dict else 0,
                "completion_tokens": token_info_dict.get("completion_tokens", 0) if token_info_dict else 0
            }
            # LangSmith 대시보드 시스템(Input/Output) 토큰 컬럼 매핑
            try:
                from langsmith.run_helpers import get_current_run_tree
                rt = get_current_run_tree()
                if rt:
                    if rt.extra is None: rt.extra = {}
                    rt.extra["usage_metadata"] = {
                        "input_tokens": usage["prompt_tokens"],
                        "output_tokens": usage["completion_tokens"],
                        "total_tokens": usage["prompt_tokens"] + usage["completion_tokens"]
                    }
                    rt.add_metadata({"usage": usage})
            except Exception:
                pass
                
            return content, usage
            
        except (requests.exceptions.RequestException, Exception) as e:
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) + 0.5 # Exponential backoff with simple jitter
                logger.warning(f"로컬 LLM 호출 실패 (시도 {attempt+1}): {e}. {wait_time}초 후 재시도...")
                time.sleep(wait_time)
            else:
                log_llm_event(target_name, f"Error after {max_retries} attempts: {e}")
                logger.error(f"{target_name}({model_size}) 최종 호출 실패: {e}")
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
def call_gemini(prompt: str, schema: dict = None) -> tuple:
    """제미나이 API를 호출합니다 (429 재시도 및 동시성 제어 포함)."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with gemini_semaphore: # 💡 동시 요청을 제한하여 분당 토큰 제한(TPM) 초과 방지
                log_llm_event("Gemini", f"Requesting {GEMINI_MODEL_NAME} (Attempt {attempt+1})", details=prompt)
                client = get_gemini_client()
                
                generate_kwargs = {
                    "model": GEMINI_MODEL_NAME,
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
                    'prompt_tokens': usage.prompt_token_count or 0,
                    'completion_tokens': usage.candidates_token_count or 0
                }
                
                return parse_llm_json(response.text), token_info
                
        except Exception as e:
            error_str = str(e)
            if "429" in error_str and attempt < max_retries - 1:
                wait_time = (attempt + 1) * 5 # 429 발생 시 대기 시간 확보
                logger.warning(f"⚠️ Gemini 429 에러(할당량 초과). {wait_time}초 후 재시도합니다... ({attempt+1}/{max_retries})")
                time.sleep(wait_time)
                continue
                
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
            log_llm_event("GeminiText", f"Requesting {GEMINI_MODEL_NAME} (Text Mode)", details=prompt)
            client = get_gemini_client()
            response = client.models.generate_content(
                model=GEMINI_MODEL_NAME,
                contents=prompt
            )
            
            usage = response.usage_metadata
            token_info = {
                'prompt_tokens': usage.prompt_token_count or 0,
                'completion_tokens': usage.candidates_token_count or 0
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
                log_llm_event("GeminiText", f"Fallback: Requesting {GEMINI_MODEL_NAME} (Text Mode)", details=prompt)
                client = get_gemini_client()
                response = client.models.generate_content(
                    model=GEMINI_MODEL_NAME,
                    contents=prompt
                )
                usage_meta = response.usage_metadata
                token_info = {
                    'prompt_tokens': usage_meta.prompt_token_count or 0,
                    'completion_tokens': usage_meta.candidates_token_count or 0
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

def agent_guard(agent_name: str, recoverable: bool = True):
    """에이전트 내결함성 데코레이터. 에러 발생 시 로그를 남기고 상태를 유지합니다."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(state: any):
            try:
                return func(state)
            except Exception as e:
                logger.error(f"❌ [{agent_name}] 에러 발생: {e}", exc_info=True)
                if recoverable:
                    error_count = state.get("error_count", 0) + 1
                    return {**state, "error_count": error_count, "last_error": str(e), "next_node": "evidence"}
                raise e
        return wrapper
    return decorator


# ==========================================
# Citation Annotation (인용 출처 마커 삽입)
# ==========================================

def annotate_citations(article_body: str, media_views: list) -> tuple:
    """본문에 인용 출처 마커 [N]를 삽입하고 상세 데이터를 생성합니다 (고도화 버전)."""
    # 입력 타입 방어 (리스트인 경우 줄바꿈으로 합침)
    if isinstance(article_body, list):
        article_body = "\n\n".join([str(s) for s in article_body])
    elif not isinstance(article_body, str):
        article_body = str(article_body or "")

    citations = []
    citation_id = 1
    
    # 0. 기존 마커 제거
    article_body = re.sub(r"\[\d+\]", "", article_body)

    # 1. 꺽쇠(<>) 보호
    angle_bracket_pattern = re.compile(r"<[^>]*>")
    placeholders = {}
    def replace_angle(m):
        key = f"\x00AB{len(placeholders)}\x00"
        placeholders[key] = m.group(0)
        return key
    safe_body = angle_bracket_pattern.sub(replace_angle, article_body)

    # 2. 따옴표 짝 매칭 (홑, 쌍, 전각 쌍, 전각 홑 지원)
    quoted_pattern = re.compile(
        r"'(?P<q1>.{10,1000}?)'|" + 
        r"\"(?P<q2>.{10,1000}?)\"|" + 
        r"“(?P<q3>.{10,1000}?)”|" + 
        r"‘(?P<q4>.{10,1000}?)’", 
        re.DOTALL
    )

    def normalize_text(t):
        if not t: return ""
        # 입력 타입 방어
        if isinstance(t, list):
            t = " ".join([str(i) for i in t])
        return re.sub(r"['\"“”‘’\s\.,!?]", "", str(t))

    def replace_with_marker(match):
        nonlocal citation_id
        quote = (match.group('q1') or match.group('q2') or match.group('q3') or match.group('q4') or "").strip()
        full_match = match.group(0)
        if not quote: return full_match
        opening_quote, closing_quote = full_match[0], full_match[-1]
        
        # 매칭 시 플레이스홀더 복원 후 정규화
        temp_quote = quote
        if "\x00AB" in quote:
            for k, v in placeholders.items(): temp_quote = temp_quote.replace(k, v)
        
        clean_target = normalize_text(temp_quote)

        for mv in media_views:
            # claim과 evidence를 모두 합쳐서 매칭 대상(pool)으로 삼음
            claim = mv.get("claim", "")
            evidence = mv.get("evidence", "")
            full_text_pool = f"{claim} {evidence}"
            
            clean_pool = normalize_text(full_text_pool)
            
            # 인용구가 합쳐진 텍스트 안에 있거나, 거꾸로 텍스트가 인용구 안에 포함되는지 확인
            if clean_target and clean_pool and (clean_target in clean_pool or clean_pool in clean_target):
                cid = citation_id
                citations.append({
                    "id": cid, "press": mv["press"], "title": mv.get("title", ""),
                    "url": mv.get("url", ""), "published_at": mv.get("published_at", ""),
                    "article_id": mv.get("article_id"), "quote": quote, "full_evidence": evidence
                })
                citation_id += 1
                return f"{opening_quote}{quote}[{cid}]{closing_quote}"
        return full_match

    annotated_body = quoted_pattern.sub(replace_with_marker, safe_body)
    for k, v in placeholders.items(): annotated_body = annotated_body.replace(k, v)
    
    logger.info(f"📎 [annotate_citations] 총 {len(citations)}개 인용 마커 삽입 완료")
    return annotated_body, citations
