export function friendlyStepName(step) {
  const map = {
    queued: "대기 중",
    running: "실행 중",
    done: "완료",
    error: "오류",
    initializing: "준비 중",
    detecting: "영역 적용 중",
    rectifying: "화면 보정 중",
    stitching: "페이지 정리 중",
    separating_audio: "드럼 음원 분리 중",
    upscaling: "해상도 올리는 중",
    exporting: "파일 저장 중",
    failed: "실패",
  };
  return map[step] || step || "진행 중";
}

export function friendlyMessage(message) {
  if (!message) {
    return "";
  }

  return message
    .replace("layout mode selected: bottom_bar", "영상 형태: 하단 악보 바")
    .replace("layout mode selected: full_scroll", "영상 형태: 전체 악보 스크롤")
    .replace("layout mode selected: page_turn", "영상 형태: 페이지 넘김")
    .replace("runtime acceleration:", "가속 모드:")
    .replace("opencv=cuda", "OpenCV=CUDA")
    .replace("opencv=opencl", "OpenCV=OpenCL")
    .replace("opencv=cpu", "OpenCV=CPU")
    .replace("hat_available=True", "HAT=사용 가능")
    .replace("hat_available=False", "HAT=미사용/불가")
    .replace("hat_device=cuda", "HAT장치=CUDA")
    .replace("hat_device=mps", "HAT장치=MPS")
    .replace("hat_device=cpu", "HAT장치=CPU")
    .replace("hat_reason=ok", "HAT상태=정상")
    .replace("ffmpeg_hwaccel=", "FFmpeg=")
    .replace("initializing pipeline", "작업을 준비하고 있어요")
    .replace("running ffmpeg extract (", "ffmpeg 프레임 추출 (")
    .replace("running ffmpeg preview extraction", "ffmpeg 미리보기 추출 시작")
    .replace("frame extraction completed", "영상 장면 추출 완료")
    .replace("starting audio separation", "드럼 음원 분리 시작")
    .replace("audio separation completed", "드럼 음원 분리 완료")
    .replace("audio separation request accepted:", "오디오 분리 요청 접수:")
    .replace("audio source ready:", "오디오 입력 준비 완료:")
    .replace("audio source cache hit: youtube preview cache reused", "오디오 소스: 유튜브 캐시 재사용")
    .replace("audio source cache miss: youtube downloaded and cached", "오디오 소스: 유튜브 다운로드 후 캐시 저장")
    .replace("audio separation stage: verify dependencies", "오디오 분리 단계: 의존성 확인")
    .replace("audio separation dependencies: demucs/torch/torchcodec ready", "오디오 분리 의존성 확인 완료(demucs/torch/torchcodec)")
    .replace("audio separation workspace:", "오디오 분리 작업 폴더:")
    .replace("audio separation stage: extract audio track (ffmpeg)", "오디오 분리 단계: 오디오 추출(ffmpeg)")
    .replace("audio separation torch runtime:", "오디오 분리 torch 상태:")
    .replace("audio extraction finished:", "오디오 추출 완료:")
    .replace("audio separation input prepared", "오디오 트랙 준비 완료")
    .replace("audio separation stage: run demucs inference (this may take a while)", "오디오 분리 단계: Demucs 추론 실행(시간이 걸릴 수 있어요)")
    .replace("demucs process started:", "Demucs 프로세스 시작:")
    .replace("demucs process completed", "Demucs 프로세스 완료")
    .replace("demucs inference finished in", "Demucs 추론 완료(소요)")
    .replace("audio separation stage: collect separated stems", "오디오 분리 단계: stem 결과 수집")
    .replace("audio stems detected:", "검출된 stem:")
    .replace("audio separation stage: export stem files", "오디오 분리 단계: stem 파일 저장")
    .replace("audio stem saved:", "stem 저장:")
    .replace("audio primary stem selected:", "기본 stem 선택:")
    .replace("audio separation total elapsed:", "오디오 분리 총 소요:")
    .replace("audio stems exported:", "내보낸 stem:")
    .replace("demucs:", "Demucs:")
    .replace("audio separation engine=uvr_demucs", "오디오 분리 엔진=UVR Demucs")
    .replace("audio stem exported:", "분리 음원 저장:")
    .replace("demucs is not installed. Install optional dependency and retry.", "demucs가 설치되지 않았어요. optional dependency 설치 후 다시 시도해 주세요.")
    .replace("torch is not installed. Install torch for demucs and retry.", "torch가 설치되지 않았어요. demucs용 torch를 설치해 주세요.")
    .replace("torchcodec is not installed. Install torchcodec and retry.", "torchcodec이 설치되지 않았어요. backend 가상환경에 torchcodec 설치 후 다시 시도해 주세요.")
    .replace("beat_this is not installed. Install optional dependency and retry.", "beat_this가 설치되지 않았어요. requirements-beat-this 설치 후 다시 시도해 주세요.")
    .replace("soxr is not installed. Install soxr and retry.", "soxr가 설치되지 않았어요. soxr 설치 후 다시 시도해 주세요.")
    .replace("rotary-embedding-torch is not installed. Install it and retry.", "rotary-embedding-torch가 설치되지 않았어요. 설치 후 다시 시도해 주세요.")
    .replace("Beat tracking requires GPU, but CUDA/MPS is not available.", "GPU 전용 모드인데 비트 분석용 GPU(CUDA/MPS)를 찾지 못했어요.")
    .replace("beat tracking stage: prepare audio input", "비트 분석 단계: 오디오 입력 준비")
    .replace("beat tracking input prepared:", "비트 분석 입력 준비 완료:")
    .replace("beat tracking stage: run model inference", "비트 분석 단계: 모델 추론 실행")
    .replace("beat tracking torch runtime:", "비트 분석 torch 상태:")
    .replace("beat tracking inference completed in", "비트 분석 추론 완료(소요)")
    .replace("beat tracking tsv saved:", "비트 분석 파일 저장:")
    .replace("beat tracking input selected:", "비트 분석 입력 선택:")
    .replace("beat tracking source audio extracted:", "비트 분석용 오디오 추출 완료:")
    .replace("beat tracking source cache hit: youtube preview cache reused", "비트 분석 소스: 유튜브 캐시 재사용")
    .replace("beat tracking source cache miss: youtube downloaded and cached", "비트 분석 소스: 유튜브 다운로드 후 캐시 저장")
    .replace("beat tracking model=", "비트 분석 설정: model=")
    .replace("beat tracking result:", "비트 분석 결과:")
    .replace("beat_this import failed:", "beat_this 로드 실패:")
    .replace("Audio separation requires GPU, but CUDA/MPS is not available.", "GPU 전용 모드인데 GPU(CUDA/MPS)를 찾지 못했어요. GPU 전용을 끄고 다시 실행해 주세요.")
    .replace("gpu_reason=cuda_build_missing", "원인: CUDA 빌드가 아닌 torch 설치")
    .replace("gpu_reason=cuda_no_visible_device", "원인: CUDA 장치가 torch에 보이지 않음")
    .replace("gpu_reason=cuda_runtime_unavailable", "원인: CUDA 런타임 비활성")
    .replace("gpu_reason=mps_unavailable", "원인: MPS 비활성")
    .replace("gpu_reason=torch_missing", "원인: torch 미설치/로드 실패")
    .replace("Demucs separation failed:", "Demucs 분리 실패:")
    .replace("preview source preparation failed:", "유튜브 영상 준비 실패:")
    .replace("capture sensitivity=low, sampling fps=0.60", "캡처 민감도: 낮음 (중복 최소화)")
    .replace("capture sensitivity=medium, sampling fps=1.00", "캡처 민감도: 보통 (추천)")
    .replace("capture sensitivity=high, sampling fps=1.80", "캡처 민감도: 높음 (세밀)")
    .replace("temporal dedupe mode: aggressive", "중복 제거 강도: 강함")
    .replace("temporal dedupe mode: normal", "중복 제거 강도: 보통")
    .replace("temporal dedupe mode: sensitive", "중복 제거 강도: 약함")
    .replace("upscale disabled, using original resolution", "업스케일 꺼짐: 원본 해상도 유지")
    .replace("upscale enabled (gpu-only)", "업스케일 켜짐: GPU 전용 처리")
    .replace("upscale engine preference: auto", "업스케일 엔진 우선순위: 자동")
    .replace("upscale engine preference: hat", "업스케일 엔진 우선순위: HAT 우선")
    .replace("upscale engine preference: opencv", "업스케일 엔진 우선순위: OpenCV 우선")
    .replace("upscale engine preference: ffmpeg", "업스케일 엔진 우선순위: FFmpeg 우선")
    .replace("upscale quality profile: document_text", "업스케일 프로필: 문서/악보 선명도 우선")
    .replace("upscale post-process: unsharp enabled", "업스케일 후처리: 선명도 보정 사용")
    .replace("upscale engine: hat", "업스케일 엔진: HAT (Transformer)")
    .replace("hat runtime device: cuda", "HAT 실행 장치: CUDA")
    .replace("hat runtime device: mps", "HAT 실행 장치: MPS")
    .replace("hat runtime device: cpu", "HAT 실행 장치: CPU")
    .replace("hat cpu override enabled", "HAT CPU 강제 사용이 켜져 있습니다")
    .replace("upscale engine: ffmpeg_scale_vt", "업스케일 엔진: FFmpeg scale_vt (Metal)")
    .replace("upscale engine: opencv_cuda", "업스케일 엔진: OpenCV CUDA")
    .replace("upscale engine: opencv_opencl", "업스케일 엔진: OpenCV OpenCL")
    .replace("upscale factor: 2.0x", "업스케일 배율: 2x")
    .replace("upscale factor: 3.0x", "업스케일 배율: 3x")
    .replace("upscaled pages:", "업스케일 완료 페이지 수:")
    .replace("upscaling completed", "업스케일 완료")
    .replace("upscaling skipped", "업스케일 생략 (원본 해상도)")
    .replace("GPU-only upscaling requires OpenCV GPU mode (cuda/opencl).", "GPU 업스케일을 켰지만 OpenCV GPU 가속(CUDA/OpenCL)을 찾지 못했어요.")
    .replace("GPU upscaling failed while resizing output pages.", "GPU 업스케일 처리 중 오류가 발생했어요.")
    .replace("GPU-only upscaling failed:", "GPU 업스케일 실패:")
    .replace("GPU-only upscaling requires HAT or OpenCV GPU mode (cuda/opencl) or ffmpeg scale_vt.", "업스케일 엔진(HAT/OpenCV CUDA/OpenCL/FFmpeg scale_vt)을 찾지 못했어요.")
    .replace("scale_vt failed at frame", "scale_vt 실패 (프레임)")
    .replace("HAT inference failed:", "HAT 추론 실패:")
    .replace("HAT produced no output pages", "HAT 업스케일 결과 이미지를 만들지 못했어요")
    .replace("hat_unavailable(missing_repo)", "HAT 미사용: DRUMSHEET_HAT_REPO 미설정")
    .replace("hat_unavailable(repo_not_found)", "HAT 미사용: HAT 레포 경로를 찾지 못함")
    .replace("hat_unavailable(missing_hat_test_py)", "HAT 미사용: hat/test.py 없음")
    .replace("hat_unavailable(missing_weights)", "HAT 미사용: DRUMSHEET_HAT_WEIGHTS 미설정")
    .replace("hat_unavailable(weights_not_found)", "HAT 미사용: HAT 가중치 파일 없음")
    .replace("hat_unavailable(option_template_not_found)", "HAT 미사용: 옵션 템플릿 파일 없음")
    .replace("hat_unavailable(torch_missing)", "HAT 미사용: torch 미설치")
    .replace("hat_unavailable(cpu_only_disallowed)", "HAT 미사용: CUDA 없음 (CPU 허용 꺼짐)")
    .replace("hat_cpu_disallowed", "HAT 미사용: GPU 전용 모드에서 CPU 실행 불가")
    .replace("upscaling produced no output pages", "업스케일 결과 이미지를 만들지 못했어요")
    .replace("sheet detection completed", "영역 적용 완료")
    .replace("rectification completed", "화면 보정 완료")
    .replace("stitching completed", "페이지 정리 완료")
    .replace("export finished", "파일 저장 완료")
    .replace("job failed:", "작업 실패:")
    .replace("job failed", "작업 실패")
    .replace("job source cache hit: youtube preview cache reused", "작업 소스: 유튜브 캐시 재사용")
    .replace("job source cache miss: youtube downloaded and cached", "작업 소스: 유튜브 다운로드 후 캐시 저장")
    .replace("create job", "작업 시작")
    .replace("detected frame", "프레임 확인")
    .replace("using manual ROI for all frames", "직접 지정한 영역으로 전체 프레임 처리")
    .replace("stitch disabled, returning one page per frame", "페이지 합치기 끔: 프레임별로 저장")
    .replace("stitch disabled, returning filtered frame pages", "페이지 합치기 끔: 중복 프레임 정리 후 저장")
    .replace("overlap detected", "겹치는 부분 발견")
    .replace("youtube bottom-priority detection enabled", "유튜브 화면 특성에 맞게 하단 우선으로 찾는 중")
    .replace("no stable candidate, using bottom fallback region", "자동 인식이 불안정해 하단 기본 영역으로 보완")
    .replace("low-confidence detection, reusing previous region", "인식 신뢰도가 낮아 이전 영역을 유지")
    .replace("low-confidence detection, using youtube bottom fallback region", "인식 신뢰도가 낮아 유튜브 하단 기본 영역 사용")
    .replace("low-confidence detection, using full-page fallback region", "인식 신뢰도가 낮아 전체 악보 기본 영역 사용")
    .replace("low-confidence detection, using center fallback region", "인식 신뢰도가 낮아 화면 중앙 기본 영역 사용")
    .replace("page transition detected, resetting ROI smoothing", "페이지 전환 감지: 영역 보정 히스토리 초기화")
    .replace("page-turn mode: compressing repeated pages", "페이지 넘김 모드: 같은 페이지 중복 프레임 정리 중")
    .replace("page transition detected", "페이지 전환 감지")
    .replace("page-turn pages generated", "페이지 넘김 결과 페이지 수")
    .replace("temporal dedupe removed", "중복 프레임 자동 정리");
}

export function friendlyStatusText(step, message) {
  const stepText = friendlyStepName(step);
  const msgText = friendlyMessage(message);
  return msgText ? `${stepText}: ${msgText}` : stepText;
}

export function friendlyApiError(detail) {
  if (!detail) {
    return "요청 처리 중 오류가 발생했어요.";
  }

  if (Array.isArray(detail)) {
    const locTokens = detail
      .map((item) => {
        if (item && typeof item === "object" && Array.isArray(item.loc)) {
          return item.loc.join(".");
        }
        return "";
      })
      .join(" ");
    if (locTokens.includes("options.detect.roi")) {
      return "악보 영역 좌표가 필요합니다. 3단계에서 미리보기 화면을 불러와 드래그로 지정해 주세요.";
    }
    const joined = detail
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        if (item && typeof item === "object" && typeof item.msg === "string") {
          return item.msg;
        }
        return String(item || "");
      })
      .filter(Boolean)
      .join(" / ");
    return joined || "요청 처리 중 오류가 발생했어요.";
  }

  if (detail && typeof detail === "object") {
    if (typeof detail.detail === "string") {
      return friendlyApiError(detail.detail);
    }
    if (typeof detail.message === "string") {
      return friendlyApiError(detail.message);
    }
    return "요청 처리 중 오류가 발생했어요.";
  }

  const map = {
    "file_path is required when source_type is file": "로컬 파일을 먼저 선택해 주세요.",
    "file_path does not exist": "선택한 파일을 찾을 수 없어요. 경로를 다시 확인해 주세요.",
    "youtube_url is required when source_type is youtube": "유튜브 주소를 입력해 주세요.",
    "roi is too small. drag a larger sheet region.": "영역이 너무 작아요. 악보가 충분히 들어오도록 더 크게 드래그해 주세요.",
    "preview image failed to load": "영역 지정 화면을 표시하지 못했어요. 앱을 재시작 후 다시 시도해 주세요.",
    "preview source preparation failed": "유튜브 영상을 준비하지 못했어요. 잠시 뒤 다시 시도해 주세요.",
    "GPU-only upscaling requires OpenCV GPU mode (cuda/opencl).": "GPU 업스케일을 켰지만 OpenCV GPU 가속(CUDA/OpenCL)을 찾지 못했어요. 업스케일을 끄거나 GPU 환경을 확인해 주세요.",
    "GPU-only upscaling requires HAT or OpenCV GPU mode (cuda/opencl) or ffmpeg scale_vt.": "업스케일 엔진(HAT/OpenCV CUDA/OpenCL/FFmpeg scale_vt)을 찾지 못했어요. 설정을 확인해 주세요.",
    "Audio separation requires GPU, but CUDA/MPS is not available.": "GPU 전용 모드인데 GPU(CUDA/MPS)를 찾지 못했어요. GPU 전용을 끄고 다시 실행해 주세요.",
    "demucs is not installed. Install optional dependency and retry.": "demucs가 설치되지 않았어요. optional dependency 설치 후 다시 시도해 주세요.",
    "torch is not installed. Install torch for demucs and retry.": "torch가 설치되지 않았어요. demucs용 torch를 설치해 주세요.",
    "torchcodec is not installed. Install torchcodec and retry.": "torchcodec이 설치되지 않았어요. backend 가상환경에 torchcodec 설치 후 다시 시도해 주세요.",
    "beat_this is not installed. Install optional dependency and retry.": "beat_this가 설치되지 않았어요. requirements-beat-this 설치 후 다시 시도해 주세요.",
    "soxr is not installed. Install soxr and retry.": "soxr가 설치되지 않았어요. soxr 설치 후 다시 시도해 주세요.",
    "rotary-embedding-torch is not installed. Install it and retry.": "rotary-embedding-torch가 설치되지 않았어요. 설치 후 다시 시도해 주세요.",
    "Beat tracking requires GPU, but CUDA/MPS is not available.": "GPU 전용 모드인데 비트 분석용 GPU(CUDA/MPS)를 찾지 못했어요.",
    "audio_path does not exist": "선택된 분석 오디오 파일을 찾을 수 없어요. 음원 분리를 다시 실행해 주세요.",
    "audio separation supports only mp3, wav, mp4 for local files": "오디오 분리는 로컬 파일 기준 mp3, wav, mp4만 지원해요.",
    "soundfile is not installed. Install soundfile and retry.": "soundfile이 설치되지 않았어요. requirements-beat-this 또는 `pip install soundfile`로 설치 후 다시 시도해 주세요.",
  };

  if (typeof detail === "string" && detail.startsWith("preview frame extraction failed:")) {
    return "영역 지정 화면 생성에 실패했어요. 영상 코덱 문제일 수 있어서, 시작 시간을 1~3초로 바꿔 다시 시도해 주세요.";
  }
  if (typeof detail === "string" && detail.startsWith("preview source preparation failed:")) {
    return "유튜브 영상을 불러오지 못했어요. URL을 확인하고 다시 시도해 주세요.";
  }
  if (typeof detail === "string" && detail.startsWith("audio separation failed:")) {
    const reason = detail.replace("audio separation failed:", "").trim();
    return reason ? `오디오 분리 실패: ${reason}` : "오디오 분리에 실패했어요.";
  }
  if (typeof detail === "string" && detail.startsWith("beat tracking failed:")) {
    const reason = detail.replace("beat tracking failed:", "").trim();
    return reason ? `비트 분석 실패: ${reason}` : "비트 분석에 실패했어요.";
  }

  return map[detail] || detail;
}
