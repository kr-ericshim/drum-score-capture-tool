# Drum Score Capture Tool 개발 운영 문서

마지막 갱신: 2026-02-23  
문서 목적: 현재 개발 상태, 결정 사항, 개선 백로그를 한 곳에서 관리하기 위한 공용 문서

## 1. 사용 규칙
- 이 문서는 사용자와 AI가 함께 업데이트한다.
- 기능을 추가/수정하면 반드시 이 문서의 `변경 이력`과 `백로그`를 함께 갱신한다.
- 작업 시작 전 `우선순위 백로그`를 보고, 작업 종료 후 `다음 액션`을 정리한다.
- 상태 표기 기준:
  - `완료`: 현재 코드 반영 + 기본 검증 완료
  - `진행 중`: 구현 중이거나 검증 중
  - `대기`: 아직 시작 전
  - `보류`: 의도적으로 미룸

## 2. 현재 개발 상태 요약
- 상태: MVP 확장 단계
- 핵심 흐름:
  - `악보 캡처` 탭: 입력 -> 처리 -> 결과
- 데스크톱: Electron
- 로컬 백엔드: FastAPI + OpenCV + FFmpeg

## 3. 현재 구현 기능 (완료)
### 3-1. 악보 캡처 파이프라인
- 로컬 파일/유튜브 입력
- 프레임 추출 (캡처 민감도 기반 샘플링)
- 악보 영역 자동 탐지 (하단 바/스크롤/페이지 넘김 힌트 반영)
- 수동 영역 지정 (미리보기 프레임 드래그 ROI)
- 원근 보정 + 기본 화질 개선
- 중복 프레임 제거(플레이헤드 변화 억제 강화)
- PNG/JPG/PDF 내보내기

### 3-2. UI/UX 개선
- 용어 단순화 (ROI/옵션 문구 개선)
- 로컬 비디오 미니 플레이어 + 시작/끝 슬라이더
- 유튜브도 미니 플레이어 준비 가능 (`유튜브 영상 불러오기`)
- Stepper 자동 단계 이동 제거(사용자가 연 단계 유지)
- 소스 변경 시 ROI/프리뷰 자동 초기화(이전 영상 프레임 혼입 방지)
- 수동 ROI 편집 위치를 옵션 카드 근처로 이동
- 상단 가속 상태 카드 추가 (CPU/GPU/장치명/엔진 표시)
- 초보자용 원클릭 설치/실행 런처 추가 (`easy_setup_*.command/.bat`, `run_app_*.command/.bat`)
- 앱 내부 GUI에 원클릭 설치/복구 버튼 추가 (백엔드 비연결 시 복구 동선 제공)

### 3-3. 가속/성능
- FFmpeg: GPU 우선, 실패 시 CPU 폴백
- OpenCV: CUDA -> OpenCL -> CPU 순서
- 런타임 API (`GET /runtime`)로 가속 상태 노출
- 업스케일 옵션(2x/3x, GPU 전용)
- macOS `scale_vt`는 필터 존재 + 실행 self-test 통과 시에만 활성
- 유튜브 입력 소스는 preview/source 캐시를 구간선택/영역선택/본 작업에서 공통 재사용

## 4. 현재 제약/주의 사항
- `GPU 전용` 옵션 사용 시 CUDA/MPS 미감지 환경에서 작업 실패가 정상이다.
- macOS 환경에서도 `scale_vt`가 시스템/ffmpeg 빌드 상태에 따라 비활성일 수 있다.
- Windows 환경에서는 ffmpeg/ffprobe 경로가 상대 경로로 해석되면 실행 실패할 수 있어, 절대 경로 resolver를 우선 사용한다.
- 유튜브 입력은 정책/네트워크/코덱 이슈로 실패 가능성이 있다.

## 5. 필수 설치 체크
- 초보자 원클릭 설치 진입점:
  - macOS: `easy_setup_mac.command` 실행
  - Windows: `easy_setup_windows.bat` 실행
- 초보자 원클릭 실행:
  - macOS: `run_app_mac.command` 실행
- Windows: `run_app_windows.bat` 실행
- 기본 백엔드:
  - `pip install -r backend/requirements.txt`

## 6. 배포 용량 최적화
- 기본(full) 빌드:
  - `desktop/package.json`의 기본 `npm run dist`로 빌드
  - `.venv` + `third_party`를 포함해 동작성 최상
  - 대략 1GB대 크기
- 크기 최적화(full-compact) 빌드:
  - `npm run dist:compact` 또는 `npm run pack:compact`
  - `.venv`는 유지하면서 HAT 실험체크포인트/불필요 메타데이터만 제외
  - 목표: 기본 full 대비 체감 15~35% 축소
- `dist:compact`를 쓰더라도 캡처/업스케일 기본 플래그는 동일하게 동작
- 다만 HAT 기본 가중치 파일은 기본 번들에서 제외될 수 있어 최초 실행 시 별도 다운로드/세팅이 필요할 수 있음
- 경량(lean) 빌드:
  - `npm run dist:lean` 또는 `npm run pack:lean`
  - `.venv`, `third_party`, `requirements*`, `scripts`를 제외해 설치본 크기 축소
  - 동작 전제: 사용자 시스템 Python에서 필요한 패키지가 별도 설치되어 있어야 함
  - 경량 빌드에서는 `.venv` 미포함 환경이므로 사용자 시스템 Python/패키지 의존성 안내가 필요

## 8. 우선순위 백로그
| ID | 우선순위 | 항목 | 상태 | 담당 |
|---|---|---|---|---|
| B-001 | P1 | 캡처 결과 이미지 품질 튜닝 프리셋(선명/균형/원본) | 대기 | 공동 |
| B-002 | P1 | 수동 ROI 편집을 모달화(스크롤 최소화) | 대기 | 공동 |
| B-003 | P2 | 프로젝트 저장/재열기 기능 | 대기 | 공동 |

## 9. 결정 사항 (Decision Log)
- D-001: 데스크톱 UX는 악보 캡처 핵심 흐름에 집중한다.
- D-002: 업스케일은 GPU 우선 원칙을 유지하고, 실행 불가 경로는 UI에서 비활성 처리한다.
- D-003: 유튜브도 로컬과 동일하게 미니 플레이어 기반 구간 선택 흐름을 제공한다.
- D-004: 유지보수를 위해 기능 모듈 분리를 우선한다. (단일 파일 집중 금지)

## 10. 변경 이력
| 날짜 | 작성 | 변경 내용 |
|---|---|---|
| 2026-02-22 | AI | 초기 문서 생성, 현재 기능/백로그/결정 사항 반영 |
| 2026-02-22 | AI | 결과 검토 UI와 재생 보조 흐름 정리 |
| 2026-02-22 | AI | null.value 방어 패치, 환경 점검 스크립트(`doctor.py`) 및 오류 대응 가이드 추가 |
| 2026-02-22 | AI | ffmpeg/ffprobe 절대 경로 resolver 추가(Windows 상대 경로 오류 대응), 추출/업스케일 호출부 공통 적용 |
| 2026-03-09 | AI | 드럼 음원 분리 기능(UI/API/파이프라인/의존성) 제거, 배포 용량 축소 방향으로 정리 |
| 2026-02-22 | AI | ROI 프리뷰 요청 토큰 가드 및 소스 변경 시 ROI 초기화로 이전 영상 프레임이 섞이는 문제 완화 |
| 2026-02-23 | AI | 컴맹 모드 원클릭 설치/실행 스크립트 추가(macOS/Windows) + README 초간단 설치 동선 추가 |
| 2026-02-23 | AI | 앱 내부 GUI 원클릭 설치/복구 및 백엔드 재연결 버튼 추가, 로그/상태 표시 연동 |

## 11. 다음 액션
- 1) 배포용 빌드 크기 재측정 및 compact/lean 전략 재정의
- 2) DMG 산출물이 raw UDRW로 남는 원인 점검 및 압축 포맷 고정

## 12. 자주 나오는 오류와 대응
- `npm error enoent Could not read package.json`
  - 원인: `desktop` 폴더가 아닌 상위 폴더에서 실행
  - 조치: `cd score_capture_program/desktop && npm start`
- `The local processing service stopped unexpectedly`
  - 원인: 백엔드 의존성 누락/가상환경 불일치 가능성 높음
  - 조치:
    - `cd backend && source .venv/bin/activate && python scripts/doctor.py`
    - 필요시 `uvicorn app.main:app --reload`로 단독 실행 후 로그 확인
- `GPU-only upscaling requires OpenCV GPU mode (cuda/opencl).`
  - 조치:
    - GPU 전용 옵션 해제 후 실행
    - `python scripts/doctor.py`에서 OpenCV/FFmpeg 런타임 상태 확인
- `ffmpeg` 실행 경로 오류 (`WinError 2`, 상대 경로 실행 실패)
  - 조치:
    - 앱이 자동으로 절대 경로 탐색(`DRUMSHEET_FFMPEG_BIN` → backend 번들 경로 → PATH)하도록 반영됨
    - 수동 지정이 필요하면:
      - `DRUMSHEET_FFMPEG_BIN=<절대경로>\ffmpeg.exe`
      - `DRUMSHEET_FFPROBE_BIN=<절대경로>\ffprobe.exe`
    - `python scripts/doctor.py`에서 `ffmpeg_resolved`, `ffprobe_resolved` 값 확인

## 13. 점검 스크립트
- 경로: `backend/scripts/doctor.py`
- 목적: 명령어(ffmpeg/ffprobe/yt-dlp), 필수 모듈, 앱 런타임 가속 상태를 한 번에 점검
- 실행:
  - `cd backend && source .venv/bin/activate && python scripts/doctor.py`
