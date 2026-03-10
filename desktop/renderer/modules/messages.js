import { getLocale } from "./i18n.js";

export function friendlyStepName(step) {
  const map = getLocale() === "ko"
    ? {
        queued: "대기",
        running: "실행 중",
        done: "완료",
        error: "오류",
        initializing: "준비 중",
        detecting: "영역 적용 중",
        rectifying: "화면 보정 중",
        stitching: "페이지 정리 중",
        upscaling: "선명도 보정 중",
        exporting: "저장 중",
        failed: "실패",
      }
    : {
        queued: "Queued",
        running: "Running",
        done: "Done",
        error: "Error",
        initializing: "Initializing",
        detecting: "Applying regions",
        rectifying: "Rectifying",
        stitching: "Organizing pages",
        upscaling: "Enhancing clarity",
        exporting: "Saving",
        failed: "Failed",
      };
  return map[step] || step || (getLocale() === "ko" ? "진행 중" : "In progress");
}

export function friendlyMessage(message) {
  if (!message) {
    return "";
  }

  const locale = getLocale();
  const replacements = locale === "ko"
    ? [
        ["layout mode selected: bottom_bar", "레이아웃: 하단 바"],
        ["layout mode selected: full_scroll", "레이아웃: 전체 스크롤"],
        ["layout mode selected: page_turn", "레이아웃: 페이지 넘김"],
        ["runtime acceleration:", "가속 모드:"],
        ["opencv=cuda", "OpenCV=CUDA"],
        ["opencv=opencl", "OpenCV=OpenCL"],
        ["opencv=cpu", "OpenCV=CPU"],
        ["hat_available=True", "HAT=사용 가능"],
        ["hat_available=False", "HAT=사용 불가"],
        ["hat_device=cuda", "HAT 장치=CUDA"],
        ["hat_device=mps", "HAT 장치=MPS"],
        ["hat_device=cpu", "HAT 장치=CPU"],
        ["hat_reason=ok", "HAT 상태=정상"],
        ["ffmpeg_hwaccel=", "FFmpeg="],
        ["initializing pipeline", "작업 준비"],
        ["running ffmpeg extract (", "FFmpeg 프레임 추출 ("],
        ["running ffmpeg preview extraction", "FFmpeg 미리보기 추출 시작"],
        ["frame extraction completed", "프레임 추출 완료"],
        ["preview source preparation failed:", "영상 준비 실패:"],
        ["capture sensitivity=low, sampling fps=0.60", "캡처 민감도: 낮음"],
        ["capture sensitivity=medium, sampling fps=1.00", "캡처 민감도: 보통"],
        ["capture sensitivity=high, sampling fps=1.80", "캡처 민감도: 높음"],
        ["temporal dedupe mode: aggressive", "중복 제거: 강함"],
        ["temporal dedupe mode: normal", "중복 제거: 보통"],
        ["temporal dedupe mode: sensitive", "중복 제거: 약함"],
        ["upscale disabled, using original resolution", "업스케일: 사용 안 함"],
        ["upscale enabled (gpu-only)", "업스케일: GPU 전용"],
        ["upscale engine preference: auto", "업스케일 엔진 우선순위: 자동"],
        ["upscale engine preference: hat", "업스케일 엔진 우선순위: HAT"],
        ["upscale engine preference: opencv", "업스케일 엔진 우선순위: OpenCV"],
        ["upscale engine preference: ffmpeg", "업스케일 엔진 우선순위: FFmpeg"],
        ["upscale quality profile: document_text", "업스케일 프로필: 문서/악보"],
        ["upscale post-process: unsharp enabled", "업스케일 후처리: 선명도 보정 사용"],
        ["upscale engine: hat", "업스케일 엔진: HAT"],
        ["hat runtime device: cuda", "HAT 실행 장치: CUDA"],
        ["hat runtime device: mps", "HAT 실행 장치: MPS"],
        ["hat runtime device: cpu", "HAT 실행 장치: CPU"],
        ["hat cpu override enabled", "HAT CPU 강제 사용"],
        ["upscale engine: ffmpeg_scale_vt", "업스케일 엔진: FFmpeg scale_vt"],
        ["upscale engine: opencv_cuda", "업스케일 엔진: OpenCV CUDA"],
        ["upscale engine: opencv_opencl", "업스케일 엔진: OpenCV OpenCL"],
        ["upscale factor: 2.0x", "업스케일 배율: 2x"],
        ["upscale factor: 3.0x", "업스케일 배율: 3x"],
        ["upscaled pages:", "업스케일 페이지 수:"],
        ["upscaling completed", "업스케일 완료"],
        ["upscaling skipped", "업스케일 생략"],
        ["GPU-only upscaling requires OpenCV GPU mode (cuda/opencl).", "OpenCV GPU 가속(CUDA/OpenCL)을 사용할 수 없습니다."],
        ["GPU upscaling failed while resizing output pages.", "GPU 업스케일 처리 중 오류가 발생했습니다."],
        ["GPU-only upscaling failed:", "GPU 업스케일 실패:"],
        ["GPU-only upscaling requires HAT or OpenCV GPU mode (cuda/opencl) or ffmpeg scale_vt.", "사용 가능한 업스케일 엔진을 찾을 수 없습니다."],
        ["scale_vt failed at frame", "scale_vt 실패 (프레임)"],
        ["HAT inference failed:", "HAT 추론 실패:"],
        ["HAT produced no output pages", "HAT 업스케일 결과를 생성하지 못했습니다."],
        ["hat_unavailable(missing_repo)", "HAT 사용 불가: 저장소 미설정"],
        ["hat_unavailable(repo_not_found)", "HAT 사용 불가: 저장소 경로 없음"],
        ["hat_unavailable(missing_hat_test_py)", "HAT 사용 불가: hat/test.py 없음"],
        ["hat_unavailable(missing_weights)", "HAT 사용 불가: 가중치 미설정"],
        ["hat_unavailable(weights_not_found)", "HAT 사용 불가: 가중치 파일 없음"],
        ["hat_unavailable(option_template_not_found)", "HAT 사용 불가: 옵션 템플릿 없음"],
        ["hat_unavailable(torch_missing)", "HAT 사용 불가: torch 미설치"],
        ["hat_unavailable(cpu_only_disallowed)", "HAT 사용 불가: CUDA 없음"],
        ["hat_cpu_disallowed", "HAT 사용 불가: GPU 전용 모드"],
        ["upscaling produced no output pages", "업스케일 결과를 생성하지 못했습니다."],
        ["sheet detection completed", "영역 적용 완료"],
        ["rectification completed", "화면 보정 완료"],
        ["stitching completed", "페이지 정리 완료"],
        ["export finished", "파일 저장 완료"],
        ["review export finished", "검토 반영 저장 완료"],
        ["review export saved:", "검토 반영 저장:"],
        ["capture crop saved", "캡처 자르기 저장 완료"],
        ["job failed:", "작업 실패:"],
        ["job failed", "작업 실패"],
        ["job source cache hit: youtube preview cache reused", "작업 소스: 유튜브 캐시 재사용"],
        ["job source cache miss: youtube downloaded and cached", "작업 소스: 유튜브 다운로드 후 캐시 저장"],
        ["create job", "작업 시작"],
        ["detected frame", "프레임 확인"],
        ["using manual ROI for all frames", "직접 지정한 영역으로 전체 프레임 처리"],
        ["stitch disabled, returning one page per frame", "페이지 합치기 사용 안 함: 프레임별 저장"],
        ["stitch disabled, returning filtered frame pages", "페이지 합치기 사용 안 함: 중복 프레임 정리 후 저장"],
        ["overlap detected", "겹침 구간 감지"],
        ["youtube bottom-priority detection enabled", "유튜브 하단 우선 탐지 사용"],
        ["no stable candidate, using bottom fallback region", "탐지 불안정: 하단 기본 영역 사용"],
        ["low-confidence detection, reusing previous region", "탐지 신뢰도 낮음: 이전 영역 유지"],
        ["low-confidence detection, using youtube bottom fallback region", "탐지 신뢰도 낮음: 유튜브 하단 기본 영역 사용"],
        ["low-confidence detection, using full-page fallback region", "탐지 신뢰도 낮음: 전체 영역 사용"],
        ["low-confidence detection, using center fallback region", "탐지 신뢰도 낮음: 중앙 영역 사용"],
        ["page transition detected, resetting ROI smoothing", "페이지 전환 감지: 영역 보정 기록 초기화"],
        ["page-turn mode: compressing repeated pages", "페이지 넘김 모드: 중복 페이지 정리"],
        ["page transition detected", "페이지 전환 감지"],
        ["page-turn pages generated", "페이지 넘김 결과 페이지 수"],
        ["temporal dedupe removed", "중복 프레임 정리"],
      ]
    : [
        ["layout mode selected: bottom_bar", "Layout: bottom bar"],
        ["layout mode selected: full_scroll", "Layout: full scroll"],
        ["layout mode selected: page_turn", "Layout: page turn"],
        ["runtime acceleration:", "Acceleration:"],
        ["preview source preparation failed:", "Source preparation failed:"],
        ["review export saved:", "Review export saved:"],
      ];

  return message
    .split("\n")
    .map((line) => replacements.reduce((value, [from, to]) => value.replace(from, to), line))
    .join("\n");
}

export function friendlyStatusText(step, message) {
  const stepText = friendlyStepName(step);
  const msgText = friendlyMessage(message);
  const guideMap = getLocale() === "ko"
    ? {
        queued: "작업 대기열에 등록되었습니다.",
        initializing: "영상 정보를 읽는 중입니다.",
        detecting: "필요한 장면을 선택하는 중입니다.",
        rectifying: "악보 화면을 보정하는 중입니다.",
        stitching: "페이지를 정리하는 중입니다.",
        upscaling: "선명도 보정을 적용하는 중입니다.",
        exporting: "파일을 저장하는 중입니다.",
        done: "작업이 완료되었습니다.",
        failed: "작업 중 오류가 발생했습니다.",
      }
    : {
        queued: "The job has been queued.",
        initializing: "Reading video information.",
        detecting: "Selecting useful scenes.",
        rectifying: "Adjusting the score view.",
        stitching: "Organizing pages.",
        upscaling: "Applying clarity enhancement.",
        exporting: "Saving files.",
        done: "The job is complete.",
        failed: "An error occurred during processing.",
      };
  const technicalPattern = /(ffmpeg|opencv|torch|cuda|mps|layout|hat_|scale_vt|gpu|cpu|runtime|engine|profile|dedupe|threshold|roi|fps|cache)/i;
  const detail = msgText && !technicalPattern.test(msgText) ? msgText : guideMap[String(step || "").toLowerCase()] || "";
  return detail ? `${stepText}: ${detail}` : stepText;
}

export function friendlyApiError(detail) {
  if (!detail) {
    return getLocale() === "ko" ? "요청 처리 중 오류가 발생했습니다." : "An error occurred while handling the request.";
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
      return getLocale() === "ko" ? "악보 영역 좌표가 필요합니다. 3단계에서 미리보기 화면을 불러온 뒤 드래그로 지정합니다." : "ROI coordinates are required. Open a preview in step 3 and drag the score area.";
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
    return joined || (getLocale() === "ko" ? "요청 처리 중 오류가 발생했습니다." : "An error occurred while handling the request.");
  }

  if (detail && typeof detail === "object") {
    if (typeof detail.detail === "string") {
      return friendlyApiError(detail.detail);
    }
    if (typeof detail.message === "string") {
      return friendlyApiError(detail.message);
    }
    return getLocale() === "ko" ? "요청 처리 중 오류가 발생했습니다." : "An error occurred while handling the request.";
  }

  const map = getLocale() === "ko" ? {
    "file_path is required when source_type is file": "로컬 파일을 먼저 선택합니다.",
    "file_path does not exist": "선택한 파일을 찾을 수 없습니다. 경로를 확인합니다.",
    "youtube_url is required when source_type is youtube": "유튜브 주소를 입력합니다.",
    "roi is too small. drag a larger sheet region.": "영역이 너무 작습니다. 악보가 충분히 포함되도록 더 크게 지정합니다.",
    "preview image failed to load": "영역 지정 화면을 표시할 수 없습니다. 앱을 다시 시작한 뒤 재시도합니다.",
    "preview source preparation failed": "유튜브 영상을 준비할 수 없습니다. 잠시 후 다시 시도합니다.",
    "GPU-only upscaling requires OpenCV GPU mode (cuda/opencl).": "GPU 업스케일에 필요한 OpenCV GPU 가속(CUDA/OpenCL)을 사용할 수 없습니다.",
    "GPU-only upscaling requires HAT or OpenCV GPU mode (cuda/opencl) or ffmpeg scale_vt.": "사용 가능한 업스케일 엔진을 찾을 수 없습니다.",
    "keep_captures must include at least one capture": "검토 반영 시 최소 1개의 캡처를 포함해야 합니다.",
    "no valid captures selected": "선택한 캡처를 찾을 수 없습니다. 다시 선택합니다.",
    "roi is too small for capture crop": "영역이 너무 작습니다. 더 크게 지정합니다.",
    "capture crop produced empty image": "선택한 영역에서 이미지를 생성할 수 없습니다. 영역을 다시 지정합니다.",
    "failed to save cropped capture": "자른 캡처를 저장할 수 없습니다. 다시 시도합니다.",
    "job is still running": "작업 실행 중에는 검토 반영을 사용할 수 없습니다. 완료 후 다시 시도합니다.",
    "cache clear is blocked while jobs are running": "작업 실행 중에는 캐시를 정리할 수 없습니다. 완료 후 다시 시도합니다.",
  } : {
    "file_path is required when source_type is file": "Select a local file first.",
    "file_path does not exist": "The selected file could not be found. Check the path.",
    "youtube_url is required when source_type is youtube": "Enter a YouTube URL.",
    "roi is too small. drag a larger sheet region.": "The ROI is too small. Drag a larger score area.",
    "preview image failed to load": "Could not open the preview image. Restart the app and try again.",
    "preview source preparation failed": "Could not prepare the YouTube video. Try again shortly.",
    "GPU-only upscaling requires OpenCV GPU mode (cuda/opencl).": "OpenCV GPU acceleration (CUDA/OpenCL) is not available for GPU-only upscaling.",
    "GPU-only upscaling requires HAT or OpenCV GPU mode (cuda/opencl) or ffmpeg scale_vt.": "No supported upscaling engine is available.",
    "keep_captures must include at least one capture": "Keep at least one capture when applying review selection.",
    "no valid captures selected": "The selected captures could not be found. Select them again.",
    "roi is too small for capture crop": "The crop area is too small. Make it larger.",
    "capture crop produced empty image": "The selected area produced an empty image. Choose a different area.",
    "failed to save cropped capture": "Failed to save the cropped capture. Try again.",
    "job is still running": "Review export is not available while the job is still running.",
    "cache clear is blocked while jobs are running": "Cache cannot be cleared while jobs are running.",
  };

  if (typeof detail === "string" && detail.startsWith("preview frame extraction failed:")) {
    return getLocale() === "ko"
      ? "영역 지정 화면을 생성할 수 없습니다. 시작 시간을 5~10초 정도로 옮겨 다시 시도합니다."
      : "Could not generate the preview frame. Move the start time to around 5-10 seconds and try again.";
  }
  if (typeof detail === "string" && detail.startsWith("preview source preparation failed:")) {
    const reason = detail.replace("preview source preparation failed:", "").trim();
    const normalizedReason = reason.toLowerCase();
    if (normalizedReason.includes("timed out") || normalizedReason.includes("timeout")) {
      return getLocale() === "ko"
        ? "유튜브 영상 준비 시간이 초과되었습니다. 잠시 후 다시 시도하거나 다른 링크로 확인합니다."
        : "Preparing the YouTube video timed out. Try again shortly or test another link.";
    }
    if (normalizedReason.includes("sign in to confirm you're not a bot")) {
      return getLocale() === "ko"
        ? "유튜브가 봇 확인을 요구하고 있습니다. 잠시 후 다시 시도하거나 다른 링크로 확인합니다."
        : "YouTube requested a bot check. Try again later or test another link.";
    }
    if (normalizedReason.includes("video unavailable")) {
      return getLocale() === "ko"
        ? "이 유튜브 영상은 현재 내려받을 수 없습니다. 공개 상태와 지역 제한을 확인합니다."
        : "This YouTube video is not available for download. Check its visibility and region restrictions.";
    }
    return reason
      ? (getLocale() === "ko" ? `유튜브 영상 준비 실패: ${reason}` : `YouTube preparation failed: ${reason}`)
      : (getLocale() === "ko" ? "유튜브 영상을 불러올 수 없습니다. 주소를 확인한 뒤 다시 시도합니다." : "Could not load the YouTube video. Check the URL and try again.");
  }
  if (typeof detail === "string" && detail.startsWith("review export failed:")) {
    const reason = detail.replace("review export failed:", "").trim();
    return reason ? (getLocale() === "ko" ? `검토 반영 저장 실패: ${reason}` : `Review export failed: ${reason}`) : (getLocale() === "ko" ? "검토 반영 저장에 실패했습니다." : "Failed to save the reviewed export.");
  }
  if (typeof detail === "string" && detail.startsWith("capture path must be inside this job directory:")) {
    return getLocale() === "ko" ? "현재 작업에서 생성된 캡처만 다시 자를 수 있습니다. 결과를 새로 고친 뒤 다시 시도합니다." : "Only captures created by the current job can be recropped. Refresh the results and try again.";
  }
  if (typeof detail === "string" && detail.startsWith("capture file not found:")) {
    return getLocale() === "ko" ? "선택한 캡처 파일을 찾을 수 없습니다. 결과를 다시 생성한 뒤 시도합니다." : "The selected capture file could not be found. Regenerate the results and try again.";
  }
  if (typeof detail === "string" && detail.startsWith("unsupported capture format:")) {
    return getLocale() === "ko" ? "현재 캡처 형식은 다시 자르기를 지원하지 않습니다. PNG 또는 JPG 결과에서 시도합니다." : "This capture format does not support recropping. Try a PNG or JPG result.";
  }
  return map[detail] || detail;
}
