// ============================================================
// Projects 状态管理 (Zustand)
// ============================================================

import { create } from 'zustand';
import type { Project, Issue } from '../api/projects';
import type { IssueComment } from '../api/issues';
import * as projectsApi from '../api/projects';

interface ProjectsState {
  projects: Project[];
  currentProject: Project | null;
  issues: Issue[];
  currentIssue: Issue | null;
  comments: IssueComment[];
  activeTab: 'projects' | 'issues';
  isLoading: boolean;

  loadProjects: () => Promise<void>;
  loadProjectDetail: (projectId: string) => Promise<void>;
  createProject: (data: Partial<Project>) => Promise<void>;
  updateProject: (projectId: string, data: Partial<Project>) => Promise<void>;
  deleteProject: (projectId: string) => Promise<void>;

  loadIssues: (projectId?: string) => Promise<void>;
  loadIssueDetail: (issueId: string) => Promise<void>;
  createIssue: (data: Partial<Issue>) => Promise<void>;
  updateIssue: (issueId: string, data: Partial<Issue>) => Promise<void>;
  deleteIssue: (issueId: string) => Promise<void>;

  loadComments: (issueId: string) => Promise<void>;
  addComment: (issueId: string, content: string) => Promise<void>;

  setActiveTab: (tab: 'projects' | 'issues') => void;
  setCurrentProject: (project: Project | null) => void;
  setCurrentIssue: (issue: Issue | null) => void;
}

export const useProjectsStore = create<ProjectsState>((set, get) => ({
  projects: [],
  currentProject: null,
  issues: [],
  currentIssue: null,
  comments: [],
  activeTab: 'projects',
  isLoading: false,

  loadProjects: async () => {
    set({ isLoading: true });
    try {
      const data = await projectsApi.fetchProjects();
      set({ projects: data as Project[], isLoading: false });
    } catch (e) {
      console.error('Failed to load projects:', e);
      set({ isLoading: false });
    }
  },

  loadProjectDetail: async (projectId: string) => {
    set({ isLoading: true });
    try {
      const data = await projectsApi.fetchProject(projectId);
      set({ currentProject: data as Project, isLoading: false });
    } catch (e) {
      console.error('Failed to load project detail:', e);
      set({ isLoading: false });
    }
  },

  createProject: async (data) => {
    try {
      const result = await projectsApi.createProject(data as any);
      set((state) => ({ projects: [...state.projects, result as Project] }));
    } catch (e) {
      console.error('Failed to create project:', e);
    }
  },

  updateProject: async (projectId, data) => {
    try {
      await projectsApi.updateProject(projectId, data);
      set((state) => ({
        projects: state.projects.map((p) => (p.id === projectId ? { ...p, ...data } : p)),
        currentProject: state.currentProject?.id === projectId
          ? { ...state.currentProject, ...data }
          : state.currentProject,
      }));
    } catch (e) {
      console.error('Failed to update project:', e);
    }
  },

  deleteProject: async (projectId) => {
    try {
      await projectsApi.deleteProject(projectId);
      set((state) => ({
        projects: state.projects.filter((p) => p.id !== projectId),
        currentProject: state.currentProject?.id === projectId ? null : state.currentProject,
      }));
    } catch (e) {
      console.error('Failed to delete project:', e);
    }
  },

  loadIssues: async (projectId?) => {
    set({ isLoading: true });
    try {
      const data = await projectsApi.fetchIssues(projectId || '');
      set({ issues: data as Issue[], isLoading: false });
    } catch (e) {
      console.error('Failed to load issues:', e);
      set({ isLoading: false });
    }
  },

  loadIssueDetail: async (issueId: string) => {
    set({ isLoading: true });
    try {
      const data = await projectsApi.fetchIssue(issueId);
      set({ currentIssue: data as Issue, isLoading: false });
    } catch (e) {
      console.error('Failed to load issue detail:', e);
      set({ isLoading: false });
    }
  },

  createIssue: async (data) => {
    try {
      const result = await projectsApi.createIssue('', data as any);
      set((state) => ({ issues: [...state.issues, result as Issue] }));
    } catch (e) {
      console.error('Failed to create issue:', e);
    }
  },

  updateIssue: async (issueId, data) => {
    try {
      await projectsApi.updateIssue(issueId, data);
      set((state) => ({
        issues: state.issues.map((i) => (i.id === issueId ? { ...i, ...data } : i)),
        currentIssue: state.currentIssue?.id === issueId
          ? { ...state.currentIssue, ...data }
          : state.currentIssue,
      }));
    } catch (e) {
      console.error('Failed to update issue:', e);
    }
  },

  deleteIssue: async (issueId) => {
    try {
      await projectsApi.deleteIssue(issueId);
      set((state) => ({
        issues: state.issues.filter((i) => i.id !== issueId),
        currentIssue: state.currentIssue?.id === issueId ? null : state.currentIssue,
      }));
    } catch (e) {
      console.error('Failed to delete issue:', e);
    }
  },

  loadComments: async (issueId: string) => {
    try {
      const data = await projectsApi.fetchComments(issueId);
      set({ comments: data as unknown as IssueComment[] });
    } catch (e) {
      console.error('Failed to load comments:', e);
    }
  },

  addComment: async (issueId, content) => {
    try {
      const result = await projectsApi.createComment(issueId, content);
      set((state) => ({ comments: [...state.comments, result as unknown as IssueComment] }));
    } catch (e) {
      console.error('Failed to add comment:', e);
    }
  },

  setActiveTab: (tab) => set({ activeTab: tab }),
  setCurrentProject: (project) => set({ currentProject: project }),
  setCurrentIssue: (issue) => set({ currentIssue: issue }),
}));
