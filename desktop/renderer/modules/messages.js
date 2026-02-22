export function friendlyStepName(step) {
  const map = {
    queued: "대기 중",
    running: "실행 중",
    done: "완료",
    error: "오류",
    initializing: "준비 중",
    detecting: "악보 위치 찾는 중",
    rectifying: "화면 보정 중",
    stitching: "페이지 정리 중",
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
    .replace("ffmpeg_hwaccel=", "FFmpeg=")
    .replace("initializing pipeline", "작업을 준비하고 있어요")
    .replace("running ffmpeg extract (", "ffmpeg 프레임 추출 (")
    .replace("running ffmpeg preview extraction", "ffmpeg 미리보기 추출 시작")
    .replace("frame extraction completed", "영상 장면 추출 완료")
    .replace("capture sensitivity=low, sampling fps=0.60", "캡처 민감도: 낮음 (중복 최소화)")
    .replace("capture sensitivity=medium, sampling fps=1.00", "캡처 민감도: 보통 (추천)")
    .replace("capture sensitivity=high, sampling fps=1.80", "캡처 민감도: 높음 (세밀)")
    .replace("temporal dedupe mode: aggressive", "중복 제거 강도: 강함")
    .replace("temporal dedupe mode: normal", "중복 제거 강도: 보통")
    .replace("temporal dedupe mode: sensitive", "중복 제거 강도: 약함")
    .replace("upscale disabled, using original resolution", "업스케일 꺼짐: 원본 해상도 유지")
    .replace("upscale enabled (gpu-only)", "업스케일 켜짐: GPU 전용 처리")
    .replace("upscale factor: 2.0x", "업스케일 배율: 2x")
    .replace("upscale factor: 3.0x", "업스케일 배율: 3x")
    .replace("upscaled pages:", "업스케일 완료 페이지 수:")
    .replace("upscaling completed", "업스케일 완료")
    .replace("upscaling skipped", "업스케일 생략 (원본 해상도)")
    .replace("GPU-only upscaling requires OpenCV GPU mode (cuda/opencl).", "GPU 업스케일을 켰지만 OpenCV GPU 가속(CUDA/OpenCL)을 찾지 못했어요.")
    .replace("GPU upscaling failed while resizing output pages.", "GPU 업스케일 처리 중 오류가 발생했어요.")
    .replace("upscaling produced no output pages", "업스케일 결과 이미지를 만들지 못했어요")
    .replace("sheet detection completed", "악보 위치 찾기 완료")
    .replace("rectification completed", "화면 보정 완료")
    .replace("stitching completed", "페이지 정리 완료")
    .replace("export finished", "파일 저장 완료")
    .replace("job failed:", "작업 실패:")
    .replace("job failed", "작업 실패")
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

  const map = {
    "file_path is required when source_type is file": "로컬 파일을 먼저 선택해 주세요.",
    "file_path does not exist": "선택한 파일을 찾을 수 없어요. 경로를 다시 확인해 주세요.",
    "youtube_url is required when source_type is youtube": "유튜브 주소를 입력해 주세요.",
    "roi is required when detect mode is manual": "직접 영역 지정을 선택했다면 좌표를 입력해 주세요.",
    "preview image failed to load": "영역 지정 화면을 표시하지 못했어요. 앱을 재시작 후 다시 시도해 주세요.",
    "GPU-only upscaling requires OpenCV GPU mode (cuda/opencl).": "GPU 업스케일을 켰지만 OpenCV GPU 가속(CUDA/OpenCL)을 찾지 못했어요. 업스케일을 끄거나 GPU 환경을 확인해 주세요.",
  };

  if (typeof detail === "string" && detail.startsWith("preview frame extraction failed:")) {
    return "영역 지정 화면 생성에 실패했어요. 영상 코덱 문제일 수 있어서, 시작 시간을 1~3초로 바꿔 다시 시도해 주세요.";
  }

  return map[detail] || detail;
}
