// ============================================================
// K8s Scheduler 状态管理 (Zustand)
// ============================================================

import { create } from 'zustand';
import type { K8sJob, K8sCluster } from '../api/k8s';
import * as k8sApi from '../api/k8s';

interface K8sState {
  jobs: K8sJob[];
  clusters: K8sCluster[];
  currentJob: K8sJob | null;
  isLoading: boolean;

  loadJobs: () => Promise<void>;
  loadClusters: () => Promise<void>;
  loadJobDetail: (jobId: string) => Promise<void>;
  submitJob: (data: { task_id: string; template?: string; config?: Record<string, unknown> }) => Promise<void>;
  cancelJob: (jobId: string) => Promise<void>;
  deleteJob: (jobId: string) => Promise<void>;
  setCurrentJob: (job: K8sJob | null) => void;
}

export const useK8sStore = create<K8sState>((set, get) => ({
  jobs: [],
  clusters: [],
  currentJob: null,
  isLoading: false,

  loadJobs: async () => {
    set({ isLoading: true });
    try {
      const data = await k8sApi.fetchJobs();
      set({ jobs: data as any as K8sJob[], isLoading: false });
    } catch (e) {
      console.error('Failed to load K8s jobs:', e);
      set({ isLoading: false });
    }
  },

  loadClusters: async () => {
    try {
      const data = await k8sApi.fetchClusters();
      set({ clusters: data as K8sCluster[] });
    } catch (e) {
      console.error('Failed to load clusters:', e);
    }
  },

  loadJobDetail: async (jobId: string) => {
    set({ isLoading: true });
    try {
      const data = await k8sApi.fetchJobDetail(jobId);
      set({ currentJob: data as K8sJob, isLoading: false });
    } catch (e) {
      console.error('Failed to load job detail:', e);
      set({ isLoading: false });
    }
  },

  submitJob: async (data) => {
    try {
      const result = await k8sApi.submitJob(data as any);
      set((state) => ({ jobs: [...state.jobs, result as K8sJob] }));
    } catch (e) {
      console.error('Failed to submit job:', e);
    }
  },

  cancelJob: async (jobId: string) => {
    try {
      await k8sApi.cancelJob(jobId);
      set((state) => ({
        jobs: state.jobs.map((j) => (j.job_id === jobId ? { ...j, status: 'canceled' as K8sJob['status'] } : j)),
      }));
    } catch (e) {
      console.error('Failed to cancel job:', e);
    }
  },

  deleteJob: async (jobId: string) => {
    try {
      await k8sApi.deleteJob(jobId);
      set((state) => ({
        jobs: state.jobs.filter((j) => j.job_id !== jobId),
        currentJob: state.currentJob?.job_id === jobId ? null : state.currentJob,
      }));
    } catch (e) {
      console.error('Failed to delete job:', e);
    }
  },

  setCurrentJob: (job) => set({ currentJob: job }),
}));
