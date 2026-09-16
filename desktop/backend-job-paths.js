"use strict";

const path = require("path");

function resolveBackendJobsDir({ app, backendDir, env = process.env } = {}) {
  const configured = String(env.DRUMSHEET_JOBS_DIR || "").trim();
  if (configured) {
    return configured;
  }

  if (app?.isPackaged && typeof app.getPath === "function") {
    return path.join(app.getPath("userData"), "jobs");
  }

  return path.join(backendDir, "jobs");
}

module.exports = {
  resolveBackendJobsDir,
};
