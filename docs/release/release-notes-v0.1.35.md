# v0.1.35 — In-app updates / 앱 내 업데이트

## 업데이트 확인과 설치

- 앱을 켤 때 새 버전을 한 번 확인하며, 사이드바의 **업데이트** 버튼으로 직접 확인할 수도 있습니다. **이번 버전 건너뛰기**는 자동 확인에만 적용됩니다.
- 사용자가 **업데이트**를 눌러야 설치 파일을 내려받습니다. GitHub Releases의 파일 크기와 SHA-256을 확인하고, 설치 또는 재시도 전에 다시 검사합니다.
- **재시작하여 설치**로 Windows 설치 프로그램을 실행하거나 macOS 앱을 교체합니다. macOS에서 직접 교체할 수 없거나 교체에 실패하면 DMG를 열어 수동 설치를 안내합니다.
- 진행 중인 캡처·YouTube 준비·PDF 재생성과 미적용 편집이 있으면 설치를 보류합니다. 설치 준비 중에는 백엔드가 새 작업 요청을 차단합니다.
- macOS 앱 교체는 같은 볼륨에서 수행하고, 새 버전 실행 전까지 기존 앱 백업을 보존합니다. 손상된 설치 파일과 현재보다 오래된 설치 기록은 재사용하지 않습니다.

**v0.1.34 이하 버전에서는 이 버전을 한 번 수동 설치해야 합니다.** 이 기능은 v0.1.35에서 이후 버전으로 업데이트할 때 사용할 수 있습니다.

## Update checks and installation

- The app checks for a new version once at launch. Use **Update** in the sidebar to check manually. **Skip this version** applies only to automatic checks.
- Download starts only after you choose **Update**. The installer size and SHA-256 are checked against GitHub Releases metadata and checked again before installation or retry.
- **Restart to install** launches the Windows installer or replaces the macOS app. If macOS cannot replace the app or a swap fails, it opens the DMG for manual installation.
- Running captures, YouTube preparation, PDF rebuilds, and unapplied edits hold installation. The backend blocks new work while installation is prepared.
- macOS swaps use the app's own volume and retain the previous app until the new version launches. Corrupted installers and records targeting an older version are not reused.

**Users on v0.1.34 or earlier must install this version manually once.** In-app updates are available from v0.1.35 to subsequent versions.

## Platforms and verification / 플랫폼과 검증 범위

Windows x64 NSIS and macOS Apple Silicon DMG are provided. Windows remains unsigned; macOS uses a free ad-hoc signature without Apple notarization. See the installation guides if the operating system blocks the first launch.

Windows x64 NSIS와 macOS Apple Silicon DMG를 제공합니다. Windows는 서명이 없으며 macOS는 무료 ad-hoc 서명을 사용하고 Apple 공증은 없습니다. 최초 실행이 차단되면 설치 안내를 참고하세요.

The release workflow runs platform tests and packaged startup/synthetic capture smoke checks before publishing. These checks do not establish an installed-app update end to end or fresh-machine Gatekeeper/SmartScreen behavior.

릴리즈 workflow는 플랫폼별 테스트와 패키지 시작·합성 영상 캡처 검증 후 설치 파일을 공개합니다. 실제 설치된 앱의 업데이트 전체 과정이나 새 컴퓨터의 Gatekeeper·SmartScreen 동작을 검증한 것은 아닙니다.
