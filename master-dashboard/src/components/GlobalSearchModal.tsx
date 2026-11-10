import React, { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Search, X, MessageSquare, CreditCard, ShoppingBag, AlertTriangle, ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { Button } from './ui';

interface SearchResult {
  id: string;
  type: 'refund' | 'order' | 'conversation' | 'escalation';
  title: string;
  subtitle: string;
  path: string;
}

interface GlobalSearchModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const GlobalSearchModal: React.FC<GlobalSearchModalProps> = ({ isOpen, onClose }) => {
  const [query, setQuery] = useState('');
  const navigate = useNavigate();
  const term = query.trim();

  const search = useQuery({
    queryKey: ['globalSearch', term],
    queryFn: async () => (await api.get('/api/admin/v1/search', { params: { q: term } })).data.results as SearchResult[],
    enabled: isOpen && term.length >= 2,
    retry: false,
  });

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isOpen) onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!isOpen) setQuery('');
  }, [isOpen]);

  if (!isOpen) return null;

  const selectResult = (result: SearchResult) => {
    navigate(result.path);
    onClose();
  };

  const iconFor = (type: SearchResult['type']) => {
    if (type === 'refund') return <CreditCard className="w-4 h-4" />;
    if (type === 'order') return <ShoppingBag className="w-4 h-4" />;
    if (type === 'conversation') return <MessageSquare className="w-4 h-4" />;
    return <AlertTriangle className="w-4 h-4" />;
  };

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="global-search-title"
      className="fixed inset-0 z-50 flex items-start justify-center pt-24 p-4">
      <button type="button" aria-label="Close search" className="fixed inset-0 bg-black/60 backdrop-blur-md" onClick={onClose} />
      <div className="relative w-full max-w-xl glass-data border border-[rgba(63,210,192,0.35)] shadow-[0_24px_64px_rgba(0,0,0,0.6)] rounded-3xl overflow-hidden z-10">
        <h2 id="global-search-title" className="sr-only">Search Support Desk records</h2>
        <div className="flex items-center px-4 py-3.5 border-b border-[rgba(63,210,192,0.18)]">
          <Search className="w-5 h-5 text-[#3FD2C0] mr-3 shrink-0" />
          <input autoFocus type="search" value={query} onChange={(event) => setQuery(event.target.value)}
            aria-label="Search record IDs" placeholder="Search refunds, orders, conversations, or escalations…"
            className="w-full bg-transparent text-[#EAF6F4] placeholder-[#84ABA6] text-sm outline-none" />
          {query && <button type="button" aria-label="Clear search" onClick={() => setQuery('')} className="p-1 text-[#84ABA6] hover:text-[#EAF6F4]"><X className="w-4 h-4" /></button>}
        </div>

        <div className="p-3 min-h-32 max-h-96 overflow-y-auto" aria-live="polite">
          {term.length < 2 ? (
            <p className="text-sm text-[#84ABA6] text-center py-8">Enter at least 2 characters to search tenant records.</p>
          ) : search.isLoading ? (
            <p className="text-sm text-[#B6D5D1] text-center py-8">Searching…</p>
          ) : search.isError ? (
            <div role="alert" className="text-center py-6 space-y-3">
              <p className="text-sm text-[#FF8585]">Search failed. Your records were not changed.</p>
              <Button size="sm" variant="secondary" onClick={() => search.refetch()}>Retry search</Button>
            </div>
          ) : search.data?.length ? (
            <div className="space-y-1">
              {search.data.map((result) => (
                <button key={`${result.type}:${result.id}`} type="button" onClick={() => selectResult(result)}
                  className="w-full flex items-center justify-between px-3 py-2.5 rounded-xl hover:bg-[rgba(63,210,192,0.1)] text-left transition-colors group">
                  <span className="flex items-center gap-3 min-w-0">
                    <span className="w-8 h-8 rounded-lg bg-[rgba(11,74,71,0.6)] border border-[rgba(63,210,192,0.2)] flex items-center justify-center text-[#3FD2C0] shrink-0">{iconFor(result.type)}</span>
                    <span className="min-w-0"><span className="block truncate text-sm font-semibold text-[#EAF6F4] group-hover:text-[#3FD2C0]">{result.title}</span><span className="block truncate text-xs text-[#84ABA6]">{result.subtitle}</span></span>
                  </span>
                  <ArrowRight className="w-4 h-4 text-[#84ABA6] group-hover:text-[#3FD2C0] shrink-0" />
                </button>
              ))}
            </div>
          ) : (
            <p className="text-sm text-[#84ABA6] text-center py-8">No matching records found for “{term}”.</p>
          )}
        </div>
        <div className="px-4 py-2 bg-[rgba(4,30,29,0.7)] border-t border-[rgba(63,210,192,0.15)] flex items-center justify-between text-[11px] text-[#84ABA6]">
          <span>Esc to close</span><span>Tenant-scoped live results</span>
        </div>
      </div>
    </div>
  );
};
