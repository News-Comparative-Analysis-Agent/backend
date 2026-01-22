# 📋 백엔드 도메인별 이슈 템플릿 (Copy & Paste용)

각 도메인 개발을 시작할 때, 아래 내용을 복사해서 **GitHub Issue**나 **Jira**에 등록하세요.

---

## 1. 👤 [Feat] User 도메인 구현 (인증/계정)

**개요 (Description)**
사용자 회원가입 및 OAuth(소셜 로그인) 인증 기능을 구현합니다.
`users` 테이블을 기반으로 JWT 토큰 발급 및 검증 로직을 포함합니다.

**할 일 (Checklist)**
- [x] ORM 모델 구현 (`app/domains/users/models.py`)
- [ ] Pydantic 스키마 정의 (`schemas.py`): `UserCreate`, `UserResponse`, `Token`
- [ ] OAuth 인증 로직 구현 (Google/Kakao API 연동)
- [ ] JWT 발급 및 검증 유틸리티 (`core/security.py`)
- [ ] API 라우터 구현 (`router.py`): `/auth/login`, `/users/me`

---

## 2. 🏷️ [Feat] Topic & Publisher 도메인 구현 (기준 정보)

**개요 (Description)**
뉴스 분석의 기준이 되는 '주제(공약)'와 '언론사' 정보를 관리하는 도메인을 구현합니다.
초기 데이터 시딩(Seeding) 스크립트도 포함해야 합니다.

**할 일 (Checklist)**
- [x] ORM 모델 구현 (`topics/models.py`, `publishers/models.py`)
- [ ] 초기 데이터 주입 스크립트 (`seeds/initial_data.py`)
- [ ] 언론사 목록 조회 API (`router.py`)
- [ ] 주제 목록 조회 API (`router.py`)

---

## 3. 📰 [Feat] Article 도메인 및 크롤러 구현 (핵심)

**개요 (Description)**
네이버 뉴스 정치 섹션을 크롤링하고, AI를 통해 분석한 결과를 저장하는 핵심 도메인입니다.
`articles`와 `article_bodies` 테이블을 관리합니다.

**할 일 (Checklist)**
- [x] ORM 모델 구현 (`articles/models.py`)
- [ ] 네이버 뉴스 크롤러 구현 (`services/crawler/`)
    - [ ] `Fetcher`: HTML 요청 및 파싱
    - [ ] `Parsers`: 언론사별 본문 전처리
- [ ] AI 분석 서비스 연동 (`services/analyzer/`)
    - [ ] 요약, 바이어스(성향), 키워드 추출 프롬프트
- [ ] 기사 목록 조회 및 상세 조회 API (`router.py`)

---

## 4. ✍️ [Feat] Analytics & Stats 도메인 구현 (통계)

**개요 (Description)**
수집된 기사를 바탕으로 일별 트렌드 통계와 키워드 네트워크를 생성합니다.
대시보드 성능을 위해 배치(Batch)로 집계 데이터를 생성해야 합니다.

**할 일 (Checklist)**
- [x] ORM 모델 구현 (`stats/models.py`)
- [ ] 일별 통계 집계 배치 로직 (`services/aggregator.py`)
    - [ ] `DailyTopicStats` 생성 (기사 수, 성향 분포)
- [ ] 키워드 네트워크 분석 로직 (`services/network.py`)
    - [ ] Co-occurrence(동시출현) 계산 및 `KeywordRelation` 저장
- [ ] 대시보드용 통계 조회 API (`router.py`)

---

## 5. 📝 [Feat] Draft 도메인 구현 (에디터)

**개요 (Description)**
사용자가 분석된 기사를 바탕으로 글을 작성하는 '초안(Draft)' 기능을 구현합니다.
심층 분석(Context Crawling) 결과도 이곳에서 처리합니다.

**할 일 (Checklist)**
- [x] ORM 모델 구현 (`drafts/models.py`)
- [ ] 초안 생성/수정/삭제 (CRUD) API (`router.py`)
- [ ] 심층 분석 트리거 로직 (`services/deep_analysis.py`)
    - [ ] 앵커 기사 기준 연관 기사 재수집
- [ ] 초안-기사 참조 관계(`DraftReference`) 관리 로직
