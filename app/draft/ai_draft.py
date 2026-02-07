from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import google.generativeai as genai
import time
import json

router = APIRouter()

model = genai.GenerativeModel('gemini-2.0-flash-exp')

async def stream_generator(prompt: str):
    # stream=True 옵션이 핵심! (한 번에 안 기다리고 줄 때마다 받음)
    response = model.generate_content(prompt, stream=True)
    
    for chunk in response:
        text_chunk = chunk.text
        
        data = json.dumps({"text": text_chunk}, ensure_ascii=False)
        yield f"data: {data}\n\n"
        

@router.post("/api/draft/stream")
async def generate_draft_stream(request: dict):
    user_prompt = request.get("prompt")
    system_prompt = f"다음 주제에 대해 짧은 글을 써줘: {user_prompt}"

    return StreamingResponse(
        stream_generator(system_prompt), 
        media_type="text/event-stream"
    )