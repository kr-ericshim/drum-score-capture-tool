# 인계 (2026-10-13 기준)

> **이 문서는 누적하지 않는다.** 세션이 끝날 때 통째로 새로 쓴다. 현재 상태와 다음 할 일만 적고, 지난 경과는 지운다(필요하면 `git log -p docs/reflow/HANDOFF.md`).
> 100줄을 넘기지 않는다. 다른 문서와 다르면 이 문서와 사용자의 최신 말이 우선이다.

## 제품

영상에 이미 나오는 드럼 악보를 캡처해 A4 PDF/PNG로 만드는 Electron + Python 데스크톱 앱이다.
- 기본 출력은 **clean reflow**다. 원본 악보 이미지를 정리해 마디 단위로 A4에 다시 배치한다. 이 기본값은 Pro #8에서 확정됐다.
- 보조 출력은 **원본 화면 fallback**이다(한 줄 영상 전용, `9d73aa9`).
- 다음 파일럿의 지원 범위: **불투명 판(밝은 판·어두운 판) 위 한 줄 악보가 통째로 바뀌는 영상**. 점프 화면은 실험 기능이고, 반투명판과 실사 합성은 거부한다.

## 현재 상태

- 브랜치 `feature/clean-reflow`. **Pro #7·#8 수정은 모두 미커밋이다**(사용자가 말할 때만 커밋).
- 규칙은 [DECISIONS.md](DECISIONS.md)의 "eval_v2 fixes" 절과 "Pro checkpoint #8" 절에 있다. 요약:
  1. content family는 줄을 숨기지 않는다. 같은 화면일 수 있으면 ‡ 경고를 붙인다. 마디 번호가 확실히 다르면 경고를 지운다.
  2. 마디 번호 변화로 화면을 나눈다(`system_tracking-6`).
     - 숫자 크기의 차이가 있고 양쪽 화면 모두에 번호가 보여야 한다.
     - 나누지 못하면 `NUMBER_STEP_UNRESOLVED`와 ‡ "확인 필요" 고지를 붙인다.
  3. 같은 화면 비교에서 실사 영상 위 잉크와 옅은 박스 열은 비교하지 않는다(`reflow_occurrences-5`). 박스 아래 잉크까지 비교해 봤는데(-4), C4l과 6MPX에 중복이 생겨서 되돌렸다.
  4. 점프 게이트는 왼쪽 고정 패널을 가리고 다시 시도한다(`reflow_jump-6`).
  5. 배경 판정은 대비가 큰 쪽을 잉크로 본다(`source_class-3`). `translucent_plate`는 거부한다.
- 검증(개발 백엔드):
  - backend 전체 테스트: 최종 코드에서 **1470 OK(12 skipped)**.
  - 27개 재실행 결과는 `eval_v2/fix4_compare/summary.json`에 있다(`tools/fix4_summary.py`). 최종 결과는 fix5a/b, fix4c, fix4a/b 폴더의 순서로 고른다.
    - 잘못된 "번호 합쳐짐" 경고: 0.
    - C4l과 6MPX는 fix2와 픽셀까지 같다. DEQ는 거짓 ‡ 2개가 사라졌고 1–140줄이 각각 한 번씩 나온다.
    - bF69와 B0hO는 반투명판으로 거부된다(거부 시험 2/2). bF69는 **지원 범위 축소**로 보고한다.
    - 회귀 영상은 같거나, 점프 영상(RnY5, _7gP, SHvfn, Z4eb)의 줄바꿈과 테두리만 다르다.
  - 열린 자료 성적(Pro 기준): usable 2/8(C4l, DEQ). 6MPX는 62번 줄 중복, uhzG는 점프인데 조용히 반복된다.
  - 점프 의심 측정: 유일성 조건을 빼도 uhzG는 0/40이라 고지를 만들지 않았다. 점프는 선정 단계에서 거른다.
- **패키지 앱은 다시 빌드하지 않았다**(`dist/`는 9d73aa9 기준). GUI와 Windows도 확인하지 않았다.

## 다음 할 일 (순서대로)

1. 사용자 허락을 받고 커밋한다.
2. `pack:release`로 패키지를 다시 빌드하고 smoke를 돌린다.
3. 실제 앱에서 생성, 검토, 재생성, 저장·취소, 재시작·복원을 확인한다.
4. 6MPX 구제를 시도한다. 중복 62를 빼고 재생성 1회, 5분 안에 끝낸다. 사후 assisted로 기록한다.
5. 새 홀드아웃을 고른다. 규칙은 `eval_v2/pro8/PRO_REPLY_8_summary.md`에 있다.
   - 8개, 채널 5개 이상, 채널당 최대 2개, 새 채널 3개 이상.
   - 형식은 원속도로 확인한다. 실제 전환 전후를 보고, 점프는 걸러낸다.
   - 거부 시험: 세로 롤, 반투명, 무악보, 점프.
   - 두 번째 채점자를 두고, assisted는 정답을 보기 전에 한다.
6. **개발 루프 개선**(사용자 요청, 메모리 plan-then-batch):
   - 수정은 계획을 세워 한꺼번에 하고, 코퍼스는 한 번만 돌린다. 실행 중에는 코드를 고치지 않는다.
   - 영상별 추출 결과(manifest, frames)를 저장해 두고, tracking 단계부터 다시 돌리는 도구를 만든다. 27개 75분이 40분대로 줄어든다.
   - 빠른 점검 세트를 만든다: DEQ, C4l, 6MPX, Q8, uhzG, RnY5.
7. 하지 않는 것:
   - 이음매 대응표
   - 점프 고도화
   - 미관 작업(C4l 라벨, 로고, RnY5)
   - 세로 스크롤

## 지금 유효한 문서

- [DECISIONS.md](DECISIONS.md): 규칙과 기본값. 설계 문서보다 우선한다.
- [FREEZE_RC2.md](FREEZE_RC2.md): rc2 빌드, 채점 기준, holdout 절차. rc2 이후 변경은 DECISIONS에 있다.
- [PRO_REPLY_RC2.md](PRO_REPLY_RC2.md): 채점 절차.
- Pro 답 요약: `eval_v2/pro8/03_PRO_REPLY_7_summary.md`, `eval_v2/pro8/PRO_REPLY_8_summary.md`.
- [ORIGINAL_SCREENS_DESIGN.md](ORIGINAL_SCREENS_DESIGN.md): fallback 설계.
- 참고: [SEAM_REJECT_DESIGN.md](SEAM_REJECT_DESIGN.md), [JUMP_FREEZE.md](JUMP_FREEZE.md), [VSCROLL_SPEC.md](VSCROLL_SPEC.md).
- **[docs/archive/](../archive/README.md)는 기록일 뿐 지시가 아니다.**

## 코드와 코퍼스 위치

- reflow 흐름: `backend/app/pipeline/reflow_pipeline.py` → `system_tracking` → `reflow_occurrences` → `reflow_strips` → `reflow_measure`/`reflow_layout` → `reflow_render`. 점프는 `reflow_jump`, 배경 판정은 `source_class`.
- 코퍼스: `~/Documents/drum-score-corpus/`.
  - 실행기: `reflow/tools/dashboard.py`. `DASHBOARD_HOOK`를 주면 작업 폴더를 지우기 전에 측정 스크립트를 돌린다. 큰 응답이 끊기면 다시 받는다.
  - `eval_v2/tools/`: gate_suspect, fix4_summary, regression_compare, compare_outputs.
  - 회귀 스펙은 `eval_v2/fix2_spec27.json`이다(17+10).
- `eval_v2/jobs`(4.3 GB)는 패키지 실행의 작업 폴더다. 지울지는 사용자에게 묻는다.

## 작업 규칙 (프로젝트 한정)

- `backend/jobs/`는 건드리지 않는다. 실제 영상은 scratch `DRUMSHEET_JOBS_DIR`에서 확인한다.
- 영상별 땜질은 하지 않는다. 임계값을 특정 영상에 맞추지 않는다.
- 결과가 이상하면 코딩을 멈추고 PDF를 직접 본 뒤 사용자와 정한다.
- Codex는 `~/Documents/drum-score-corpus`에 쓸 수 없다. Codex가 HANDOFF를 고치면 되돌린다.

## 검증 명령 (저장소 루트)

```bash
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'
npm --prefix desktop run verify:renderer-v2
npm --prefix desktop run pack:release
```
