# 원본 화면 fallback 설계 (2026-10-11, 2차 확정판)

상태: **확정 설계.** [HANDOFF.md](HANDOFF.md) "다음 할 일" 1번의 유일한 기준 문서다. 다른 문서와 다르면 이 문서를 따른다.

- 같은 날 쓴 1차 단순판은 **이 문서로 대체되었다.** 1차판과 다른 점은 맨 아래 "1차판에서 바뀐 것"에 적었다.
- 그보다 앞선 판(reflow manifest 재사용, 잉크 포함 판정, 증명 파일, 검증기 등)과 [ORIGINAL_SCREENS_FALLBACK_REVIEW.md](../archive/reflow/ORIGINAL_SCREENS_FALLBACK_REVIEW.md)(Astra 검토)는 폐기된 방향이다. 구현 근거로 쓰지 않는다.
- 1차판대로 만든 코드가 worktree `score_capture_os2`(브랜치 `feature/original-screens-simple`, 커밋 안 함)에 있다. 이 문서에 맞게 고쳐서 쓴다.

## 1. 목적과 대상

정리된 악보(clean reflow)가 틀렸을 때, 버튼 하나로 **옛 앱(v0.2.1) 방식**으로 다시 만든다. 화면을 일정 간격으로 캡처하고, 같은 화면을 거른 뒤, 화면 전체를 순서대로 A4에 붙이는 방식이다.

**대상은 악보가 한 줄씩 바뀌는 영상뿐이다.** 화면 아래쪽 띠에 악보 한 줄이 나오고 그 줄이 통째로 바뀌는 영상이 그렇다.
- **페이지 넘김 영상은 지원하지 않는다.** 넘김 애니메이션 장면이 모두 다른 화면으로 남아 쓸 수 없다(실측: Q8XtphO6Xz0, 화면 144장 중 100장 가까이가 넘김 장면, 72쪽). 이런 장면은 확실하게 자동으로 골라낼 수도 없고, 사용자가 하나하나 빼기에는 너무 많다. 페이지 넘김 영상은 clean reflow가 지원한다.
- **스크롤 영상(세로, 가로)도 지원하지 않는다.** 같은 줄이 여러 화면에 겹쳐 반복된다(실측: Shorts 5pe5bLexYN4).
- 실측 확인: 한 줄 영상 S1nlqQdnUks는 옛 앱과 같은 결과가 나왔다. 악보 18줄이 2쪽에 빠짐없이 들어갔고, 군더더기는 빈 화면 1장과 검은 화면 1장뿐이었다.

**원칙**
- 단순하게 만든다. clean reflow 분석 결과(manifest, tracking, strips, ledger, verify)에 의존하지 않는다. `observations.crop_roi` 같은 작은 이미지 함수는 가져다 써도 된다.
- 애매하면 남긴다. 중복은 허용하고 누락은 허용하지 않는다.
- 화면을 자르거나, 이어 붙이거나, 보정하지 않는다.
- **자동으로 빼는 것은 100% 확실한 것만이다.** 조금이라도 틀릴 수 있으면 지우지 않고 "제외 후보"로 보여주고, 사용자가 보고 결정한다.

## 2. 언제 쓸 수 있나 (한 줄 영상 판정)

- 사용자가 적용한 악보 영역(ROI)의 네 점을 감싸는 사각형 기준으로 **가로 ÷ 세로가 2.25 이상**이면 한 줄 영상으로 본다. 옛 앱의 `inferLayoutHintFromRoi`가 `bottom_bar`로 판정하던 기준과 같다.
  - 실측 비율: S1nlqQdnUks 8.7(사용 가능), Q8XtphO6Xz0 1.95(불가), Shorts 5pe5bLexYN4 1.15(불가).
- 이 기준은 2026-10-11 사용자가 "일단 고정"으로 정했다. 바꾸려면 사용자 확인을 받는다.
- 렌더러와 백엔드가 같은 기준을 쓴다.
  - 렌더러: 기준에 못 미치면 버튼을 보여주지 않는다.
  - 백엔드: 같은 요청이 와도 409로 거절한다. 오류 코드는 `ORIGINAL_SCREENS_NOT_ONE_LINE`이다.

## 3. 동작

### 3.1 처음 만들기 (버튼을 눌렀을 때)

1. **캡처**: 작업에 저장된 소스 영상(`result.source_video_path`)을 `extract.extract_frames`로 **0.5초 간격(2 fps)**으로 캡처한다.
   - 작업의 캡처 구간(`options.extract.start_sec`/`end_sec`)이 있으면 그 구간만 캡처한다.
   - 프레임마다 적용된 ROI 그대로 `crop_roi`로 자른다.
   - legacy 경로의 나머지 단계(ROI 자동 보정, rectify, 오버레이 제거, 배경 평탄화)는 쓰지 않는다.
2. **같은 화면 거르기**: 기존 `stitch.select_review_candidates`를 `dedupe_level="sensitive"`, `layout_hint="page_turn"`으로 고정해서 쓴다. 비교기는 고치지 않는다.
3. **단색 화면 자동 제외** (유일하게 자동으로 지우는 경우):
   - 화면을 회색조로 바꿨을 때, 밝기 0.1 백분위와 99.9 백분위의 차이가 **10 이하**이면 그 화면을 지운다.
   - 이런 화면은 거의 한 가지 색으로 채워져 있다. 검은 화면이나 악보가 나오기 전 빈 판이 여기에 해당한다. 오선 한 줄만 있어도 차이가 훨씬 커서 지워지지 않는다.
   - 지운 화면은 결과에 남기지 않는다. 개수만 로그에 적는다.
4. **제외 후보 표시**: 남은 화면에 기존 `export.diagnose_capture_sequence`를 그대로 돌린다(옛 앱과 같은 함수).
   - `recommended_action == "exclude"`인 화면(악보가 거의 없는 화면, 영상 화면)은 **제외 후보**다. 체크를 해제한 상태로 시작하고, 첫 PDF에서도 빠진다.
   - 나머지 화면은 모두 체크된 상태로 시작한다.
   - 이 함수는 판정을 바꾸지 않고 그대로 쓴다.
5. **PDF 만들기**: 체크된 화면으로 §4의 배치대로 A4 페이지를 만든다. 체크된 화면이 하나도 없으면 실패로 끝내고, 이전 결과를 그대로 둔다.

### 3.2 다시 만들기 (리뷰에서 체크를 바꾼 뒤)

- 저장해 둔 화면(`original_screens/screens/`)에서 사용자가 체크한 것만으로 PDF를 다시 만든다. **다시 캡처하지 않는다.**
- 화면 목록과 순서는 바꾸지 않는다. 사용자 재정렬은 지원하지 않는다.

## 4. PDF 배치 (옛 앱처럼 악보만)

- A4 300 dpi다. 여백은 clean reflow와 같다(좌우 15 mm, 위아래 14 mm, `reflow_layout`의 값).
- **PDF에는 악보 화면만 넣는다.**
  - 화면 번호, 시간, 안내 문구, 테두리를 넣지 않는다.
  - 2026-10-11 사용자가 "옛 앱처럼 악보만"으로 정했다.
  - **예외는 곡 제목(문서 머리말) 하나다.** 옛 앱처럼 첫 페이지 맨 위에 넣는다(2026-10-11 사용자 확정).
    - 값은 clean 결과와 같은 문서 머리말을 쓴다. 작업의 `export.document_header`가 있으면 그것을, 없으면 `result.reflow.header`(영상 제목 등)를 쓴다. 이 중 제목, 연주자, BPM, 날짜, 메모만 쓴다.
    - 미완성 안내(`incomplete`)와 잘림 안내(`source_clipped`)는 clean 전용이라 넣지 않는다.
    - 그리기는 clean reflow의 머리말 그리기(`reflow_render._layout_header`, `header_height`)를 그대로 쓴다. 머리말과 첫 화면 사이 간격은 `reflow_layout.HEADER_GAP_MM`(5 mm)이다.
    - 머리말에 쓸 값이 없으면 아무것도 그리지 않는다. 쪽 번호는 넣지 않는다.
- 화면 너비를 본문 너비에 맞추고, 모든 화면에 같은 배율을 쓴다. 한 화면이 페이지 본문보다 높으면 그 화면만 줄인다.
- 화면을 위에서 아래로 시간순으로 붙인다. 화면 사이 간격은 2 mm다. 다음 화면이 남은 자리에 들어가지 않으면 다음 페이지로 넘긴다.
- 화면을 쪼개거나 잘라내지 않는다. `stitch_pages`, page-turn 압축(`_collect_page_turn_pages`), 옛 export의 긴 이미지 분할(`_split_long_page`)은 쓰지 않는다.
- 내보내기는 기존 `export_composed_pages`로 PDF, 페이지 PNG, 미리보기를 만든다.

## 5. 화면(UI)

- **진입점은 하나다**: clean 결과의 리뷰 화면에 둔 보조 버튼 "결과가 이상하면 원본 화면으로 다시 만들기" / "Rebuild as original screens".
  - §2의 한 줄 영상 판정을 통과할 때만 보인다.
  - 진행률과 취소를 보여준다. 끝날 때까지 지금 결과를 그대로 보여준다.
- **거부 화면(`UNSUPPORTED_LAYOUT` 등)에는 버튼을 두지 않는다.** 거부되는 영상(스크롤, 라이브 오버레이)은 모두 이 모드의 대상이 아니다.
- **완료 후 리뷰 화면 ("원본 화면" 모드)**:
  - 화면 목록: 화면마다 썸네일, `#번호`, 영상 시간(`m:ss`), 체크박스를 보여준다. 제외 후보에는 "제외 후보" 표시와 이유(`diagnose_capture_sequence`의 `warning_reasons`)를 붙인다. 이 표시는 기존 리뷰 카드 표시(`autoExcludeCandidate`)를 재사용한다.
  - "PDF 다시 만들기": 체크한 화면으로 §3.2를 실행한다.
  - A4 미리보기, "원본 이미지 폴더 열기"(`original_screens/screens/`).
  - 정리된 악보 전용 조작(seam, 줄 크기, 마디 재배치, 줄 검토)은 숨긴다.
- **안내 문구**(화면에만 보이고 PDF에는 넣지 않는다):
  - KO "원본 화면 모드: 영상 화면을 그대로 담았습니다. 같은 부분이 반복될 수 있습니다."
  - EN "Original screens: the video's screens as shown. Parts may repeat."
- **오류 문구**: 소스 영상이 없으면 "원본 영상을 찾을 수 없어 다시 만들 수 없습니다" / "The source video is missing, so this can't be rebuilt." (코드 `SOURCE_VIDEO_MISSING`)

## 6. 결과 저장과 API

- **폴더**: 결과는 별도 폴더 `original_screens/`에 만든다. 캡처 화면은 `original_screens/screens/screen_NNNN.png`이고, 제외 후보도 여기에 저장한다.
  - staged 폴더에 다 만든 다음에만 설치한다. 그때 작업 결과가 새 폴더를 가리키게 바꾼다(`result.output_model = "original_screens_v1"`).
  - 실패하거나 취소하면 이전 결과와 파일이 그대로 남는다.
  - 다시 만들기(§3.2)도 같은 방식이다. 새 staged 폴더에 `screens/`를 복사하고 페이지를 새로 쓴 뒤 설치한다.
- **이전 clean 결과**(`export/`)는 지우지 않는다. "정리된 악보로 돌아가기"는 v1에 넣지 않는다. 원본 화면 모드가 된 작업에 clean 다시 만들기 요청이 오면 지금처럼 거절한다.
- **revision**: 성공할 때마다 기존 `result.reflow.revision`을 1 올린다. 미리보기 URL의 `?r=<revision>`이 바뀐다. 새 카운터나 이력은 만들지 않는다.
- **결과 기록**: `result.original_screens`에 다음을 둔다.
  - `screens`: 화면마다 `{path, t, candidate, reasons}`
  - `selected`: PDF에 들어간 화면 경로 목록
  - `screens_dir`, `frames_captured`, `blank_dropped`(단색이라 자동으로 지운 수), `interval_sec`
- **API**: `JobReviewExportRequest`에 `output_model: "original_screens_v1"`을 둔다.
  - `keep_captures`가 없으면 §3.1(캡처부터)이다.
  - `keep_captures`가 있으면 §3.2(저장된 화면 중 그 경로만)다. 이 작업의 `original_screens.screens`에 없는 경로가 있으면 400이다.
  - clean 전용 필드(`system_order`, `staff_gap_mm`, `staff_gap_mm_explicit`, `measure_reflow`, `rejected_seam_ids`)나 `keep_images`가 같이 오면 422로 거절한다.
- **받는 작업**:
  - clean 결과가 완료된 작업(`DONE`, `clean_reflow_v1`)
  - clean 결과가 사용자 결정을 기다리는 작업(LAYOUT_CONFLICT, ledger 실패 대기)
  - 이미 원본 화면 모드인 작업(`DONE`, `original_screens_v1`)
  - 거부된 작업(`UNSUPPORTED_LAYOUT`, `NO_SCORE_SYSTEMS`, `UNSUPPORTED_SOURCE`)은 받지 않는다.
  - 모든 경우에 §2 판정을 통과해야 한다.
- 기존 export 작업 잠금, 202 task, polling, 취소 흐름을 그대로 쓴다. 진행 단계는 `capturing`, `comparing`, `rendering`, `writing`이다.

## 7. 테스트

1. 비교기: 합성 프레임 A, A(playhead 이동), B, B, A, A → 화면 3장(A, B, A), 순서 유지.
2. 비교기: 음표 하나만 바뀐 A, A, A′, A′ → 화면 2장.
3. 단색 화면과 제외 후보:
   - 검은 화면과 흰 화면은 자동으로 지워진다.
   - 오선 한 줄만 있는 화면은 지워지지 않는다.
   - `diagnose_capture_sequence`가 exclude로 판정한 화면은 `candidate=true`로 저장되고 첫 PDF에서 빠진다.
4. 작업 흐름:
   - 완료된 작업(가로로 긴 ROI)에서 만들기 → PDF와 `screens/`가 생기고 revision이 1 오른다.
   - `keep_captures`로 다시 만들기 → 그 화면만 들어가고, 다시 캡처하지 않는다.
   - 중간에 취소하거나 소스 영상이 없으면 이전 결과가 그대로 남는다.
   - 거부된 작업이나 네모에 가까운 ROI(비율 2.25 미만)는 409로 거절한다.

그다음 백엔드 전체 테스트와 `verify:renderer-v2`를 돌린다. 실제 한 줄 영상 2개(S1nlqQdnUks, aOED5zskhGk)로 결과 PDF를 눈으로 확인한다.

## 8. 하지 않는 것

다음은 이 모드에 넣지 않는다. 넣자는 제안이 나오면 이 문서를 근거로 거절한다.
- 페이지 넘김 영상과 스크롤 영상 지원. 거부 화면의 버튼.
- 넘김 애니메이션 장면을 자동으로 골라내는 규칙. 단색 화면 외의 자동 삭제.
- reflow manifest, tracking, 잉크 포함 판정, playhead 예외 같은 새 비교 로직. 기존 비교기(`page_diff`, `stitch._filter_redundant_frames`)와 `diagnose_capture_sequence`의 동작 수정.
- 겹침 이어 붙이기, 화면 자르기와 분할, 배경 정리.
- PDF 안의 화면 번호, 시간, 안내 문구, 쪽 번호. (곡 제목 머리말은 §4대로 넣는다.)
- 증명 파일, 커버리지 검증기, "모든 화면 포함" 같은 수치 보증 문구.
- 새 revision 체계, 복원 이력, "정리된 악보로 돌아가기", 여러 화면을 한 줄에 배치하기, 사용자 재정렬.

## 1차판에서 바뀐 것 (2026-10-11, 사용자와 실제 결과를 보고 정함)

- 대상을 한 줄 영상으로 좁혔다. 페이지 넘김과 스크롤은 지원하지 않는다(§1, §2).
- 거부 화면의 버튼과, 거부된 작업을 받는 예외를 없앴다(§5, §6).
- 단색 화면은 자동으로 지우고, 그 밖에 의심스러운 화면은 체크를 해제한 제외 후보로 보여준다(§3.1).
- 리뷰에서 체크한 화면만으로 다시 만들 수 있다(§3.2, `keep_captures`).
- PDF의 `#번호 시간` 표시와 첫 페이지 안내 문구를 뺐다. 안내 문구는 화면에만 보인다. 대신 곡 제목 머리말을 첫 페이지에 넣는다(§4, §5).
- 확인 영상을 회귀 영상과 Shorts에서 한 줄 영상 2개로 바꿨다(§7).
