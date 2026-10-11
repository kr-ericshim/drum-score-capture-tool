# 원본 화면 fallback 설계 (2026-10-11, 단순판)

상태: **확정 설계, 미구현.** [HANDOFF.md](HANDOFF.md) "다음 할 일" 1번의 유일한 기준 문서다. 이 문서와 다른 문서가 다르면 이 문서를 따른다.
이전 판(reflow manifest 재사용, 잉크 포함 판정, playhead 예외, 증명 파일과 검증기, revision과 복원)은 **폐기**했다.
[ORIGINAL_SCREENS_FALLBACK_REVIEW.md](../archive/reflow/ORIGINAL_SCREENS_FALLBACK_REVIEW.md)(Astra 검토)도 폐기된 방향이니 구현 근거로 쓰지 않는다.

## 1. 목적

정리된 악보(clean reflow)가 틀렸을 때 버튼 하나로 **예전 방식**으로 다시 만든다.
예전 방식은 일정 간격으로 화면을 캡처하고, 같은 화면을 거른 뒤, 화면 전체를 순서대로 붙이는 것이다.
결과가 지저분하고 반복되어도 괜찮다. 빠지는 부분만 없으면 된다.

**원칙**
- 단순해야 한다. 안전장치는 고장 날 구석이 적어야 안전장치다.
- clean reflow 분석 결과(manifest, tracking, strips, ledger, verify)에 **의존하지 않는다**. 메인 방식이 망가져도 이 모드는 동작해야 한다. `observations.crop_roi` 같은 작은 이미지 함수를 가져다 쓰는 것은 괜찮다.
- 애매하면 남긴다. 중복은 허용하고 누락은 허용하지 않는다.
- 화면을 자르지도, 이어 붙이지도, 보정하지도 않는다.

## 2. 동작

1. **캡처**: 소스 영상을 일정 간격으로 캡처하고(기존 `extract.extract_frames`), 사용자가 적용한 ROI 그대로 자른다(`crop_roi`).
   - 간격은 **0.5초(2 fps)로 고정**한다. 예전 기본값 1초보다 촘촘하게 잡아 짧게 지나가는 화면을 줄인다.
   - legacy 경로(`main._execute_job(legacy_pipeline=True)`)의 나머지 단계는 쓰지 않는다: `detect_sheet_regions`의 ROI 자동 보정, `rectify` 보정, 오버레이 제거, 배경 평탄화.
   - 작업 프레임은 끝나면 지워지므로, 다시 만들 때는 소스 영상에서 새로 캡처한다(1–2분 정도 걸려도 된다).
2. **같은 화면 거르기**: 기존 `stitch.select_review_candidates`(내부 `page_diff.compare_frames`)를 `dedupe_level="sensitive"`, `layout_hint="page_turn"`으로 고정해서 쓴다.
   - 예전부터 쓰던 비교기다. playhead 이동은 같은 화면으로 보고, 애매한 판정은 남긴다. 더 선명한 같은 화면이 오면 그것으로 바꾼다.
   - 이미 본 화면으로 **한 장만** 돌아갔다가 바로 떠나면 깜박임으로 보고 버린다(0.5초 간격이면 1초 미만의 복귀). 두 장 이상 머물면 남긴다. 이 동작도 그대로 둔다.
   - 비교기는 고치지 않고, 새 비교 규칙도 만들지 않는다.
3. **붙이기**: 남은 화면을 시간순으로 세로 한 줄로 A4에 배치한다.
   - ROI 너비를 본문 너비에 맞추고, 모든 화면을 같은 배율로 넣는다. 한 화면이 한 페이지보다 크면 그 화면만 줄인다.
   - 화면을 쪼개거나 잘라내지 않는다.
   - **`stitch_pages`와 page-turn 압축(`_collect_page_turn_pages`)은 쓰지 않는다.** 겹침을 이어 붙이는 단계가 유일하게 내용을 지울 수 있는 곳이다.
   - 각 화면 왼쪽 여백에 작은 회색 글씨로 `#n  m:ss`를 적는다. 화면 픽셀 위에는 아무것도 그리지 않는다.
4. **내보내기**: 기존 `export_composed_pages`로 PDF와 페이지 PNG를 만든다. 캡처한 화면 원본도 `export/screens/screen_NNNN.png`로 함께 둔다.

## 3. 알려진 한계 (UI에서 숨기지 않는다)

- 0.5초보다 짧게 지나간 화면은 빠질 수 있다.
- ROI 안에 움직이는 영상(연주자, 애니메이션 로고)이 있으면 같은 화면이 여러 번 남는다. 지저분하지만 빠지지는 않는다.
- ROI 밖의 악보는 당연히 담기지 않는다.

## 4. 진입점과 UI

- **리뷰 화면**: 보조 버튼 "결과가 이상하면 원본 화면으로 다시 만들기" / "Rebuild as original screens".
  - 진행률과 취소를 보여준다. 끝날 때까지 지금 결과를 그대로 보여준다.
- **거부 화면**(`UNSUPPORTED_LAYOUT`, 예: 세로 스크롤): 거부 메시지 아래에 같은 버튼을 둔다.
- **완료 후**:
  - "원본 화면" 모드 표시, A4 미리보기, "원본 이미지 폴더 열기".
  - 정리된 악보 전용 조작(seam, 줄 크기, 마디 재배치, 줄 검토)은 숨긴다.
- **안내 문구**(첫 페이지 머리말과 화면 공통):
  - KO "원본 화면 모드: 영상 화면을 그대로 담았습니다. 같은 부분이 반복될 수 있습니다."
  - EN "Original screens: the video's screens as shown. Parts may repeat."
- **오류**: 소스 영상이 없으면 "원본 영상을 찾을 수 없어 다시 만들 수 없습니다" / "The source video is missing, so this can't be rebuilt."

## 5. 결과 저장

- 새 결과는 별도 폴더 `original_screens/`에 만들고, 다 만들어진 다음에만 작업 결과가 그 폴더를 가리키게 바꾼다(`result.output_model = "original_screens_v1"`). 실패하거나 취소하면 이전 결과가 그대로 남는다.
- 이전 clean 결과 폴더는 지우지 않고 그대로 둔다. "정리된 악보로 돌아가기" 버튼은 v1에 넣지 않는다(필요하면 나중에).
- 기존 export 작업 잠금과 202 task, polling, 취소 흐름을 그대로 쓴다.
- 성공하면 **기존** `result.reflow.revision`을 1 올린다. 미리보기 URL의 `?r=<revision>`이 바뀌어 옛 미리보기가 캐시에 남지 않는다. 새 카운터나 이력은 만들지 않는다.
- API는 `JobReviewExportRequest`에 `output_model: "original_screens_v1"` 하나만 추가한다. clean 전용 필드(`system_order`, `staff_gap_mm*`, `measure_reflow`, `rejected_seam_ids`)가 같이 오면 422로 거절한다.
- 거부된 작업(`UNSUPPORTED_LAYOUT`)에서도 이 요청을 받는다. 지금 review export가 완료된 작업만 받는다면, 이 요청에 한해서만 예외로 둔다.
- 다시 만들 때 필요한 것은 작업에 저장된 소스 영상 경로(`result.source_video_path`)와 적용된 ROI뿐이다. 소스 영상이 없으면 §4의 오류로 끝낸다.

## 6. 테스트 (3개)

1. 합성 프레임 A, A(playhead 이동), B, B, A, A → 화면 3장(A, B, A), 순서 유지.
2. 음표 하나만 바뀐 A, A, A′, A′ → 화면 2장(바뀐 화면을 버리지 않는다).
3. 완료된 작업과 거부된 작업 각각에서 다시 만들기 → PDF와 `screens/`가 생기고 revision이 1 오른다. 중간에 취소하거나 소스 영상이 없으면 이전 결과가 그대로 남는다.

그다음 백엔드 전체 테스트와 `verify:renderer-v2`를 돌리고, 실제 영상 2개(회귀 영상 1개, 거부되는 Shorts `5pe5bLexYN4` 1개)로 결과 PDF를 눈으로 확인한다.

## 7. 규모

백엔드 하루, 렌더러 반나절에서 하루. 커밋은 사용자 확인 후에만 한다. `backend/jobs/`는 건드리지 않는다.

## 8. 하지 않는 것

다음은 이 모드에 넣지 않는다. 넣자는 제안이 나오면 이 문서를 근거로 거절한다.
- reflow manifest, tracking, 잉크 포함 판정, playhead 예외 규칙 같은 새 비교 로직.
- 증명 파일, 커버리지 검증기, "모든 화면 포함" 같은 수치 보증 문구.
- 영상 전체 프레임 디코딩, 표시 변화마다 캡처하기.
- 새 revision 체계, 복원 이력, "정리된 악보로 돌아가기", 여러 화면을 한 줄에 배치하기, 사용자 재정렬.
- 기존 비교기(`page_diff`, `stitch._filter_redundant_frames`)의 동작 수정.
