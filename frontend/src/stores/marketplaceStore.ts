// ============================================================
// AI Marketplace 状态管理 (Zustand)
// ============================================================

import { create } from 'zustand';
import type { MarketplacePackage, Rating } from '../api/marketplace';
import * as marketplaceApi from '../api/marketplace';

interface MarketplaceState {
  packages: MarketplacePackage[];
  currentPackage: MarketplacePackage | null;
  ratings: Rating[];
  isLoading: boolean;
  searchQuery: string;
  selectedCategory: string;

  loadPackages: () => Promise<void>;
  loadPackageDetail: (packageId: string) => Promise<void>;
  installPackage: (packageId: string) => Promise<void>;
  uninstallPackage: (packageId: string) => Promise<void>;
  searchPackages: (query: string) => Promise<void>;
  submitRating: (packageId: string, score: number, comment: string) => Promise<void>;
  setSearchQuery: (query: string) => void;
  setSelectedCategory: (category: string) => void;
}

export const useMarketplaceStore = create<MarketplaceState>((set, get) => ({
  packages: [],
  currentPackage: null,
  ratings: [],
  isLoading: false,
  searchQuery: '',
  selectedCategory: 'all',

  loadPackages: async () => {
    set({ isLoading: true });
    try {
      const data = await marketplaceApi.fetchPackages();
      set({ packages: data as MarketplacePackage[], isLoading: false });
    } catch (e) {
      console.error('Failed to load packages:', e);
      set({ isLoading: false });
    }
  },

  loadPackageDetail: async (packageId: string) => {
    set({ isLoading: true });
    try {
      const data = await marketplaceApi.fetchPackageDetail(packageId);
      set({ currentPackage: data as MarketplacePackage, isLoading: false });
    } catch (e) {
      console.error('Failed to load package detail:', e);
      set({ isLoading: false });
    }
  },

  installPackage: async (packageId: string) => {
    try {
      await marketplaceApi.installPackage(packageId);
      await get().loadPackages();
    } catch (e) {
      console.error('Failed to install package:', e);
    }
  },

  uninstallPackage: async (packageId: string) => {
    try {
      await marketplaceApi.uninstallPackage(packageId);
      await get().loadPackages();
    } catch (e) {
      console.error('Failed to uninstall package:', e);
    }
  },

  searchPackages: async (query: string) => {
    set({ isLoading: true });
    try {
      const data = await marketplaceApi.searchPackages(query);
      set({ packages: data as MarketplacePackage[], isLoading: false });
    } catch (e) {
      console.error('Failed to search packages:', e);
      set({ isLoading: false });
    }
  },

  submitRating: async (packageId, score, comment) => {
    try {
      await marketplaceApi.submitRating(packageId, score, comment);
      await get().loadPackageDetail(packageId);
    } catch (e) {
      console.error('Failed to submit rating:', e);
    }
  },

  setSearchQuery: (query) => set({ searchQuery: query }),
  setSelectedCategory: (category) => set({ selectedCategory: category }),
}));
