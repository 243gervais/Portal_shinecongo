const bootstrapElement = document.getElementById("portal-bootstrap");

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

export async function apiFetch(path, options = {}) {
  const {
    method = "GET",
    data,
    headers = {},
    query,
    signal,
  } = options;

  const search = query ? `?${new URLSearchParams(query).toString()}` : "";
  const requestHeaders = {
    Accept: "application/json",
    ...headers,
  };
  const requestOptions = {
    method,
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

  if (!["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase())) {
    requestHeaders["X-CSRFToken"] = getCsrfToken();
  }

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

  return payload;
}
