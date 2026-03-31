const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

function apiUrl(path: string) {
  return `${API_BASE_URL}${path}`;
}

async function buildErrorMessage(response: Response, fallback: string) {
  try {
    const payload = await response.json();
    if (payload?.detail && typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {
    // Ignore JSON parsing errors and return fallback message.
  }

  return `${fallback} (HTTP ${response.status})`;
}

function buildAuthHeaders(token?: string) {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

export async function login(username: string, password: string) {
  const response = await fetch(apiUrl("/api/v1/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

  if (!response.ok) {
    throw new Error(await buildErrorMessage(response, "Credenciales incorrectas"));
  }

  return response.json() as Promise<{
    access_token: string;
    token_type: string;
    expires_in: number;
  }>;
}

export async function analyzeText(content: string, token?: string) {
  const response = await fetch(apiUrl("/api/v1/analyze"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...buildAuthHeaders(token),
    },
    body: JSON.stringify({
      input_type: "text",
      content,
      mode: "both",
      labels: ["soporte", "ventas", "reclamacion"],
    }),
  });

  if (!response.ok) {
    throw new Error(await buildErrorMessage(response, "No se pudo analizar el texto"));
  }

  return response.json();
}

export async function analyzePdf(file: File, token?: string) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(apiUrl("/api/v1/analyze-pdf-file"), {
    method: "POST",
    headers: {
      ...buildAuthHeaders(token),
    },
    body: formData,
  });

  if (!response.ok) {
    throw new Error(await buildErrorMessage(response, "No se pudo analizar el PDF"));
  }

  return response.json();
}
