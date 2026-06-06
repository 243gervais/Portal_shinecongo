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

export async function apiFetch(path, options = {}) {
  const {
    method = "GET",
    data,
    headers = {},
    query,
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
    const error = new Error(payload?.message || "Une erreur est survenue.");
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return payload;
}
