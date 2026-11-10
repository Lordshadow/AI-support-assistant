import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { Modal } from './ui/Modal';
import { Button } from './ui/Button';
import { ShieldAlert, KeyRound } from 'lucide-react';

export const StepUpModal: React.FC = () => {
  const { stepUpOpen, setStepUpOpen, performStepUp } = useAuth();
  const [password, setPassword] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password) {
      setError('Staff password is required for step-up elevation.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const ok = await performStepUp(password, mfaCode || undefined);
      if (ok) {
        setPassword('');
        setMfaCode('');
      } else {
        setError('Elevation failed. Invalid password or MFA code.');
      }
    } catch {
      setError('An error occurred during step-up elevation.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      isOpen={stepUpOpen}
      onClose={() => setStepUpOpen(false)}
      title="Elevated Access Required (Step-Up)"
      description="This high-privilege action requires temporary security re-verification (valid for 5 minutes)."
      maxWidth="sm"
    >
      <form onSubmit={handleSubmit} className="space-y-4 pt-2">
        <div className="flex items-center gap-3 p-3 rounded-xl bg-[rgba(255,165,2,0.1)] border border-[rgba(255,165,2,0.3)] text-[#FFA502] text-xs">
          <ShieldAlert className="w-5 h-5 shrink-0" />
          <span>Spec 15.1.8 Step-Up: Required for refunds &gt; ₹5,000 or customer PII unmasking.</span>
        </div>

        {error && (
          <div className="p-3 rounded-xl bg-[rgba(255,82,82,0.15)] border border-[rgba(255,82,82,0.4)] text-[#FF8585] text-xs">
            {error}
          </div>
        )}

        <div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-[#B6D5D1] mb-1.5">
            Staff Password
          </label>
          <div className="relative">
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your current password"
              className="w-full px-4 py-2.5 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-[#EAF6F4] placeholder-[#84ABA6] focus:border-[#3FD2C0] focus:ring-1 focus:ring-[#3FD2C0] outline-none text-sm"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-[#B6D5D1] mb-1.5">
            MFA / TOTP Code (Optional if not enrolled)
          </label>
          <div className="relative">
            <input
              type="text"
              maxLength={6}
              value={mfaCode}
              onChange={(e) => setMfaCode(e.target.value)}
              placeholder="e.g. 123456"
              className="w-full px-4 py-2.5 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-[#EAF6F4] placeholder-[#84ABA6] focus:border-[#3FD2C0] focus:ring-1 focus:ring-[#3FD2C0] outline-none text-sm font-mono tracking-widest"
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 pt-4 border-t border-[rgba(63,210,192,0.15)]">
          <Button variant="ghost" type="button" onClick={() => setStepUpOpen(false)}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" isLoading={loading} leftIcon={<KeyRound className="w-4 h-4" />}>
            Elevate Access
          </Button>
        </div>
      </form>
    </Modal>
  );
};
