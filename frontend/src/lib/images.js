const MAX_SOURCE_BYTES = 30 * 1024 * 1024;
const MAX_EDGE = 1600;

export function isPhotoFile(file) {
  return !!file && (/^image\/(jpeg|png|webp|gif|heic|heif)$/i.test(file.type || "")
    || (!file.type && /\.(jpe?g|png|webp|gif|heic|heif)$/i.test(file.name || "")));
}

async function decodePhoto(file) {
  if (typeof createImageBitmap === "function") {
    try { return await createImageBitmap(file); } catch (_) { /* Try the browser's image decoder. */ }
  }
  const url = URL.createObjectURL(file);
  try {
    return await new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error("Format non lisible. Choisissez une photo JPG, PNG ou WEBP."));
      image.src = url;
    });
  } finally { URL.revokeObjectURL(url); }
}

export async function preparePhoto(file) {
  if (!isPhotoFile(file)) throw new Error("Choisissez une photo JPG, PNG, WEBP ou un format photo compatible avec votre téléphone.");
  if (file.size > MAX_SOURCE_BYTES) throw new Error("Cette photo dépasse 30 Mo. Choisissez une version plus petite.");
  const image = await decodePhoto(file);
  try {
    const ratio = Math.min(1, MAX_EDGE / Math.max(image.width, image.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.width * ratio));
    canvas.height = Math.max(1, Math.round(image.height * ratio));
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Impossible de préparer la photo. Réessayez avec une autre image.");
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.8));
    canvas.width = 0;
    canvas.height = 0;
    if (!blob || blob.size > 10 * 1024 * 1024) throw new Error("Impossible de réduire cette photo. Choisissez une autre image.");
    return new File([blob], `${file.name.replace(/\.[^.]+$/, "") || "photo"}.jpg`, {
      type: "image/jpeg", lastModified: file.lastModified,
    });
  } finally { image.close?.(); }
}

export async function preparePhotoSelection(fileList) {
  const items = [];
  const errors = [];
  // Sequential decoding prevents several large phone photos occupying memory together.
  for (const source of Array.from(fileList || [])) {
    try {
      const file = await preparePhoto(source);
      items.push({ id: crypto.randomUUID(), file, previewUrl: URL.createObjectURL(file) });
    } catch (error) { errors.push(`${source.name}: ${error.message}`); }
  }
  return { items, errors };
}
