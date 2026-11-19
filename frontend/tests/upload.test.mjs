import test from 'node:test';
import assert from 'node:assert/strict';

globalThis.document = { getElementById: () => null, cookie: 'csrftoken=upload-token' };
let loginRedirects = 0;
globalThis.window = { location: { pathname: '/manager/', search: '', assign() { loginRedirects += 1; } } };
const { apiFetch } = await import('../src/lib/api.js');

class UploadRequest {
  static instances = [];
  static result = 'success';
  constructor() { this.upload = {}; this.headers = {}; UploadRequest.instances.push(this); }
  open(method, url) { this.method = method; this.url = url; }
  setRequestHeader(key, value) { this.headers[key] = value; }
  send(body) {
    this.body = body;
    queueMicrotask(() => {
      this.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 });
      if (UploadRequest.result === 'timeout') { this.ontimeout(); return; }
      this.status = UploadRequest.result === 'expired' ? 403 : 201;
      this.responseText = UploadRequest.result === 'expired' ? '<html>CSRF verification failed</html>' : JSON.stringify({ saved: true });
      this.onload();
    });
  }
}
globalThis.XMLHttpRequest = UploadRequest;

test('multipart upload sends CSRF and reports progress without overriding the boundary', async () => {
  const data = new FormData(); data.append('photo', new Blob(['image']), 'phone.jpg');
  let progress;
  assert.deepEqual(await apiFetch('/manager/lavages/', { method: 'POST', data, onUploadProgress(value) { progress = value; } }), { saved: true });
  const xhr = UploadRequest.instances.at(-1);
  assert.equal(xhr.headers['X-CSRFToken'], 'upload-token');
  assert.equal(xhr.headers['Content-Type'], undefined);
  assert.equal(xhr.body, data);
  assert.equal(progress, 50);
  assert.equal(xhr.withCredentials, true);
});

test('upload timeouts are actionable and never automatically retried', async () => {
  UploadRequest.result = 'timeout';
  const before = UploadRequest.instances.length;
  await assert.rejects(apiFetch('/manager/lavages/', { method: 'POST', data: new FormData(), onUploadProgress() {} }), /photos restent sélectionnées/);
  assert.equal(UploadRequest.instances.length, before + 1);
});

test('expired upload session preserves the form and never displays proxy HTML', async () => {
  UploadRequest.result = 'expired';
  await assert.rejects(apiFetch('/manager/lavages/', { method: 'POST', data: new FormData(), onUploadProgress() {} }), /session a expiré/);
  assert.equal(loginRedirects, 0);
});
