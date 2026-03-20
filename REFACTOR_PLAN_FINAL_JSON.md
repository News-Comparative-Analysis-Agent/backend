# 리팩토링 계획: 최종 JSON 스키마 고정 + 할루시네이션 최소화

## 0. 배경 / 목표

현재 파이프라인은 에이전트별로 중간 구조(`claim_cards`, `structured_issues`, Writer/Editor용 `outline`)를 거친 뒤 최종 JSON을 만듭니다.

사용자 목표는 아래 2가지입니다.

1. **최종 JSON 스키마를 고정**한다. (형식/키를 모델이 임의로 바꾸지 못하게)
2. Qwen2.5-7B(최종 실행 모델)가 **할루시네이션을 덜 하도록** 입력/생성 범위를 단계적으로 축소한다.

추가로, 사용자 요청에 따라 **Evidence 에이전트 진입 시점에 `title/description/background/core_contentions`를 state에 반드시 포함시키는 방향은 채택하지 않는다.**(해당 항목은 Evidence가 아니라 “최종 JSON을 만드는 시점”에 주입한다.)

## 1. 최종 JSON 스키마(고정)

최종 산출물(= `edited_article`)은 아래 키만 가진다고 가정한다.

```json
{
  "issue_id": 1,
  "title": "15자 이내 이슈 제목",
  "description": "이슈의 배경과 핵심 내용 3~4문장",
  "background": "이슈 발생 핵심 발단 1~2문장",
  "core_contentions": "주요 쟁점/갈등 1~2문장",
  "conflict_summary": "언론사 간 시각 차이 요약",
  "media_views": [
    {
      "press": "언론사명",
      "claim": "핵심 주장",
      "evidence": "원문 인용구",
      "url": "기사 URL",
      "narrative": "서술형 분석 문장"
    }
  ],
  "article_body": "최종 비평 기사 본문"
}
```

## 2. 에이전트 역할 재정의(스키마 고정 관점)

### 2.1 EvidenceAgent (LLM + DB 저장)

목표: **근거 기반 claim/evidence만 뽑는다.**

- EvidenceAgent가 LLM으로 생성/추출:
  - `media_views[][].press` (DB/기사 메타)
  - `media_views[][].claim` (LLM)
  - `media_views[][].evidence` (LLM, 원문 인용구)
  - `media_views[][].url` (DB/기사 메타)
- EvidenceAgent가 **생성하지 않음**(할루시네이션 저감):
  - `media_views[].narrative`
  - `conflict_summary`
  - top-level `title/description/background/core_contentions`
- DB 저장:
  - 기존처럼 `claim_cards`(주장 카드)는 DB에 저장은 유지한다. (요청사항: DB 저장 변함없음)

출력(다음 단계로 넘길 state):
- `media_views`(필요 최소 필드만, narrative 제외)
- `claim_cards`는 유지 가능(호환/로그/디버깅 목적)

> 주의: `title/description/background/core_contentions`는 state에 넣지 않는다. Evidence는 필요하지 않도록 설계한다.

### 2.2 IssueAgent (LLM)

목표: **언론사 간 시각 차이 요약(conflict_summary)과 언론사 주장에 대한 설명(media_views[].narrative)를 생성한다.**

- 입력:
  - Evidence가 만든 `media_views[].{press,claim,evidence,url}`
- LLM 출력:
  - `conflict_summary`
  - `media_views[].narrative`
- 생성하지 않음:
  - `article_body`
  - top-level 이슈 메타(title/description/background/core_contentions)

출력:
- `conflict_summary`
- (선택) 검증을 위한 보조 정보(예: contention grouping용 내부 구조)는 state에 넣되, 최종 스키마와 분리한다.

### 2.3 WriterAgent (선택: 아티클 뼈대/초안 생성)

현재 구조는 Writer가 outline JSON을 만들고 Editor가  최종 완성을 합니다.

리팩토링 목표에서는 “최종 스키마 고정”이 최우선이므로 다음 중 하나로 정한다.

- 옵션 A(권장): Writer는 `article_body`의 **뼈대(구조/문단 구성/서술 가이드)**만 만들고,
  Editor가 최종 고정 스키마를 한 번에 생성한다.
- 옵션 B: Writer가 최종 스키마에 가까운 형태로 만들되(키 고정),
  Editor가 narrative/문장만 다듬고 최종 trim을 수행한다.

본 문서는 **옵션 A**를 전제로 작성한다.

### 2.4 EditorAgent (LLM + 최종 스키마 “고정” 출력 담당)

목표: **edited_article을 최종 고정 JSON 스키마로만 반환**한다.

Editor가 채울 필드:
- `issue_id` : state에서
- top-level 이슈 메타:
  - `title/description/background/core_contentions`
  - 방법: `issue_id`로 DB(IssueLabel)를 조회해서 “주입”한다. (Evidence state에 넣지 않음)
- `conflict_summary` : state에서 가져와 그대로 사용용
- `article_body` : LLM 생성 최종 비평기사 초안 생성

Editor의 “스키마 고정 규칙”:
- 모델 출력은 JSON 파싱 시:
  - 허용된 키만 남기고(inclusion whitelist)
  - narrative/media_views 형태/필드 누락 시 실패로 처리
- 최종 반환은 **반드시 고정 키만** 포함한다.

### 2.5 JudgeAgent (LLM 검증 + 재시도 라우팅)

목표: Qwen2.5-7B 기반 생성에서 가장 위험한 “사실 추가”를 줄인다.

Judge가 검증할 체크:
- `media_views[].narrative`가 해당 항목의 `evidence`에 없는 사실(문장 단위/표현 단위)을 포함하는지
  - 엄격한 string-match(완벽하지는 않지만 1차 방어) + LLM 기반 판정 조합
- `article_body`에도 evidence 밖 사실이 들어갔는지
- JSON 키가 스키마 고정 규칙을 위반했는지(불필요 키/누락 키)

실패 시:
- `writer` 재시도 또는 `editor` 재시도로 라우팅(현재 로직 유지하되, 실패 유형에 맞춰 재작성 범위를 좁힌다.)

## 3. State(전달 데이터) 슬리밍 계획

핵심: state에 “최종 스키마 전체를 여러 번” 복제하지 않는다.

추천 state 흐름:
- Evidence → Issue:
  - `media_views` (narrative 제외)
  - (선택) `claim_cards`는 그대로 유지
- Issue → Editor:
  - `conflict_summary`
- Editor:
  - DB에서 top-level 이슈 메타 조회 후 최종 스키마 조립

따라서 아래는 최소화/권장하지 않음:
- Evidence에서 `title/description/background/core_contentions/conflict_summary/article_body` 같은 “최종 top-level”을 state에 미리 만들어 반복 복제

## 4. 코드 변경 순서(실행 계획)

### 4.1 1단계: 스키마/키 고정 규칙 확정

- 최종 JSON 키 whitelist를 확정한다(위 스키마 그대로).
- Editor 출력 trim 로직을 “항상” 적용하도록 정한다.
- narrative는 “입력 evidence 기반” 범위에서만 나오도록 프롬프트 문구를 명확히 한다.

### 4.2 2단계: EvidenceAgent 출력 최소화

- EvidenceAgent가 state에 넘기는 최소 필드는 `media_views[]`(press/claim/evidence/url)로 제한한다.
- narrative를 생성/포함하지 않는다.
- claim_cards DB 저장 로직은 유지한다.

### 4.3 3단계: IssueAgent 출력 축소

- IssueAgent는 `conflict_summary`만 생성하고,
- media_views는 유지/전달만 한다(가능하면 claim/evidence 그대로).

### 4.4 4단계: EditorAgent를 “최종 스키마 출력 전담”으로 정리

- EditorAgent는 `issue_id`로 DB 조회해서 top-level 메타 주입:
  - `title/description/background/core_contentions`
- EditorAgent 프롬프트에서 입력은 다음으로 제한:
  - state의 `conflict_summary`
  - state의 `media_views[]`(근거)
  - (DB에서 로드한) 이슈 메타
- EditorAgent 출력은 최종 스키마만 반환하고 trim(whitelist)한다.

필요 시 그래프 수정:
- 현재 `editor_wrapper`가 DB 세션 없이 `EditorAgent()`를 생성한다.
- EditorAgent에서 DB 조회가 필요하므로,
  - `editor_wrapper`에 `SessionLocal()`을 주입하거나
  - 혹은 EditorAgent에 DB를 전달하는 방식으로 수정한다.

### 4.5 5단계: Judge 검증 로직 강화(키/사실 검증)

- Judge는:
  - 스키마 키 누락/불필요 키 발생 여부
  - narrative/article_body가 evidence 기반인지(강한 프롬프트 + 가능하면 간단한 문자열 포함 체크)
  를 중심으로 실패를 판단한다.

### 4.6 6단계: state.py TypedDict 정리

- `ComparisonState`에는 “정말 필요한 키만” 둔다.
- 예: `media_views`, `conflict_summary` 중심으로 구성.
- “payload 중복용 필드(issue_payload_items 등)”는 필요성이 줄어들면 제거한다.

## 5. 검증/테스트 계획

1. 단일 이슈 처리에서:
   - Evidence가 `media_views` 생성
   - IssueAgent가 `conflict_summary` 생성
   - EditorAgent가 최종 고정 스키마만 생성
2. Judge가 FAIL 시:
   - editor 재시도 루프가 동작하는지
3. 최종 저장/조회 경로에서:
   - `issue.pre_generated_draft`에 저장된 JSON이 스키마 고정 키만 포함하는지

## 6. 리스크 및 완화책

- 리스크: Qwen2.5-7B가 narrative/article_body에서 evidence 밖 사실을 말할 수 있음
  - 완화: narrative/artcle_body 생성 횟수 최소화 + Judge 검증 강화 + failure 시 재작성 범위 좁히기
- 리스크: Editor 모델 출력이 스키마 외 키를 포함
  - 완화: Editor trim(whitelist) + JSON schema 강제(가능한 경우) + Judge에서 키 위반을 FAIL 처리

