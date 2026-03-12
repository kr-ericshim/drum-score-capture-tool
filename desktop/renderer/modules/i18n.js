const LOCALE_STORAGE_KEY = "drum-sheet-language";
const SUPPORTED_LOCALES = ["ko", "en"];

const translations = {
  ko: {
    "document.title": "Drum Sheet Capture Tool",
    "header.kicker": "Drum Sheet Capture",
    "header.title": "드럼 악보 캡처",
    "header.subtitle": "영상에서 악보 영역을 지정해 PNG, JPG, PDF로 저장합니다.",
    "header.start": "영상 선택",
    "header.themeToggle": "테마 전환",
    "header.languageToggle": "언어 전환",
    "header.workflowAria": "캡처 작업 흐름",
    "header.pipelineAria": "처리 파이프라인",
    "step.source": "영상 선택",
    "step.source.pending": "입력 대기",
    "step.source.required": "선택 필요",
    "step.roi": "영역 지정",
    "step.roi.pending": "미설정",
    "step.roi.required": "영역 지정 필요",
    "step.export": "저장",
    "step.export.pending": "형식 확인",
    "step.export.defaultSummary": "PNG/PDF · 추천",
    "runtime.checking": "확인 중",
    "runtime.deviceLabel": "장치",
    "runtime.engineLabel": "엔진",
    "runtime.waiting": "연결 대기",
    "source.helper": "로컬 파일 또는 유튜브 주소 중 하나를 입력합니다.",
    "source.file": "로컬 파일",
    "source.youtube": "유튜브 URL",
    "source.filePlaceholder": "영상 파일을 선택합니다",
    "source.browse": "파일 선택",
    "source.copyPath": "경로 복사",
    "source.youtubePlaceholder": "유튜브 주소를 입력합니다 (https://www.youtube.com/...)",
    "source.prepareYoutube": "유튜브 영상 준비",
    "source.prepareHint": "준비가 끝나면 아래에서 대표 프레임과 처리 구간을 확인할 수 있습니다.",
    "source.prepareLog": "유튜브 준비 로그",
    "source.downloadHint": "유튜브 다운로드 가능 여부는 영상 정책과 실행 환경에 따라 달라질 수 있습니다.",
    "roi.eyebrow": "중요 단계",
    "roi.title": "악보 영역을 지정합니다",
    "roi.helper": "프레임을 불러온 뒤 악보 전체가 들어오도록 범위를 지정합니다.",
    "roi.chip.drag": "모서리 드래그",
    "roi.chip.nudge": "방향키 미세 이동",
    "roi.chip.framebar": "프레임 바 선택",
    "range.title": "악보가 선명하게 보이는 시점을 먼저 선택합니다",
    "range.play": "재생",
    "range.back5": "5초 이전",
    "range.forward5": "5초 이후",
    "range.hint": "여기서는 대표 프레임만 선택합니다. 처리 구간을 줄여야 하는 경우에만 아래 상세 설정을 사용합니다.",
    "range.advanced": "상세 설정: 처리 구간 제한",
    "range.startSec": "시작 시간 (초)",
    "range.endSec": "끝 시간 (초)",
    "range.startSlider": "시작 슬라이더",
    "range.endSlider": "끝 슬라이더",
    "range.setStart": "현재 시점으로 시작 지정",
    "range.setEnd": "현재 시점으로 종료 지정",
    "range.clear": "시작/끝 초기화",
    "roi.openFrame": "악보 화면 열기",
    "roi.reloadFrame": "현재 시점 다시 불러오기",
    "roi.toolsHint": "열린 프레임에서 범위를 드래그합니다. 방향키는 1px, Shift+방향키는 10px 단위로 이동합니다.",
    "roi.frame": "프레임",
    "roi.adjustBounds": "경계 조정",
    "roi.frameMetaIdle": "프레임 준비 전",
    "roi.stageHelp": "악보 전체가 들어오도록 범위를 지정합니다. 상단과 하단에 여백을 조금 남기는 편이 안전합니다.",
    "roi.assistHint": "미리보기를 불러오면 오른쪽 패널에서 경계 위험과 확대 보조 화면을 확인할 수 있습니다.",
    "roi.apply": "영역 적용",
    "roi.cropKicker": "선택 영역",
    "roi.cropTitle": "선택 영역 확인",
    "roi.cropSummary": "프레임을 불러온 뒤 ROI를 지정하면 선택 영역만 확대해 표시합니다.",
    "roi.cropCanvasAria": "ROI 선택 영역 미리보기",
    "roi.metric.widthEmpty": "폭 -",
    "roi.metric.heightEmpty": "높이 -",
    "roi.metric.topMarginEmpty": "상단 여백 -",
    "roi.metric.bottomMarginEmpty": "하단 여백 -",
    "roi.zoomKicker": "확대 보기",
    "roi.zoomTitle": "경계 여유 확인",
    "roi.zoomSummary": "선택 영역 주변까지 함께 표시해 경계 여유를 확인합니다.",
    "roi.zoomCanvasAria": "ROI 확대 보조 미리보기",
    "roi.healthKicker": "실행 전 진단",
    "roi.healthTitle": "진행 전 확인",
    "roi.healthIdle": "대기 중",
    "roi.healthSummary": "ROI를 지정하면 진단 결과를 표시합니다.",
    "roi.healthListDefault": "악보 화면을 열고 ROI를 지정하면 경계 위험을 먼저 표시합니다.",
    "roi.healthBackendHint": "현재는 화면 기준 즉시 진단을 제공합니다.",
    "roi.advanced": "고급 설정: 좌표 직접 입력",
    "roi.coordinates": "좌표 직접 입력",
    "roi.copyCoords": "좌표 복사",
    "export.settingsTitle": "처리 설정",
    "export.settingsHelper": "ROI 확인이 끝나면 바로 실행할 수 있도록 이 영역에서 저장 옵션을 정리합니다.",
    "export.preset.basic": "기본",
    "export.preset.scroll": "스크롤 맞춤",
    "export.preset.quality": "선명도 우선",
    "export.preset.hint": "기본은 페이지 넘김을 줄이는 연주 모드입니다. 필요할 때만 다른 모드를 선택하세요.",
    "export.advanced": "상세 설정",
    "export.stitch": "스크롤 악보를 한 장으로 합치기",
    "export.overlap": "겹침 판단 민감도",
    "export.upscale": "출력 선명도 향상",
    "export.upscaleFactor": "업스케일 배율",
    "export.upscale2x": "2x (권장)",
    "export.upscaleHint": "사용 시 업스케일은 GPU 전용으로 처리합니다. GPU를 사용할 수 없으면 시작 전에 안내합니다.",
    "cta.initialHint": "1단계에서 영상을 선택합니다.",
    "cta.runRequired": "영상 선택 필요",
    "cta.cancel": "조회 중단",
    "cta.outputFolder": "결과 폴더",
    "progress.title": "진행 현황",
    "progress.helper": "처리 시작 후 진행 상태를 표시합니다.",
    "progress.current": "현재 상태",
    "status.idle": "대기 중",
    "pipe.download": "영상 준비",
    "pipe.extract": "장면 모으기",
    "pipe.detect": "악보 자르기",
    "pipe.rectify": "페이지 정리",
    "pipe.upscale": "선명도 보정",
    "pipe.export": "저장하기",
    "logs.detail": "상세 로그",
    "result.title": "결과",
    "result.helper": "검토가 필요한 페이지를 먼저 올려 표시합니다.",
    "result.openFolder": "결과 폴더 열기",
    "result.openPdf": "PDF 열기",
    "result.copyPath": "경로 복사",
    "result.pinWindow": "창 고정: 끔",
    "result.pinHint": "창 고정 사용 시 앱 창이 다른 창 위에 유지됩니다.",
    "result.reviewSummary": "캡처 결과를 검토하고 제외할 항목을 선택합니다.",
    "result.selectionTitle": "캡처 선택",
    "result.selectionHint": "포함할 이미지를 고른 뒤 바로 반영합니다.",
    "result.previewTitle": "큰 미리보기",
    "result.previewHint": "썸네일을 누르면 여기에서 바로 확인합니다.",
    "result.keepAll": "전체 포함",
    "result.applyReview": "선택 반영 후 페이지 재생성",
    "result.pathChipEmpty": "출력 경로: -",
    "source.qualityGateTitle": "고화질 영상을 확보하지 못했습니다",
    "source.qualityGateBody": "현재 환경에서는 악보 판독에 충분한 해상도로 이 영상을 가져오지 못했습니다. 가능하면 다른 플랫폼 또는 직접 확보한 원본 영상 파일을 사용하세요.",
    "source.qualityGateBodyWithResolution": "현재 협상된 영상 해상도는 {resolution}입니다. 이 해상도로는 악보 판독 정확도가 크게 떨어질 수 있으니, 다른 플랫폼 또는 직접 확보한 원본 영상 파일을 사용하는 편이 안전합니다.",
    "source.qualityGateOpenFile": "로컬 파일 열기",
    "source.qualityGateShowLog": "로그 보기",
    "support.title": "문제 해결",
    "support.helper": "실행 오류가 있거나 고급 설정이 필요할 때만 확인합니다.",
    "support.setup": "자동 설치 및 복구",
    "support.setup.checking": "엔진 확인 중",
    "support.setup.desc": "로컬 엔진 연결 상태를 확인하는 중입니다.",
    "support.setup.run": "자동 설치/복구",
    "support.setup.restart": "엔진 다시 연결",
    "support.setup.clearCache": "캐시 정리",
    "support.setup.clearLog": "로그 지우기",
    "support.setup.cacheHint": "캐시 정리 시 이전 결과 파일과 임시 파일을 삭제합니다.",
    "support.setup.defaultLog": "[안내] 문제가 발생하면 아래 로그에서 원인을 확인할 수 있습니다.",
    "support.runtime": "실행 정보",
    "support.runtime.title": "런타임 정보 확인 중",
    "support.runtime.desc": "정보를 불러오는 중입니다.",
    "support.runtime.desktopVersion": "앱 버전",
    "support.runtime.backendVersion": "백엔드 버전",
    "support.runtime.cacheNamespace": "미리보기 캐시 네임스페이스",
    "support.runtime.ffmpeg": "영상 추출 (FFmpeg)",
    "support.runtime.opencv": "이미지 처리 (OpenCV)",
    "support.runtime.upscale": "선명도 엔진",
    "support.runtime.gpu": "GPU 이름",
    "support.runtime.cpu": "CPU 이름",
    "support.runtime.order": "FFmpeg 우선순위",
    "crop.title": "캡처 다시 자르기",
    "crop.close": "닫기",
    "crop.helper": "필요한 부분만 남기도록 영역을 드래그합니다. 적용 시 해당 캡처만 교체합니다.",
    "crop.reset": "영역 초기화",
    "crop.apply": "현재 캡처에 반영",
    "language.ko": "KO",
    "language.en": "EN",
  },
  en: {
    "document.title": "Drum Sheet Capture Tool",
    "header.kicker": "Drum Sheet Capture",
    "header.title": "Drum Sheet Capture",
    "header.subtitle": "Select the score area from a video and save it as PNG, JPG, or PDF.",
    "header.start": "Select Video",
    "header.themeToggle": "Toggle theme",
    "header.languageToggle": "Switch language",
    "header.workflowAria": "Capture workflow",
    "header.pipelineAria": "Processing pipeline",
    "step.source": "Source",
    "step.source.pending": "Waiting",
    "step.source.required": "Required",
    "step.roi": "ROI",
    "step.roi.pending": "Not set",
    "step.roi.required": "ROI needed",
    "step.export": "Export",
    "step.export.pending": "Choose format",
    "step.export.defaultSummary": "PNG/PDF · Recommended",
    "runtime.checking": "Checking",
    "runtime.deviceLabel": "Device",
    "runtime.engineLabel": "Engine",
    "runtime.waiting": "Waiting",
    "source.helper": "Provide either a local file or a YouTube URL.",
    "source.file": "Local File",
    "source.youtube": "YouTube URL",
    "source.filePlaceholder": "Select a video file",
    "source.browse": "Browse",
    "source.copyPath": "Copy Path",
    "source.youtubePlaceholder": "Enter a YouTube URL (https://www.youtube.com/...)",
    "source.prepareYoutube": "Prepare Video",
    "source.prepareHint": "After preparation, you can review a sample frame and processing range below.",
    "source.prepareLog": "YouTube preparation log",
    "source.downloadHint": "YouTube download availability may vary by video policy and local environment.",
    "roi.eyebrow": "Key Step",
    "roi.title": "Set the score area",
    "roi.helper": "Load a frame, then include the full visible score in the selection.",
    "roi.chip.drag": "Drag corners",
    "roi.chip.nudge": "Arrow-key nudge",
    "roi.chip.framebar": "Pick frame",
    "range.title": "Choose a moment where the score is easy to read",
    "range.play": "Play",
    "range.back5": "Back 5s",
    "range.forward5": "Forward 5s",
    "range.hint": "Use this to choose a representative frame. Limit the processing range only when needed.",
    "range.advanced": "Advanced: limit processing range",
    "range.startSec": "Start time (sec)",
    "range.endSec": "End time (sec)",
    "range.startSlider": "Start slider",
    "range.endSlider": "End slider",
    "range.setStart": "Use current time as start",
    "range.setEnd": "Use current time as end",
    "range.clear": "Clear range",
    "roi.openFrame": "Open Score Frame",
    "roi.reloadFrame": "Reload Current Frame",
    "roi.toolsHint": "Drag on the frame to mark the area. Arrow keys move by 1px and Shift+Arrow moves by 10px.",
    "roi.frame": "Frame",
    "roi.adjustBounds": "Adjust bounds",
    "roi.frameMetaIdle": "Frame not ready",
    "roi.stageHelp": "Keep the full score inside the selection. Leaving a small top and bottom margin is safer.",
    "roi.assistHint": "After loading a frame, use the right panel to review edge risk and zoomed assistance.",
    "roi.apply": "Apply ROI",
    "roi.cropKicker": "Selection",
    "roi.cropTitle": "Selection Preview",
    "roi.cropSummary": "Once ROI is set, this view zooms into the selected score area.",
    "roi.cropCanvasAria": "ROI selection preview",
    "roi.metric.widthEmpty": "Width -",
    "roi.metric.heightEmpty": "Height -",
    "roi.metric.topMarginEmpty": "Top margin -",
    "roi.metric.bottomMarginEmpty": "Bottom margin -",
    "roi.zoomKicker": "Zoom View",
    "roi.zoomTitle": "Edge Margin Check",
    "roi.zoomSummary": "Shows the area around the ROI so you can check boundary spacing.",
    "roi.zoomCanvasAria": "ROI zoom helper preview",
    "roi.healthKicker": "Pre-run Check",
    "roi.healthTitle": "Review Before Run",
    "roi.healthIdle": "Idle",
    "roi.healthSummary": "Diagnostics will appear after you set the ROI.",
    "roi.healthListDefault": "Open a score frame and set the ROI to see clipping warnings first.",
    "roi.healthBackendHint": "For now, immediate on-screen diagnostics are shown.",
    "roi.advanced": "Advanced: enter coordinates directly",
    "roi.coordinates": "Manual coordinates",
    "roi.copyCoords": "Copy Coordinates",
    "export.settingsTitle": "Processing Settings",
    "export.settingsHelper": "Once ROI looks right, finalize save options here and run immediately.",
    "export.preset.basic": "Basic",
    "export.preset.scroll": "Scroll",
    "export.preset.quality": "Quality",
    "export.preset.hint": "Basic is the performance-focused default. Change presets only when needed.",
    "export.advanced": "Advanced settings",
    "export.stitch": "Merge scrolling score into one page",
    "export.overlap": "Overlap sensitivity",
    "export.upscale": "Enhance output clarity",
    "export.upscaleFactor": "Upscale factor",
    "export.upscale2x": "2x (Recommended)",
    "export.upscaleHint": "Upscaling uses GPU-only processing. You will be warned before starting if GPU is unavailable.",
    "cta.initialHint": "Start by selecting a video in step 1.",
    "cta.runRequired": "Video Required",
    "cta.cancel": "Stop Polling",
    "cta.outputFolder": "Output Folder",
    "progress.title": "Progress",
    "progress.helper": "Shows job progress after processing begins.",
    "progress.current": "Current status",
    "status.idle": "Idle",
    "pipe.download": "Prepare video",
    "pipe.extract": "Collect scenes",
    "pipe.detect": "Crop score",
    "pipe.rectify": "Organize pages",
    "pipe.upscale": "Enhance clarity",
    "pipe.export": "Save files",
    "logs.detail": "Detailed log",
    "result.title": "Results",
    "result.helper": "Pages that likely need review are shown first.",
    "result.openFolder": "Open Folder",
    "result.openPdf": "Open PDF",
    "result.copyPath": "Copy Path",
    "result.pinWindow": "Pin Window: Off",
    "result.pinHint": "When pinning is enabled, the app window stays above other windows.",
    "result.reviewSummary": "Review capture results and exclude anything you do not want to keep.",
    "result.selectionTitle": "Choose captures",
    "result.selectionHint": "Pick the images to keep and apply the selection right away.",
    "result.previewTitle": "Large preview",
    "result.previewHint": "Click any thumbnail to inspect it here without leaving the result area.",
    "result.keepAll": "Keep All",
    "result.applyReview": "Apply Selection and Regenerate Pages",
    "result.pathChipEmpty": "Output Path: -",
    "source.qualityGateTitle": "High-quality video could not be secured",
    "source.qualityGateBody": "The current environment could not fetch this video at a resolution that is reliable enough for score capture. If possible, use the original video file or a copy obtained from another platform.",
    "source.qualityGateBodyWithResolution": "The negotiated video resolution is {resolution}. That is likely too soft for reliable score capture, so using the original file or a copy from another platform is safer.",
    "source.qualityGateOpenFile": "Open Local File",
    "source.qualityGateShowLog": "Show Log",
    "support.title": "Troubleshooting",
    "support.helper": "Open this only when you hit runtime errors or need advanced recovery.",
    "support.setup": "Automatic Setup and Recovery",
    "support.setup.checking": "Checking engine",
    "support.setup.desc": "Checking the local engine connection.",
    "support.setup.run": "Auto Setup/Repair",
    "support.setup.restart": "Reconnect Engine",
    "support.setup.clearCache": "Clear Cache",
    "support.setup.clearLog": "Clear Log",
    "support.setup.cacheHint": "Clearing cache removes previous output files and temporary files.",
    "support.setup.defaultLog": "[Info] If something goes wrong, inspect the log below.",
    "support.runtime": "Runtime Info",
    "support.runtime.title": "Checking runtime info",
    "support.runtime.desc": "Loading runtime information.",
    "support.runtime.desktopVersion": "App version",
    "support.runtime.backendVersion": "Backend version",
    "support.runtime.cacheNamespace": "Preview cache namespace",
    "support.runtime.ffmpeg": "Video extraction (FFmpeg)",
    "support.runtime.opencv": "Image processing (OpenCV)",
    "support.runtime.upscale": "Clarity engine",
    "support.runtime.gpu": "GPU name",
    "support.runtime.cpu": "CPU name",
    "support.runtime.order": "FFmpeg priority",
    "crop.title": "Recrop Capture",
    "crop.close": "Close",
    "crop.helper": "Drag to keep only the needed area. Applying this replaces only the current capture.",
    "crop.reset": "Reset Area",
    "crop.apply": "Apply to Current Capture",
    "language.ko": "KO",
    "language.en": "EN",
  },
};

const listeners = new Set();

function normalizeLocale(raw) {
  const value = String(raw || "").trim().toLowerCase();
  if (value.startsWith("ko")) {
    return "ko";
  }
  return "en";
}

function detectInitialLocale() {
  const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
  if (stored) {
    return normalizeLocale(stored);
  }
  return normalizeLocale(navigator.language || navigator.userLanguage || "en");
}

let currentLocale = detectInitialLocale();

function formatTemplate(template, params = {}) {
  return String(template || "").replace(/\{\{(.*?)\}\}/g, (_, rawKey) => {
    const key = String(rawKey || "").trim();
    return params[key] == null ? "" : String(params[key]);
  });
}

export function getLocale() {
  return currentLocale;
}

export function isLocale(locale) {
  return currentLocale === locale;
}

export function t(key, params = {}) {
  const localeTable = translations[currentLocale] || translations.en;
  const fallbackTable = translations.en;
  const template = localeTable[key] ?? fallbackTable[key] ?? key;
  return formatTemplate(template, params);
}

export function setLocale(locale) {
  const next = SUPPORTED_LOCALES.includes(locale) ? locale : normalizeLocale(locale);
  if (next === currentLocale) {
    return;
  }
  currentLocale = next;
  window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
  document.documentElement.lang = next;
  listeners.forEach((listener) => {
    try {
      listener(next);
    } catch (_) {
      // noop
    }
  });
}

export function onLocaleChange(listener) {
  if (typeof listener !== "function") {
    return () => {};
  }
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function applyI18n(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.getAttribute("data-i18n") || "");
  });
  root.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    node.setAttribute("placeholder", t(node.getAttribute("data-i18n-placeholder") || ""));
  });
  root.querySelectorAll("[data-i18n-title]").forEach((node) => {
    node.setAttribute("title", t(node.getAttribute("data-i18n-title") || ""));
  });
  root.querySelectorAll("[data-i18n-aria-label]").forEach((node) => {
    node.setAttribute("aria-label", t(node.getAttribute("data-i18n-aria-label") || ""));
  });
  document.title = t("document.title");
  document.documentElement.lang = currentLocale;
}

export function initLocale() {
  document.documentElement.lang = currentLocale;
  applyI18n(document);
}
