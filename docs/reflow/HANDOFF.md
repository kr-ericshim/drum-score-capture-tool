# 인계 (2026-10-14, 감사 수정 코퍼스 확인과 부작용 수정 후)

> **이 문서는 누적하지 않는다.** 세션이 끝날 때 통째로 새로 쓴다. 현재 상태와 다음 할 일만 적는다(지난 경과는 `git log -p docs/reflow/HANDOFF.md`).
> 100줄을 넘기지 않는다. 다른 문서와 다르면 이 문서와 사용자의 최신 말이 우선이다.

## 제품

영상에 이미 나오는 드럼 악보를 캡처해 A4 PDF/PNG로 만드는 Electron + Python 데스크톱 앱이다.
- 기본 출력은 **clean reflow**(원본 악보 이미지를 정리해 마디 단위로 A4에 재배치)다. 보조 출력은 **원본 화면 fallback**(한 줄 영상 전용)이다.
- 파일럿 지원 범위: **불투명 판 위 한 줄 악보가 통째로 바뀌는 영상**. 점프는 실험 기능, 반투명판·실사 합성은 거부, 여러 줄 페이지와 세로 롤은 파일럿 밖.

## 현재 상태

- 브랜치 `feature/clean-reflow`. 감사 수정 배치(`e408c72`, 정리 `5954d31`) 뒤에 부작용 수정 `1ed3f6d`를 넣었다.
- **코퍼스 27개 실행(감사 수정 후)**: `eval_v2/audit27{a,b}_dashboard`. 지원/거부 판정은 fade27과 모두 같다. 사라진 마디는 보지 못했다.
  - 예상대로: C4l·Q8·6MPX ‡ 하나씩(F03), 2NzO 번호 단계 안내(F04), 정상 영상에 `VIDEO_DECODE_INCOMPLETE` 없음(F08).
  - `SHORT_DISPLAY`가 Q8 607개, uhzG 326개(둘 다 지원 범위 밖). 지원 영상은 6개 이하.
  - 부작용 2개를 찾아 `1ed3f6d`로 고쳤다. 규칙은 [DECISIONS.md](DECISIONS.md) F10·F11 항목.
    - F11: 끊긴 옅은 테두리선 조각이 약한 표기로 보호돼 줄이 높아졌다(w7mK 3→4장, 0MiL, aOED). 같은 가장자리의 얇은 조각을 합쳐 폭으로 판단한다.
    - F10: SZwT의 편집기 아이콘이 줄마다 남았다. 서로 다른 화면 8개 이상 중 80% 이상에서 같은 자리에 있는 작은 기호는 chrome으로 본다.
  - 수정 후 6개 재실행(`eval_v2/edgelogo_{a,b}_dashboard`): w7mK·0MiL·SZwT는 fade27과 픽셀까지 같다. aOED는 3장 그대로(가사 아래 여백만 조금 늘어남). C4l은 음자리표 가장자리 파란 번짐만 정리됐다. 27개 전체는 다시 돌리지 않았다.
- 검증: backend **1540 OK(12 skipped)**, `verify:renderer-v2` 363 통과, `pack:release` 재빌드, `smoke:packaged-runtime`·`smoke:packaged-electron` 통과.
- **형식 선별 도구 첫 실행**(저장소 밖, `eval_v2/format_screen_dev/runs/summary.md`): 16개 모두 기대와 맞고 60초 예산 안(최대 34초).
  - 첫 실행(`runs_v1/`)에서 C4l을 "반투명/실사 비지원 후보"로 잘못 냈다. 고친 것(protocol `format_screen-2`, `DESIGN_FROM_REPORT.md` 끝에 기록):
    - auto ROI를 앱과 똑같이(`estimate_auto_roi` + `apply_notation_envelope`) 만든다.
    - 점프 근거는 겹친 부분 잔차 6.0 이하만 인정한다. 진짜 점프 0.6–2.4, C4l 반복 그루브 13.7–15.4.
  - 이 16개는 개발 자료이지 성적이 아니다.
- 코퍼스 hook: `DASHBOARD_HOOK=eval_v2/tools/keep_tracking.py`로 돌리면 영상마다 작업 폴더의 JSON(tracking, manifest, occurrences 등)이 `<out>/<id>/workspace_json/`에 남는다.

- **패키지 앱 실사용 확인(2026-10-14, C4l, scratch `DRUMSHEET_JOBS_DIR`)**: 생성 17줄(‡ 줄 7, 짝 줄 6) → 줄 6 해제 후 PDF 다시 만들기 → 27번 줄 한 번, ‡ 없음(F07 동작) → 다른 이름으로 저장 창 취소 정상 → 재시작 후 검토 선택(16/35) 복원.
  - **막힘 버그(고침)**: 자동 ROI 제안은 소수점 좌표로 draft에 들어가는데, 적용은 에디터가 반올림한 정수 좌표를 저장했다. 그래서 적용 직후 내보내기가 "악보 영역 변경사항을 먼저 적용합니다"로 막혔다(고치기 전 패키지에서 재현). 이제 ROI 화면·단계 표시·내보내기·검토 다시 만들기가 한 판정(`selectors.hasPendingRoiDraft`, 픽셀 단위 비교)을 쓰고, 적용하면 draft를 적용값으로 맞춘 뒤 늦은 자동 제안이 덮어쓰지 못한다. 고친 패키지에서 같은 순서로 PDF 정보 창이 열리는 것을 확인했다. 검토 화면 쪽 누락은 Codex 리뷰가 찾았다.
  - 작은 문제 4개는 고쳤다(`19c0943`–`315ada1`, renderer 테스트 370개 통과, 패키지 앱에서는 확인 안 함): 없어진 작업 복원 시 안내 후 내보내기 단계로 이동, 재시작 직후 영역 확인은 백엔드 준비 뒤 실행, 재시작 후에도 저장된 PDF 라벨 유지(같은 선택일 때만), 840 높이에서 검토 목록이 패널의 절반 이상 차지.
  - 사용자 앱 데이터(localStorage)의 마지막 세션은 scratch 작업 폴더를 가리킨다. 평소처럼 앱을 열면 위 404 복원 오류가 한 번 뜬다.

## 다음 할 일 (순서대로)

1. 새 홀드아웃: 선별 도구 + 사람 1배속 확인으로 고른다. 규칙은 `eval_v2/pro8/PRO_REPLY_8_summary.md`와 `DESIGN_FROM_REPORT.md`의 선정 프로토콜.
2. 그 뒤 검토: 앱 안 형식 확인(선별 도구 재사용), 다음 확장(고정 다단 페이지).

## 알려진 한계

- 0.5초 샘플 사이에만 나온 화면은 여전히 놓친다(F06 중간 부분).
- 점프 커버리지 판정은 1관측 화면을 보지 않는다(목록에는 남음).
- 다운로드가 덜 된 짧은 파일은 통과하고 manifest 기록에만 남는다.
- 리셋 사슬의 먼 쌍은 번호 차이로만 해제한다(최악은 ‡ 하나 더).
- F10: 화면이 7개 이하인 영상에서는 같은 자리의 작은 로고가 남을 수 있다.
- 선별 도구 점프 잔차 기준(6.0)은 개발 영상 16개로만 정했다.

## 하지 않는 것

이음매 대응표, 점프 고도화, 미관 작업(C4l 라벨, 로고, RnY5), 세로 스크롤, 반투명판 완화(F13). PDF 첫 페이지 "확인 필요" 고지는 보류(사용자 결정, 플래그 잡음 때문).

## 지금 유효한 문서

- [DECISIONS.md](DECISIONS.md): 규칙과 기본값. 설계 문서보다 우선한다.
- [audit_2026-10-13/README.md](audit_2026-10-13/README.md): 감사 항목.
- [FREEZE_RC2.md](FREEZE_RC2.md), [PRO_REPLY_RC2.md](PRO_REPLY_RC2.md): rc2 빌드, 채점 절차.
- Pro 답 요약: `eval_v2/pro8/03_PRO_REPLY_7_summary.md`, `eval_v2/pro8/PRO_REPLY_8_summary.md`.
- [ORIGINAL_SCREENS_DESIGN.md](ORIGINAL_SCREENS_DESIGN.md): fallback 설계.
- **[docs/archive/](../archive/README.md)는 기록일 뿐 지시가 아니다.**

## 코드와 코퍼스 위치

- reflow 흐름: `reflow_pipeline.py` → `system_tracking` → `reflow_occurrences` → `reflow_strips` → `reflow_measure`/`reflow_layout` → `reflow_render`. 점프 `reflow_jump`, 배경 판정 `source_class`, 디코딩 `observations`, chrome `overlay_composite`.
- 코퍼스 `~/Documents/drum-score-corpus/`: 실행기 `reflow/tools/dashboard.py`, `eval_v2/tools/`(run_quick.sh, quick_compare.py, keep_tracking.py, format_screen*), 회귀 스펙 `eval_v2/fix2_spec27.json`. 27개는 fade27과 같은 두 묶음 `eval_v2/audit27_{a,b}.json`으로 나눠 돌린다(약 1시간).
- `eval_v2/jobs`(4.3 GB)는 패키지 실행 작업 폴더다. 지울지는 사용자에게 묻는다.

## 작업 규칙 (프로젝트 한정)

- `backend/jobs/`는 건드리지 않는다. 실제 영상은 scratch `DRUMSHEET_JOBS_DIR`에서 확인한다.
- 영상별 땜질과 특정 영상에 맞춘 임계값은 하지 않는다.
- 영상·코퍼스 실행 전에 전원 연결을 사용자에게 묻는다.
- 같은 저장소를 다른 세션이 동시에 고칠 수 있다. 워커를 띄우기 전에 `git status`와 다른 세션의 작업 파일을 확인한다.
- Codex는 `~/Documents/drum-score-corpus`에 쓸 수 없다. Codex가 HANDOFF를 고치면 되돌린다.

## 검증 명령 (저장소 루트)

```bash
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'
npm --prefix desktop run verify:renderer-v2
npm --prefix desktop run pack:release
```
