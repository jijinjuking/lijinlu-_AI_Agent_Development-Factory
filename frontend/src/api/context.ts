// ============================================================
// context API — Context Engine 接口
// ============================================================
import { http } from './http';

export interface ContextStats {
  vector_store_count: number;
  cache: {
    total_entries: number;
    max_entries: number;
    total_hits: number;
    default_ttl_sec: number;
  };
  embedding_dim: number;
  max_context_tokens: number;
}

export interface IndexEntry {
  id: string;
  source_type: string;
  source_id: string | null;
  title: string;
  chunk_count: number;
  token_count: number;
  status: string;
  created_at: string | null;
}

export interface SearchResult {
  id: string;
  text: string;
  metadata: Record<string, unknown>;
  score: number;
}

export interface SearchResponse {
  status: string;
  query: string;
  results: SearchResult[];
  count: number;
}

export interface BuildResponse {
  status: string;
  context: string;
  sources: SearchResult[];
  token_count: number;
  cache_hit: boolean;
  retrieval_count: number;
}

export interface InjectResponse {
  status: string;
  injected_context: string;
  has_context: boolean;
}

export interface IndexResponse {
  status: string;
  indexed_chunks: number;
  vector_ids: string[];
  content_hash: string;
}

// ---- API 函数 ----

/** 获取引擎统计 */
export async function fetchStats(): Promise<ContextStats> {
  return http.get<ContextStats>('/context/stats');
}

/** 语义搜索 */
export async function semanticSearch(query: string, topK = 5): Promise<SearchResponse> {
  return http.post<SearchResponse>('/context/search', { query, top_k: topK });
}

/** 构建上下文 */
export async function buildContext(
  query: string,
  tokenBudget = 2000,
  useCache = true,
): Promise<BuildResponse> {
  return http.post<BuildResponse>('/context/build', {
    query,
    token_budget: tokenBudget,
    use_cache: useCache,
  });
}

/** 注入上下文 */
export async function injectContext(query: string, tokenBudget = 2000): Promise<InjectResponse> {
  return http.post<InjectResponse>('/context/inject', { query, token_budget: tokenBudget });
}

/** 索引文本 */
export async function indexText(text: string, metadata = {}): Promise<IndexResponse> {
  return http.post<IndexResponse>('/context/index', { text, metadata });
}

/** 批量索引 */
export async function indexBatch(documents: Record<string, unknown>[]): Promise<{ status: string; indexed_docs: number; total_chunks: number; vector_ids: string[] }> {
  return http.post('/context/index/batch', { documents });
}

/** 缓存统计 */
export async function cacheStats(): Promise<ContextStats['cache']> {
  return http.get<ContextStats['cache']>('/context/cache/stats');
}

/** 清空缓存 */
export async function clearCache(): Promise<{ status: string; message: string }> {
  return http.post('/context/cache/clear');
}

/** 清空索引 */
export async function clearIndex(): Promise<{ status: string; message: string }> {
  return http.post('/context/index/clear');
}

/** 索引条目列表 */
export async function listIndexEntries(sourceType?: string): Promise<{ entries: IndexEntry[]; total: number }> {
  const params = sourceType ? { source_type: sourceType } : undefined;
  return http.get('/context/index/list', params);
}

/** 删除索引条目 */
export async function deleteIndexEntry(id: string): Promise<{ status: string; message: string }> {
  return http.delete(`/context/index/${id}`);
}
