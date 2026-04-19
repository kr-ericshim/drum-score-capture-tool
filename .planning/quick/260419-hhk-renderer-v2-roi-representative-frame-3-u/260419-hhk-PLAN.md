---
mode: quick-full
quick_id: 260419-hhk
slug: renderer-v2-roi-representative-frame-3-u
description: renderer-v2 ROI representative frame 추천 3후보 + 자동 선택 UI 도입 및 검증
status: planned
must_haves:
  - ROI stage exposes exactly 3 preview candidates for the representative frame flow.
  - Source entry auto-selects one candidate and auto-loads the ROI stage preview without an extra manual load click.
  - User can override the auto-selected candidate before applying ROI.
  - Export job payload keeps options.extract.start_sec at 0 even if ROI preview candidates use non-zero timestamps.
  - Tests are updated for 3 candidates, auto-select/auto-load, user override, and start_sec regression coverage.
---

# 260419-hhk Plan

## Task 1. 후보 상태와 source→ROI 진입 규칙 정리

**files**
- `desktop/renderer-v2/src/app/session/selectors.js`
- `desktop/renderer-v2/src/features/source/sourceController.js`
- `desktop/renderer-v2/src/app/App.js`

**action**
- 현재 `sourceController`가 파일 선택 직후 `roi.frameTime` 하나만 잡아 ROI 단계로 넘기는 흐름을, `roi`에 3개 대표 프레임 후보와 현재 선택 후보를 같이 들고 가는 구조로 확장한다.
- 로컬 파일 선택과 유튜브 prepare 완료 모두 같은 규칙으로 후보 3개를 계산하고, `durationSec` 기준 `20% / 33% / 50%` 시점을 후보로 고정한다. 기본 선택은 가운데 후보(`33%`)로 두고 ROI 단계에 진입하게 만든다.
- 자동 선택 직후 ROI 프리뷰 요청이 한 번만 일어나도록 `App.js`에서 진입 시점과 invalidation 타이밍을 정리하되, export payload 생성부의 `start_sec: 0` 계약은 그대로 둔다.

**verify**
- 파일 선택 또는 유튜브 준비 완료 직후 ROI 단계로 자동 이동한다.
- ROI 상태에 후보 3개와 현재 선택 후보가 채워진다.
- 첫 진입에서 선택된 후보 기준 프리뷰가 자동으로 로드된다.
- `buildJobPayload()`의 `options.extract.start_sec`는 여전히 `0`으로 유지된다.

**done**
- source 진입 시 ROI 대표 프레임 후보 3개와 자동 선택 상태가 항상 준비되고, preview/export 하위 상태가 이전 세션 값으로 오염되지 않는다.

## Task 2. ROI 화면에 3후보 추천 + 자동 선택/수동 override UI 연결

**files**
- `desktop/renderer-v2/src/features/roi/RoiScreen.js`
- `desktop/renderer-v2/src/app/App.js`
- `desktop/renderer-v2/src/lib/i18n.js`

**action**
- ROI 화면 상단에 현재 프레임 슬라이더만 의존하지 않고, 추천된 3개 후보를 바로 비교할 수 있는 선택 UI를 추가한다.
- ROI 단계에 들어오면 자동 선택된 후보가 활성 상태로 보이고, 사용자가 다른 후보를 누르면 해당 후보로 프리뷰를 다시 로드하도록 연결한다.
- 후보 변경 시 기존 preview/ROI/export 준비 상태를 무효화해서 사용자가 새 후보 기준으로 ROI를 다시 적용하도록 만들고, ROI editor 적용 이후 export 단계로 넘어가는 현재 의미는 유지한다.

**verify**
- ROI 화면에서 후보 3개가 동시에 보이고, 하나만 선택 상태로 표시된다.
- 자동 선택된 후보는 진입 직후 이미 프리뷰가 떠 있다.
- 다른 후보를 누르면 새 프리뷰로 바뀌고 기존 applied ROI/export 준비 상태는 다시 잠긴다.

**done**
- 사용자는 자동 선택을 그대로 쓰거나 후보를 바꿔도 되고, 최종 ROI 적용 이후의 export 흐름 의미는 지금과 동일하게 유지된다.

## Task 3. 런타임 테스트로 자동 선택/override/start_sec 회귀 고정

**files**
- `desktop/renderer-v2/src/tests/app-runtime-flows.test.js`
- `desktop/renderer-v2/src/tests/roi-screen.test.js`
- `desktop/renderer-v2/src/tests/session-selectors.test.js`

**action**
- source 선택 후 ROI 진입 시 후보 3개 생성, 기본 후보 자동 선택, 자동 프리뷰 로드를 검증하는 테스트를 추가한다.
- 렌더 레벨에서 ROI 화면이 정확히 후보 3개를 보여주고, 가운데 후보가 기본 활성 상태로 보이는지 검증한다.
- 사용자가 다른 후보로 override 했을 때 stale preview/ROI/export 상태가 지워지고 새 후보 기준으로만 진행되는지 검증한다.
- 기존 export regression을 유지하거나 보강해서 representative frame 후보가 non-zero timestamp를 쓰더라도 최종 job payload의 `options.extract.start_sec`는 0임을 계속 고정한다.

**verify**
- `cd desktop && node --test renderer-v2/src/tests/session-selectors.test.js renderer-v2/src/tests/source-controller.test.js renderer-v2/src/tests/roi-screen.test.js renderer-v2/src/tests/app-runtime-flows.test.js`

**done**
- 대표 프레임 후보 3개, auto-select+auto-load, user override, `start_sec: 0` 계약이 모두 테스트로 고정된다.
