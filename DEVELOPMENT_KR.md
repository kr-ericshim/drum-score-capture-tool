# Drum Score Capture Tool 개발 운영 문서

마지막 갱신: 2026-02-22  
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
  - `드럼 음원 분리` 탭: 입력 -> 분리 실행 -> 결과 파일
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
- 탭형 메뉴 추가 (`악보 캡처`, `드럼 음원 분리`)

### 3-3. 가속/성능
- FFmpeg: GPU 우선, 실패 시 CPU 폴백
- OpenCV: CUDA -> OpenCL -> CPU 순서
- 런타임 API (`GET /runtime`)로 가속 상태 노출
- 업스케일 옵션(2x/3x, GPU 전용)
- macOS `scale_vt`는 필터 존재 + 실행 self-test 통과 시에만 활성
- 유튜브 입력 소스는 preview/source 캐시를 구간선택/영역선택/본 작업에서 공통 재사용

### 3-4. 오디오 분리 (UVR Demucs 경로)
- 오디오 전용 API: `POST /audio/separate`
- 옵션:
  - 엔진: `uvr_demucs`
  - 모델: `htdemucs`, `htdemucs_ft`, `htdemucs_6s`
  - stem: `drums`
  - 형식: `wav`/`mp3`
- 분리 결과 경로/장치 정보 UI 표시
- 앱 내 내장 플레이어:
  - 바로 재생/정지
  - 재생 속도 조절
  - stem별 볼륨 믹서

### 3-5. 비트 분석 (Beat This!)
- 비트 분석 API: `POST /audio/beat-track`
- 입력:
  - 분리된 stem 경로 직접 분석(권장)
  - 또는 원본 소스(file/youtube)에서 오디오 추출 후 분석
- 출력:
  - beats/downbeats 시각(초)
  - 추정 BPM
  - `.beats` 파일 저장(옵션)
- UI:
  - `비트 분석 실행` 버튼
  - 모델 선택(`small0`, `final0`)
  - 타임라인 비트/다운비트 마커 표시

## 4. 현재 제약/주의 사항
- 오디오 분리는 `demucs`, `torch`, `torchaudio` 설치가 필요하다.
- 오디오 분리는 `torchcodec`도 필요하다.
- 비트 분석은 `beat_this`, `soxr`, `rotary-embedding-torch` 설치가 필요하다.
- `GPU 전용` 옵션 사용 시 CUDA/MPS 미감지 환경에서 작업 실패가 정상이다.
- 상단 런타임의 GPU 감지(FFmpeg/OpenCV)와 오디오 분리 GPU(torch CUDA/MPS)는 기준이 다를 수 있다.
- macOS 환경에서도 `scale_vt`가 시스템/ffmpeg 빌드 상태에 따라 비활성일 수 있다.
- Windows 환경에서는 ffmpeg/ffprobe 경로가 상대 경로로 해석되면 실행 실패할 수 있어, 절대 경로 resolver를 우선 사용한다.
- 유튜브 입력은 정책/네트워크/코덱 이슈로 실패 가능성이 있다.

## 5. 필수 설치 체크
- 기본 백엔드:
  - `pip install -r backend/requirements.txt`
- 오디오 분리 추가:
  - `pip install -r backend/requirements-uvr.txt`
  - `pip install torch torchaudio torchcodec`
- 비트 분석 추가:
  - `pip install -r backend/requirements-beat-this.txt`

## 6. 우선순위 백로그
| ID | 우선순위 | 항목 | 상태 | 담당 |
|---|---|---|---|---|
| B-001 | P0 | 오디오 분리 페이지에 실시간 진행률(큐/실행/완료) 추가 | 진행 중 | 공동 |
| B-002 | P0 | 오디오 분리 결과 미리듣기(내장 audio 플레이어) | 완료 | 공동 |
| B-003 | P1 | 드럼 분리 모델별 품질/속도 가이드 문구 추가 | 대기 | 공동 |
| B-004 | P1 | 캡처 결과 이미지 품질 튜닝 프리셋(선명/균형/원본) | 대기 | 공동 |
| B-005 | P1 | 수동 ROI 편집을 모달화(스크롤 최소화) | 대기 | 공동 |
| B-006 | P2 | 프로젝트 저장/재열기 기능 | 대기 | 공동 |
| B-007 | P0 | 비트 분석 결과를 타임라인 마커와 A-B 반복 연습으로 확장 | 진행 중 | 공동 |

## 7. 결정 사항 (Decision Log)
- D-001: 악보 캡처와 오디오 분리는 탭으로 분리해 UX 복잡도를 낮춘다.
- D-002: 업스케일은 GPU 우선 원칙을 유지하고, 실행 불가 경로는 UI에서 비활성 처리한다.
- D-003: 유튜브도 로컬과 동일하게 미니 플레이어 기반 구간 선택 흐름을 제공한다.
- D-004: 유지보수를 위해 기능 모듈 분리를 우선한다. (단일 파일 집중 금지)

## 8. 변경 이력
| 날짜 | 작성 | 변경 내용 |
|---|---|---|
| 2026-02-22 | AI | 초기 문서 생성, 현재 기능/백로그/결정 사항 반영 |
| 2026-02-22 | AI | 내장 stem 플레이어(속도/볼륨) 및 Beat This! 비트 분석 API/UI 반영 |
| 2026-02-22 | AI | null.value 방어 패치, 환경 점검 스크립트(`doctor.py`) 및 오류 대응 가이드 추가 |
| 2026-02-22 | AI | ffmpeg/ffprobe 절대 경로 resolver 추가(Windows 상대 경로 오류 대응), 오디오/추출/업스케일 호출부 공통 적용 |
| 2026-02-22 | AI | torch 런타임 진단 추가(오디오 GPU 분리 표기), CUDA 미탐지 원인 코드(`torch_gpu_reason`) 노출 |
| 2026-02-22 | AI | 유튜브 다운로드 캐시를 preview/frame·jobs·audio/beat에 공통 적용, Stepper 자동 단계 이동 제거 |
| 2026-02-22 | AI | ROI 프리뷰 요청 토큰 가드 및 소스 변경 시 ROI 초기화로 이전 영상 프레임이 섞이는 문제 완화 |

## 9. 다음 액션
- 1) 비트 마커 기반 A-B 반복 연습 기능 추가
- 2) 비트 분석 모델 선택 가이드(정확도/속도) UI 문구 추가
- 3) 오디오 분리 진행률/로그를 Job 방식으로 확장

## 10. 자주 나오는 오류와 대응
- `npm error enoent Could not read package.json`
  - 원인: `desktop` 폴더가 아닌 상위 폴더에서 실행
  - 조치: `cd score_capture_program/desktop && npm start`
- `The local processing service stopped unexpectedly`
  - 원인: 백엔드 의존성 누락/가상환경 불일치 가능성 높음
  - 조치:
    - `cd backend && source .venv/bin/activate && python scripts/doctor.py`
    - 필요시 `uvicorn app.main:app --reload`로 단독 실행 후 로그 확인
- `demucs is not installed` / `No module named demucs`
  - 조치: `pip install -r backend/requirements-uvr.txt` (반드시 `backend/.venv` 활성 상태)
- `TorchCodec is required for save_with_torchcodec`
  - 조치: `pip install torchcodec`
- `Audio/Beat GPU 전용, but CUDA/MPS is not available`
  - 조치:
    - GPU 전용 옵션 해제 후 실행
    - `python scripts/doctor.py`에서 `torch.mps.is_available` 또는 `torch.cuda.is_available` 확인
- `ffmpeg` 실행 경로 오류 (`WinError 2`, 상대 경로 실행 실패)
  - 조치:
    - 앱이 자동으로 절대 경로 탐색(`DRUMSHEET_FFMPEG_BIN` → backend 번들 경로 → PATH)하도록 반영됨
    - 수동 지정이 필요하면:
      - `DRUMSHEET_FFMPEG_BIN=<절대경로>\ffmpeg.exe`
      - `DRUMSHEET_FFPROBE_BIN=<절대경로>\ffprobe.exe`
    - `python scripts/doctor.py`에서 `ffmpeg_resolved`, `ffprobe_resolved` 값 확인

## 11. 점검 스크립트
- 경로: `backend/scripts/doctor.py`
- 목적: 명령어(ffmpeg/ffprobe/yt-dlp), 필수/옵션 모듈, torch 장치, 앱 런타임 가속 상태를 한 번에 점검
- 실행:
  - `cd backend && source .venv/bin/activate && python scripts/doctor.py`
