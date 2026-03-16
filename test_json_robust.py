import json
import re

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
            return None

    # 전략 1: ```json ... ``` 또는 ``` ... ``` 추출
    for pattern in [r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```"]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            blob = match.group(1).strip()
            res = try_parse(blob)
            if res: return res
            
            # 파싱 실패 시: 마지막이 잘렸을 가능성 (Unterminated string)
            for i in range(1, 101):
                if len(blob) <= i: break
                for suffix in ['"', '"}', '"} ]', '}']:
                    try: 
                        return json.loads(blob[:-i] + suffix)
                    except: continue

    # 전략 2: 마크다운 외부에서 { } 또는 [ ] 블록 찾기 (탐욕적 매칭)
    matches = list(re.finditer(r"({.*}|\[.*\])", text, re.DOTALL))
    if matches:
        matches.sort(key=lambda m: len(m.group(0)), reverse=True)
        for m in matches:
            blob = m.group(1).strip()
            res = try_parse(blob)
            if res: return res

    # 전략 3: 최후의 수단
    start = text.find('{')
    if start == -1: start = text.find('[')
    end = text.rfind('}')
    if end == -1: end = text.rfind(']')
    
    if start != -1 and end != -1 and end > start:
        blob = text[start:end+1]
        res = try_parse(blob)
        if res: return res
        
        for i in range(1, 101):
            if len(blob) <= i: break
            for suffix in ['"', '"}', '"} ]', '}']:
                try: 
                    return json.loads(blob[:-i] + suffix)
                except: continue
    return None

# Test 1: Unclosed string at the end of a field
test1 = """{
    "title": "장동혁 수호 집회",
    "description": "전한길과 ... 제시되었다.",
    "background": "장동혁은 최근 역사적 인물로 부상하면서 그의 관련 이슈들이 사회적으로 논란을 일으키고 있다. 이에 전한길과 고성국이 이 문제에 직접介入以中文回答：

{
    "title": "长东赫保护集会"
}"""

# Test 2: Another unclosed string
test2 = """{
    "title": "검찰개혁 수정안 선명성 논란",
    "description": "이재명 대통령은 검찰개혁 수정안이 선명성을 높이기보다는 재수정이 필요하다고 주장, 법안의 명확성과 효과성에 대한 논란이 일고 있습니다.",
    "background": "이재명 대통령은 최근 검찰개혁 관련 법안의 수정안을 발표했으나, 법안의 명확성과 선명성을 높이기보다는 원래 법안을 재수정해야 한다는 의견을 제시함으로써 법안의 효율성에 대한 의문을 제기하고 있습니다.",
    "core_contentions": "이 이슈와 관련된 주요 쟁점은 법안의 명확성과 선명성에 대한 의견分化，这里是一个中文"""

print(f"Test 1 Parsed: {parse_llm_json(test1) is not None}")
if parse_llm_json(test1):
    print(f"Test 1 Title: {parse_llm_json(test1).get('title')}")

print(f"Test 2 Parsed: {parse_llm_json(test2) is not None}")
if parse_llm_json(test2):
    print(f"Test 2 Title: {parse_llm_json(test2).get('title')}")
