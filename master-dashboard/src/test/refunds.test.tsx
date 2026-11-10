import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RefundsPage } from '../pages/RefundsPage';
import { AuthProvider } from '../context/AuthContext';
import { api } from '../api/client';

vi.mock('../api/client', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
  setCsrfToken: vi.fn(),
  getCsrfToken: vi.fn(() => 'csrf-mock'),
}));

const mockRefunds = [
  {
    refund_id: 'REF-001',
    order_id: 'ORD-991',
    customer_id: 'cust_401',
    amount_inr: 2500,
    reason: 'Damaged packaging during transit',
    state: 'pending_approval',
    created_at: new Date().toISOString(),
    customer_trust_level: 'verified',
    requested_by: 'staff_different',
  },
  {
    refund_id: 'REF-002',
    order_id: 'ORD-992',
    customer_id: 'cust_402',
    amount_inr: 6500,
    reason: 'Defective audio driver',
    state: 'pending_approval',
    created_at: new Date().toISOString(),
    customer_trust_level: 'verified',
    requested_by: 'staff_001', // Self requested
  },
];

const renderRefunds = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <RefundsPage />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

describe('RefundsPage Approval Queue (Spec 16.4 Screen 2)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.get as any).mockResolvedValue({ data: mockRefunds });
  });

  it('renders pending refunds list and detail card', async () => {
    renderRefunds();
    await waitFor(() => {
      expect(screen.getAllByText(/REF-001/)[0]).toBeInTheDocument();
      expect(screen.getAllByText(/2,500/)[0]).toBeInTheDocument();
    });
  });

  it('rejecting a refund requires a documented staff note', async () => {
    renderRefunds();
    await waitFor(() => {
      expect(screen.getByText('Reject Refund')).toBeInTheDocument();
    });

    // Click reject without note
    fireEvent.click(screen.getByText('Reject Refund'));
    expect(
      screen.getByText(/A documented staff note is strictly required to reject a refund request/i)
    ).toBeInTheDocument();
  });

  it('blocks self-approval when refund was requested by same staff', async () => {
    // Set active staff to staff_001 in session storage
    sessionStorage.setItem(
      'novaretail_staff_meta',
      JSON.stringify({
        staffId: 'staff_001',
        email: 'staff@novaretail.com',
        fullName: 'Test Staff',
        role: 'manager',
        tenantId: 'tenant_novaretail',
      })
    );

    renderRefunds();
    await waitFor(() => {
      expect(screen.getByText(/REF-002/)).toBeInTheDocument();
    });

    // Select self-requested refund REF-002
    fireEvent.click(screen.getByText(/REF-002/));

    await waitFor(() => {
      expect(screen.getByText(/Spec 15.1.8 Enforcement: You cannot approve this refund/i)).toBeInTheDocument();
    });
  });

  it('blocks Support Executive from approving refunds exceeding ₹5,000 threshold', async () => {
    sessionStorage.setItem(
      'novaretail_staff_meta',
      JSON.stringify({
        staffId: 'staff_exec_99',
        email: 'exec@novaretail.com',
        fullName: 'Frontline Executive',
        role: 'executive',
        tenantId: 'tenant_novaretail',
      })
    );

    renderRefunds();
    await waitFor(() => {
      expect(screen.getByText(/REF-002/)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/REF-002/));

    await waitFor(() => {
      expect(screen.getByText(/Spec 16.4 Supervisory Gate: Refunds exceeding ₹5,000/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /requires manager sign-off/i })).toBeDisabled();
    });
  });
});
