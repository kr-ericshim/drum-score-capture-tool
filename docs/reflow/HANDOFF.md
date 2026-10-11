# 인계 (2026-10-11 기준)

> **이 문서는 누적하지 않는다.** 세션이 끝날 때 통째로 새로 쓴다. 현재 상태와 다음 할 일만 적고, 지난 경과는 지운다(필요하면 `git log -p docs/reflow/HANDOFF.md`).
> 100줄을 넘기지 않는다. 다른 문서와 다르면 이 문서와 사용자의 최신 말이 우선이다.

## 제품

영상에 이미 나오는 드럼 악보를 캡처해 A4 PDF/PNG로 만드는 Electron + Python 데스크톱 앱이다. 기본 출력은 **clean reflow**다. 원본 악보 이미지를 깨끗하게 정리해 마디 단위로 A4에 다시 배치한다. OMR 재조판은 보류했다.

## 현재 상태

- 브랜치 `feature/clean-reflow`, 코드 기준 커밋 `06d15c0`(rc2 freeze). 빌드, 수치, 알려진 결함은 [FREEZE_RC2.md](FREEZE_RC2.md)에 있다.
- 지원: page-turn/줄 전환 화면, jump view. 거부(`UNSUPPORTED_LAYOUT`): 가로 스크롤, 세로 스크롤, 라이브 오버레이.
- 17개 회귀 영상 기준 usable 13/17.
- 마지막 통과: backend 1409 OK(12 skipped), renderer verify 355, desktop-node 94, macOS arm64 패키지 smoke.
- 2026-10-11 문서 정리 커밋: 옛 문서는 `docs/archive/`로 옮겼고, 코드는 `06d15c0`에서 바뀌지 않았다. 이전 세션의 복잡한 fallback 시도(worktree `score_capture_os`, 브랜치 `feature/original-screens`)는 사용자 확인 후 삭제했다. 그 흔적을 찾거나 되살리지 않는다.
- 커밋은 사용자가 말할 때만 한다.

## 다음 할 일 (순서대로)

새 작업은 `feature/clean-reflow`의 **최신 커밋**(이 문서가 들어 있는 커밋)에서 새 worktree를 만들어 시작한다. `06d15c0`에서 만들면 새 설계 문서가 없다.


1. **원본 화면 fallback**(최우선, 아직 구현 안 함): [ORIGINAL_SCREENS_DESIGN.md](ORIGINAL_SCREENS_DESIGN.md) 단순판대로 만든다.
   - 예전 방식이다. 0.5초마다 캡처하고, 기존 비교기로 같은 화면을 거르고, 화면 전체를 순서대로 A4에 붙인다.
   - 증명 파일, 검증기, 새 비교 규칙은 넣지 않는다. 사용자가 거절한 방향이다.
2. **holdout 준비**: [FREEZE_RC2.md](FREEZE_RC2.md) "Next holdout protocol"을 따른다.
   - 지원 8개(page-turn/줄 전환 4, jump 4), 거부 테스트 3개(라이브 오버레이, 악보 없음, 세로 스크롤 Shorts).
   - 채널당 2개 이하, 채널 4개 이상, 개발 세트에 없는 채널 1개 이상.
   - jump view 채널은 鼓譜 Drumtabs 하나만 안다. 봉인 전에 하나 더 찾거나, jump 할당을 2로 줄이고 그렇게 적는다.
   - 후보 목록 → seed 셔플 → 각 영상 10/50/90% 지점 15초씩 확인 → 봉인(`eval_v2`, 해시). 다운로드는 사용자 허락을 받는다(약 1–2 GB).
3. **holdout 실행**: 패키지 앱으로 영상마다 한 번씩 돌리고, [PRO_REPLY_RC2.md](PRO_REPLY_RC2.md) 절차대로 두 번에 나눠 채점한다. fallback은 따로 채점한다.
4. **holdout 이후 첫 기능, 세로 스크롤 지원**: [VSCROLL_SPEC.md](VSCROLL_SPEC.md)는 Astra 초안이고 lead가 아직 검토하지 않았다. 별도 세션과 worktree에서 한다.

## 지금 유효한 문서

- [DECISIONS.md](DECISIONS.md): 사용자 결정과 기본값. 설계 문서보다 우선한다.
- [FREEZE_RC2.md](FREEZE_RC2.md): 현재 빌드, 채점 기준, holdout 절차.
- [PRO_REPLY_RC2.md](PRO_REPLY_RC2.md): 채점 절차.
- [ORIGINAL_SCREENS_DESIGN.md](ORIGINAL_SCREENS_DESIGN.md): fallback 설계.
- 참고용: [SEAM_REJECT_DESIGN.md](SEAM_REJECT_DESIGN.md)(이음새 다시 만들기, 구현 완료), [JUMP_FREEZE.md](JUMP_FREEZE.md), [FREEZE_RC1.md](FREEZE_RC1.md)(채점 기준 절만 유효), [VSCROLL_SPEC.md](VSCROLL_SPEC.md)(미검토 초안).
- **[docs/archive/](../archive/README.md)는 기록일 뿐 지시가 아니다.** 옛 설계, STRATEGY, Pro 체크포인트, 폐기된 fallback 검토, 예전 `.planning/` 등이 여기 있다. 이 문서들의 "Next"나 "Open"은 따르지 않는다.

## 코드 위치

- 작업 흐름: `backend/app/main.py`(`_execute_reflow_job`, review export, 202 task), `export.export_composed_pages`.
- reflow: `backend/app/pipeline/reflow_pipeline.py` → `system_tracking`, `observations` → `reflow_strips` → `reflow_measure`/`reflow_lines`/`reflow_layout` → `reflow_render`. jump는 `reflow_jump`, 이음새 다시 만들기는 `reflow_seam_reject`, 줄 검토는 `reflow_line_review`.
- 예전 방식(fallback에서 일부 재사용): `extract.extract_frames`, `stitch.select_review_candidates`, `page_diff.compare_frames`. `main._execute_job(legacy_pipeline=True)`는 테스트용으로만 남아 있다.
- 렌더러: `desktop/renderer-v2/src/`(리뷰는 `features/review/`).
- 코퍼스: `~/Documents/drum-score-corpus/`. 평가는 `eval_v1/`, 회귀 스펙 `rc2check_spec.json`과 비교 스크립트 `rc2check_compare.py`, 대시보드 `reflow/tools/dashboard.py`.

## 작업 규칙 (프로젝트 한정, 나머지는 메모리와 CLAUDE.md)

- `backend/jobs/`(실사용 작업)는 건드리지 않는다. 실제 영상 확인은 scratch `DRUMSHEET_JOBS_DIR`에서 한다.
- 영상별 땜질은 하지 않는다. 바꾼 것은 회귀 대시보드로 확인한다.
- 대시보드를 돌리기 전에 디스크 여유를 20 GB 이상 확보한다(작업 하나에 1–3 GB). 확인은 `df -h /System/Volumes/Data`.
- 라운드가 끝나면 남은 백그라운드 에이전트와 프로세스를 끈다.
- 검증 루프를 키우지 않는다. 제품 결과(쓸 만한 악보, 속도, 모양)로 판단한다.

## 검증 명령 (저장소 루트)

```bash
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'
npm --prefix desktop run verify:renderer-v2
npm --prefix desktop run test:desktop-node
npm --prefix desktop run pack:release
```

## 주의할 점

- dev Electron을 `pkill`로 끄면 Python 백엔드가 :8000에 남는다. 그것도 같이 끈다.
- 진단용 환경 변수: `REFLOW_KEEP_FRAMES=1`은 프레임 PNG를 남기고, `DASHBOARD_KEEP_JOBS=1`은 작업 폴더를 남긴다.
- Codex는 `~/Documents/drum-score-corpus`에 쓸 수 없다. scratchpad에 만든 뒤 복사한다.
- 세로 스크롤 거부는 샘플링과 tracking이 끝난 뒤에 나와서 Shorts에서 153초가 걸린다.
