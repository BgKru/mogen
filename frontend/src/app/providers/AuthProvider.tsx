import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import {
  fetchCsrfToken,
  fetchCurrentUser,
  loginUser,
  logoutUser,
  registerUser,
} from "../../features/auth/api/authApi";
import { getCsrfToken, setCsrfToken } from "../../shared/api/client";
import { ApiError } from "../../shared/api/errors";
import { queryKeys } from "../../shared/api/queryKeys";
import type { LoginInput, RegisterInput, User } from "../../shared/types/api";
import { AuthContext, type AuthStatus } from "./auth-context";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const queryClient = useQueryClient();

  const clearSession = useCallback(() => {
    setCsrfToken(null);
    setUser(null);
    setStatus("unauthenticated");
    queryClient.removeQueries({ queryKey: queryKeys.currentUser });
  }, [queryClient]);

  useEffect(() => {
    let active = true;

    async function initialise() {
      try {
        const currentUser = await fetchCurrentUser();
        if (!active) {
          return;
        }
        try {
          const token = await fetchCsrfToken();
          if (active) {
            setCsrfToken(token);
          }
        } catch (error) {
          if (error instanceof ApiError && error.status === 401) {
            if (active) {
              clearSession();
            }
            return;
          }
        }
        if (active) {
          setUser(currentUser);
          setStatus("authenticated");
        }
      } catch {
        if (active) {
          clearSession();
        }
      }
    }

    void initialise();
    return () => {
      active = false;
    };
  }, [clearSession]);

  useEffect(() => {
    const handleUnauthorized = () => clearSession();
    window.addEventListener("auth:unauthorized", handleUnauthorized);
    return () => window.removeEventListener("auth:unauthorized", handleUnauthorized);
  }, [clearSession]);

  const startSession = useCallback(
    (currentUser: User) => {
      setUser(currentUser);
      setStatus("authenticated");
      queryClient.setQueryData(queryKeys.currentUser, currentUser);
    },
    [queryClient],
  );

  const login = useCallback(
    async (input: LoginInput) => {
      const currentUser = await loginUser(input);
      try {
        setCsrfToken(await fetchCsrfToken());
      } catch {
        setCsrfToken(null);
      }
      startSession(currentUser);
      return currentUser;
    },
    [startSession],
  );

  const register = useCallback(
    async (input: RegisterInput) => {
      const currentUser = await registerUser(input);
      try {
        setCsrfToken(await fetchCsrfToken());
      } catch {
        setCsrfToken(null);
      }
      startSession(currentUser);
      return currentUser;
    },
    [startSession],
  );

  const logout = useCallback(async () => {
    try {
      if (!getCsrfToken()) {
        try {
          setCsrfToken(await fetchCsrfToken());
        } catch {
          // Continue: logout still clears the local state below.
        }
      }
      await logoutUser();
    } finally {
      clearSession();
      queryClient.clear();
    }
  }, [clearSession, queryClient]);

  const value = useMemo(
    () => ({
      user,
      status,
      isAuthenticated: status === "authenticated",
      login,
      register,
      logout,
    }),
    [login, logout, register, status, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
