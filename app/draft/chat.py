from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import google.generativeai as genai
from app.core.config import settings

router = APIRouter()


if settings.GOOGLE_API_KEY:
    genai.configure(api_key=settings.GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.0-flash')
else:
    model = None # API 키가 없는 경우 처리

class ChatMessage(BaseModel):
    role: str # "user" or "model" or "system"
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage] # 대화 내역 (마지막 메시지가 사용자의 현재 질문)
    draft_content: Optional[str] = "" # 현재 작성 중인 초안 내용 (Context)
    
class ChatResponse(BaseModel):
    response: str
    modified_content: Optional[str] = None # AI가 초안을 수정한 경우, 수정된 전체 내용

@router.post("/chat", response_model=ChatResponse)
async def chat_with_ai(request: ChatRequest):
    """
    AI 챗봇과의 대화를 처리합니다.
    - 사용자의 질문과 현재 작성 중인 초안 내용을 바탕으로 답변을 생성합니다.
    - 초안 수정이 필요한 경우, modified_content에 수정된 내용을 담아 반환합니다.
    """
    if not model:
        raise HTTPException(status_code=500, detail="Google Gemini API Key is not configured.")

    try:
        # 1. 시스템 프롬프트 구성 (JSON 출력을 강제)
        system_prompt = """
당신은 기사 작성을 돕는 스마트 AI 어시스턴트입니다.
사용자는 현재 뉴스 기사 초안을 작성하고 있는 기자 또는 작가입니다.

[역할]
1. 사용자의 질문에 친절하고 전문적으로 답변하세요.
2. 'draft_content'가 제공되면, 문맥을 파악하여 피드백을 제공하세요.
3. **중요**: 사용자가 초안 수정을 명시적으로 요청하거나(예: "이 문단 다듬어줘", "통계 추가해줘"), 수정이 필요한 질문을 하면, **초안 전체를 수정한 결과**를 제공해야 합니다.

[출력 형식]
반드시 다음 JSON 형식으로만 응답하세요. 마크다운 코드 블록(` ```json `)을 포함하지 마세요.
{
    "response": "사용자에게 할 말 (한국어)",
    "modified_content": "수정된 전체 초안 내용 (수정 사항이 없으면 null)"
}
"""
        
        # 2. 대화 내역 구성
        context_message = f"{system_prompt}\n\n[현재 작성 중인 초안]\n{request.draft_content}\n\n"
        
        if request.messages:
            last_user_input = request.messages[-1].content
            full_prompt = context_message + f"[사용자 질문]\n{last_user_input}"
            
            # Gemini 호출 (JSON 모드 사용)
            response = model.generate_content(
                full_prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            
            # JSON 파싱
            import json
            try:
                result = json.loads(response.text)
                return ChatResponse(
                    response=result.get("response", ""),
                    modified_content=result.get("modified_content")
                )
            except json.JSONDecodeError:
                # 파싱 실패 시 일반 텍스트로 처리 (유연성 확보)
                return ChatResponse(response=response.text, modified_content=None)
            
        else:
            return ChatResponse(response="무엇을 도와드릴까요?", modified_content=None)

    except Exception as e:
        # 에러 로깅 필요
        print(f"Gemini Chat Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI 응답 생성 중 오류가 발생했습니다: {str(e)}")
