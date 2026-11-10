import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import {
  Panel,
  Button,
  TableSkeleton,
} from '../components/ui';
import {
  Users,
  PlusCircle,
  CheckCircle2,
  AlertTriangle,
  UserPlus,
} from 'lucide-react';

export const StaffAdminPage: React.FC = () => {
  const queryClient = useQueryClient();

  const [tenantForm, setTenantForm] = useState({
    tenant_id: '',
    name: '',
    owner_name: '',
    owner_email: '',
    owner_password: '',
  });
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [staffForm, setStaffForm] = useState({ full_name: '', email: '', password: '', role: 'executive' });

  // 1. Fetch active sessions
  const { data: sessions = [], isLoading, isError: sessionsError, refetch: refetchSessions } = useQuery<any[]>({
    queryKey: ['staffSessions'],
    queryFn: async () => {
      const resp = await api.get('/api/admin/v1/auth/sessions');
      return resp.data || [];
    },
  });

  const { data: staffUsers = [], isLoading: staffLoading, isError: staffError, refetch: refetchStaff } = useQuery<any[]>({
    queryKey: ['staffUsers'],
    queryFn: async () => (await api.get('/api/admin/v1/auth/staff')).data || [],
  });

  const createStaffMutation = useMutation({
    mutationFn: async () => (await api.post('/api/admin/v1/auth/staff', staffForm)).data,
    onSuccess: (data) => {
      setSuccessMsg(`Staff account for ${data.email} was created.`);
      setStaffForm({ full_name: '', email: '', password: '', role: 'executive' });
      setErrorMsg(null);
      queryClient.invalidateQueries({ queryKey: ['staffUsers'] });
    },
    onError: (err: any) => setErrorMsg(err.response?.data?.detail || 'Failed to create staff account.'),
  });

  // Revoke session mutation
  const revokeMutation = useMutation({
    mutationFn: async (sessionId: string) => {
      await api.delete(`/api/admin/v1/auth/sessions/${sessionId}`);
    },
    onSuccess: (_, sessionId) => {
      setSuccessMsg(`Session ${sessionId.slice(0, 12)}... was revoked.`);
      queryClient.invalidateQueries({ queryKey: ['staffSessions'] });
    },
    onError: (err: any) => {
      setErrorMsg(err.response?.data?.detail || 'Failed to revoke staff session.');
    },
  });

  // Create tenant mutation
  const createTenantMutation = useMutation({
    mutationFn: async (payload: typeof tenantForm) => {
      const resp = await api.post('/api/admin/v1/auth/tenants', payload);
      return resp.data;
    },
    onSuccess: (data) => {
      setSuccessMsg(`Workspace "${data.name}" successfully created. Administrator can now log in.`);
      setTenantForm({ tenant_id: '', name: '', owner_name: '', owner_email: '', owner_password: '' });
      setErrorMsg(null);
    },
    onError: (err: any) => {
      setErrorMsg(err.response?.data?.detail || 'Failed to create workspace.');
    },
  });

  const handleCreateTenant = (e: React.FormEvent) => {
    e.preventDefault();
    createTenantMutation.mutate(tenantForm);
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div>
        <p className="micro-label">SPEC 16.4 • TENANT ADMINISTRATION</p>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-[#EAF6F4] tracking-tight mt-0.5">
          Staff & Workspace Administration
        </h1>
        <p className="text-sm text-[#B6D5D1] mt-1">
          Manage active staff logins, revoke sessions, and provision isolated tenant workspaces.
        </p>
      </div>

      {successMsg && (
        <div className="p-4 rounded-2xl bg-[rgba(46,213,115,0.15)] border border-[rgba(46,213,115,0.4)] text-[#2ED573] text-sm flex items-center gap-3">
          <CheckCircle2 className="w-5 h-5 shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      {errorMsg && (
        <div className="p-4 rounded-2xl bg-[rgba(255,82,82,0.15)] border border-[rgba(255,82,82,0.4)] text-[#FF8585] text-sm flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      <Panel tier="data" notchedLabel="STAFF ACCOUNTS" notchedIcon={<UserPlus className="w-3.5 h-3.5 text-[#3FD2C0]" />}>
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); setErrorMsg(null); createStaffMutation.mutate(); }}>
            <h2 className="text-sm font-bold text-[#EAF6F4]">Create staff account</h2>
            <label className="block text-xs text-[#B6D5D1]">Full name<input required maxLength={255} value={staffForm.full_name} onChange={(event) => setStaffForm({ ...staffForm, full_name: event.target.value })} className="mt-1 w-full px-3 py-2 rounded-lg bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm" /></label>
            <label className="block text-xs text-[#B6D5D1]">Email<input required type="email" value={staffForm.email} onChange={(event) => setStaffForm({ ...staffForm, email: event.target.value })} className="mt-1 w-full px-3 py-2 rounded-lg bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm" /></label>
            <label className="block text-xs text-[#B6D5D1]">Temporary password<input required minLength={12} type="password" value={staffForm.password} onChange={(event) => setStaffForm({ ...staffForm, password: event.target.value })} className="mt-1 w-full px-3 py-2 rounded-lg bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm" /><span className="text-[11px] text-[#84ABA6]">At least 12 characters.</span></label>
            <label className="block text-xs text-[#B6D5D1]">Role<select value={staffForm.role} onChange={(event) => setStaffForm({ ...staffForm, role: event.target.value })} className="mt-1 w-full px-3 py-2 rounded-lg bg-[#0B4A47] border border-[rgba(63,210,192,0.25)] text-sm"><option value="executive">Executive</option><option value="manager">Manager</option><option value="admin">Admin</option></select></label>
            <Button type="submit" size="sm" variant="primary" isLoading={createStaffMutation.isPending}>Create staff account</Button>
          </form>
          <div className="xl:col-span-2 overflow-x-auto">
            <div className="flex items-center justify-between mb-2"><h2 className="text-sm font-bold text-[#EAF6F4]">Workspace staff</h2>{staffError && <Button size="sm" variant="secondary" onClick={() => refetchStaff()}>Retry</Button>}</div>
            {staffLoading ? <TableSkeleton rows={3} /> : staffError ? <p role="alert" className="text-sm text-[#FF8585]">Staff list could not be loaded.</p> : staffUsers.length === 0 ? <p className="text-sm text-[#84ABA6] py-5">No staff accounts found.</p> : (
              <table className="w-full text-left text-sm"><thead><tr className="text-xs uppercase text-[#84ABA6]"><th className="p-2">Name</th><th className="p-2">Email</th><th className="p-2">Role</th></tr></thead><tbody>{staffUsers.map((user) => <tr key={user.staff_id} className="border-t border-[rgba(63,210,192,0.12)] text-[#EAF6F4]"><td className="p-2">{user.full_name}</td><td className="p-2">{user.email}</td><td className="p-2 capitalize">{user.role}</td></tr>)}</tbody></table>
            )}
          </div>
        </div>
      </Panel>

      {/* Grid: Create Tenant Workspace & Active Sessions */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left: Provision Tenant Workspace */}
        <div className="lg:col-span-5">
          <Panel
            tier="data"
            notchedLabel="NEW WORKSPACE PROVISIONING"
            notchedIcon={<PlusCircle className="w-3.5 h-3.5 text-[#3FD2C0]" />}
          >
            <form onSubmit={handleCreateTenant} className="space-y-3.5 pt-2">
              <div>
                <label className="block text-xs font-semibold text-[#B6D5D1] mb-1">
                  Tenant Identifier (Slug)
                </label>
                <input
                  required
                  type="text"
                  placeholder="e.g. tenant_apex_retail"
                  value={tenantForm.tenant_id}
                  onChange={(e) => setTenantForm({ ...tenantForm, tenant_id: e.target.value })}
                  className="w-full px-3.5 py-2 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm text-[#EAF6F4] font-mono focus:border-[#3FD2C0] outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#B6D5D1] mb-1">
                  Workspace Display Name
                </label>
                <input
                  required
                  type="text"
                  placeholder="e.g. Apex Electronics Store"
                  value={tenantForm.name}
                  onChange={(e) => setTenantForm({ ...tenantForm, name: e.target.value })}
                  className="w-full px-3.5 py-2 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm text-[#EAF6F4] focus:border-[#3FD2C0] outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#B6D5D1] mb-1">
                  Initial Administrator Name
                </label>
                <input
                  required
                  type="text"
                  placeholder="e.g. Jane Doe"
                  value={tenantForm.owner_name}
                  onChange={(e) => setTenantForm({ ...tenantForm, owner_name: e.target.value })}
                  className="w-full px-3.5 py-2 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm text-[#EAF6F4] focus:border-[#3FD2C0] outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#B6D5D1] mb-1">
                  Administrator Email
                </label>
                <input
                  required
                  type="email"
                  placeholder="admin@apexstore.com"
                  value={tenantForm.owner_email}
                  onChange={(e) => setTenantForm({ ...tenantForm, owner_email: e.target.value })}
                  className="w-full px-3.5 py-2 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm text-[#EAF6F4] focus:border-[#3FD2C0] outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#B6D5D1] mb-1">
                  Initial Password
                </label>
                <input
                  required
                  type="password"
                  placeholder="••••••••••••"
                  value={tenantForm.owner_password}
                  onChange={(e) => setTenantForm({ ...tenantForm, owner_password: e.target.value })}
                  className="w-full px-3.5 py-2 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm text-[#EAF6F4] focus:border-[#3FD2C0] outline-none"
                />
              </div>

              <Button
                type="submit"
                variant="primary"
                size="sm"
                className="w-full mt-2"
                isLoading={createTenantMutation.isPending}
                leftIcon={<PlusCircle className="w-4 h-4" />}
              >
                Provision Workspace
              </Button>
            </form>
          </Panel>
        </div>

        {/* Right: Active Sessions Table */}
        <div className="lg:col-span-7">
          <Panel
            tier="data"
            notchedLabel="ACTIVE STAFF SESSIONS"
            notchedIcon={<Users className="w-3.5 h-3.5 text-[#3FD2C0]" />}
          >
            {isLoading ? (
              <TableSkeleton rows={4} />
            ) : sessionsError ? (
              <div role="alert" className="space-y-3 py-5 text-sm text-[#FF8585]">Staff sessions could not be loaded.<Button size="sm" variant="secondary" onClick={() => refetchSessions()}>Retry</Button></div>
            ) : sessions.length === 0 ? (
              <p className="text-center py-8 text-sm text-[#84ABA6]">
                No active staff sessions recorded.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-[rgba(63,210,192,0.2)] text-[11px] uppercase tracking-wider text-[#84ABA6]">
                      <th className="py-3 px-3 font-bold">Session ID</th>
                      <th className="py-3 px-3 font-bold">Staff ID</th>
                      <th className="py-3 px-3 font-bold">Tenant</th>
                      <th className="py-3 px-3 font-bold">Expires</th>
                      <th className="py-3 px-3 font-bold text-right">Revoke</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[rgba(63,210,192,0.1)]">
                    {sessions.map((s) => (
                      <tr key={s.session_id} className="hover:bg-[rgba(11,74,71,0.3)] font-mono text-xs">
                        <td className="py-3 px-3 text-[#EAF6F4]">
                          {s.session_id.slice(0, 12)}...
                        </td>
                        <td className="py-3 px-3 text-[#3FD2C0] font-sans">
                          {s.staff_id}
                        </td>
                        <td className="py-3 px-3 text-[#B6D5D1]">
                          {s.active_tenant_id}
                        </td>
                        <td className="py-3 px-3 text-[#84ABA6]">
                          {s.expires_at ? new Date(s.expires_at).toLocaleTimeString('en-IN') : '-'}
                        </td>
                        <td className="py-3 px-3 text-right">
                          <Button
                            variant="danger"
                            size="sm"
                            className="py-1 px-2.5 text-xs"
                            onClick={() => revokeMutation.mutate(s.session_id)}
                            isLoading={revokeMutation.isPending}
                          >
                            Revoke
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
};
