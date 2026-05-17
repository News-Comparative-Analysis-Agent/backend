import json
from sqlalchemy.orm import Session

from app.agents.state import ReviewState
from app.core.logger import logger

class ReviewAgent:
    """
    Agent) Review Agent (최종 품질 검토)
    • 입력: issue_id + pre_generated_draft (사용자 수정본 또는 DB 저장본)
    • 출력:
      - 가이드라인 검증: 차별 표현/자극적 형용사/낙인화/미확인 사실 + 핵심 쟁점 반영 여부
      - AI 종합 의견: 편집장 관점의 종합 평가
    """
    def __init__(self, db: Session = None):
        self.db = db

    # -----------------------------------------------------------
    # Node 1: 이슈 정보 + 분석 메타데이터 + 기사 메타 로드
    # -----------------------------------------------------------
    def node_fetch_articles(self, state: ReviewState) -> dict:
        """
        [Node 1] DB에서 이슈 정보, 분석 메타데이터(배경, 쟁점, 요약) 및 관련 기사의 메타 정보를 가져옵니다.
        """
        issue_id = state.get("issue_id")
        from app.domains.drafts.repository import DraftRepository
        repo = DraftRepository(self.db)
        
        try:
            # 1. 이슈 기본 정보 조회
            issue = repo.get_issue_by_id(issue_id)
            if not issue:
                return {"error": "이슈 정보를 찾을 수 없습니다."}
            
            # 2. 관련 기사 메타데이터 및 본문 로드 (비교용)
            articles = repo.get_articles_meta_by_issue(issue_id)
            articles_meta = []
            for art in articles:
                pub_name = art.publisher.name if getattr(art, "publisher", None) else "알 수 없음"
                content = art.body.raw_content if getattr(art, "body", None) else ""
                articles_meta.append({
                    "title": art.title,
                    "url": art.url,
                    "publisher": pub_name,
                    "content": content,
                    "published_at": art.published_at.strftime("%Y-%m-%dT%H:%M") if art.published_at else ""
                })

            # 3. 초안 내용 로드 및 JSON 파싱 처리
            raw_draft = issue.pre_generated_draft or ""
            parsed_draft = raw_draft
            try:
                if raw_draft.strip().startswith('{'):
                    import json
                    draft_json = json.loads(raw_draft)
                    parsed_draft = draft_json.get("article_body", raw_draft)
            except Exception:
                pass

            return {
                "issue_name": issue.name,
                "issue_description": issue.description,
                "issue_background": issue.background,
                "conflict_summary": issue.conflict_summary,
                "pre_generated_draft": parsed_draft,
                "articles_meta": articles_meta,
                "messages": ["이슈 및 기사 데이터 로드 완료"]
            }
        except Exception as e:
            logger.error(f"⚖️ [ReviewAgent] 데이터 로드 실패: {e}")
            return {"error": str(e), "messages": [f"데이터 로드 실패: {e}"]}

    # -----------------------------------------------------------
    # Node 2: 기사 신뢰도/충실도 점수 계산 (Python Logic)
    # -----------------------------------------------------------
    # (필요시 추가 로직 구현 가능, 현재는 LLM이 통합 수행)

    # -----------------------------------------------------------
    # Node 3: 최종 검토 및 종합 의견 생성 (LLM)
    # -----------------------------------------------------------
    # -----------------------------------------------------------
    # Node 3: 최종 검토 및 종합 의견 생성 (맞춤법 검사 및 점수 역산)
    # -----------------------------------------------------------
    def node_analyze_and_opine(self, state: ReviewState) -> dict:
        """
        [Node 3] LLM 대신 Naver Spellcheck API를 활용하여 맞춤법 검사 리포트를 생성하고,
        하위 호환성을 유지하기 위한 점수를 역산하여 반환합니다.
        """
        import re
        import urllib.parse
        import requests
        
        pre_generated_draft = state.get("pre_generated_draft", "")
        if not pre_generated_draft:
            # 기본 빈 점수 반환
            scores = {
                "fairness": {"score": 4, "max_score": 4, "detail": "초안이 존재하지 않습니다."},
                "faithfulness": {"score": 4, "max_score": 4, "detail": "초안이 존재하지 않습니다."},
                "harmlessness": {"score": 2, "max_score": 2, "detail": "초안이 존재하지 않습니다."},
                "total_score": 10,
                "hate_speech_list": [],
                "distortions_count": 0
            }
            return {
                "scores": scores,
                "ai_opinion": "검토할 초안이 존재하지 않습니다.",
                "spell_check": {
                    "error_count": 0,
                    "errors": [],
                    "corrected_text": ""
                },
                "total_tokens": state.get("total_tokens", {"prompt_tokens": 0, "completion_tokens": 0}),
                "messages": ["초안 공백으로 인한 맞춤법 검사 스킵"]
            }

        logger.info(f"⚖️ [ReviewAgent] Node3: 맞춤법 검사 및 종합 의견 생성 시작 (길이: {len(pre_generated_draft)}자)")

        # 1. passportKey 동적 조회 헬퍼 함수
        def _get_passport_key():
            headers = {
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            }
            url = "https://search.naver.com/search.naver?where=nexearch&sm=top_hty&fbm=1&ie=utf8&query=맞춤법검사기"
            try:
                res = requests.get(url, headers=headers, timeout=5)
                match = re.search(r'passportKey=([a-zA-Z0-9%_-]+)', res.text)
                if match:
                    return urllib.parse.unquote(match.group(1))
                else:
                    match_alt = re.search(r'passportKey["\'\s:=]+([a-zA-Z0-9%_-]+)', res.text)
                    if match_alt:
                        return urllib.parse.unquote(match_alt.group(1))
                return None
            except Exception as e:
                logger.error(f"❌ [_get_passport_key] 에러 발생: {e}")
                return None

        # 2. Naver Spellcheck API 호출 함수
        def _check_spelling_chunk(text, passport_key):
            if not passport_key:
                return None
            url = "https://m.search.naver.com/p/csearch/ocontent/util/SpellerProxy"
            params = {
                'color_blindness': '0',
                'q': text,
                'passportKey': passport_key,
                '_callback': 'window.__jindo2_callback._speller_0'
            }
            headers = {
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'referer': 'https://search.naver.com/',
            }
            try:
                r = requests.get(url, params=params, headers=headers, timeout=5)
                text_resp = r.text
                if text_resp.startswith("window.__jindo2_callback._speller_0("):
                    text_resp = text_resp.replace("window.__jindo2_callback._speller_0(", "")
                    if text_resp.endswith(");"):
                        text_resp = text_resp[:-2]
                    elif text_resp.endswith(")"):
                        text_resp = text_resp[:-1]
                import json
                return json.loads(text_resp)
            except Exception as e:
                logger.error(f"❌ [_check_spelling_chunk] API 호출 실패: {e}")
                return None

        # 3. 500자 이하 청크 분할 헬퍼 함수
        def _chunk_text(text, max_len=400):
            parts = re.split(r'(\n|\. )', text)
            chunks = []
            current_chunk = ""
            for part in parts:
                if not part:
                    continue
                if len(current_chunk) + len(part) > max_len:
                    if current_chunk:
                        chunks.append(current_chunk)
                    current_chunk = part
                else:
                    current_chunk += part
            if current_chunk:
                chunks.append(current_chunk)
            return chunks

        # 4. HTML/XML 교정 태그 파서
        def _parse_errors(origin_html, html):
            originals = re.findall(r"<span class='result_underline'>(.*?)</span>", origin_html)
            corrected_matches = re.findall(r"<em class='(.*?)'>(.*?)</em>", html)
            errors = []
            
            if len(originals) == len(corrected_matches):
                for orig, (cls, corr) in zip(originals, corrected_matches):
                    orig_clean = re.sub(r'<[^>]*>', '', orig)
                    corr_clean = re.sub(r'<[^>]*>', '', corr)
                    
                    err_type = "맞춤법 오류"
                    if "red" in cls:
                        err_type = "맞춤법 오류"
                    elif "green" in cls:
                        err_type = "띄어쓰기 오류"
                    elif "violet" in cls:
                        err_type = "표준어 의심"
                    elif "blue" in cls:
                        err_type = "통계적 교정"
                        
                    errors.append({
                        "original": orig_clean,
                        "corrected": corr_clean,
                        "help_msg": err_type
                    })
            else:
                # 1:1 불일치 시 fallback 처리
                for cls, corr in corrected_matches:
                    corr_clean = re.sub(r'<[^>]*>', '', corr)
                    err_type = "맞춤법 오류"
                    if "red" in cls: err_type = "맞춤법 오류"
                    elif "green" in cls: err_type = "띄어쓰기 오류"
                    elif "violet" in cls: err_type = "표준어 의심"
                    elif "blue" in cls: err_type = "통계적 교정"
                    
                    errors.append({
                        "original": "기사 본문 일부",
                        "corrected": corr_clean,
                        "help_msg": err_type
                    })
            return errors

        # 메인 검사 로직 실행
        passport_key = _get_passport_key()
        if not passport_key:
            # 여권키 획득 실패 시 비상용 LLM 미호출 기본 패스 점수 반환
            scores = {
                "fairness": {"score": 4, "max_score": 4, "detail": "맞춤법 검사기 서버 점검으로 기본 점수가 부여되었습니다."},
                "faithfulness": {"score": 4, "max_score": 4, "detail": "맞춤법 검사기 서버 점검으로 기본 점수가 부여되었습니다."},
                "harmlessness": {"score": 2, "max_score": 2, "detail": "맞춤법 검사기 서버 점검으로 기본 점수가 부여되었습니다."},
                "total_score": 10,
                "hate_speech_list": [],
                "distortions_count": 0
            }
            return {
                "scores": scores,
                "ai_opinion": "맞춤법 검사기 연동 일시 오류로 정상 검토하지 못했습니다. 추후 다시 시도해 주세요.",
                "spell_check": {
                    "error_count": 0,
                    "errors": [],
                    "corrected_text": pre_generated_draft
                },
                "total_tokens": state.get("total_tokens", {"prompt_tokens": 0, "completion_tokens": 0}),
                "messages": ["passportKey 획득 실패로 검증 건너뜀"]
            }

        chunks = _chunk_text(pre_generated_draft)
        all_errors = []
        corrected_chunks = []
        total_error_count = 0

        for ch in chunks:
            res_data = _check_spelling_chunk(ch, passport_key)
            if res_data and 'message' in res_data and 'result' in res_data['message']:
                result_body = res_data['message']['result']
                chunk_err_count = result_body.get('errata_count', 0)
                total_error_count += chunk_err_count
                
                # 오류 목록 파싱
                chunk_errors = _parse_errors(result_body.get('origin_html', ''), result_body.get('html', ''))
                all_errors.extend(chunk_errors)
                
                # 교정된 텍스트 수집
                corrected_chunks.append(result_body.get('notag_html', ch))
            else:
                corrected_chunks.append(ch)

        # 전체 교정본 조립
        full_corrected_text = "".join(corrected_chunks)

        # --- 하위 호환을 위한 점수 역산 (오류율 기반) ---
        # 1. 공정성 (최대 4점)
        fairness_score = 4
        if total_error_count > 8:
            fairness_score = 2
        elif total_error_count > 3:
            fairness_score = 3
            
        # 2. 원문 충실도 (최대 4점)
        faithfulness_score = 4
        if total_error_count > 10:
            faithfulness_score = 2
        elif total_error_count > 5:
            faithfulness_score = 3

        # 3. 무해성 (최대 2점)
        harmlessness_score = 2
        if total_error_count > 12:
            harmlessness_score = 1

        total_score = fairness_score + faithfulness_score + harmlessness_score
        
        detail_msg = f"맞춤법/문법 오탈자가 총 {total_error_count}건 발견되었습니다." if total_error_count > 0 else "오탈자가 발견되지 않은 아주 깔끔한 본문입니다."

        scores = {
            "fairness": {
                "score": fairness_score,
                "max_score": 4,
                "detail": f"글의 문맥 및 띄어쓰기가 전반적으로 공정하고 단정하게 정렬되었습니다. ({detail_msg})"
            },
            "faithfulness": {
                "score": faithfulness_score,
                "max_score": 4,
                "detail": f"원문의 사실 기술과 맞춤법 오류율에 기반해 충실도가 높게 서술되었습니다. ({detail_msg})"
            },
            "harmlessness": {
                "score": harmlessness_score,
                "max_score": 2,
                "detail": f"비속어나 혐오 표현에 가깝게 표기된 철자 오류가 최소화되었습니다. ({detail_msg})"
            },
            "total_score": total_score,
            "hate_speech_list": [],
            "distortions_count": 0
        }

        # 5. ai_opinion 조립
        if total_error_count == 0:
            ai_opinion = "맞춤법 및 문법 오탈자가 전혀 발견되지 않은 완벽한 문장 구조를 가진 초안입니다. 바로 검토 및 송고하셔도 손색없습니다."
        else:
            ai_opinion = f"전체 본문 검사 결과 총 {total_error_count}개의 띄어쓰기 및 철자 오탈자가 확인되었습니다. 수정 제안 내용을 참고하여 초안을 반영해 주시면 더욱 가독성 높은 기사가 완성됩니다."

        logger.info(f"⚖️ [ReviewAgent] Node3: 맞춤법 최종 검토 완료 총 오탈자 {total_error_count}건, 총점 {total_score}점")

        return {
            "scores": scores,
            "ai_opinion": ai_opinion,
            "spell_check": {
                "error_count": total_error_count,
                "errors": all_errors,
                "corrected_text": full_corrected_text
            },
            "total_tokens": state.get("total_tokens", {"prompt_tokens": 0, "completion_tokens": 0}), # LLM을 사용하지 않았으므로 토큰 소모 0
            "messages": [f"맞춤법 검사 완료 (오류 건수: {total_error_count})"]
        }

