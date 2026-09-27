const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");

function run(command, args) {
  return execFileSync(command, args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
}

function verifyApp(app) {
  run("codesign", ["--verify", "--deep", "--strict", "--verbose=2", app]);
  // Resources executables are not all traversed by codesign --deep.
  const backend = path.join(app, "Contents", "Resources", "backend");
  for (const binary of ["bin/ffmpeg", "bin/ffprobe", "runtime/drumsheet-backend/drumsheet-backend"]) {
    run("codesign", ["--verify", "--strict", "--verbose=2", path.join(backend, binary)]);
  }
  console.log(`[verify-macos-signature] valid bundle and backend signatures: ${app}`);
}

function verifyDmg(dmg, expectedVersion) {
  run("hdiutil", ["verify", dmg]);
  const mount = fs.mkdtempSync(path.join(os.tmpdir(), "drumsheet-signature-"));
  let attached = false;
  try {
    run("hdiutil", ["attach", "-readonly", "-nobrowse", "-mountpoint", mount, dmg]);
    attached = true;
    const app = path.join(mount, "Drum Sheet Capture.app");
    const version = run("/usr/libexec/PlistBuddy", ["-c", "Print :CFBundleShortVersionString", path.join(app, "Contents", "Info.plist")]).trim();
    if (version !== expectedVersion) throw new Error(`DMG version ${version} does not match ${expectedVersion}`);
    verifyApp(app);
  } finally {
    if (attached) run("hdiutil", ["detach", mount]);
    fs.rmdirSync(mount);
  }
}

module.exports = { verifyApp, verifyDmg };

if (require.main === module) {
  try {
    if (process.platform !== "darwin") throw new Error("macOS is required");
    const target = process.argv[2];
    if (!target) throw new Error("Usage: node verify-macos-signature.js <app|dmg>");
    if (target.endsWith(".dmg")) verifyDmg(path.resolve(target), require("../package.json").version);
    else verifyApp(path.resolve(target));
  } catch (error) {
    console.error(error.stderr?.toString() || error.message);
    process.exitCode = 1;
  }
}
