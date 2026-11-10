import { beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { OverviewPage } from '../pages/OverviewPage';
import { AuthProvider } from '../context/AuthContext';
import { useAuth } from '../context/AuthContext';
import { api } from '../api/client';

vi.mock('../api/client', () => ({ api: { get: vi.fn() } }));
vi.mock('../context/AuthContext', () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => children,
  useAuth: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useAuth).mockReturnValue({ staff: { role: 'manager' } } as any);
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path.endsWith('/refunds/pending')) return { data: [] } as any;
    if (path.includes('/escalations?')) return { data: { escalations: [], count: 2 } } as any;
    if (path.endsWith('/reports')) return { data: { deflection_rate: 0.82, spend_daily_inr: 250, spend_daily_cap_inr: 1000, latency_p50_ms: 120 } } as any;
    if (path === '/health') return { data: { status: 'healthy', dependencies: { postgres: 'healthy', redis: 'healthy' } } } as any;
    throw new Error(`Unexpected endpoint ${path}`);
  });
});

const renderOverview = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <OverviewPage />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

describe('OverviewPage Component', () => {
  it('renders command center title and KPI cards', () => {
    renderOverview();
    expect(screen.getByText('Command Center Overview')).toBeInTheDocument();
    expect(screen.getByText('Pending Approvals')).toBeInTheDocument();
    expect(screen.getByText('Open Escalations')).toBeInTheDocument();
    expect(screen.getByText('Deflection Rate')).toBeInTheDocument();
    expect(screen.getByText('Token Spend Today')).toBeInTheDocument();
  });

  it('renders system telemetry labels that match the health checks they display', async () => {
    renderOverview();
    expect(screen.getByText('Assistant API')).toBeInTheDocument();
    expect(screen.getByText('PostgreSQL')).toBeInTheDocument();
    expect(screen.getByText('Redis Session Store')).toBeInTheDocument();
    expect(await screen.findByText('Observed p50 latency: 120ms')).toBeInTheDocument();
  });

  it('loads live manager metrics and queue counts from the expected APIs', async () => {
    renderOverview();
    await waitFor(() => expect(screen.getByText('82%')).toBeInTheDocument());
    expect(screen.getByText('2 waiting')).toBeInTheDocument();
    expect(screen.getByText('₹250')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/admin/v1/refunds/pending');
    expect(api.get).toHaveBeenCalledWith('/api/admin/v1/escalations?state=open');
    expect(api.get).toHaveBeenCalledWith('/api/admin/v1/reports');
    expect(api.get).toHaveBeenCalledWith('/health');
  });

  it('does not call manager-only reports for executives', async () => {
    vi.mocked(useAuth).mockReturnValue({ staff: { role: 'executive' } } as any);
    renderOverview();
    expect(await screen.findAllByText('Report metrics are available to managers and admins.')).toHaveLength(2);
    expect(api.get).not.toHaveBeenCalledWith('/api/admin/v1/reports');
  });

  it('shows health failures and exposes a retry action', async () => {
    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path === '/health') throw new Error('offline');
      if (path.endsWith('/refunds/pending')) return { data: [] } as any;
      if (path.includes('/escalations?')) return { data: { escalations: [], count: 0 } } as any;
      return { data: { deflection_rate: 0.82, spend_daily_inr: 250, spend_daily_cap_inr: 1000 } } as any;
    });
    renderOverview();
    expect(await screen.findByRole('alert')).toHaveTextContent('Retry service health');
  });
});
