import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Button } from '../components/ui/Button';
import { StatusBadge } from '../components/ui/StatusBadge';
import { Panel } from '../components/ui/Panel';
import { Card } from '../components/ui/Card';
import { Modal } from '../components/ui/Modal';
import { EmptyState } from '../components/ui/EmptyState';
import { PipelineLoadingModal } from '../components/PipelineLoadingModal';
import { IngestionJob } from '../types/schemas';

describe('Design System UI Primitives', () => {
  it('renders Button with primary pill styling and handles click', () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Approve Action</Button>);
    const btn = screen.getByRole('button', { name: /approve action/i });
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('renders Button with loading state disabled', () => {
    render(<Button isLoading>Processing</Button>);
    const btn = screen.getByRole('button');
    expect(btn).toBeDisabled();
  });

  it('renders StatusBadge with accessible semantic status', () => {
    render(<StatusBadge status="success" label="Grounded 98%" />);
    expect(screen.getByText('Grounded 98%')).toBeInTheDocument();
  });

  it('renders Panel with signature notched tab pill', () => {
    render(
      <Panel notchedLabel="QUEUE STATUS">
        <div>Panel content</div>
      </Panel>
    );
    expect(screen.getByText('QUEUE STATUS')).toBeInTheDocument();
    expect(screen.getByText('Panel content')).toBeInTheDocument();
  });

  it('renders Card with corner action button trigger', () => {
    const handleAction = vi.fn();
    render(
      <Card title="Refund #101" onAction={handleAction} actionTitle="Inspect Refund">
        <p>Details</p>
      </Card>
    );
    expect(screen.getByText('Refund #101')).toBeInTheDocument();
    const actionBtn = screen.getByRole('button', { name: /inspect refund/i });
    fireEvent.click(actionBtn);
    expect(handleAction).toHaveBeenCalledTimes(1);
  });

  it('renders Modal and triggers onClose on ESC key', () => {
    const handleClose = vi.fn();
    render(
      <Modal isOpen={true} onClose={handleClose} title="Confirm Approval">
        <p>Are you sure?</p>
      </Modal>
    );
    expect(screen.getByText('Confirm Approval')).toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it('renders EmptyState with guidance and call-to-action', () => {
    const handleAction = vi.fn();
    render(
      <EmptyState
        title="Queue Cleared"
        description="No pending tickets."
        actionLabel="Refresh List"
        onAction={handleAction}
      />
    );
    expect(screen.getByText('Queue Cleared')).toBeInTheDocument();
    const btn = screen.getByRole('button', { name: /refresh list/i });
    fireEvent.click(btn);
    expect(handleAction).toHaveBeenCalledTimes(1);
  });

  it('renders PipelineLoadingModal with active progress and shows Cancel Pipeline button with confirmation', () => {
    const handleCancel = vi.fn();
    const handleClose = vi.fn();
    const activeJob: IngestionJob = {
      job_id: 'job_cat_test123',
      tenant_id: 'tenant_novaretail',
      source_type: 'catalog',
      status: 'running',
      progress_pct: 45,
      stats: { products_seen: 4, chunks_indexed: 12 },
    };

    render(
      <PipelineLoadingModal
        isOpen={true}
        onClose={handleClose}
        job={activeJob}
        onCancelPipeline={handleCancel}
      />
    );

    expect(screen.getByText('RUNNING')).toBeInTheDocument();
    expect(screen.getByText('45%')).toBeInTheDocument();
    const cancelBtn = screen.getByRole('button', { name: /cancel pipeline/i });
    expect(cancelBtn).toBeInTheDocument();

    // Click Cancel Pipeline to trigger confirmation prompt
    fireEvent.click(cancelBtn);
    expect(screen.getByText(/abort sync\?/i)).toBeInTheDocument();
    const confirmBtn = screen.getByRole('button', { name: /yes, cancel/i });
    fireEvent.click(confirmBtn);
    expect(handleCancel).toHaveBeenCalledWith('job_cat_test123');
  });

  it('renders PipelineLoadingModal with cancelled status banner and badge', () => {
    const handleClose = vi.fn();
    const cancelledJob: IngestionJob = {
      job_id: 'job_cat_test456',
      tenant_id: 'tenant_novaretail',
      source_type: 'catalog',
      status: 'cancelled',
      progress_pct: 100,
      error_message: 'The ingestion pipeline was safely halted by staff.',
      stats: { products_seen: 4, chunks_indexed: 8 },
    };

    render(
      <PipelineLoadingModal
        isOpen={true}
        onClose={handleClose}
        job={cancelledJob}
      />
    );

    expect(screen.getByText('CANCELLED')).toBeInTheDocument();
    expect(screen.getByText(/pipeline cancelled by staff:/i)).toBeInTheDocument();
    expect(screen.getByText(/close window/i)).toBeInTheDocument();
  });
});
