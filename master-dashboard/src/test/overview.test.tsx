import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { OverviewPage } from '../pages/OverviewPage';
import { AuthProvider } from '../context/AuthContext';

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

  it('renders system telemetry section with LLM gateway and pgvector indicators', () => {
    renderOverview();
    expect(screen.getByText('LLM Orchestrator Gateway')).toBeInTheDocument();
    expect(screen.getByText('PostgreSQL & pgvector')).toBeInTheDocument();
    expect(screen.getByText('Staff Auth & Session Gate')).toBeInTheDocument();
  });
});
