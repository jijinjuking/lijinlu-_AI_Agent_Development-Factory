// ============================================================
// Multi-Tenant System 状态管理 (Zustand)
// ============================================================

import { create } from 'zustand';
import type { Tenant, TenantUser } from '../api/tenant';
import * as tenantApi from '../api/tenant';

interface TenantState {
  tenants: Tenant[];
  currentTenant: Tenant | null;
  users: TenantUser[];
  isLoading: boolean;

  loadTenants: () => Promise<void>;
  loadTenantDetail: (tenantId: string) => Promise<void>;
  createTenant: (data: Partial<Tenant>) => Promise<void>;
  updateTenant: (tenantId: string, data: Partial<Tenant>) => Promise<void>;
  deleteTenant: (tenantId: string) => Promise<void>;
  loadUsers: (tenantId: string) => Promise<void>;
  addUser: (tenantId: string, data: Partial<TenantUser>) => Promise<void>;
  removeUser: (tenantId: string, userId: string) => Promise<void>;
}

export const useTenantStore = create<TenantState>((set, get) => ({
  tenants: [],
  currentTenant: null,
  users: [],
  isLoading: false,

  loadTenants: async () => {
    set({ isLoading: true });
    try {
      const data = await tenantApi.fetchTenants();
      set({ tenants: data as Tenant[], isLoading: false });
    } catch (e) {
      console.error('Failed to load tenants:', e);
      set({ isLoading: false });
    }
  },

  loadTenantDetail: async (tenantId: string) => {
    set({ isLoading: true });
    try {
      const data = await tenantApi.fetchTenantDetail(tenantId);
      set({ currentTenant: data as Tenant, isLoading: false });
    } catch (e) {
      console.error('Failed to load tenant detail:', e);
      set({ isLoading: false });
    }
  },

  createTenant: async (data) => {
    try {
      const result = await tenantApi.createTenant(data as any);
      set((state) => ({ tenants: [...state.tenants, result as Tenant] }));
    } catch (e) {
      console.error('Failed to create tenant:', e);
    }
  },

  updateTenant: async (tenantId, data) => {
    try {
      await tenantApi.updateTenant(tenantId, data);
      set((state) => ({
        tenants: state.tenants.map((t) => (t.tenant_id === tenantId ? { ...t, ...data } : t)),
        currentTenant: state.currentTenant?.tenant_id === tenantId
          ? { ...state.currentTenant, ...data }
          : state.currentTenant,
      }));
    } catch (e) {
      console.error('Failed to update tenant:', e);
    }
  },

  deleteTenant: async (tenantId: string) => {
    try {
      await tenantApi.deleteTenant(tenantId);
      set((state) => ({
        tenants: state.tenants.filter((t) => t.tenant_id !== tenantId),
        currentTenant: state.currentTenant?.tenant_id === tenantId ? null : state.currentTenant,
      }));
    } catch (e) {
      console.error('Failed to delete tenant:', e);
    }
  },

  loadUsers: async (tenantId: string) => {
    set({ isLoading: true });
    try {
      const data = await tenantApi.fetchUsers(tenantId);
      set({ users: data as TenantUser[], isLoading: false });
    } catch (e) {
      console.error('Failed to load users:', e);
      set({ isLoading: false });
    }
  },

  addUser: async (tenantId, data) => {
    try {
      await tenantApi.addUser(tenantId, (data as any).email || '', (data as any).role || 'member');
      set((state) => ({ users: [...state.users, data as any as TenantUser] }));
    } catch (e) {
      console.error('Failed to add user:', e);
    }
  },

  removeUser: async (tenantId: string, userId: string) => {
    try {
      await tenantApi.removeUser(tenantId, userId);
      set((state) => ({
        users: state.users.filter((u) => u.user_id !== userId),
      }));
    } catch (e) {
      console.error('Failed to remove user:', e);
    }
  },
}));
