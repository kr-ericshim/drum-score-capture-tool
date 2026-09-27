import test from 'node:test';
import assert from 'node:assert/strict';
import { parseCaptureTime, captureRange } from '../features/export/captureRange.js';
import { createInitialSessionState } from '../app/session/selectors.js';
import { buildExportScreenModel, renderExportScreen } from '../features/export/ExportScreen.js';
import { canRunExport } from '../app/session/runtimeSafety.js';
import { saveSession, restoreSession } from '../app/session/persistence.js';

test('capture time supports seconds, minutes and hours with strict inner components', () => {
  assert.equal(parseCaptureTime('1:30.5'),90.5); assert.equal(parseCaptureTime('1:02:03'),3723);
  assert.equal(parseCaptureTime('90'),90); assert.equal(parseCaptureTime(''),null);
  for (const value of ['-1','1:60','1:00:60','Infinity','1e3','1:']) assert.ok(Number.isNaN(parseCaptureTime(value)));
});
test('range validation blocks invalid starts and preserves full-video defaults', () => {
  const s = createInitialSessionState(); s.source.filePath='/fixture.mp4'; s.source.metadata={durationSec:120};
  s.roi.appliedRect=[[0,0],[100,0],[100,100],[0,100]];
  assert.deepEqual(captureRange(s),{start:0,end:null,error:''});
  for (const [start,end,error] of [['2:00','','duration'],['1:00','0:30','order'],['0','2:01','duration'],['1:','','format']]) {
    s.exportConfig.rangeStart=start; s.exportConfig.rangeEnd=end;
    assert.equal(captureRange(s).error,error); assert.equal(canRunExport(s),false); assert.equal(buildExportScreenModel(s).canRun,false);
  }
  s.exportConfig.rangeStart='0:20'; s.exportConfig.rangeEnd='2:00'; assert.equal(captureRange(s).error,'');
});
test('range persists with the selected source and stays disabled while running', () => {
  const s=createInitialSessionState();s.source.filePath='/fixture.mp4';s.exportConfig.rangeStart='30';s.exportConfig.rangeEnd='1:00';
  let saved; const storage={setItem:(_,v)=>{saved=v;},getItem:()=>saved}; saveSession(storage,s);
  const restored=restoreSession(storage,createInitialSessionState());assert.equal(restored.exportConfig.rangeEnd,'1:00');
  restored.exportConfig.runStatus='running';
  for (const locale of ['ko','en']) { restored.ui.locale=locale;assert.match(renderExportScreen(restored),/data-action="capture-range"[^>]*disabled/); }
});
