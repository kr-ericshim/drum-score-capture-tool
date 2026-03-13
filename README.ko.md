# Drum Sheet Capture 사용 가이드

[README hub로 돌아가기](./README.md)

## 개요

Drum Sheet Capture는 영상에서 드럼 악보 영역을 지정하고, 결과를 PNG, JPG, PDF로 저장하는 로컬 데스크톱 앱입니다.

지원 배포 대상:

- Windows 설치 파일
- macOS DMG

## 설치

GitHub Releases에서 운영체제에 맞는 파일을 받습니다.

- Windows: 설치 프로그램 `.exe`
- macOS: `.dmg`

기본 릴리스는 standalone 설치본입니다.
동결된 backend runtime을 함께 포함하므로 별도 Python 설치 없이 실행하는 구성을 기준으로 배포합니다.

## 실행

1. 앱을 실행합니다.
2. 첫 화면에서 `영상 선택`을 누릅니다.
3. 로컬 파일 또는 유튜브 URL 중 하나를 선택합니다.

첫 실행 시에는 저장된 언어 설정이 있으면 그 값을 우선 사용합니다.
저장값이 없으면 시스템 언어가 `ko*`인 경우 한국어, 그 외는 영어로 시작합니다.

## 기본 사용 흐름

1. 영상 선택
2. 악보가 잘 보이는 시점의 프레임 열기
3. ROI 박스로 악보 영역 지정
4. 저장 형식 선택
5. 처리 시작
6. 결과 검토 후 내보내기

## 결과물

앱은 아래 형식으로 결과를 저장할 수 있습니다.

- PNG
- JPG
- PDF

결과 페이지는 검토 단계에서 포함/제외를 조정한 뒤 다시 내보낼 수 있습니다.

## 문제 해결

### macOS에서 Gatekeeper가 앱 실행을 막는 경우

서명되지 않은 공개 빌드에서는 macOS Gatekeeper가 앱 또는 DMG 실행을 막을 수 있습니다.

1. 먼저 DMG를 엽니다.
2. 앱을 `Applications`로 복사합니다.
3. Terminal을 열고 설치된 앱에서 격리 속성을 제거합니다.

```bash
xattr -dr com.apple.quarantine "/Applications/Drum Sheet Capture.app"
```

다운로드한 DMG 자체가 열리지 않으면 DMG 파일에 먼저 같은 명령을 적용할 수 있습니다.

```bash
xattr -dr com.apple.quarantine "/path/to/Drum.Sheet.Capture-<version>-arm64.dmg"
```

그다음 앱을 다시 실행합니다.

### 백엔드 연결 실패

- 앱을 다시 실행합니다.
- 그래도 실패하면 최신 릴리스 설치본인지 먼저 확인합니다.

### 프레임이 잘 안 잡히는 경우

- 악보가 선명하게 보이는 시점으로 이동한 뒤 프레임을 다시 불러옵니다.
- ROI를 너무 바짝 잡지 말고 상하 여백을 조금 남깁니다.

### 결과 페이지 크기나 잘림이 이상한 경우

- ROI를 다시 조정한 뒤 재실행합니다.
- 결과 검토에서 의심 페이지를 먼저 확인합니다.

## 릴리스 파일 안내

GitHub 공개 배포 기준 빌드는 `dist:release` 프로필을 사용합니다.

이 프로필은:

- standalone 설치형 유지
- frozen backend runtime 포함
- Windows/macOS 중심 배포
- 개발용 캐시, 테스트, 문서, 불필요 자산 제외

`full` 빌드는 내부 확인용 대형 패키지이고, 일반 공개 배포 기준은 아닙니다.
