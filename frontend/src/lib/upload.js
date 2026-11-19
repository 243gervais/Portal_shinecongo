export function sendUpload(url, options, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const cleanup = () => options.signal?.removeEventListener("abort", abort);
    const fail = (message) => { cleanup(); reject(new Error(message)); };
    const abort = () => xhr.abort();
    xhr.open(options.method, url);
    xhr.withCredentials = true;
    xhr.timeout = 120_000;
    Object.entries(options.headers).forEach(([key, value]) => xhr.setRequestHeader(key, value));
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100));
    };
    xhr.onload = () => {
      cleanup();
      const loginRedirect = /\/login\//.test(xhr.responseURL || "");
      resolve({
        status: loginRedirect ? 401 : xhr.status,
        ok: !loginRedirect && xhr.status >= 200 && xhr.status < 300,
        text: async () => loginRedirect ? JSON.stringify({ message: "Votre session a expiré. Reconnectez-vous dans un autre onglet, puis réessayez ici; vos photos restent sélectionnées." }) : xhr.responseText,
      });
    };
    xhr.onerror = () => fail("Connexion interrompue. Vos photos restent sélectionnées; vérifiez le réseau puis réessayez.");
    xhr.ontimeout = () => fail("L'envoi prend trop de temps. Vos photos restent sélectionnées; vérifiez le réseau puis réessayez.");
    xhr.onabort = () => { cleanup(); reject(new DOMException("Aborted", "AbortError")); };
    if (options.signal?.aborted) { reject(new DOMException("Aborted", "AbortError")); return; }
    options.signal?.addEventListener("abort", abort, { once: true });
    xhr.send(options.body);
  });
}
