<!-- minimum-os: darwin=13.0 -->
# v0.2.0 — New app runtime and macOS 13 requirement / 새 앱 실행 환경과 macOS 13 요구

## macOS 13 이상 필요

- 앱 실행 환경인 Electron을 39에서 44로 올렸습니다. Electron 39는 보안 지원이 끝났고, 44에는 39에 들어오지 않은 보안 수정이 함께 들어 있습니다.
- 이 버전부터 **macOS 13(Ventura) 이상**에서 실행됩니다. Apple Silicon Mac은 모두 macOS 13 이상으로 업데이트할 수 있습니다.
- **macOS 12를 쓰고 있다면 앱 안 업데이트를 누르지 말고 v0.1.37을 계속 쓰세요.** v0.1.37 이하의 앱은 이 요구 사항을 알지 못해 업데이트를 제안합니다. 이미 업데이트해서 앱이 열리지 않으면 릴리스 페이지에서 v0.1.37을 다시 설치하세요.
- 이 버전부터는 새 버전이 지금 운영체제에서 실행되지 않으면 자동 설치 대신 필요한 운영체제 버전을 알려 줍니다.

## 작은 변경

- 영상 선택 창이 마지막으로 연 폴더에서 열립니다. 앱을 다시 시작하면 다운로드 폴더에서 시작합니다.
- 진단 로그와 문제 보고 내용은 클립보드 복사가 끝난 뒤에 다음 단계로 넘어갑니다.

## macOS 13 or later required

- Electron, the app runtime, moves from 39 to 44. Electron 39 is out of security support, and 44 includes security fixes that 39 never received.
- From this version the app runs on **macOS 13 (Ventura) or later**. Every Apple Silicon Mac can update to macOS 13 or later.
- **If you are on macOS 12, do not press Update in the app; keep using v0.1.37.** Apps up to v0.1.37 cannot read this requirement and will still offer the update. If you already updated and the app no longer opens, reinstall v0.1.37 from the releases page.
- From this version on, when a newer release cannot run on your system, the app tells you which OS version it needs instead of installing it.

## Small changes

- The video picker opens in the folder you last used. After a restart it starts in Downloads.
- Copying diagnostics or a problem report finishes before the next step continues.

## Platforms and verification / 플랫폼과 검증 범위

Windows x64 NSIS and macOS Apple Silicon DMG are provided. Windows remains unsigned; macOS uses a free ad-hoc signature without Apple notarization. From v0.1.35, the app can update itself to this version.

Windows x64 NSIS와 macOS Apple Silicon DMG를 제공합니다. Windows는 서명이 없으며 macOS는 무료 ad-hoc 서명을 사용하고 Apple 공증은 없습니다. v0.1.35부터는 앱 안에서 이 버전으로 업데이트할 수 있습니다.

The release workflow runs platform tests and packaged startup/synthetic capture smoke checks before publishing. The macOS package with Electron 44 was also built and started locally. Capture from real videos, installed-app updates, the macOS 12 behavior, and fresh-machine Gatekeeper/SmartScreen behavior were not verified end to end.

릴리즈 workflow는 플랫폼별 테스트와 패키지 시작·합성 영상 캡처 검증 후 설치 파일을 공개합니다. Electron 44로 만든 macOS 패키지를 로컬에서도 만들어 실행해 보았습니다. 실제 영상 캡처, 설치된 앱의 업데이트 전체 과정, macOS 12에서의 동작, 새 컴퓨터의 Gatekeeper·SmartScreen 동작은 확인하지 않았습니다.
