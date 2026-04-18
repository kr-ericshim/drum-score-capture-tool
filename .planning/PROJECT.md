# Score Capture Program

## What This Is

Score Capture Program은 개인 연주자가 악보 영상에서 악보 영역을 지정하면 프레임 변화를 기준으로 페이지를 자동 캡쳐하고, 검토 후 PDF 악보로 정리해주는 로컬 데스크톱 앱이다. 정식 출시 목표는 단순한 캡쳐 유틸리티가 아니라, 캡쳐 정확도와 검토 흐름, 최종 PDF 문서 품질까지 모두 신뢰할 수 있는 개인 연습/카피용 악보 제작 도구로 완성하는 것이다.

## Core Value

개인 연주자가 영상으로부터 빠르고 정확하게 usable한 악보를 뽑고, 별도 편집 없이 바로 보관하거나 인쇄할 수 있는 문서 품질의 PDF를 얻어야 한다.

## Requirements

### Validated

- ✓ 로컬 영상 파일을 열고 악보 영역(ROI)을 지정해 캡쳐 작업을 시작할 수 있다 — existing
- ✓ YouTube 소스를 준비해서 같은 캡쳐 흐름으로 이어갈 수 있다 — existing
- ✓ 프레임 변화 기반으로 후보 악보 페이지를 자동 캡쳐하고 검토 목록을 만들 수 있다 — existing
- ✓ 검토 단계에서 유지할 페이지를 선택한 뒤 PNG/PDF로 export할 수 있다 — existing

### Active

- [ ] 정식 출시 기준으로 캡쳐 누락, 중복, 오검출을 줄여 개인 연주자가 신뢰할 수 있는 정확도를 확보한다
- [ ] 검토 화면에서 잘못 잡힌 페이지를 빠르고 분명하게 걸러내고 최종 결과를 자신 있게 확정할 수 있다
- [ ] export 직전에 제목, 연주자, 날짜, BPM 같은 메타데이터를 입력할 수 있다
- [ ] exported PDF 최상단에 실제 악보처럼 정돈된 헤더 레이아웃이 반영된다
- [ ] 최종 PDF가 인쇄 및 보관 가능한 악보 문서 품질로 출력된다
- [ ] 초보 사용자도 source -> ROI -> capture -> review -> export 흐름을 헷갈리지 않고 끝낼 수 있다
- [ ] 패키징된 데스크톱 빌드가 추가 개발환경 없이 실행되고, 정식 출시 전 검증 체계가 갖춰진다

### Out of Scope

- 계정 시스템 — 중앙 서버 계획이 없고 개인용 로컬 도구에 집중한다
- 클라우드 sync — local-first 제품 방향과 맞지 않는다
- 협업 기능 — 현재 대상 사용자는 개인 연주자다
- 템플릿 마켓 — 출시 핵심 가치보다 후순위이며 현재 계획에 없다
- 중앙 서버/온라인 처리 — 로컬 실행, 로컬 데이터, 로컬 export를 유지한다

## Context

- 현재 코드는 Electron 셸 + FastAPI 백엔드 + OpenCV/Pillow 기반 처리 파이프라인으로 구성된 brownfield 데스크톱 앱이다
- 기본 사용자 흐름은 source 준비 -> ROI 지정 -> 자동 캡쳐 -> review -> export 구조이며, renderer-v2가 사실상 주 UI다
- 기존 기능은 이미 캡쳐/검토/export의 골격을 제공하지만, heuristic 정확도, review 확신감, PDF 문서 완성도, 패키징 검증은 정식 출시 기준으로 더 올라가야 한다
- export는 현재 캡쳐 이미지 묶음 중심이라 문서형 악보 느낌이 약하다. 사용자는 export 직전에 메타데이터를 입력하고, PDF 첫 부분이 실제 악보처럼 보이길 원한다
- 사용자는 `정확도`, `PDF 결과물 퀄리티`, `작업 속도`, `사용 흐름 단순함`을 모두 중요하게 본다. 한 축만 좋아지는 방향은 제품 목표와 맞지 않는다

## Constraints

- **Tech stack**: Electron + FastAPI + OpenCV/Pillow 로컬 파이프라인 유지 — 기존 코드베이스와 배포 흐름을 활용해야 한다
- **Product model**: Local-first desktop only — 중앙 서버를 두지 않는 방향이 명시적으로 결정되었다
- **Target user**: 개인 연주자 — 협업/관리자용 복잡도보다 1인 작업 흐름의 명확성이 우선이다
- **Release quality**: 정확도, export 품질, 속도, 단순함을 함께 끌어올려야 한다 — 한 축만 최적화하는 식의 절충은 피한다
- **Packaging**: 정식 출시는 패키징된 앱 기준이어야 한다 — 개발환경 의존 실행만으로는 충분하지 않다

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| 로컬 우선 데스크톱 제품으로 유지한다 | 중앙 서버, 계정, sync 계획이 없고 개인용 워크플로 최적화가 우선이다 | ✓ Good |
| 핵심 사용자는 개인 연주자다 | 제품 판단 기준을 협업 복잡도보다 1인 악보 추출 경험에 맞춘다 | ✓ Good |
| 메타데이터 입력 시점은 export 직전으로 둔다 | 사용자가 가장 자연스럽다고 느끼는 타이밍이고 review 결과를 본 뒤 문서화할 수 있다 | — Pending |
| export PDF는 단순 캡쳐 번들보다 악보 문서 품질을 목표로 한다 | 최종 결과물이 바로 쓰일 수 있어야 정식 출시 가치가 생긴다 | — Pending |
| 출시 품질은 정확도, review 확신감, export 완성도, 패키징 신뢰성의 묶음으로 다룬다 | 사용자는 특정 한 축이 아니라 전체 완성도를 원한다 | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `$gsd-transition`):
1. Requirements invalidated? -> Move to Out of Scope with reason
2. Requirements validated? -> Move to Validated with phase reference
3. New requirements emerged? -> Add to Active
4. Decisions to log? -> Add to Key Decisions
5. "What This Is" still accurate? -> Update if drifted

**After each milestone** (via `$gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check -> still the right priority?
3. Audit Out of Scope -> reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-19 after initialization*
