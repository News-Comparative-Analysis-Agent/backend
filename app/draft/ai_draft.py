from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import google.generativeai as genai
import time
import json
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.domains.issues.models import IssueLabel
from app.domains.articles.models import Article
from app.core.config import settings

router = APIRouter()

# model = genai.GenerativeModel('gemini-2.0-flash-exp')
genai.configure(api_key=settings.GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

async def stream_generator(prompt: str):
    # stream=True 옵션이 핵심! (한 번에 안 기다리고 줄 때마다 받음)
    try:
        response = model.generate_content(prompt, stream=True)
        
        for chunk in response:
            if chunk.text:
                text_chunk = chunk.text
                data = json.dumps({"text": text_chunk}, ensure_ascii=False)
                yield f"data: {data}\n\n"
    except Exception as e:
        error_msg = json.dumps({"text": f"\n\n[Error] 생성 중 오류 발생: {str(e)}"}, ensure_ascii=False)
        yield f"data: {error_msg}\n\n"
        

from app.domains.publishers.models import Publisher

@router.post("/stream")
async def generate_draft_stream(request: dict, db: Session = Depends(get_db)):
    # stream=True 옵션이 핵심! (한 번에 안 기다리고 줄 때마다 받음)
    issue_id = request.get("issue_id")
    
    context_text = ""
    
    if issue_id:
        # 1. 이슈 정보 조회
        issue = db.query(IssueLabel).filter(IssueLabel.id == issue_id).first()
        if issue:
            # 2. 관련 기사 조회 (상위 5개, 언론사 정보 포함)
            articles = db.query(Article).join(Publisher).filter(Article.issue_label_id == issue_id).limit(5).all()
            
            article_summaries = []
            for idx, art in enumerate(articles, 1):
                publisher_name = art.publisher.name if art.publisher else "알 수 없는 언론사"
                article_summaries.append(f"[{idx}] 언론사: {publisher_name} | 제목: {art.title}\n요약: {art.summary or '내용 없음'}")
            
            # 이슈 키워드 (배열을 문자열로 변환)
            keywords_str = ", ".join(issue.keyword) if issue.keyword else "없음"
            
            context_text = f"""
            [참고 자료]
            주제: {issue.name}
            핵심 키워드: {keywords_str}
            
            관련 기사 요약:
            {chr(10).join(article_summaries)}
            """
    
    system_prompt = f"""
# Role (당신의 역할)
당신은 대한민국 언론의 보도 행태를 날카롭게 분석하는 **'미디어 전문 비평가'**입니다.
주어진 5개 내외의 뉴스 기사들을 읽고, 해당 이슈를 바라보는 **언론사별 시각 차이(Frame)**를 비교 분석하는 기사를 작성하세요.

# Input Data (분석할 기사 목록)
{context_text} 
(여기에는 기사 제목, 언론사명, 본문 내용이 들어갑니다)

# Analysis Goals (분석 목표)
1. **쟁점 파악**: 이 사안의 핵심 팩트(Fact)는 무엇인가?
2. **구도 설정**: 언론사들의 반응이 어떻게 갈리는가? (예: 찬성 vs 반대, 우려 vs 기대, 보수지 vs 진보지 등)
3. **논조 비교**: 각 언론사가 주장을 뒷받침하기 위해 어떤 근거(통계, 인터뷰, 사례)를 들었는가?

# Writing Guidelines (작성 지침)
기사는 아래 **5단 구성**을 엄격히 지켜 작성해 주세요.

1. **[헤드라인]**: 이슈의 핵심과 언론의 대립 구도가 한눈에 보이는 제목 (예: "OOO 사태"... A신문 "우려" vs B신문 "기대")
2. **[전문 (Lead)]**: 사건의 개요를 간략히(2문장 이내) 요약하고, 언론사 간의 시각차가 뚜렷함을 명시할 것.
3. **[본문 1 - 팩트]**: 주관적 해석을 배제하고, 사건 자체의 'Fact'만 건조하게 서술할 것.
4. **[본문 2 - 시각 A (제1그룹)]**:
   - 비슷한 논조를 보인 언론사들을 묶어서 서술할 것.
   - **반드시 언론사 실명을 언급할 것.** (예: "조선일보는 ~라고 지적했다", "중앙일보는 ~를 문제 삼았다")
   - 그들이 내세운 핵심 논리나 근거를 인용할 것.
5. **[본문 3 - 시각 B (제2그룹)]**:
   - 'A그룹'과 반대되거나 다른 측면을 강조한 언론사들을 서술할 것.
   - **반드시 언론사 실명을 언급할 것.** (예: "반면 한겨레는 ~에 주목했다", "경향신문은 ~라고 반박했다")
   - 접속사('한편', '반면', '대조적으로')를 사용하여 A그룹과의 차이를 부각할 것.
6. **[결론 (Closing)]**:
   - 양측의 주장을 종합하며 미디어 비평가로서의 마무리 멘트.
   - 어느 한쪽을 편들지 말고, "언론이 각자의 프레임으로 사안을 해석하고 있다"는 뉘앙스로 마무리.

# Tone & Manner
- 특정 정치색을 드러내지 말고 **제3자의 관찰자 시점**을 유지할 것.
- 문체는 신문 기사체(해라체, ~했다)를 사용할 것.
- **반드시 입력된 기사 내용에 기반해야 하며, 없는 사실을 지어내지 말 것.**

# Output Generation
위 지침에 따라 완성된 하나의 **비평 기사**만 출력해 주세요.
    """

    return StreamingResponse(
        stream_generator(system_prompt), 
        media_type="text/event-stream"
    )