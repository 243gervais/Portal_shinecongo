const bootstrapElement = document.getElementById("portal-bootstrap");
const DEFAULT_GET_CACHE_TTL_MS = 30_000;
const apiGetCache = new Map();
const apiInflight = new Map();

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
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      params.append(key, value);
    }
  });
  const serialized = params.toString();
  return serialized ? `?${serialized}` : "";
}

export function clearApiCache() {
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
  if (isCacheableGet) {
    const cachedPayload = readCachedPayload(cacheKey);
    if (cachedPayload !== undefined) {
      return cachedPayload;
    }

    if (!signal && apiInflight.has(cacheKey)) {
      return clonePayload(await apiInflight.get(cacheKey));
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
    const response = await fetch(`/api/portal${path}${search}`, requestOptions);
    const payload = await parseResponse(response);

    if (!response.ok) {
      const detail = String(payload?.detail || payload?.message || "").toLowerCase();
      const looksUnauthenticated = detail.includes("authentication") || detail.includes("credentials") || detail.includes("connexion");
      if (response.status === 401 || (response.status === 403 && looksUnauthenticated)) {
        redirectToLogin();
      }
      const error = new Error(errorMessageFromPayload(payload));
      error.status = response.status;
      error.payload = payload;
      throw error;
    }

    if (isCacheableGet) {
      writeCachedPayload(cacheKey, payload, cacheTtlMs);
    } else if (!["GET", "HEAD", "OPTIONS"].includes(normalizedMethod)) {
      clearApiCache();
    }

    return payload;
  })();

  if (isCacheableGet && !signal) {
    apiInflight.set(cacheKey, requestPromise);
  }

  try {
    return clonePayload(await requestPromise);
  } finally {
    if (isCacheableGet && !signal) {
      apiInflight.delete(cacheKey);
    }
  }
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
