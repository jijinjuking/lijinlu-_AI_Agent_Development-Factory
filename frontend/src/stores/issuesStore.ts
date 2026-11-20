/**
 * Issues 状态管理 (Zustand)
 *
 * 独立的跨项目 Issue Store，提供：
 * - 列表视图（筛选 by project/status/priority）
 * - 详情视图（含任务树、评论）
 * - 分解 / 派发操作
 */
import { create } from 'zustand';
import type { Issue, IssueComment, TaskTreeNode, Attachment } from '../api/issues';
import * as issuesApi from '../api/issues';

interface IssueFilters {
  projectId: string;
  status: string;
  priority: string;
}

interface IssuesState {
  // Data
  issues: Issue[];
  currentIssue: Issue | null;
  taskTree: TaskTreeNode[];
  comments: IssueComment[];
  attachments: Attachment[];
  filters: IssueFilters;
  isLoading: boolean;
  error: string | null;

  // Actions — 列表
  loadIssues: (params?: { project_id?: string; status?: string; priority?: string }) => Promise<void>;
  createIssue: (data: {
    project_id: string;
    title: string;
    description?: string;
    priority?: string;
  }) => Promise<Issue | null>;
  updateIssue: (issueId: string, data: Partial<Issue>) => Promise<void>;
  deleteIssue: (issueId: string) => Promise<void>;
  setFilters: (filters: Partial<IssueFilters>) => void;

  // Actions — 详情
  loadIssueDetail: (issueId: string) => Promise<void>;
  loadTaskTree: (issueId: string) => Promise<void>;
  decomposeIssue: (issueId: string, strategy?: string) => Promise<void>;
  dispatchIssue: (issueId: string) => Promise<void>;

  // Actions — 评论
  loadComments: (issueId: string) => Promise<void>;
  addComment: (issueId: string, content: string) => Promise<void>;

  // Actions — 附件
  loadAttachments: (issueId: string) => Promise<void>;
  uploadAttachment: (issueId: string, file: File) => Promise<void>;
  deleteAttachment: (issueId: string, attachmentId: string) => Promise<void>;
}

export const useIssuesStore = create<IssuesState>((set, get) => ({
  issues: [],
  currentIssue: null,
  taskTree: [],
  comments: [],
  attachments: [],
  filters: { projectId: '', status: '', priority: '' },
  isLoading: false,
  error: null,

  // ===== 列表 =====

  loadIssues: async (params?) => {
    set({ isLoading: true, error: null });
    try {
      const data = await issuesApi.fetchIssues({
        project_id: params?.project_id ?? (get().filters.projectId || undefined),
        status: (params?.status || get().filters.status || undefined) as Issue['status'],
        priority: (params?.priority || get().filters.priority || undefined) as Issue['priority'],
      });
      set({ issues: data, isLoading: false });
    } catch (e) {
      console.error('Failed to load issues:', e);
      set({ error: String(e), isLoading: false });
    }
  },

  createIssue: async (data) => {
    try {
      const result = await issuesApi.createIssue(data as any);
      set((state) => ({ issues: [result, ...state.issues] }));
      return result;
    } catch (e) {
      console.error('Failed to create issue:', e);
      set({ error: String(e) });
      return null;
    }
  },

  updateIssue: async (issueId, data) => {
    try {
      const updated = await issuesApi.updateIssue(issueId, data);
      set((state) => ({
        issues: state.issues.map((i) => (i.issue_id === issueId ? updated : i)),
        currentIssue: state.currentIssue?.issue_id === issueId ? updated : state.currentIssue,
      }));
    } catch (e) {
      console.error('Failed to update issue:', e);
      set({ error: String(e) });
    }
  },

  deleteIssue: async (issueId) => {
    try {
      await issuesApi.deleteIssue(issueId);
      set((state) => ({
        issues: state.issues.filter((i) => i.issue_id !== issueId),
        currentIssue: state.currentIssue?.issue_id === issueId ? null : state.currentIssue,
      }));
    } catch (e) {
      console.error('Failed to delete issue:', e);
      set({ error: String(e) });
    }
  },

  setFilters: (filters) => set((state) => ({ filters: { ...state.filters, ...filters } })),

  // ===== 详情 =====

  loadIssueDetail: async (issueId) => {
    set({ isLoading: true, error: null });
    try {
      const [issue, tree] = await Promise.all([
        issuesApi.fetchIssue(issueId),
        issuesApi.fetchTaskTree(issueId).catch(() => [] as TaskTreeNode[]),
      ]);
      set({ currentIssue: issue, taskTree: tree, isLoading: false });
    } catch (e) {
      console.error('Failed to load issue detail:', e);
      set({ error: String(e), isLoading: false });
    }
  },

  loadTaskTree: async (issueId) => {
    try {
      const tree = await issuesApi.fetchTaskTree(issueId);
      set({ taskTree: tree });
    } catch (e) {
      console.error('Failed to load task tree:', e);
    }
  },

  decomposeIssue: async (issueId, strategy?) => {
    set({ isLoading: true });
    try {
      const result = await issuesApi.decomposeIssue(
        issueId,
        (strategy || 'hybrid') as issuesApi.DecompositionStrategy,
      );
      set({ currentIssue: result.issue, isLoading: false });
      // 分解后重新加载任务树
      const tree = await issuesApi.fetchTaskTree(issueId).catch(() => [] as issuesApi.TaskTreeNode[]);
      set({ taskTree: tree });
    } catch (e) {
      console.error('Failed to decompose issue:', e);
      set({ error: String(e), isLoading: false });
    }
  },

  dispatchIssue: async (issueId) => {
    set({ isLoading: true });
    try {
      await issuesApi.dispatchIssue(issueId);
      set({ isLoading: false });
      // 派发后重新加载详情
      await get().loadIssueDetail(issueId);
    } catch (e) {
      console.error('Failed to dispatch issue:', e);
      set({ error: String(e), isLoading: false });
    }
  },

  // ===== 评论 =====

  loadComments: async (issueId) => {
    try {
      const data = await issuesApi.fetchComments(issueId);
      set({ comments: data as unknown as IssueComment[] });
    } catch (e) {
      console.error('Failed to load comments:', e);
    }
  },

  addComment: async (issueId, content) => {
    try {
      const result = await issuesApi.addComment(issueId, content);
      set((state) => ({ comments: [...state.comments, result as unknown as IssueComment] }));
    } catch (e) {
      console.error('Failed to add comment:', e);
    }
  },

  // ===== 附件 =====

  loadAttachments: async (issueId) => {
    try {
      const data = await issuesApi.fetchAttachments(issueId);
      set({ attachments: data });
    } catch (e) {
      console.error('Failed to load attachments:', e);
    }
  },

  uploadAttachment: async (issueId, file) => {
    try {
      await issuesApi.uploadAttachment(issueId, file);
      // 刷新附件列表
      await get().loadAttachments(issueId);
    } catch (e) {
      console.error('Failed to upload attachment:', e);
      throw e;
    }
  },

  deleteAttachment: async (issueId, attachmentId) => {
    try {
      await issuesApi.deleteAttachment(issueId, attachmentId);
      set((state) => ({
        attachments: state.attachments.filter((a) => a.id !== attachmentId),
      }));
    } catch (e) {
      console.error('Failed to delete attachment:', e);
    }
  },
}));
