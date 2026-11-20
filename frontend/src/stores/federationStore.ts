// ============================================================
// Runtime Federation 状态管理 (Zustand)
// ============================================================

import { create } from 'zustand';
import type { FederationMember, SyncStatus } from '../api/federation';
import * as federationApi from '../api/federation';

interface FederationState {
  members: FederationMember[];
  syncStatus: SyncStatus | null;
  isLoading: boolean;
  selectedMemberId: string | null;

  loadMembers: () => Promise<void>;
  loadSyncStatus: () => Promise<void>;
  addMember: (data: Partial<FederationMember>) => Promise<void>;
  removeMember: (memberId: string) => Promise<void>;
  syncNow: () => Promise<void>;
  selectMember: (memberId: string | null) => void;
}

export const useFederationStore = create<FederationState>((set, get) => ({
  members: [],
  syncStatus: null,
  isLoading: false,
  selectedMemberId: null,

  loadMembers: async () => {
    set({ isLoading: true });
    try {
      const data = await federationApi.fetchMembers();
      set({ members: data as FederationMember[], isLoading: false });
    } catch (e) {
      console.error('Failed to load federation members:', e);
      set({ isLoading: false });
    }
  },

  loadSyncStatus: async () => {
    try {
      const data = await federationApi.fetchSyncStatus();
      set({ syncStatus: data as unknown as SyncStatus });
    } catch (e) {
      console.error('Failed to load sync status:', e);
    }
  },

  addMember: async (data) => {
    try {
      const result = await federationApi.addMember(data as any);
      set((state) => ({ members: [...state.members, result as FederationMember] }));
    } catch (e) {
      console.error('Failed to add member:', e);
    }
  },

  removeMember: async (memberId: string) => {
    try {
      await federationApi.removeMember(memberId);
      set((state) => ({
        members: state.members.filter((m) => m.member_id !== memberId),
        selectedMemberId: state.selectedMemberId === memberId ? null : state.selectedMemberId,
      }));
    } catch (e) {
      console.error('Failed to remove member:', e);
    }
  },

  syncNow: async () => {
    try {
      await federationApi.syncNow();
      await get().loadSyncStatus();
    } catch (e) {
      console.error('Failed to sync:', e);
    }
  },

  selectMember: (memberId) => set({ selectedMemberId: memberId }),
}));
