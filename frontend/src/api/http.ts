// ============================================================
// http — 统一请求客户端（axios 替代，零依赖）
// ============================================================

const BASE = '/api/v1';

/**
 * 从 localStorage 读取 access_token，
 * 返回 Bearer 认证请求头（如未登录返回空对象）。
 */
function getAuthHeader(): Record<string, string> {
  const token = localStorage.getItem('access_token');
  if (token) {
    return { Authorization: `Bearer ${token}` };
  }
  return {};
}

/** 通用请求方法 */
async function request<T>(
  path: string,
  options?: RequestInit & { params?: Record<string, string | number | undefined> }
): Promise<T> {
  let url = `${BASE}${path}`;

  // 拼接 query string
  if (options?.params) {
    const qs = Object.entries(options.params)
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join('&');
    if (qs) url += `?${qs}`;
  }

  const { params, ...init } = options ?? {};

  // 合并默认 headers 与认证头
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...getAuthHeader(),
    ...((init.headers as Record<string, string>) ?? {}),
  };

  const res = await fetch(url, {
    ...init,
    headers,
  });

  if (!res.ok) {
    const body = await res.text().catch(() => '');
    // 优先取后端 {"detail": "..."} / {"message": "..."}，避免把原始 JSON 直接抛给用户
    let msg = body || res.statusText;
    try {
      const parsed = JSON.parse(body);
      if (typeof parsed?.detail === 'string') {
        msg = parsed.detail;
      } else if (Array.isArray(parsed?.detail)) {
        msg = parsed.detail.map((d: any) => d?.msg ?? JSON.stringify(d)).join('；');
      } else if (typeof parsed?.message === 'string') {
        msg = parsed.message;
      }
    } catch {
      /* 非 JSON 响应，保留原文 */
    }
    // 将 HTTP 状态码挂到错误对象上，方便调用方区分 401/403/500
    const err: any = new Error(msg);
    err.status = res.status;
    err.detail = msg;
    throw err;
  }

  return res.json();
}

/** CRUD 快捷方法 */
export const http = {
  get: <T>(path: string, params?: Record<string, string | number | undefined>) =>
    request<T>(path, { method: 'GET', params }),

  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    }),

  put: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'PUT',
      body: body ? JSON.stringify(body) : undefined,
    }),

  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'PATCH',
      body: body ? JSON.stringify(body) : undefined,
    }),

  delete: <T>(path: string) =>
    request<T>(path, { method: 'DELETE' }),

  /** 上传文件（multipart/form-data，不设 Content-Type 让浏览器自动加 boundary） */
  upload: <T>(path: string, formData: FormData) => {
    const headers: Record<string, string> = getAuthHeader();
    return fetch(`${BASE}${path}`, {
      method: 'POST',
      headers,
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const body = await res.text().catch(() => '');
        const err: any = new Error(`Upload ${res.status}: ${body || res.statusText}`);
        err.status = res.status;
        throw err;
      }
      return res.json() as Promise<T>;
    });
  },
};

// Named exports（供 runtime.ts 等文件使用）
export const get = http.get;
export const post = http.post;
export const put = http.put;
export const patch = http.patch;
export const del = http['delete'];
