import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SettingsPage } from '../pages/SettingsPage';
import { AuthProvider } from '../context/AuthContext';
import { api } from '../api/client';

vi.mock('../api/client', () => ({
  api: {
    get: vi.fn(),
    put: vi.fn(),
  },
  setCsrfToken: vi.fn(),
  getCsrfToken: vi.fn(() => 'csrf-mock'),
}));

const mockSettings = {
  tenant_id: 'tenant_novaretail',
  name: 'NovaRetail Demo Store',
  auto_refund_limit_inr: 2000,
  daily_spend_cap_inr: 2500,
  monthly_spend_cap_inr: 50000,
  working_hours_start: '09:00',
  working_hours_end: '20:00',
  timezone: 'Asia/Kolkata',
  supported_languages: ['en', 'hi', 'ta', 'te'],
  confidence_threshold: 0.85,
  grounding_threshold: 0.90,
  refund_turnaround_hours: 24,
};

const renderSettings = () => {
  sessionStorage.setItem(
    'novaretail_staff_meta',
    JSON.stringify({
      staffId: 'staff_mgr',
      email: 'manager@novaretail.com',
      fullName: 'Manager User',
      role: 'manager',
      tenantId: 'tenant_novaretail',
    })
  );

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <SettingsPage />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

describe('SettingsPage & Audit Diff Confirmation (Spec 16.4 Screen 6)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.get as any).mockResolvedValue({ data: mockSettings });
  });

  it('renders settings fields for manager', async () => {
    renderSettings();
    await waitFor(() => {
      expect(screen.getByText('System & Tenant Settings')).toBeInTheDocument();
      expect(screen.getByText('Auto-Refund Limit (INR)')).toBeInTheDocument();
      expect(screen.getByText('Review Changes & Diff')).toBeInTheDocument();
    });
  });

  it('changing a setting and submitting opens side-by-side diff confirmation modal', async () => {
    renderSettings();
    await waitFor(() => {
      expect(screen.getByDisplayValue('2000')).toBeInTheDocument();
    });

    const refundInput = screen.getByDisplayValue('2000');
    fireEvent.change(refundInput, { target: { value: '3500' } });

    const reviewBtn = screen.getByText('Review Changes & Diff');
    fireEvent.click(reviewBtn);

    await waitFor(() => {
      expect(screen.getByText('Confirm Configuration Changes (Audit Diff)')).toBeInTheDocument();
      expect(screen.getByText('auto_refund_limit_inr')).toBeInTheDocument();
      expect(screen.getByText('2000')).toBeInTheDocument();
      expect(screen.getByText('3500')).toBeInTheDocument();
      expect(screen.getByText('Commit Changes to Audit Log')).toBeInTheDocument();
    });
  });
});
