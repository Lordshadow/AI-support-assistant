import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConversationsPage } from '../pages/ConversationsPage';
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

const mockConvs = {
  conversations: [
    {
      conv_id: 'conv_test_101',
      customer_id: 'cust_882',
      channel: 'whatsapp',
      handoff_state: 'none',
      last_activity: new Date().toISOString(),
      turn_count: 2,
    },
  ],
  count: 1,
};

const mockTurns = {
  conv_id: 'conv_test_101',
  turns: [
    {
      turn_id: 'turn_01',
      step_index: 1,
      user_masked: 'Can I return my headphones? My phone is +91 ••••• •••89',
      assistant_masked: 'Yes, items in original condition can be returned within 30 days.',
      intent: 'return_policy_inquiry',
      timestamp: new Date().toISOString(),
    },
  ],
};

const mockTrace = {
  turn_id: 'turn_01',
  conv_id: 'conv_test_101',
  step_index: 1,
  intent: 'return_policy_inquiry',
  intent_confidence: 0.98,
  route_taken: 'rag_grounded',
  auth_level: 'verified',
  resolved_product_id: 'P1041',
  retrieved_chunks: [
    { chunk_id: 'chk_policy_01', title: 'Return Policy Section 3', score: 0.95, text: '30-day window' },
  ],
  tool_calls: [{ name: 'get_product_details', arguments: { product_id: 'P1041' } }],
  grounding_score: 0.96,
  grounding_result: 'grounded',
  prompt_version: 'v2.4.1',
  model_name: 'claude-3-7-sonnet',
  tokens_prompt: 412,
  tokens_completion: 88,
  latency_ms: 390,
  cost_inr: 0.88,
  user_masked: 'Can I return my headphones? My phone is +91 ••••• •••89',
  assistant_masked: 'Yes, items in original condition can be returned within 30 days.',
  created_at: new Date().toISOString(),
};

const renderConversations = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <ConversationsPage />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

describe('ConversationsPage & Spec 14.1 Trace Inspector', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.get as any).mockImplementation((url: string) => {
      if (url.includes('/turns/turn_01/trace')) {
        return Promise.resolve({ data: mockTrace });
      }
      if (url.includes('/conversations/conv_test_101')) {
        return Promise.resolve({ data: mockTurns });
      }
      return Promise.resolve({ data: mockConvs });
    });
  });

  it('renders conversations list and masked DPDP dialogue', async () => {
    renderConversations();
    await waitFor(() => {
      expect(screen.getAllByText('conv_test_101')[0]).toBeInTheDocument();
      expect(screen.getByText(/Can I return my headphones\? My phone is \+91 ••••• •••89/i)).toBeInTheDocument();
    });
  });

  it('clicking "Why this answer?" opens Spec 14.1 trace inspector drawer', async () => {
    renderConversations();
    await waitFor(() => {
      expect(screen.getByText(/Why this answer\?/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/Why this answer\?/i));

    await waitFor(() => {
      expect(screen.getByText(/WHY THIS ANSWER\? \(SPEC 14\.1 TRACE\)/i)).toBeInTheDocument();
      expect(screen.getByText(/rag_grounded/i)).toBeInTheDocument();
      expect(screen.getByText(/Return Policy Section 3/i)).toBeInTheDocument();
      expect(screen.getByText('get_product_details()')).toBeInTheDocument();
    });
  });

  it('shows missing trace evidence when the API fails without inventing values', async () => {
    (api.get as any).mockImplementation((url: string) => {
      if (url.includes('/turns/turn_01/trace')) return Promise.reject(new Error('trace unavailable'));
      if (url.includes('/conversations/conv_test_101')) return Promise.resolve({ data: mockTurns });
      return Promise.resolve({ data: mockConvs });
    });

    renderConversations();
    await waitFor(() => expect(screen.getByText(/Why this answer\?/i)).toBeInTheDocument());
    fireEvent.click(screen.getByText(/Why this answer\?/i));

    await waitFor(() => expect(screen.getByText(/trace could not be loaded/i)).toBeInTheDocument());
    expect(screen.queryByText(/claude-3-7-sonnet/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/grounded 96%/i)).not.toBeInTheDocument();
  });

  it('filters by supported channel and persisted handoff states', async () => {
    renderConversations();
    await waitFor(() => expect(screen.getByText(/Why this answer\?/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText('Filter conversations by channel'), { target: { value: 'whatsapp' } });
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining('channel=whatsapp')));

    fireEvent.change(screen.getByLabelText('Filter conversations by handoff state'), { target: { value: 'assigned' } });
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining('handoff_state=assigned')));

    fireEvent.change(screen.getByLabelText('Filter conversations by handoff state'), { target: { value: 'resolved' } });
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining('handoff_state=resolved')));
  });
});
