import React from 'react';
import { HelpCircle, ArrowLeft } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../components/ui/Button';

export const NotFoundPage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-[70vh] flex items-center justify-center p-4">
      <div className="glass-data max-w-md w-full text-center p-8 rounded-3xl border border-[rgba(63,210,192,0.3)] shadow-[0_24px_64px_rgba(0,0,0,0.6)]">
        <div className="w-16 h-16 rounded-2xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] flex items-center justify-center mx-auto mb-4 text-[#3FD2C0]">
          <HelpCircle className="w-8 h-8" />
        </div>
        <h1 className="text-2xl font-bold text-[#EAF6F4] mb-2">404 Route Not Found</h1>
        <p className="text-sm text-[#B6D5D1] mb-6 leading-relaxed">
          The requested dashboard view or resource does not exist or has been moved.
        </p>

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
