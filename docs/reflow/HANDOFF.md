# 인계 (2026-10-11 기준)

> **이 문서는 누적하지 않는다.** 세션이 끝날 때 통째로 새로 쓴다. 현재 상태와 다음 할 일만 적고, 지난 경과는 지운다(필요하면 `git log -p docs/reflow/HANDOFF.md`).
> 100줄을 넘기지 않는다. 다른 문서와 다르면 이 문서와 사용자의 최신 말이 우선이다.

## 제품

영상에 이미 나오는 드럼 악보를 캡처해 A4 PDF/PNG로 만드는 Electron + Python 데스크톱 앱이다. 기본 출력은 **clean reflow**다. 원본 악보 이미지를 깨끗하게 정리해 마디 단위로 A4에 다시 배치한다. OMR 재조판은 보류했다.

보조 출력은 **원본 화면 fallback** 하나다. clean 결과가 이상할 때 옛 앱 방식으로 다시 만든다. **한 줄씩 나오는 영상(atthedrum 같은 아래쪽 띠 형식) 전용이다.**

## 현재 상태

- clean reflow: 브랜치 `feature/clean-reflow`, 코드 기준 rc2 freeze `06d15c0`. 빌드, 수치, 알려진 결함은 [FREEZE_RC2.md](FREEZE_RC2.md)에 있다.
  - 지원: page-turn/줄 전환 화면, jump view. 거부(`UNSUPPORTED_LAYOUT`): 가로 스크롤, 세로 스크롤, 라이브 오버레이.
  - 17개 회귀 영상 기준 usable 13/17.
- **원본 화면 fallback: 구현 완료, 커밋함(push 안 함, `feature/clean-reflow`에 아직 안 합침).**
  - worktree `../score_capture_os2`, 브랜치 `feature/original-screens-simple`(`3a293b7`에서 시작, 이 문서가 들어 있는 커밋).
  - 기준 문서는 [ORIGINAL_SCREENS_DESIGN.md](ORIGINAL_SCREENS_DESIGN.md)(2차 확정판) 하나다. 같은 날의 1차 단순판(페이지 넘김과 스크롤까지 대상, PDF에 번호와 시간)은 대체되었다.
  - 백엔드: `backend/app/pipeline/original_screens.py`, `main._review_export_original_screens`. 요청은 `JobReviewExportRequest.output_model="original_screens_v1"`이다.
  - 렌더러:
    - clean 리뷰 왼쪽 아래 버튼(한 줄 영상일 때만 보임)
    - 원본 화면 리뷰 모드(`review.originalScreens`, 행 종류 `screen`)
    - `lib/api.js reviewExportBody`
  - Codex 리뷰가 지적한 세 가지를 고치고 회귀 테스트를 붙였다.
    - 화면 저장 실패가 조용히 화면을 빠뜨리던 문제
    - 결과 기록 실패 때 대기 상태가 "완료"로 바뀌던 문제
    - clean 리뷰의 실행 취소 기록이 원본 화면 모드에 남던 문제
- 마지막 통과(worktree, Codex 지적 수정 뒤): backend 1420 OK(12 skipped), `verify:renderer-v2` 360.
  - `test:desktop-node`는 desktop 프로세스를 바꾸지 않아서 돌리지 않았다.
- 실제 확인:
  - 한 줄 영상 S1nlqQdnUks와 aOED5zskhGk로 PDF를 만들어 사용자가 봤다. 각 2쪽이고 빠진 줄이 없었다.
  - 개발용 Electron에서 버튼 → 진행률 → 원본 화면 모드 → 체크 해제 후 다시 만들기를 눌러 확인했다. 1440×960과 1120×840, 한국어와 영어로 봤다.
  - **패키지 앱과 Windows에서는 확인하지 않았다.**

## 다음 할 일 (순서대로)

1. **fallback 마무리**: `feature/clean-reflow`에 합칠지 사용자에게 묻는다.
   - 패키지 앱 smoke(`npm --prefix desktop run pack:release` 후 실행)에서 버튼이 보이고 PDF가 나오는지 한 번 본다.
2. **holdout 준비**: [FREEZE_RC2.md](FREEZE_RC2.md) "Next holdout protocol"을 따른다.
   - 지원 8개(page-turn/줄 전환 4, jump 4), 거부 테스트 3개(라이브 오버레이, 악보 없음, 세로 스크롤 Shorts).
   - 채널당 2개 이하, 채널 4개 이상, 개발 세트에 없는 채널 1개 이상.
   - jump view 채널은 鼓譜 Drumtabs 하나만 안다. 봉인 전에 하나 더 찾거나, jump 할당을 2로 줄이고 그렇게 적는다.
   - 후보 목록 → seed 셔플 → 각 영상 10/50/90% 지점 15초씩 확인 → 봉인(`eval_v2`, 해시). 다운로드는 사용자 허락을 받는다(약 1–2 GB).
3. **holdout 실행**: 패키지 앱으로 영상마다 한 번씩 돌리고, [PRO_REPLY_RC2.md](PRO_REPLY_RC2.md) 절차대로 두 번에 나눠 채점한다. fallback은 한 줄 영상에서만 따로 채점한다.
4. **holdout 이후 첫 기능, 세로 스크롤 지원**: [VSCROLL_SPEC.md](VSCROLL_SPEC.md)는 Astra 초안이고 lead가 아직 검토하지 않았다. 별도 세션과 worktree에서 한다. fallback과는 연결하지 않는다.

## 지금 유효한 문서

- [DECISIONS.md](DECISIONS.md): 사용자 결정과 기본값. 설계 문서보다 우선한다.
- [FREEZE_RC2.md](FREEZE_RC2.md): 현재 빌드, 채점 기준, holdout 절차.
- [PRO_REPLY_RC2.md](PRO_REPLY_RC2.md): 채점 절차.
- [ORIGINAL_SCREENS_DESIGN.md](ORIGINAL_SCREENS_DESIGN.md): fallback 설계(2차 확정판). "하지 않는 것" 목록을 지킨다.
- 참고용: [SEAM_REJECT_DESIGN.md](SEAM_REJECT_DESIGN.md)(구현 완료), [JUMP_FREEZE.md](JUMP_FREEZE.md), [FREEZE_RC1.md](FREEZE_RC1.md)(채점 기준 절만 유효), [VSCROLL_SPEC.md](VSCROLL_SPEC.md)(미검토 초안).
- **[docs/archive/](../archive/README.md)는 기록일 뿐 지시가 아니다.** 이 문서들의 "Next"나 "Open"은 따르지 않는다.

## 코드 위치

- 작업 흐름: `backend/app/main.py`(`_execute_reflow_job`, review export, 202 task), `export.export_composed_pages`.
- reflow: `backend/app/pipeline/reflow_pipeline.py` → `system_tracking`, `observations` → `reflow_strips` → `reflow_measure`/`reflow_lines`/`reflow_layout` → `reflow_render`. jump는 `reflow_jump`, 이음새 다시 만들기는 `reflow_seam_reject`, 줄 검토는 `reflow_line_review`.
- fallback이 재사용하는 예전 코드: `extract.extract_frames`, `stitch.select_review_candidates`, `page_diff.compare_frames`, `export.diagnose_capture_sequence`. 이 코드들의 동작은 바꾸지 않는다.
- 렌더러: `desktop/renderer-v2/src/`(리뷰는 `features/review/`).
- 옛 앱 v0.2.1: worktree `../score_capture_v021`(main `2ef54c4`). 옛 동작을 비교할 때 쓴다.
- 코퍼스: `~/Documents/drum-score-corpus/`. 평가는 `eval_v1/`, 회귀 스펙 `rc2check_spec.json`, 비교 스크립트 `rc2check_compare.py`, 대시보드 `reflow/tools/dashboard.py`. ROI 기록은 `rois.json`(자동 추천값이라 가사가 잘릴 수 있다).

## 작업 규칙 (프로젝트 한정, 나머지는 메모리와 CLAUDE.md)

- `backend/jobs/`(실사용 작업)는 건드리지 않는다. 실제 영상 확인은 scratch `DRUMSHEET_JOBS_DIR`에서 한다.
- 영상별 땜질은 하지 않는다. 바꾼 것은 회귀 대시보드로 확인한다.
- 대시보드를 돌리기 전에 디스크 여유를 20 GB 이상 확보한다(작업 하나에 1–3 GB). 확인은 `df -h /System/Volumes/Data`.
- 라운드가 끝나면 남은 백그라운드 에이전트와 프로세스를 끈다.
- 설계에 없는 게 필요해 보이면 만들지 말고 사용자에게 한 줄로 묻는다.

## 검증 명령 (저장소 루트)

```bash
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'
npm --prefix desktop run verify:renderer-v2
npm --prefix desktop run test:desktop-node
npm --prefix desktop run pack:release
```

## 주의할 점

- worktree에는 `backend/.venv`와 `desktop/node_modules`가 없다.
  - Python은 메인 저장소의 `backend/.venv/bin/python`을 쓴다.
  - node_modules는 확인할 때만 심볼릭 링크를 만들고, 끝나면 지운다.
- dev Electron을 띄울 때는 `DRUMSHEET_PYTHON_BIN`과 `DRUMSHEET_JOBS_DIR`(scratch)을 지정한다.
  - dev 앱은 사용자의 userData(`~/Library/Application Support/drum-sheet-capture`)를 같이 쓴다. localStorage 세션을 바꾸면 먼저 백업하고 끝나면 되돌린다.
  - 끌 때는 Electron 메인 프로세스와 :8000 백엔드를 모두 끈다. `pkill` 패턴이 메인 프로세스를 놓치기 쉽다.
- 진단용 환경 변수: `REFLOW_KEEP_FRAMES=1`은 프레임 PNG를 남기고, `DASHBOARD_KEEP_JOBS=1`은 작업 폴더를 남긴다.
- Codex는 `~/Documents/drum-score-corpus`에 쓸 수 없다. scratchpad에 만든 뒤 복사한다.
- 세로 스크롤 거부는 샘플링과 tracking이 끝난 뒤에 나와서 Shorts에서 153초가 걸린다.
