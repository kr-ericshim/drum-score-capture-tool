# Phase 1: Score-Style Export Header And Layout - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-19
**Phase:** 01-score-style-export-header-and-layout
**Areas discussed:** Header field scope, Header visual style, Export input placement, PDF header scope, Empty-field behavior, Modal defaults, First-page header space

---

## Header Field Scope

| Option | Description | Selected |
|--------|-------------|----------|
| 핵심형 | 제목, 연주자, BPM, 날짜, 메모 | ✓ |
| 확장형 | 핵심형 + composer, arranger, key | |
| 자유형 | 사용자가 항목 자체를 커스텀 | |

**User's choice:** 핵심형
**Notes:** Phase 1은 문서 완성도 고정이 목적이며, export 편집기를 만드는 단계는 아니라는 맥락에서 핵심 4~5개만 먼저 지원하기로 결정했다.

---

## Header Visual Style

| Option | Description | Selected |
|--------|-------------|----------|
| 정통 악보형 | 중앙 큰 제목, 그 아래/주변에 메타정보가 정돈되게 배치 | ✓ |
| 실무 문서형 | 좌우 정보 블록 위주, 정보 밀도 높음 | |
| 미니멀형 | 제목만 크게, 나머지는 아주 작게 | |

**User's choice:** 정통 악보형
**Notes:** 사용자는 `흔한 악보처럼` 보이는 결과를 원했고, 문서 첫인상이 실무 문서보다 실제 악보 쪽에 더 가깝길 원했다.

---

## Export Input Placement

| Option | Description | Selected |
|--------|-------------|----------|
| export 화면 좌측 섹션 | 현재 설정 패널 안에 메타데이터 입력 추가 | |
| export 직전 모달 | export 실행 직전에 마지막 확인창에서 입력 | ✓ |
| 별도 pre-export 단계 | export 전에 한 단계 더 둠 | |

**User's choice:** export 직전 모달
**Notes:** 메타데이터 입력은 export 직전에 하는 것이 가장 편하다는 사용자 판단을 그대로 잠갔다.

---

## PDF Header Scope

| Option | Description | Selected |
|--------|-------------|----------|
| 첫 페이지 상단만 | 가장 악보답고 본문을 덜 어지럽힘 | ✓ |
| 모든 페이지 공통 헤더 | 작은 반복 정보 포함 | |
| 별도 표지 | 표지 1장 + 본문은 헤더 없음 | |

**User's choice:** 첫 페이지 상단만
**Notes:** 반복 헤더나 별도 표지는 Phase 1 범위에서 제외했다.

---

## Empty-Field Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| 숨김 | 메모나 BPM이 비어 있으면 해당 줄 자체를 숨긴다 | ✓ |
| 빈칸 유지 | 비어 있어도 자리를 남긴다 | |

**User's choice:** 숨김
**Notes:** 채워지지 않은 항목 때문에 악보 헤더가 어색한 빈 양식처럼 보이지 않도록 줄 자체를 숨기기로 했다.

---

## Modal Defaults

| Option | Description | Selected |
|--------|-------------|----------|
| 자동 채움 | 제목은 파일명 기반, 날짜는 오늘 날짜로 시작 | ✓ |
| 전부 비움 | 모든 필드를 빈 상태로 시작 | |
| 최근값 기억 | 마지막 입력값을 다시 채움 | |

**User's choice:** 자동 채움
**Notes:** 사용자가 매번 완전히 처음부터 입력하지 않도록 제목/날짜 기본값을 제공하되, BPM과 메모는 optional 입력으로 둔다.

---

## First-Page Header Space

| Option | Description | Selected |
|--------|-------------|----------|
| 여백 안 배치 | 첫 페이지 상단 여백 안에 자연스럽게 붙임 | |
| 더 큰 타이틀 영역 허용 | 첫 페이지에서 제목/헤더가 더 큰 세로 공간을 써도 됨 | ✓ |
| 표지형 타이틀 영역 | 사실상 표지처럼 넉넉한 앞장 구성 | |

**User's choice:** 더 큰 타이틀 영역 허용
**Notes:** 첫 페이지는 악보답게 보이도록 헤더 밴드가 조금 더 커져도 괜찮다는 명시적 허용이 있었다. 다만 별도 표지로 분리하는 수준은 아니다.

---

## the agent's Discretion

- 헤더 타이포 세부 스케일과 메타정보 줄 간격
- 메모 필드 라벨/placeholder 문구
- BPM 입력 세부 UX와 validation microcopy
- 모달 confirm/cancel 버튼 문구

## Deferred Ideas

- composer, arranger, key 같은 확장 메타데이터
- 여러 헤더 템플릿/테마 지원

