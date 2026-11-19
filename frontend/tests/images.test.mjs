import test from 'node:test';
import assert from 'node:assert/strict';
import { isPhotoFile, preparePhoto, preparePhotoSelection } from '../src/lib/images.js';

test('camera photos without a MIME type are recognized but SVG is not', () => {
  assert.equal(isPhotoFile({ name: 'camera.JPG', type: '' }), true);
  assert.equal(isPhotoFile({ name: 'payload.svg', type: 'image/svg+xml' }), false);
});

test('large photos are resized before upload and bitmap memory is released', async () => {
  let closed = false;
  let canvas;
  globalThis.createImageBitmap = async () => ({ width: 6000, height: 4000, close() { closed = true; } });
  let encodedSize;
  globalThis.document = { createElement: () => (canvas = {
    getContext: () => ({ fillRect() {}, drawImage() {} }),
    toBlob(callback, type) { encodedSize = [this.width, this.height]; callback(new Blob(['reduced'], { type })); },
  }) };
  const result = await preparePhoto(new File(['source'], 'camera.png', { type: 'image/png', lastModified: 123 }));
  assert.deepEqual(encodedSize, [1600, 1067]);
  assert.equal(result.type, 'image/jpeg');
  assert.equal(result.name, 'camera.jpg');
  assert.equal(result.lastModified, 123);
  assert.equal(closed, true);
  assert.equal(canvas.width, 0);
});

test('unreadable/oversized selections show named errors without dropping valid photos', async () => {
  const oversized = { name: 'huge.jpg', type: 'image/jpeg', size: 31 * 1024 * 1024 };
  const result = await preparePhotoSelection([oversized, new File(['x'], 'ok.jpg', { type: 'image/jpeg' })]);
  assert.equal(result.items.length, 1);
  assert.match(result.errors[0], /huge.jpg.*30 Mo/);
  URL.revokeObjectURL(result.items[0].previewUrl);
});
