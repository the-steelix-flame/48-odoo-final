/**
 * The single fetch wrapper.  Owner: sinjeki.
 *
 * Every call in the app goes through here so that the auth header, the error
 * shape and the base URL live in exactly one place.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api";

const TOKEN_KEY = "dealflow.token";
const USER_KEY = "dealflow.user";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setSession(token: string, user: unknown) {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export function getStoredUser<T>(): T | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  try {
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

/**
 * Mirrors the backend's error contract (WORKFLOW.md §11).
 * `status` matters: 409 means "refresh, don't retry".
 */
export class ApiError extends Error {
  status: number;
  context?: Record<string, unknown>;

  constructor(status: number, detail: string, context?: Record<string, unknown>) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.context = context;
  }

  get isConflict() {
    return this.status === 409;
  }
  get isAuth() {
    return this.status === 401 || this.status === 403;
  }
}

type Options = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  /** Skip the Authorization header (login/signup only). */
  anonymous?: boolean;
};

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const { method = "GET", body, anonymous = false } = options;

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (!anonymous) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    // The backend isn't running, or the network died mid-demo. Say so plainly
    // rather than letting a screen render an empty white box.
    throw new ApiError(0, "Cannot reach the API. Is the Django server running on :8000?");
  }

  if (response.status === 204) return undefined as T;

  const payload = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new ApiError(
      response.status,
      payload.detail ?? `Request failed (${response.status})`,
      payload.context,
    );
  }
  return payload as T;
}

export const get = <T,>(path: string) => api<T>(path);
export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body });
export const patch = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "PATCH", body });
export const del = <T,>(path: string) => api<T>(path, { method: "DELETE" });
