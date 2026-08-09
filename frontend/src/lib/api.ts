import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";
import type { TokenResponse } from "../types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1";

const REFRESH_TOKEN_KEY = "ice_refresh_token";

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
