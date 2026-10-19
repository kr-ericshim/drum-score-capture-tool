# 보관 문서

**기록용이다. 지시가 아니다.** 여기 있는 계획, "Next", "Open", 작업 규칙, 설계 제안은 따르지 않는다.
현재 기준은 [docs/reflow/HANDOFF.md](../reflow/HANDOFF.md)와 사용자의 최신 말이다.
과거 수치나 결정 배경을 찾을 때만 읽는다.

- `reflow/`: clean reflow 개발 중의 옛 설계, 전략, Pro 체크포인트 프롬프트, 검토 문서(2026-10-06 – 10-11).
  - 코드 주석은 아직 옛 경로(`docs/reflow/DESIGN_astra.md`, `LEDGER_2D_INTERFACE.md`, `JUMP_PLAN.md` 등)를 가리킨다. 그 파일들은 이제 여기 있다.
  - `ORIGINAL_SCREENS_FALLBACK_REVIEW.md`는 사용자가 거절한 fallback 방향이다. fallback은 `docs/reflow/ORIGINAL_SCREENS_DESIGN.md`(단순판)만 따른다.
  - 2026-10-19 출시 정리 때 `docs/reflow/`에서 옮긴 것(2026-10-07 – 10-11):
    - `FREEZE_RC1.md`, `FREEZE_RC2.md`: rc1·rc2 동결 기록과 홀드아웃 채점 기준. `PRO_REPLY_RC2.md`: Pro 체크포인트 #6 답변 요약.
    - `JUMP_FREEZE.md`: 점프 뷰 임계값과 config hash 동결 기록. 규칙 자체는 `docs/reflow/DECISIONS.md` "Jump-view seam resolution"에 있다. `backend/app/pipeline/reflow_jump.py` 주석이 옛 경로로 가리킨다.
    - `SEAM_REJECT_DESIGN.md`: 사용자가 틀렸다고 한 점프 이음새를 다시 만드는 설계(구현 완료 6e0c110, da3bdfa). `reflow_render.py`, `App.js`, `test_rejected_seam_render.py` 주석이 이 이름으로 가리킨다.
- `app/`: reflow 이전 앱 개발의 계획과 보고서(2026-03 – 09).
  - `planning/`은 예전 `.planning/`(GSD 단계 계획), `superpowers/`, `plans/`, `reports/`는 예전 `docs/` 하위 폴더다.
  - `design/`: 2026-09-24 다크 사이드레일 시안 A 명세(`smart-side-rail-spec.md`), 검토 화면 비교 프로토타입과 그 이미지(예전 `docs/design/`). `reports/2026-09-27-main-consolidation/preview.html`이 이 이미지를 쓴다.
  - `DEVELOPMENT_KR.md`: 2026-02의 개발 운영 문서(상태, 백로그, 빌드 변형, 오류 대응). 예전 저장소 루트 파일이다.
