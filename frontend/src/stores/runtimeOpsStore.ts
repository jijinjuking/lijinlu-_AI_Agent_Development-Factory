// ============================================================
// Runtime Ops 状态管理 (Zustand)
// ============================================================

import { create } from 'zustand';
import type {
  WorkerInfo, SchedulerQueueStatus, SchedulerConfig,
  ModelInfo, ModelRouterConfig,
  SandboxInfo, LoopDetectorStatus, PolicyRule, AuditLogEntry,
} from '../api/runtime';
import * as runtimeApi from '../api/runtime';

interface RuntimeOpsState {
  // Scheduler
  workers: WorkerInfo[];
  schedulerStatus: SchedulerQueueStatus | null;
  schedulerConfig: SchedulerConfig | null;
  // Model Router
  models: ModelInfo[];
  modelRouterConfig: ModelRouterConfig | null;
  // Sandbox
  sandboxes: SandboxInfo[];
  // Loop Detector
  loopStatuses: LoopDetectorStatus[];
  // Policy Engine
  policyRules: PolicyRule[];
  auditLogs: AuditLogEntry[];

  isLoading: boolean;
  activeTab: string;

  // Actions
  loadAll: () => Promise<void>;
  setActiveTab: (tab: string) => void;

  // Scheduler actions
  pauseScheduler: () => Promise<void>;
  resumeScheduler: () => Promise<void>;
  updateSchedulerConfig: (data: Partial<SchedulerConfig>) => Promise<void>;

  // Model Router actions
  enableModel: (modelId: string) => Promise<void>;
  disableModel: (modelId: string) => Promise<void>;
  updateModelRouterConfig: (data: Partial<ModelRouterConfig>) => Promise<void>;

  // Sandbox actions
  createSandbox: (sandboxType: string) => Promise<void>;
  destroySandbox: (sandboxId: string) => Promise<void>;
  destroyAllSandboxes: () => Promise<void>;

  // Loop Detector actions
  resetLoop: (taskId: string) => Promise<void>;

  // Policy Engine actions
  createPolicyRule: (data: Omit<PolicyRule, 'rule_id'>) => Promise<void>;
  updatePolicyRule: (ruleId: string, data: Partial<PolicyRule>) => Promise<void>;
  deletePolicyRule: (ruleId: string) => Promise<void>;
}

export const useRuntimeOpsStore = create<RuntimeOpsState>((set, get) => ({
  workers: [],
  schedulerStatus: null,
  schedulerConfig: null,
  models: [],
  modelRouterConfig: null,
  sandboxes: [],
  loopStatuses: [],
  policyRules: [],
  auditLogs: [],
  isLoading: false,
  activeTab: 'scheduler',

  loadAll: async () => {
    set({ isLoading: true });
    try {
      const [workers, schedulerStatus, models, sandboxes, loopStatuses, rules, logs] = await Promise.all([
        runtimeApi.fetchWorkers().catch(() => []),
        runtimeApi.fetchSchedulerStatus().catch(() => null),
        runtimeApi.fetchModels().catch(() => []),
        runtimeApi.fetchSandboxes().catch(() => []),
        runtimeApi.fetchAllLoopStatuses().catch(() => []),
        runtimeApi.fetchPolicyRules().catch(() => []),
        runtimeApi.fetchAuditLogs().catch(() => []),
      ]);
      set({
        workers, schedulerStatus,
        models, sandboxes, loopStatuses, policyRules: rules, auditLogs: logs,
        isLoading: false,
      });
    } catch (e) {
      console.error('Failed to load runtime ops data:', e);
      set({ isLoading: false });
    }
  },

  setActiveTab: (tab) => set({ activeTab: tab }),

  pauseScheduler: async () => {
    await runtimeApi.pauseScheduler();
    await get().loadAll();
  },

  resumeScheduler: async () => {
    await runtimeApi.resumeScheduler();
    await get().loadAll();
  },

  updateSchedulerConfig: async (data) => {
    await runtimeApi.updateSchedulerConfig(data);
    await get().loadAll();
  },

  enableModel: async (modelId) => {
    await runtimeApi.enableModel(modelId);
    await get().loadAll();
  },

  disableModel: async (modelId) => {
    await runtimeApi.disableModel(modelId);
    await get().loadAll();
  },

  updateModelRouterConfig: async (data) => {
    await runtimeApi.updateModelRouterConfig(data);
    await get().loadAll();
  },

  createSandbox: async (sandboxType) => {
    await runtimeApi.createSandbox({ sandbox_type: sandboxType as 'docker' | 'browser' | 'python' });
    await get().loadAll();
  },

  destroySandbox: async (sandboxId) => {
    await runtimeApi.destroySandbox(sandboxId);
    await get().loadAll();
  },

  destroyAllSandboxes: async () => {
    await runtimeApi.destroyAllSandboxes();
    await get().loadAll();
  },

  resetLoop: async (taskId) => {
    await runtimeApi.resetLoop(taskId);
    await get().loadAll();
  },

  createPolicyRule: async (data) => {
    await runtimeApi.createPolicyRule(data);
    await get().loadAll();
  },

  updatePolicyRule: async (ruleId, data) => {
    await runtimeApi.updatePolicyRule(ruleId, data);
    await get().loadAll();
  },

  deletePolicyRule: async (ruleId) => {
    await runtimeApi.deletePolicyRule(ruleId);
    await get().loadAll();
  },
}));
