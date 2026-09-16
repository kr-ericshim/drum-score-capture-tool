# Drum Sheet Capture v0.1.31

## 변경 사항

- 영상 선택, 악보 영역 지정, 내보내기, 결과 검토 화면을 정리하고 한국어·영어 안내를 개선했습니다.
- 지정한 악보 영역을 기준으로 캡처하며, 악보 구조와 의심 페이지를 검토하는 처리를 보완했습니다.
- 검토 화면의 캡처 선택·자르기와 PDF 재생성 흐름을 개선하고, **PDF 다른 이름으로 저장**을 추가했습니다.
- 캡처 작업 취소와 영상 처리 하위 프로세스 제어를 보완했습니다.
- YouTube 다운로드 구성요소를 업데이트하고 설치된 앱에 포함된 JavaScript 실행 환경을 사용하도록 했습니다.
- 설치된 앱의 작업 데이터를 사용자 데이터 폴더에 저장하도록 변경했습니다.
- 배포 파일에서 개발용 테스트를 제외하고, Windows·macOS 빌드 및 패키지 실행 검증을 강화했습니다. OpenCV는 검증한 4.13 버전으로 고정했습니다.
- 다운로드, 설치, 사용 방법과 문제 해결을 담은 한국어·영어 README를 정리했습니다.

## What's changed

- Refreshed the source, score-region, export, and review screens with clearer Korean and English guidance.
- Improved capture handling for the selected score region and review diagnostics for suspicious pages.
- Improved capture selection, cropping, and PDF regeneration; added **Save PDF as…**.
- Improved capture cancellation and video subprocess control.
- Updated YouTube download components and configured the packaged app to use its bundled JavaScript runtime.
- Moved installed-app working data to the user's application data folder.
- Excluded development tests from the app and strengthened Windows/macOS packaging and runtime checks. Pinned the validated OpenCV 4.13 release.
- Updated download, installation, usage, and troubleshooting documentation.

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
xattr -dr com.apple.quarantine "/path/to/Drum.Sheet.Capture-0.1.31-arm64.dmg"
```

## Validation scope / 검증 범위

The release workflow builds both installers and checks packaged app startup, local video preview, and synthetic score capture through PNG/PDF export on Windows x64 and macOS arm64 before publishing. These automated checks do not replace a manual fresh-install walkthrough or visual review of every exported score. YouTube import depends on network access and the availability of each video.

공개 전 두 운영체제에서 설치 파일 생성, 패키징된 앱 기동, 로컬 영상 미리보기, 합성 악보 영상의 캡처와 PNG·PDF 생성을 검사합니다. 새 PC에서의 수동 설치 과정과 모든 악보 출력의 시각적 정확성까지 보증하는 검사는 아닙니다. YouTube 가져오기는 네트워크와 개별 영상의 접근 가능 여부에 영향을 받습니다.
