import React from 'react';
import { ShieldAlert, ArrowLeft } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../components/ui/Button';

interface UnauthorizedPageProps {
  requiredRoles: string[];
  currentRole: string;
}

export const UnauthorizedPage: React.FC<UnauthorizedPageProps> = ({
  requiredRoles,
  currentRole,
}) => {
  const navigate = useNavigate();

  return (
    <div className="min-h-[70vh] flex items-center justify-center p-4">
      <div className="glass-data max-w-md w-full text-center p-8 rounded-3xl border border-[rgba(255,82,82,0.4)] shadow-[0_24px_64px_rgba(0,0,0,0.6)]">
        <div className="w-16 h-16 rounded-2xl bg-[rgba(255,82,82,0.15)] border border-[rgba(255,82,82,0.4)] flex items-center justify-center mx-auto mb-4 text-[#FF5252]">
          <ShieldAlert className="w-8 h-8" />
        </div>
        <h1 className="text-2xl font-bold text-[#EAF6F4] mb-2">403 Access Denied</h1>
        <p className="text-sm text-[#B6D5D1] mb-6 leading-relaxed">
          Your active staff role is <span className="font-bold text-[#FFA502] uppercase">{currentRole}</span>.
          Access to this management console strictly requires one of:{' '}
          <span className="font-semibold text-[#3FD2C0] uppercase">
            {requiredRoles.join(', ')}
          </span>.
        </p>

        <div className="p-3 rounded-xl bg-[rgba(4,30,29,0.7)] border border-[rgba(63,210,192,0.15)] text-xs text-[#84ABA6] mb-6">
          Complies with Spec 16.4 Role-Based Access Control. Role elevation must be requested via Staff Administration.
        </div>

        <Button
          variant="primary"
          leftIcon={<ArrowLeft className="w-4 h-4" />}
          onClick={() => navigate('/')}
        >
          Return to Overview
        </Button>
      </div>
    </div>
  );
};
