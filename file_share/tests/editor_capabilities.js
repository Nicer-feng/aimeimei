// Exercise the actual entrypoint predicates without fetching editor SDKs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const sandbox = vm.createContext({window: {}});
for (const script of ['office-editor.js', 'pdf-page-editor.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../../res/file-share', script), 'utf8'), sandbox);
}
const office = sandbox.window.CloudOffice;
const pdf = sandbox.window.CloudPdfEditor;
const officeFile = {status: 'READY', filename: 'example.docx', size: 1024};
const pdfFile = {status: 'READY', file_type: 'PDF', filename: 'example.pdf', size: 1024};
office.setConfig({enabled: true, max_bytes: 20 * 1024 * 1024, formats: ['docx', 'xlsx']});
for (const capabilities of [null, {}, {edit_pdf: false, edit_office: false}]) {
  office.setCapabilities(capabilities);
  pdf.setCapabilities(capabilities);
  assert.equal(office.canEdit(officeFile), false);
  assert.equal(pdf.canEdit(pdfFile), false);
}
office.setCapabilities({edit_office: true});
pdf.setCapabilities({edit_pdf: true});
assert.equal(office.canEdit(officeFile), true);
assert.equal(pdf.canEdit(pdfFile), true);
assert.equal(pdf.canEdit({...pdfFile, status: 'TRASHED'}), false);
assert.equal(pdf.canEdit({...pdfFile, size: 21 * 1024 * 1024}), false);
office.setConfig({enabled: false});
assert.equal(office.canEdit(officeFile), false);
pdf.setCapabilities(null);
assert.equal(pdf.canEdit(pdfFile), false);
console.log('PASS: editor entrypoints deny members, allow admins, preserve readiness and limits, reset after logout');
