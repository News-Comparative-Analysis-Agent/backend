from app.domains.issues.service import IssueService

def test_get_daily_trends(seeded_db_session):
    """
    [검증 목표]
    1. 대시보드 이슈 랭킹 API가 이슈 랭킹 리스트를 정상적으로 반환하는지 테스트
    """
    # Given
    service = IssueService(seeded_db_session)
    
    # When
    results = service.get_daily_trends(limit=5)
    
    # Then
    print(f"\n[Test Result] 조회된 이슈 개수: {len(results)}")
    
    assert len(results) > 0, "DB에 시드 데이터가 있다면 결과가 비어있으면 안 됩니다."
    
    for issue in results:
        print(f" - {issue.rank}위: {issue.name} (기사 {issue.article_count}개)")
        
        # 1. 랭킹 필수 정보 확인
        assert issue.id is not None
        assert issue.name is not None
        assert issue.article_count >= 0
        assert issue.rank is not None
        

    print("\n✅ 성공: 이슈 랭킹이 정상적으로 반환되었습니다.")
