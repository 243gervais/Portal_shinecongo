const bootstrapElement = document.getElementById("portal-bootstrap");
const DEFAULT_GET_CACHE_TTL_MS = 60_000;
const MAX_GET_CACHE_ENTRIES = 80;
const apiGetCache = new Map();
const apiInflight = new Map();
let cacheGeneration = 0;
const READ_TIMEOUT_MS = 8_000;

function awaitWithSignal(promise, signal) {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(new DOMException("Aborted", "AbortError"));
  return new Promise((resolve, reject) => {
    const abort = () => reject(new DOMException("Aborted", "AbortError"));
    signal.addEventListener("abort", abort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
}

async function fetchRead(url, options, cacheKey) {
  // Only reads are retried: a timed-out write may already have been saved.
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), READ_TIMEOUT_MS);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal, cache: attempt ? "reload" : "no-store" });
      const payload = await parseResponse(response);
      if (attempt === 0 && [502, 503, 504].includes(response.status)) {
        apiGetCache.delete(cacheKey);
        continue;
      }
      return { response, payload };
    } catch (error) {
      apiGetCache.delete(cacheKey);
      if (attempt === 1) {
        if (error.name === "AbortError") {
          throw new Error("Le serveur met trop de temps a repondre. Veuillez reessayer.");
        }
        throw error;
      }
    } finally {
      clearTimeout(timeout);
    }
  }
}

export function getBootstrap() {
  if (!bootstrapElement) {
    return {};
  }

  try {
    return JSON.parse(bootstrapElement.textContent || "{}");
  } catch (_error) {
    return {};
  }
}

function getCsrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function parseResponse(response) {
  const text = await response.text();
  if (!text) {
    return null;
  }

  try {
    return JSON.parse(text);
  } catch (_error) {
    return { message: text };
  }
}

function errorMessageFromPayload(payload) {
  if (!payload) {
    return "Une erreur est survenue.";
  }
  if (typeof payload.message === "string") {
    return payload.message;
  }
  if (typeof payload.detail === "string") {
    return payload.detail;
  }
  if (typeof payload.error === "string") {
    return payload.error;
  }
  return "Une erreur est survenue.";
}

function redirectToLogin() {
  const bootstrap = getBootstrap();
  const loginUrl = bootstrap.login_url || "/login/";
  const currentUrl = `${window.location.pathname}${window.location.search}`;
  window.location.assign(`${loginUrl}?next=${encodeURIComponent(currentUrl)}`);
}

function clonePayload(payload) {
  if (payload === null || payload === undefined) {
    return payload;
  }

  if (typeof structuredClone === "function") {
    return structuredClone(payload);
  }

  return JSON.parse(JSON.stringify(payload));
}

function readCachedPayload(cacheKey) {
  const cached = apiGetCache.get(cacheKey);
  if (!cached) {
    return undefined;
  }

  if (cached.expiresAt <= Date.now()) {
    apiGetCache.delete(cacheKey);
    return undefined;
  }

  return clonePayload(cached.payload);
}

function writeCachedPayload(cacheKey, payload, ttlMs) {
  if (apiGetCache.size >= MAX_GET_CACHE_ENTRIES && !apiGetCache.has(cacheKey)) {
    const oldestKey = apiGetCache.keys().next().value;
    apiGetCache.delete(oldestKey);
  }

  apiGetCache.set(cacheKey, {
    payload: clonePayload(payload),
    expiresAt: Date.now() + ttlMs,
  });
}

function buildSearch(query) {
  if (!query) {
    return "";
  }

  const params = new URLSearchParams();
  Object.entries(query).sort(([a], [b]) => a.localeCompare(b)).forEach(([key, value]) => {
    if (key === "page" && String(value) === "1") return;
    if (value !== undefined && value !== null && value !== "") {
      params.append(key, value);
    }
  });
  const serialized = params.toString();
  return serialized ? `?${serialized}` : "";
}

export function clearApiCache() {
  cacheGeneration += 1;
  apiGetCache.clear();
  apiInflight.clear();
}

export async function apiFetch(path, options = {}) {
  const {
    method = "GET",
    data,
    headers = {},
    query,
    signal,
    cacheTtlMs = DEFAULT_GET_CACHE_TTL_MS,
  } = options;

  const normalizedMethod = method.toUpperCase();
  const search = buildSearch(query);
  const isCacheableGet = normalizedMethod === "GET" && cacheTtlMs > 0;
  const cacheKey = `${path}${search}`;
  const generation = cacheGeneration;
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
  if (isCacheableGet) {
    const cachedPayload = readCachedPayload(cacheKey);
    if (cachedPayload !== undefined) {
      return cachedPayload;
    }

    if (apiInflight.has(cacheKey)) {
      return clonePayload(await awaitWithSignal(apiInflight.get(cacheKey), signal));
    }
  }

  const requestHeaders = {
    Accept: "application/json",
    ...headers,
  };
  const requestOptions = {
    method: normalizedMethod,
    credentials: "same-origin",
    headers: requestHeaders,
    signal,
  };

  if (data instanceof FormData) {
    requestOptions.body = data;
  } else if (data !== undefined) {
    requestHeaders["Content-Type"] = "application/json";
    requestOptions.body = JSON.stringify(data);
  }

  if (!["GET", "HEAD", "OPTIONS"].includes(normalizedMethod)) {
    requestHeaders["X-CSRFToken"] = getCsrfToken();
  }

  const requestPromise = (async () => {
    const url = `/api/portal${path}${search}`;
    const { response, payload } = normalizedMethod === "GET"
      ? await fetchRead(url, requestOptions, cacheKey)
      : await (async () => {
        const response = await fetch(url, requestOptions);
        return { response, payload: await parseResponse(response) };
      })();

    if (!response.ok) {
      const detail = String(payload?.detail || payload?.message || "").toLowerCase();
      const looksUnauthenticated = detail.includes("authentication") || detail.includes("credentials") || detail.includes("connexion");
      if (response.status === 401 || (response.status === 403 && looksUnauthenticated)) {
        clearApiCache();
        redirectToLogin();
      }
      const error = new Error(errorMessageFromPayload(payload));
      error.status = response.status;
      error.payload = payload;
      throw error;
    }

    if (isCacheableGet && generation === cacheGeneration) {
      writeCachedPayload(cacheKey, payload, cacheTtlMs);
    } else if (!["GET", "HEAD", "OPTIONS"].includes(normalizedMethod)) {
      clearApiCache();
    }

    return payload;
  })();

  if (isCacheableGet) {
    apiInflight.set(cacheKey, requestPromise);
    requestPromise.finally(() => {
      if (apiInflight.get(cacheKey) === requestPromise) apiInflight.delete(cacheKey);
    }).catch(() => {});
  }

  return clonePayload(await awaitWithSignal(requestPromise, signal));
}

export async function prefetchApi(path, options = {}) {
  if (!path) {
    return;
  }

  try {
    await apiFetch(path, {
      ...options,
      method: "GET",
      signal: undefined,
    });
  } catch (_error) {
    // Prefetch is opportunistic; the page itself will show the actionable error.
  }
}
