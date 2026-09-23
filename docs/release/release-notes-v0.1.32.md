# Drum Sheet Capture v0.1.32

## 변경 사항

- 영상 선택, 악보 영역, 파일 만들기, 검토·저장 화면을 밝은 공통 스타일로 통일했습니다. 상단 단계 이동, 왼쪽 작업 도구, 오른쪽 주요 내용 배치를 사용합니다.
- 악보 영역 자동 추천을 추가했습니다. 추천은 수정 가능한 초안이며, 사용자가 영역 적용을 눌러야 확정됩니다. 추천 응답이 늦게 도착해도 사용자가 수정한 영역을 덮어쓰지 않습니다.
- 이미지 로딩과 영역 편집기 초기화 과정에서 최신 영역이 기본값으로 돌아가거나 키보드 수정이 손실되는 문제를 수정했습니다.
- 검토 중인 캡처와 출력에 포함할 캡처를 구분하고, 제외한 악보도 선명하게 확인할 수 있도록 했습니다. 재생성 전에는 이전 PDF를 여는 작업임을 명시합니다.
- 가져오기 실패 시 진행 표시를 숨기고 실패 상태를 명확히 표시합니다. 한국어·영어와 최소 창 크기의 가독성을 개선했습니다.

## What's changed

- Unified all four workflow screens with a light interface: shared top navigation, task controls on the left, and the primary media or content on the right.
- Added editable automatic score-region suggestions. Suggestions remain drafts until explicitly applied, and late responses cannot overwrite user edits.
- Fixed region-editor initialization and image-loading races that could restore a stale default region or lose keyboard edits.
- Distinguished the viewed capture from output inclusion. Excluded notation remains readable, and saved-file actions identify the previous PDF before rebuilding.
- Removed misleading progress indicators after import failure and improved Korean/English layouts at the minimum desktop size.

## Downloads / 다운로드

| Platform | Asset |
| --- | --- |
| Windows x64 — Intel/AMD 64-bit | `.exe` installer |
| macOS Apple Silicon — M-series | `arm64.dmg` |

Python, Node.js, and FFmpeg are bundled or provided by the app's runtime; no separate installation is required for the public installers. Intel Mac and native Windows ARM64 installers are not included.

일반 설치본은 Python·Node.js·FFmpeg를 별도로 설치할 필요가 없습니다. Intel Mac과 Windows ARM64 네이티브 설치본은 제공하지 않습니다.

## Installation notes / 설치 안내

The installers are unsigned. Windows SmartScreen may show an unknown publisher warning. Confirm that the download is from this repository before proceeding.

설치본은 서명되지 않아 Windows SmartScreen 경고가 표시될 수 있습니다. 이 저장소에서 받은 파일인지 확인한 뒤 진행하세요.

On macOS, open the DMG and copy **Drum Sheet Capture.app** to **Applications**. If Gatekeeper blocks the trusted download, run the following command in Terminal and reopen the app:

macOS에서는 DMG를 열고 앱을 **Applications**로 복사합니다. 이 저장소에서 받은 앱을 Gatekeeper가 차단하면 터미널에서 다음 명령을 실행한 뒤 다시 엽니다.

```bash
xattr -dr com.apple.quarantine "/Applications/Drum Sheet Capture.app"
```

If the DMG itself is blocked, substitute its actual downloaded path below:

DMG 자체가 열리지 않으면 아래 경로를 실제 다운로드한 파일 경로로 바꿔 적용하세요.

```bash
xattr -dr com.apple.quarantine "/path/to/Drum.Sheet.Capture-0.1.32-arm64.dmg"
```

## Validation scope / 검증 범위

The release workflow builds both installers and checks packaged app startup, local video preview, and synthetic score capture through PNG/PDF export on Windows x64 and macOS arm64 before publishing. These automated checks do not replace a manual fresh-install walkthrough or visual review of every exported score. YouTube import depends on network access and the availability of each video.

공개 전 두 운영체제에서 설치 파일 생성, 패키징된 앱 기동, 로컬 영상 미리보기, 합성 악보 영상의 캡처와 PNG·PDF 생성을 검사합니다. 새 PC에서의 수동 설치 과정과 모든 악보 출력의 시각적 정확성까지 보증하는 검사는 아닙니다. YouTube 가져오기는 네트워크와 개별 영상의 접근 가능 여부에 영향을 받습니다.
