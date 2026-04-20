#!/usr/bin/env node
const fs = require("fs");
const path = require("path");

const [, , action = "dist"] = process.argv;
const projectRoot = path.resolve(__dirname, "..", "..");
const distDir = path.join(projectRoot, "dist");
const desktopPackageJsonPath = path.join(projectRoot, "desktop", "package.json");
const sourceBackendMainPath = path.join(projectRoot, "backend", "app", "main.py");
const sourceExtractPath = path.join(projectRoot, "backend", "app", "pipeline", "extract.py");

function readText(filePath) {
  return fs.readFileSync(filePath, "utf8");
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function parseVersionFromPython(filePath) {
  const text = readText(filePath);
  const match = text.match(/version="([^"]+)"/);
  assert(match, `Could not parse FastAPI version from ${filePath}`);
  return match[1];
}

function parseYamlVersion(filePath) {
  const text = readText(filePath);
  const match = text.match(/^version:\s*([^\n]+)$/m);
  assert(match, `Could not parse version from ${filePath}`);
  return String(match[1] || "").trim().replace(/^['"]|['"]$/g, "");
}

function walk(dirPath, visitor) {
  if (!fs.existsSync(dirPath)) {
    return;
  }
  const entries = fs.readdirSync(dirPath, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dirPath, entry.name);
    if (entry.isDirectory()) {
      walk(fullPath, visitor);
      continue;
    }
    visitor(fullPath);
  }
}

function packagedBackendPattern() {
  if (process.platform === "darwin") {
    return /Contents[\/\\]Resources[\/\\]backend[\/\\]app[\/\\]main\.py$/;
  }
  if (process.platform === "win32") {
    return /resources[\/\\]backend[\/\\]app[\/\\]main\.py$/i;
  }
  return /(?:Contents[\/\\]Resources|resources)[\/\\]backend[\/\\]app[\/\\]main\.py$/i;
}

function findNewestPackagedBackendMain() {
  const matches = [];
  const pattern = packagedBackendPattern();
  walk(distDir, (filePath) => {
    if (!pattern.test(filePath)) {
      return;
    }
    matches.push(filePath);
  });
  assert(matches.length > 0, `No packaged backend app/main.py found under ${distDir}`);
  matches.sort((left, right) => fs.statSync(right).mtimeMs - fs.statSync(left).mtimeMs);
  return matches[0];
}

function latestMetadataPath() {
  if (process.platform === "darwin") {
    return path.join(distDir, "latest-mac.yml");
  }
  if (process.platform === "win32") {
    return path.join(distDir, "latest.yml");
  }
  return "";
}

function relative(filePath) {
  return path.relative(projectRoot, filePath) || filePath;
}

function packagedRuntimeExecutableName(platformName = process.platform) {
  return platformName === "win32" ? "drumsheet-backend.exe" : "drumsheet-backend";
}

function packagedToolExecutableName(toolName, platformName = process.platform) {
  return platformName === "win32" ? `${toolName}.exe` : toolName;
}

function platformPath(platformName = process.platform) {
  return platformName === "win32" ? path.win32 : path.posix;
}

function packagedBackendRoot(packagedBackendMainPath, platform = process.platform) {
  const pathApi = platformPath(platform);
  return pathApi.dirname(pathApi.dirname(packagedBackendMainPath));
}

function findPackagedRuntimeExecutable({
  distDir: candidateDistDir = distDir,
  packagedBackendMainPath,
  platform = process.platform,
}) {
  const pathApi = platformPath(platform);
  const backendRoot = packagedBackendRoot(packagedBackendMainPath, platform);
  return pathApi.join(
    backendRoot,
    "runtime",
    "drumsheet-backend",
    packagedRuntimeExecutableName(platform),
  );
}

function findPackagedBackendToolExecutable({
  packagedBackendMainPath,
  toolName,
  platform = process.platform,
}) {
  const pathApi = platformPath(platform);
  return pathApi.join(
    packagedBackendRoot(packagedBackendMainPath, platform),
    "bin",
    packagedToolExecutableName(toolName, platform),
  );
}

function findPackagedRendererV2Index({
  packagedBackendMainPath,
  platform = process.platform,
}) {
  const pathApi = platformPath(platform);
  const resourcesRoot = pathApi.dirname(packagedBackendRoot(packagedBackendMainPath, platform));
  return pathApi.join(resourcesRoot, "renderer-v2", "index.html");
}

function findPackagedVenvPath(packagedBackendMainPath) {
  const backendRoot = path.dirname(path.dirname(packagedBackendMainPath));
  return path.join(backendRoot, ".venv");
}

function normalizeReleaseAction(actionName = "dist") {
  const normalized = String(actionName || "dist").trim().toLowerCase();
  assert(
    normalized === "pack" || normalized === "dist",
    `Unsupported packaged release validation action: ${actionName}. Expected pack or dist.`,
  );
  return normalized;
}

function describeValidationMode(actionName = "dist") {
  const normalizedAction = normalizeReleaseAction(actionName);
  return {
    action: normalizedAction,
    requiresInstallerArtifacts: normalizedAction === "dist",
    requiresReleaseMetadata: normalizedAction === "dist",
  };
}

function assertRuntimeContract({
  packagedBackendMainPath,
  runtimeExecutablePath,
  runtimeExecutableExists,
  packagedFfmpegPath,
  packagedFfmpegExists,
  packagedFfprobePath,
  packagedFfprobeExists,
  packagedVenvExists,
}) {
  assert(
    runtimeExecutableExists,
    `Packaged backend is missing the frozen backend runtime: ${runtimeExecutablePath}`,
  );
  assert(
    packagedFfmpegExists,
    `Packaged backend is missing bundled ffmpeg: ${packagedFfmpegPath}`,
  );
  assert(
    packagedFfprobeExists,
    `Packaged backend is missing bundled ffprobe: ${packagedFfprobePath}`,
  );
  assert(
    !packagedVenvExists,
    `Packaged backend unexpectedly includes a virtualenv payload next to ${packagedBackendMainPath}`,
  );
}

function assertRendererContract({
  rendererV2IndexPath,
  rendererV2Exists,
}) {
  assert(
    rendererV2Exists,
    `Packaged release is missing renderer-v2/index.html: ${rendererV2IndexPath}`,
  );
}

function validate(actionName = action) {
  const validationMode = describeValidationMode(actionName);
  assert(fs.existsSync(desktopPackageJsonPath), `Missing ${desktopPackageJsonPath}`);
  assert(fs.existsSync(sourceBackendMainPath), `Missing ${sourceBackendMainPath}`);
  assert(fs.existsSync(sourceExtractPath), `Missing ${sourceExtractPath}`);

  const desktopVersion = JSON.parse(readText(desktopPackageJsonPath)).version;
  const sourceBackendVersion = parseVersionFromPython(sourceBackendMainPath);
  const packagedBackendMainPath = findNewestPackagedBackendMain();
  const packagedBackendVersion = parseVersionFromPython(packagedBackendMainPath);
  const packagedExtractPath = path.join(path.dirname(packagedBackendMainPath), "pipeline", "extract.py");
  const runtimeExecutablePath = findPackagedRuntimeExecutable({ packagedBackendMainPath });
  const packagedVenvPath = findPackagedVenvPath(packagedBackendMainPath);
  const rendererV2IndexPath = findPackagedRendererV2Index({ packagedBackendMainPath });
  const packagedFfmpegPath = findPackagedBackendToolExecutable({
    packagedBackendMainPath,
    toolName: "ffmpeg",
  });
  const packagedFfprobePath = findPackagedBackendToolExecutable({
    packagedBackendMainPath,
    toolName: "ffprobe",
  });

  assert(fs.existsSync(packagedExtractPath), `Missing packaged extract.py next to ${packagedBackendMainPath}`);
  assert(desktopVersion === sourceBackendVersion, `Desktop version ${desktopVersion} does not match backend source version ${sourceBackendVersion}`);
  assert(packagedBackendVersion === desktopVersion, `Packaged backend version ${packagedBackendVersion} does not match desktop version ${desktopVersion}`);
  assertRuntimeContract({
    packagedBackendMainPath,
    runtimeExecutablePath,
    runtimeExecutableExists: fs.existsSync(runtimeExecutablePath),
    packagedFfmpegPath,
    packagedFfmpegExists: fs.existsSync(packagedFfmpegPath),
    packagedFfprobePath,
    packagedFfprobeExists: fs.existsSync(packagedFfprobePath),
    packagedVenvExists: fs.existsSync(packagedVenvPath),
  });
  assertRendererContract({
    rendererV2IndexPath,
    rendererV2Exists: fs.existsSync(rendererV2IndexPath),
  });

  const packagedMainText = readText(packagedBackendMainPath);
  const packagedExtractText = readText(packagedExtractPath);
  assert(packagedMainText.includes('PREVIEW_SOURCE_CACHE_NAMESPACE = YOUTUBE_DOWNLOAD_STRATEGY_VERSION'), "Packaged backend is missing strategy-linked preview cache invalidation");
  assert(packagedExtractText.includes('YOUTUBE_DOWNLOAD_STRATEGY_VERSION = "yt-v3"'), "Packaged backend is missing the latest YouTube strategy version");
  assert(packagedExtractText.includes("ffmpeg_location"), "Packaged backend is missing ffmpeg_location handoff to yt-dlp");
  assert(packagedExtractText.includes('"bestvideo+bestaudio/best"'), "Packaged backend is missing best-quality YouTube format selection");
  assert(!packagedExtractText.includes('"player_client"'), "Packaged backend still forces a stale YouTube player client override");

  const metadataPath = latestMetadataPath();
  if (validationMode.requiresReleaseMetadata && metadataPath) {
    assert(fs.existsSync(metadataPath), `Missing release metadata file ${metadataPath}`);
    const metadataVersion = parseYamlVersion(metadataPath);
    assert(metadataVersion === desktopVersion, `Release metadata version ${metadataVersion} does not match desktop version ${desktopVersion}`);
  }

  console.log("[validate-packaged-release] release artifacts look consistent");
  console.log(`- validation mode: ${validationMode.action}`);
  console.log(`- desktop version: ${desktopVersion}`);
  console.log(`- backend source version: ${sourceBackendVersion}`);
  console.log(`- packaged backend version: ${packagedBackendVersion}`);
  console.log(`- packaged backend: ${relative(packagedBackendMainPath)}`);
  if (validationMode.requiresReleaseMetadata && metadataPath && fs.existsSync(metadataPath)) {
    console.log(`- release metadata: ${relative(metadataPath)}`);
  }
  console.log(`- runtime executable: ${relative(runtimeExecutablePath)}`);
  console.log(`- bundled ffmpeg: ${relative(packagedFfmpegPath)}`);
  console.log(`- bundled ffprobe: ${relative(packagedFfprobePath)}`);
  console.log(`- renderer-v2 entry: ${relative(rendererV2IndexPath)}`);
}

module.exports = {
  assertRendererContract,
  assertRuntimeContract,
  describeValidationMode,
  findPackagedBackendToolExecutable,
  findPackagedRendererV2Index,
  findPackagedRuntimeExecutable,
  findPackagedVenvPath,
  normalizeReleaseAction,
  validate,
};

if (require.main === module) {
  try {
    validate();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`[validate-packaged-release] ${message}`);
    process.exit(1);
  }
}
