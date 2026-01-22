# 🌿 Git Branch Strategy (2인 개발 팀용)

팀원과 충돌 없이 효율적으로 협업하기 위한 **Feature Branch Workflow** 가이드입니다.

---

## 1. 브랜치 구조 (Branch Structure)

| 브랜치 이름 | 역할 | 관리 규칙 |
| :--- | :--- | :--- |
| **`main`** | **배포 가능한 배포판 (Stable)** | - 직접 Push 금지 (Protected)<br>- 오직 PR Merge로만 업데이트 |
| **`feature/*`** | **개별 기능 개발** | - `main`에서 파생<br>- 작업 완료 후 PR 생성 |
| **`fix/*`** | **버그 수정** | - 긴급한 버그 수정 시 사용 |

---

## 2. 브랜치 명명 규칙 (Branch Naming)
도메인 또는 기능 단위로 명확하게 작성합니다.

> **형식**: `feature/{도메인}-{기능요약}`

*   `feature/user-oauth`
*   `feature/crawler-naver`
*   `fix/login-error`

---

## 3. 커밋 메시지 규칙 (Commit Convention) [중요 ✨]
커밋 메시지만 봐도 작업 내용을 알 수 있게 **태그**를 사용합니다.

> **포맷**: `[태그] 작업 내용 요약`

| 태그 | 설명 | 예시 |
| :--- | :--- | :--- |
| **[Feat]** | 새로운 기능 추가 | `[Feat] 네이버 뉴스 파싱 로직 구현` |
| **[Fix]** | 버그 수정 | `[Fix] DB 연결 타임아웃 해결` |
| **[Refactor]** | 기능 변경 없는 코드 개선 | `[Refactor] 중복 모델 코드 제거` |
| **[Style]** | 코드 포맷팅, 세미콜론 등 | `[Style] isort 적용` |
| **[Docs]** | 문서 수정 | `[Docs] README.md 업데이트` |
| **[Chore]** | 빌드/설정 파일 변경 | `[Chore] poetry 의존성 추가` |

---

## 4. PR (Pull Request) 규칙
1.  **PR 제목**: 커밋 메시지 규칙과 동일하게 작성 (`[Feat] ...`)
2.  **리뷰어 지정**: 팀원을 Reviewer로 반드시 지정
3.  **Merge 방식**: **Squash and Merge** 권장 (커밋 히스토리 깔끔하게 유지)

---

## 5. 충돌 해결 (Conflict Resolution)
충돌 발생 시 `main`을 내 브랜치로 가져와서 해결합니다.
```bash
git checkout feature/my-work
git pull origin main --rebase
# 충돌 파일 수정 후
git add .
git rebase --continue
git push -f origin feature/my-work
```
