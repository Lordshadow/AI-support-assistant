import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ScriptsPage } from '../pages/ScriptsPage';
import { AuthProvider } from '../context/AuthContext';

const renderScriptsPage = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <ScriptsPage />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

describe('ScriptsPage Component', () => {
  it('renders the header and categories', () => {
    renderScriptsPage();
    expect(screen.getByText('Developer & Operations Scripts')).toBeInTheDocument();
    expect(screen.getByText('All Runbooks')).toBeInTheDocument();
    expect(screen.getAllByText('Database & Auth')[0]).toBeInTheDocument();
    expect(screen.getAllByText('AI Evals & Tests')[0]).toBeInTheDocument();
    expect(screen.getAllByText('Knowledge & RAG')[0]).toBeInTheDocument();
    expect(screen.getAllByText('Channels & Widget')[0]).toBeInTheDocument();
    expect(screen.getAllByText('Docker & Ops')[0]).toBeInTheDocument();
  });

  it('renders script items with command and allows category filtering', () => {
    renderScriptsPage();
    expect(screen.getByText('Seed Staff Accounts & Roles')).toBeInTheDocument();
    expect(screen.getByText('Run Golden Benchmark Evaluations (R1–R5)')).toBeInTheDocument();

    // Click AI Evals category filter
    const evalsBtn = screen.getByRole('button', { name: /ai evals & tests/i });
    fireEvent.click(evalsBtn);

    // AI evals script is visible, database seed is filtered out
    expect(screen.getByText('Run Golden Benchmark Evaluations (R1–R5)')).toBeInTheDocument();
    expect(screen.queryByText('Seed Staff Accounts & Roles')).not.toBeInTheDocument();
  });

  it('filters runbooks by live search input', () => {
    renderScriptsPage();
    const searchInput = screen.getByPlaceholderText(/search runbooks/i);
    fireEvent.change(searchInput, { target: { value: 'whatsapp' } });

    expect(screen.getByText('Simulate Inbound WhatsApp Customer Message')).toBeInTheDocument();
    expect(screen.queryByText('Seed Staff Accounts & Roles')).not.toBeInTheDocument();
  });

  it('toggles between Local Shell and Docker Container execution modes', () => {
    renderScriptsPage();
    expect(screen.getByText(/python support-assistant\/db\/seed_staff\.py/i)).toBeInTheDocument();

    // Switch to Docker mode
    const dockerBtn = screen.getByRole('button', { name: /docker container/i });
    fireEvent.click(dockerBtn);

    expect(screen.getByText(/docker compose exec assistant-api python db\/seed_staff\.py/i)).toBeInTheDocument();
  });
});
