// ============================================================
// auth — 认证相关 API
// ============================================================

import { http } from './http';

/** 注册请求体 */
export interface RegisterReq {
  username: string;
  password: string;
  email?: string;
  display_name?: string;
}

/** 登录请求体 */
export interface LoginReq {
  username: string;
  password: string;
}

/** 刷新 Token 请求体 */
export interface RefreshReq {
  refresh_token: string;
}

/** Token 响应 */
export interface TokenResp {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

/** 当前登录用户信息 */
export interface CurrentUser {
  id: string;
  username: string;
  email: string | null;
  display_name: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

/** 注册 */
export async function register(req: RegisterReq): Promise<TokenResp> {
  return http.post<TokenResp>('/auth/register', req);
}

/** 登录 */
export async function login(req: LoginReq): Promise<TokenResp> {
  return http.post<TokenResp>('/auth/login', req);
}

/** 刷新 access_token */
export async function refreshToken(req: RefreshReq): Promise<TokenResp> {
  return http.post<TokenResp>('/auth/refresh', req);
}

/** 获取当前登录用户信息 */
export async function getMe(): Promise<CurrentUser> {
  return http.get<CurrentUser>('/auth/me');
}
