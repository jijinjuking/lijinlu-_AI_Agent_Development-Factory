// ============================================================
// AuthContext — 全局认证状态管理
// ============================================================

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { ReactNode } from 'react';
import type { CurrentUser, TokenResp } from '../api/auth';
import * as authApi from '../api/auth';

/** 认证 State */
interface AuthState {
  user: CurrentUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

/** AuthContext 暴露的方法 */
interface AuthContextValue extends AuthState {
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string, email?: string, displayName?: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** 从 localStorage 读取存储的 token 信息 */
function loadStoredAuth(): { accessToken: string | null; refreshToken: string | null; user: CurrentUser | null } {
  try {
    const accessToken = localStorage.getItem('access_token');
    const refreshToken = localStorage.getItem('refresh_token');
    const userStr = localStorage.getItem('auth_user');
    const user = userStr ? JSON.parse(userStr) : null;
    return { accessToken, refreshToken, user };
  } catch {
    return { accessToken: null, refreshToken: null, user: null };
  }
}

/** AuthProvider 包裹组件 */
export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const stored = loadStoredAuth();
  const [user, setUser] = useState<CurrentUser | null>(stored.user);
  const [isAuthenticated, setIsAuthenticated] = useState(!!stored.accessToken);
  const [isLoading, setIsLoading] = useState(!!stored.accessToken); // 有 token 时需要校验，设为 loading

  /** 登录 */
  const login = useCallback(async (username: string, password: string) => {
    setIsLoading(true);
    try {
      const data: TokenResp = await authApi.login({ username, password });
      localStorage.setItem('access_token', data.access_token);
      localStorage.setItem('refresh_token', data.refresh_token);

      // 获取用户信息
      const me = await authApi.getMe();
      localStorage.setItem('auth_user', JSON.stringify(me));
      setUser(me);
      setIsAuthenticated(true);
    } finally {
      setIsLoading(false);
    }
  }, []);

  /** 注册 */
  const register = useCallback(async (username: string, password: string, email?: string, displayName?: string) => {
    setIsLoading(true);
    try {
      const data: TokenResp = await authApi.register({
        username,
        password,
        email,
        display_name: displayName,
      });
      localStorage.setItem('access_token', data.access_token);
      localStorage.setItem('refresh_token', data.refresh_token);

      const me = await authApi.getMe();
      localStorage.setItem('auth_user', JSON.stringify(me));
      setUser(me);
      setIsAuthenticated(true);
    } finally {
      setIsLoading(false);
    }
  }, []);

  /** 登出 */
  const logout = useCallback(() => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('auth_user');
    setUser(null);
    setIsAuthenticated(false);
  }, []);

  /**
   * 初始化：如果有 token，尝试获取用户信息以验证 token 是否有效
   */
  useEffect(() => {
    let cancelled = false;

    async function bootstrapAuth() {
      const token = localStorage.getItem('access_token');
      if (!token) {
        setIsLoading(false);
        return;
      }
      try {
        const me = await authApi.getMe();
        if (!cancelled) {
          localStorage.setItem('auth_user', JSON.stringify(me));
          setUser(me);
          setIsAuthenticated(true);
        }
      } catch {
        // token 无效，清除
        if (!cancelled) {
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
          localStorage.removeItem('auth_user');
          setUser(null);
          setIsAuthenticated(false);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    if (stored.accessToken) {
      bootstrapAuth();
    } else {
      setIsLoading(false);
    }

    return () => { cancelled = true; };
  }, []);

  const value: AuthContextValue = {
    user,
    isAuthenticated,
    isLoading,
    login,
    register,
    logout,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};

/** 获取 AuthContext 的 hook */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}
