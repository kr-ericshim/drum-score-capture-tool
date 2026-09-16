"use strict";

const fs = require("fs");
const path = require("path");
const root = path.resolve(__dirname, "..", "..");

function assertReleaseVersions({ manifestVersion, lockVersion, lockRootVersion, backendVersion, ref = "" }) {
  if (![lockVersion, lockRootVersion, backendVersion].every((value) => value === manifestVersion)) {
    throw new Error(`Release version mismatch: desktop=${manifestVersion}, lock=${lockVersion}/${lockRootVersion}, backend=${backendVersion}`);
  }
  if (ref.startsWith("refs/tags/") && ref !== `refs/tags/v${manifestVersion}`) {
    throw new Error(`Release tag ${ref} must match v${manifestVersion}`);
  }
}

function main() {
  const manifest = require("../package.json");
  const lock = require("../package-lock.json");
  const backend = fs.readFileSync(path.join(root, "backend/app/main.py"), "utf8");
  const backendVersion = backend.match(/version="([^"]+)"/)?.[1];
  const ref = process.env.GITHUB_REF || "";
  assertReleaseVersions({
    manifestVersion: manifest.version,
    lockVersion: lock.version,
    lockRootVersion: lock.packages?.[""]?.version,
    backendVersion,
    ref,
  });
  if (ref.startsWith("refs/tags/")) {
    const notes = path.join(root, `docs/release/release-notes-v${manifest.version}.md`);
    if (!fs.existsSync(notes) || fs.statSync(notes).size === 0) throw new Error(`Missing release notes: ${notes}`);
  }
  console.log(`[check-release-version] desktop, lockfile and backend agree: ${manifest.version}`);
}

module.exports = { assertReleaseVersions };
if (require.main === module) main();
