# v0.1.33 — smaller media tools and capture ranges

## 한국어

- FFmpeg·ffprobe를 동일한 LGPL 소스 구성으로 빌드하고 해당 소스와 라이선스를 함께 제공합니다. macOS arm64 도구, AV1 소프트웨어 디코딩, Windows D3D11VA/DXVA2 지원을 유지합니다.
- 캡처 시작·종료 구간을 지정하고 유효성을 검사할 수 있습니다.
- 새 안정 버전 알림, 진단 로그 복사, 문제 보고 링크와 처리기 준비 안내를 추가했습니다.
- Python 3.11 계열과 잠금 파일 기반 빌드를 사용하며 불필요한 uvicorn 추가 모듈을 제외했습니다.

## English

- Build matching LGPL FFmpeg/ffprobe tools from pinned sources, with source archives and notices alongside installers. Retain native macOS arm64 tools, software AV1 decoding, and Windows D3D11VA/DXVA2 support.
- Select and validate a capture start/end range.
- Add stable-release notifications, redacted diagnostic copy, an issue link, and clearer engine preparation states.
- Build against the Python 3.11 line and locked dependencies without unnecessary uvicorn extras.

## Distribution

Targets: macOS Apple Silicon and Windows x64. Builds remain unsigned. This version provides update notifications and a manual download link, not automatic installation. Branch preflight does not publish a release. Hosted smoke checks do not prove fresh-machine Gatekeeper/SmartScreen acceptance or hardware decoding on every GPU.
