# 인계 (2026-10-13 저녁, 감사 수정 배치 커밋 후)

> **이 문서는 누적하지 않는다.** 세션이 끝날 때 통째로 새로 쓴다. 현재 상태와 다음 할 일만 적는다(지난 경과는 `git log -p docs/reflow/HANDOFF.md`).
> 100줄을 넘기지 않는다. 다른 문서와 다르면 이 문서와 사용자의 최신 말이 우선이다.

## 제품

영상에 이미 나오는 드럼 악보를 캡처해 A4 PDF/PNG로 만드는 Electron + Python 데스크톱 앱이다.
- 기본 출력은 **clean reflow**(원본 악보 이미지를 정리해 마디 단위로 A4에 재배치)다. 보조 출력은 **원본 화면 fallback**(한 줄 영상 전용)이다.
- 파일럿 지원 범위: **불투명 판 위 한 줄 악보가 통째로 바뀌는 영상**. 점프는 실험 기능, 반투명판·실사 합성은 거부, 여러 줄 페이지와 세로 롤은 파일럿 밖.

## 현재 상태

- 브랜치 `feature/clean-reflow`. 이번 세션의 감사 수정 배치를 한 커밋으로 넣었다(사용자 승인).
- 감사 결과와 수정: [audit_2026-10-13/README.md](audit_2026-10-13/README.md), 규칙은 [DECISIONS.md](DECISIONS.md) "Astra audit fixes (2026-10-13)".
  - 고침: F01(1관측 화면을 검토 목록에), F03(커서 리셋은 합치지 않고 ‡), F04(가운데 번호 단계), F05(이웃 하나 기준 숨김), F06(영상 끝 프레임 1회 추가 샘플), F07(선택 후 ‡ 재계산, 리셋 사슬 포함), F08(디코딩 조기 종료 = 실패, 끝 근처 seek로 진짜 끝인지 확인), F09(표기 제거 단계), F10(악보 줄 안 작은 색 기호는 chrome으로 지우지 않음), F11(옅은 표기 보호·생존 검사).
  - Codex 검수가 찾은 4개(리셋 ‡ 선택 후 소실, 디코딩 판정 허점, 점프 구간 안 1관측 화면 소실, 점프 strip의 옅은 표기 잘림)와 Opus 재검수가 찾은 디코딩 오판정(VFR 마지막 프레임 정지, 컨테이너가 더 긴 MKV/WebM)도 고쳤다.
  - 보류(사용자 결정): PDF 첫 페이지 "확인 필요" 고지. `OVERLAY_UNRECOVERED`·`MINORITY_CONTENT_DROPPED`가 지원 영상 거의 모든 줄에 붙어 있어 잡음이 된다. F13은 변경 없음.
- 검증: backend 전체 **1538 OK(12 skipped)**. 모두 합성 fixture·mock이다. **실제 영상, 코퍼스, 패키지 앱, `verify:renderer-v2`는 돌리지 않았다**(사용자가 배터리로 작업 중이라 영상·코퍼스 실행 금지).
- 형식 선별 도구(코퍼스 쪽, 저장소 밖): `~/Documents/drum-score-corpus/eval_v2/tools/format_screen.py` + 검토 페이지 `format_review.html`. 자동으로는 "비지원 후보(근거)"나 "사람 확인 필요"만 내고, "지원"은 사람이 클립 3개를 1배속으로 본 뒤에만 고를 수 있다. 설계와 개발 자료: `eval_v2/format_screen_dev/DESIGN_FROM_REPORT.md`. **실제 영상으로는 아직 한 번도 안 돌렸다.**
- Astra(max) 조언 원문은 세션 scratchpad에 있었다(휘발). 요지:
  - 순서: 핵심 손실 수정 → 앱 안 형식 확인 → 패키지 실사용 → 홀드아웃. 다음 지원 확장은 **고정 2–3줄 페이지 전체 교체**, 그다음 가로 점프.
  - 검증은 줄이되 실제 PDF·앱 확인은 남긴다. 수정마다 27개 재디코딩은 피한다.

## 다음 할 일 (순서대로, 전원 연결 후)

1. **코퍼스 27개 1회 실행**(`eval_v2/tools/run_quick.sh` 또는 27개 전체를 fade27과 비교). 볼 것:
   - C4l·DEQ에 ‡ 붙은 줄이 하나씩 늘어나는지(F03, 예상됨). ‡ 없이 늘면 결함.
   - 검토 목록의 `SHORT_DISPLAY`가 크게 늘지만 PDF는 같아야 한다(F01).
   - `content_steps`의 `kind: "removed"`가 흰 박스·회색 처리로 잘못 나뉘는지(F09). DEQ·6MPX·C4l의 새 `NUMBER_STEP_UNRESOLVED`(F04).
   - Dr5j·Fzc0·SZwT·Teo·uhzG의 `screen_chrome.protected_px`와 로고 조각 잔류(F10). 줄 높이 증가·옅은 잔여물(F11).
   - `VIDEO_DECODE_INCOMPLETE`가 정상 영상에 뜨지 않는지, `decode_end_confirmed_by_seek`가 붙은 영상이 있는지(F08).
   - 결과가 이상하면 코딩을 멈추고 PDF를 직접 본 뒤 사용자와 정한다.
2. **선별 도구 개발 실행:** `zsh ~/Documents/drum-score-corpus/eval_v2/tools/format_screen_dev16.sh` → `eval_v2/format_screen_dev/runs/summary.md`. uhzG·oGnU(이동 플래그), jrmm(세로 이동), Q8·01Mr(MULTI_ROW)가 잡히는지와 60초 예산. 이 16개는 개발 자료이지 성적이 아니다.
3. `npm --prefix desktop run verify:renderer-v2`(F08 문구 2줄 추가됨) → `pack:release`로 패키지 재빌드, smoke.
4. 실제 앱에서 생성, 검토(가운데 화면 해제 후 재내보내기 ‡ 포함), 재생성, 저장·취소, 재시작·복원.
5. 새 홀드아웃: 선별 도구 + 사람 1배속 확인으로 고른다. 규칙은 `eval_v2/pro8/PRO_REPLY_8_summary.md`와 `DESIGN_FROM_REPORT.md`의 선정 프로토콜.
6. 그 뒤 검토: 앱 안 형식 확인(선별 도구 재사용), 다음 확장(고정 다단 페이지).

## 알려진 한계 (이번 배치 이후)

- 0.5초 샘플 사이에만 나온 화면은 여전히 놓친다(F06 중간 부분).
- 점프 커버리지 판정은 1관측 화면을 보지 않는다(목록에는 남음, 잡음 방지 의도).
- 다운로드가 덜 된 파일처럼 정말 짧은 파일은 통과하고 manifest 기록에만 남는다.
- 이번 변경 전에 분석한 점프 작업은 이음매 재처리가 `SEAM_REPAIR_INCOMPATIBLE`로 끝날 수 있다(오래된 작업만).
- 리셋 사슬의 먼 쌍은 번호 차이로만 해제한다(최악은 ‡ 하나 더).

## 하지 않는 것

이음매 대응표, 점프 고도화, 미관 작업(C4l 라벨, 로고, RnY5), 세로 스크롤, 반투명판 완화(F13).

## 지금 유효한 문서

- [DECISIONS.md](DECISIONS.md): 규칙과 기본값. 설계 문서보다 우선한다.
- [FREEZE_RC2.md](FREEZE_RC2.md), [PRO_REPLY_RC2.md](PRO_REPLY_RC2.md): rc2 빌드, 채점 절차.
- Pro 답 요약: `eval_v2/pro8/03_PRO_REPLY_7_summary.md`, `eval_v2/pro8/PRO_REPLY_8_summary.md`.
- [ORIGINAL_SCREENS_DESIGN.md](ORIGINAL_SCREENS_DESIGN.md): fallback 설계.
- **[docs/archive/](../archive/README.md)는 기록일 뿐 지시가 아니다.**

## 코드와 코퍼스 위치

- reflow 흐름: `reflow_pipeline.py` → `system_tracking` → `reflow_occurrences` → `reflow_strips` → `reflow_measure`/`reflow_layout` → `reflow_render`. 점프 `reflow_jump`, 배경 판정 `source_class`, 디코딩 `observations`.
- 코퍼스 `~/Documents/drum-score-corpus/`: 실행기 `reflow/tools/dashboard.py`, `eval_v2/tools/`(run_quick.sh, quick_compare.py, audit_freq.py, format_screen*), 회귀 스펙 `eval_v2/fix2_spec27.json`.
- `eval_v2/jobs`(4.3 GB)는 패키지 실행 작업 폴더다. 지울지는 사용자에게 묻는다.

## 작업 규칙 (프로젝트 한정)

- `backend/jobs/`는 건드리지 않는다. 실제 영상은 scratch `DRUMSHEET_JOBS_DIR`에서 확인한다.
- 영상별 땜질과 특정 영상에 맞춘 임계값은 하지 않는다.
- 같은 저장소를 다른 세션이 동시에 고칠 수 있다. 워커를 띄우기 전에 `git status`와 다른 세션의 작업 파일을 확인한다.
- Codex는 `~/Documents/drum-score-corpus`에 쓸 수 없다. Codex가 HANDOFF를 고치면 되돌린다.

## 검증 명령 (저장소 루트)

```bash
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'
npm --prefix desktop run verify:renderer-v2
npm --prefix desktop run pack:release
```
