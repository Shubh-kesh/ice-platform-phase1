import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";
import type {
  BillingMilestone,
  BillingMilestoneCreateInput,
  BillingMilestoneUpdateInput,
  GoogleAuthorizeResponse,
  GoogleCallbackInput,
  HealthOverrideCreateInput,
  HealthOverrideSummary,
  Invoice,
  InvoiceClientRead,
  InvoiceCreateInput,
  Project,
  ProjectCreateInput,
  ProjectHealth,
  TokenResponse,
  User,
  UserCreateInput,
  UserUpdateInput,
} from "../types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1";

const REFRESH_TOKEN_KEY = "ice_refresh_token";

// M11 google flow session storage — the callback route verifies `state` against
// this exact value before completing the exchange.
export const GOOGLE_STATE_KEY = "ice_google_state";
export const GOOGLE_VERIFIER_KEY = "ice_google_verifier";

// Access token lives only in memory — never localStorage — so it can't be
// lifted by a XSS payload reading storage. It's lost on hard refresh, which
// is fine: bootstrapAuth() below silently exchanges the stored refresh
// token for a fresh access token on load.
let accessToken: string | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function getStoredRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setStoredRefreshToken(token: string | null) {
  if (token) localStorage.setItem(REFRESH_TOKEN_KEY, token);
  else localStorage.removeItem(REFRESH_TOKEN_KEY);
}

export const api = axios.create({
  baseURL: API_URL,
});

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

// Queue concurrent requests that 401 while a refresh is already in flight,
// so a dashboard that fires 5 requests at once doesn't trigger 5 refreshes.
let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getStoredRefreshToken();
  if (!refreshToken) return null;

  try {
    const { data } = await axios.post<TokenResponse>(`${API_URL}/auth/refresh`, {
      refresh_token: refreshToken,
    });
    setAccessToken(data.access_token);
    setStoredRefreshToken(data.refresh_token);
    return data.access_token;
  } catch {
    setAccessToken(null);
    setStoredRefreshToken(null);
    return null;
  }
}

export async function logoutApi(): Promise<void> {
  const refreshToken = getStoredRefreshToken();
  try {
    if (refreshToken) {
      // Plain axios, not `api` — the refresh-on-401 interceptor must not fire
      // during logout.
      await axios.post(`${API_URL}/auth/logout`, { refresh_token: refreshToken });
    }
  } catch {
    // Best-effort revocation — the server expires the session anyway, and local
    // state below is cleared regardless so the client is always logged out.
  } finally {
    setAccessToken(null);
    setStoredRefreshToken(null);
  }
}

// --- M11: Google sign-in -----------------------------------------------------

// Both routes are public and rate-limited; plain axios keeps them clear of the
// authenticated `api` interceptors (no bearer token exists mid-flow yet).
export async function googleAuthorize(): Promise<GoogleAuthorizeResponse> {
  const { data } = await axios.get<GoogleAuthorizeResponse>(
    `${API_URL}/auth/google/authorize`
  );
  return data;
}

export async function googleCallback(
  input: GoogleCallbackInput
): Promise<TokenResponse> {
  const { data } = await axios.post<TokenResponse>(
    `${API_URL}/auth/google/callback`,
    input
  );
  return data;
}

// --- admin user management ---------------------------------------------------

export async function listUsers(): Promise<User[]> {
  const { data } = await api.get<User[]>("/users");
  return data;
}

export async function createUser(input: UserCreateInput): Promise<User> {
  const { data } = await api.post<User>("/users", input);
  return data;
}

export async function updateUser(
  userId: string,
  input: UserUpdateInput
): Promise<User> {
  const { data } = await api.patch<User>(`/users/${userId}`, input);
  return data;
}

export async function getProjects(includeArchived = false): Promise<Project[]> {
  const { data } = await api.get<Project[]>("/projects", {
    params: includeArchived ? { include_archived: true } : {},
  });
  return data;
}

export async function getProject(projectId: string): Promise<Project> {
  const { data } = await api.get<Project>(`/projects/${projectId}`);
  return data;
}

export async function createProject(
  input: ProjectCreateInput
): Promise<Project> {
  const { data } = await api.post<Project>("/projects", input);
  return data;
}

// Lifecycle transitions follow the backend lifecycle: draft -> active ->
// completed -> archived, and restore pulls an archived project back to its
// pre-archive state. The API enforces the rules; the UI only offers the
// transitions that are legal from the current status.
export async function transitionProject(
  projectId: string,
  action: "activate" | "complete" | "archive" | "restore"
): Promise<Project> {
  const { data } = await api.post<Project>(
    `/projects/${projectId}/${action}`
  );
  return data;
}

// --- Phase 3 M3: computed project health + audited admin overrides ---

export async function getProjectsHealth(
  includeArchived = false
): Promise<ProjectHealth[]> {
  const { data } = await api.get<ProjectHealth[]>("/projects/health", {
    params: includeArchived ? { include_archived: true } : {},
  });
  return data;
}

export async function getProjectHealth(projectId: string): Promise<ProjectHealth> {
  const { data } = await api.get<ProjectHealth>(`/projects/${projectId}/health`);
  return data;
}

export async function getHealthOverrides(
  projectId: string
): Promise<HealthOverrideSummary[]> {
  const { data } = await api.get<HealthOverrideSummary[]>(
    `/projects/${projectId}/health-overrides`
  );
  return data;
}

export async function setHealthOverride(
  projectId: string,
  input: HealthOverrideCreateInput
): Promise<HealthOverrideSummary> {
  const { data } = await api.post<HealthOverrideSummary>(
    `/projects/${projectId}/health-overrides`,
    input
  );
  return data;
}

export async function revokeHealthOverride(
  projectId: string,
  overrideId: string
): Promise<void> {
  await api.delete(`/projects/${projectId}/health-overrides/${overrideId}`);
}

// --- Phase 3 M5: billing milestones + milestone-driven invoices ---

export async function listBillingMilestones(
  projectId: string
): Promise<BillingMilestone[]> {
  const { data } = await api.get<BillingMilestone[]>(
    `/projects/${projectId}/billing-milestones`
  );
  return data;
}

export async function createBillingMilestone(
  projectId: string,
  input: BillingMilestoneCreateInput
): Promise<BillingMilestone> {
  const { data } = await api.post<BillingMilestone>(
    `/projects/${projectId}/billing-milestones`,
    input
  );
  return data;
}

export async function updateBillingMilestone(
  projectId: string,
  milestoneId: string,
  input: BillingMilestoneUpdateInput
): Promise<BillingMilestone> {
  const { data } = await api.patch<BillingMilestone>(
    `/projects/${projectId}/billing-milestones/${milestoneId}`,
    input
  );
  return data;
}

export async function completeBillingMilestone(
  projectId: string,
  milestoneId: string
): Promise<BillingMilestone> {
  const { data } = await api.post<BillingMilestone>(
    `/projects/${projectId}/billing-milestones/${milestoneId}/complete`
  );
  return data;
}

// Admin/procurement receive the full InvoiceRead shape; clients receive the
// restricted InvoiceClientRead shape. Callers should type the response to the
// shape their role is allowed to see.
export async function listInvoices(
  projectId: string
): Promise<Invoice[] | InvoiceClientRead[]> {
  const { data } = await api.get<Invoice[] | InvoiceClientRead[]>(
    `/projects/${projectId}/invoices`
  );
  return data;
}

export async function createInvoice(
  projectId: string,
  input: InvoiceCreateInput
): Promise<Invoice> {
  const { data } = await api.post<Invoice>(
    `/projects/${projectId}/invoices`,
    input
  );
  return data;
}

export async function transitionInvoice(
  projectId: string,
  invoiceId: string,
  action: "issue" | "mark-paid" | "cancel"
): Promise<Invoice> {
  const { data } = await api.post<Invoice>(
    `/projects/${projectId}/invoices/${invoiceId}/${action}`
  );
  return data;
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };

    const isAuthEndpoint = originalRequest?.url?.includes("/auth/");

    if (error.response?.status === 401 && !originalRequest._retry && !isAuthEndpoint) {
      originalRequest._retry = true;

      if (!refreshPromise) {
        refreshPromise = refreshAccessToken().finally(() => {
          refreshPromise = null;
        });
      }

      const newToken = await refreshPromise;
      if (newToken) {
        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return api(originalRequest);
      }

      // Refresh failed — force back to login.
      window.location.href = "/login";
    }

    return Promise.reject(error);
  }
);
