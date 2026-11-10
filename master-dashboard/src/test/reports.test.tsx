import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReportsPage } from '../pages/ReportsPage';
import { api } from '../api/client';

vi.mock('../api/client', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  setCsrfToken: vi.fn(),
  getCsrfToken: vi.fn(() => 'csrf-mock'),
}));

const renderReports = () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ReportsPage />
    </QueryClientProvider>
  );
};

describe('ReportsPage live report controls', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.get as any).mockImplementation((url: string) => {
      if (url.includes('/spend')) {
        return Promise.resolve({ data: { daily: { spent_inr: 0, cap_inr: 2500 }, monthly: { spent_inr: 0, cap_inr: 50000 } } });
      }
      if (url.includes('export.csv')) return Promise.resolve({ data: new Blob(['Metric,Value\nConversations,1']) });
      return Promise.resolve({ data: { conversations: { deflection_rate_pct: 100, deflected: 1, total: 1 }, latency_ms: { p50: 120, p95: 120 }, financials: { cost_per_conversation_inr: 0 }, top_intents: [] } });
    });
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:qa-report') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  });

  it('loads a selected date range and downloads CSV through the authenticated API client', async () => {
    renderReports();
    fireEvent.click(screen.getByRole('tab', { name: '7 Days' }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/admin/v1/reports/metrics?days=7'));

    fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/admin/v1/reports/export.csv?days=7', { responseType: 'blob' }));
    expect(URL.createObjectURL).toHaveBeenCalled();
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled();
  });

  it('rounds the complementary escalation rate to one decimal place', async () => {
    (api.get as any).mockImplementation((url: string) => {
      if (url.includes('/spend')) return Promise.resolve({ data: { daily: { spent_inr: 0, cap_inr: 2500 }, monthly: { spent_inr: 0, cap_inr: 50000 } } });
      return Promise.resolve({ data: { conversations: { deflection_rate_pct: 79.2, deflected: 57, total: 72 }, top_intents: [] } });
    });
    renderReports();
    await waitFor(() => expect(screen.getByText('20.8%')).toBeInTheDocument());
  });
});
