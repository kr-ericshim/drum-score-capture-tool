const os = require('node:os');
function redactDiagnostic(value, secrets = []) {
  let text = String(value ?? '').slice(0, 30000);
  for (const secret of [...secrets, os.homedir()].filter(Boolean)) text = text.split(secret).join('[redacted]');
  return text
    .replace(/\[redacted\][\\/][^\r\n]+/g, '[local path]')
    .replace(/https?:\/\/[^\s<>"']+/gi, '[url]')
    .replace(/(?:authorization|cookie|set-cookie|token|api[_-]?key|password)\s*[:=]\s*[^\r\n]+/gi, '[credential redacted]')
    .replace(/(?:[A-Za-z]:[\\/]|\/(?:Users|home|tmp|private|var|Volumes)\/)[^\r\n]+/g, '[local path]');
}
function createDiagnosticLog(secrets = []) {
  const lines = [];
  return {
    append(text) {
      lines.push(...redactDiagnostic(text, secrets).split(/\r?\n/).filter(Boolean));
      if (lines.length > 100) lines.splice(0, lines.length - 100);
    },
    report({ version, backend, detail }) {
      return redactDiagnostic([
        `Drum Sheet Capture ${version}`,
        `${process.platform} ${process.arch}; OS ${os.release()}`,
        `Backend ready: ${Boolean(backend.ready)}; starting: ${Boolean(backend.starting)}`,
        backend.error || '', detail || '', ...lines,
      ].join('\n'), secrets);
    },
  };
}
module.exports = { redactDiagnostic, createDiagnosticLog };
