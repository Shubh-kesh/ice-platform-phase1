import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  api,
  setAccessToken,
  getStoredRefreshToken,
  setStoredRefreshToken,
} from "./api";
import type { TokenResponse, User } from "../types";

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  // Starts true: we don't know yet whether a stored refresh token is valid.
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    bootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function bootstrap() {
    const refreshToken = getStoredRefreshToken();
    if (!refreshToken) {
      setIsLoading(false);
      return;
    }
    try {
      const { data } = await api.post<TokenResponse>("/auth/refresh", {
        refresh_token: refreshToken,
      });
      setAccessToken(data.access_token);
      setStoredRefreshToken(data.refresh_token);
      const me = await api.get<User>("/auth/me");
      setUser(me.data);
    } catch {
      setAccessToken(null);
      setStoredRefreshToken(null);
    } finally {
      setIsLoading(false);
    }
  }

  async function login(email: string, password: string) {
    const { data } = await api.post<TokenResponse>("/auth/login", {
      email,
      password,
    });
    setAccessToken(data.access_token);
    setStoredRefreshToken(data.refresh_token);
    const me = await api.get<User>("/auth/me");
    setUser(me.data);
  }

  function logout() {
    setAccessToken(null);
    setStoredRefreshToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
