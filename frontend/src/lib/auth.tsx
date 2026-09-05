"use client";

/**
 * AuthProvider.  Owner: sinjeki.
 *
 * PHASE 1 (today): `login()` posts email + password to our own /auth/login,
 * which checks the real Django password hasher and returns a signed token.
 * Simplified, not faked.
 *
 * PHASE 2 (end of day): swap the body of `login()` for the Firebase Web SDK
 * and hand its ID token to the same `setSession`. NOTHING ELSE IN THE APP
 * CHANGES — every screen consumes `useAuth()`, not the transport.
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { clearSession, getStoredUser, getToken, post, setSession } from "@/lib/api";
import type { AuthResponse, Role, User } from "@/types";

interface AuthState {
  user: User | null;
  role: Role | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  signup: (email: string, password: string, fullName: string, role: Role) => Promise<User>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    // Rehydrate from localStorage on first paint so a refresh doesn't log out.
    if (getToken()) setUser(getStoredUser<User>());
    setLoading(false);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const result = await post<AuthResponse>("/auth/login", { email, password });
    setSession(result.token, result.user);
    setUser(result.user);
    return result.user;
  }, []);

  const signup = useCallback(
    async (email: string, password: string, fullName: string, role: Role) => {
      const result = await post<AuthResponse>("/auth/signup", {
        email,
        password,
        full_name: fullName,
        role,
      });
      setSession(result.token, result.user);
      setUser(result.user);
      return result.user;
    },
    [],
  );

  const logout = useCallback(() => {
    clearSession();
    setUser(null);
    router.push("/login");
  }, [router]);

  return (
    <AuthContext.Provider
      value={{ user, role: user?.role ?? null, loading, login, signup, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}

/** Where a role lands after login. Customers never see the internal shell. */
export function landingPathFor(role: Role): string {
  return role === "CUSTOMER" ? "/portal" : "/dashboard";
}
