"use strict";

const fs = require("fs");
const path = require("path");

// Logical file bytes, not allocated disk blocks. Do not follow framework symlinks.
function fileBytes(target) {
  const stat = fs.lstatSync(target);
  if (stat.isSymbolicLink()) return 0;
  if (!stat.isDirectory()) return stat.size;
  return fs.readdirSync(target).reduce((total, name) => total + fileBytes(path.join(target, name)), 0);
}

function writeSizeReport({ packagedBackendMainPath, installerArtifacts, version, outputPath }) {
  const backendRoot = path.dirname(path.dirname(packagedBackendMainPath));
  const resourcesRoot = path.dirname(backendRoot);
  const appRoot = process.platform === "darwin"
    ? path.dirname(path.dirname(resourcesRoot))
    : path.dirname(resourcesRoot);
  const appBytes = fileBytes(appRoot);
  const components = {
    backendRuntime: fileBytes(path.join(backendRoot, "runtime")),
    mediaTools: fileBytes(path.join(backendRoot, "bin")),
    desktopAsar: fileBytes(path.join(resourcesRoot, "app.asar")),
  };
  const frameworkRoot = path.join(path.dirname(resourcesRoot), "Frameworks");
  if (process.platform === "darwin" && fs.existsSync(frameworkRoot)) {
    components.electronFrameworks = fileBytes(frameworkRoot);
  }
  components.other = appBytes - Object.values(components).reduce((sum, size) => sum + size, 0);
  const report = {
    version,
    platform: process.platform,
    generatedAt: new Date().toISOString(),
    measurement: "Logical file bytes; symlinks excluded. Installer bytes are compressed artifact sizes.",
    appPath: appRoot,
    appBytes,
    components,
    installers: installerArtifacts.map((artifact) => ({ name: path.basename(artifact), bytes: fileBytes(artifact) })),
  };
  fs.writeFileSync(outputPath, `${JSON.stringify(report, null, 2)}\n`);
  console.log(`[packaged-size] app: ${(appBytes / 1024 ** 2).toFixed(1)} MiB`);
  for (const [name, bytes] of Object.entries(components)) {
    console.log(`- ${name}: ${(bytes / 1024 ** 2).toFixed(1)} MiB`);
  }
  for (const installer of report.installers) {
    console.log(`- ${installer.name}: ${(installer.bytes / 1024 ** 2).toFixed(1)} MiB`);
  }
  console.log(`- size report: ${outputPath}`);
  return report;
}

module.exports = { fileBytes, writeSizeReport };
