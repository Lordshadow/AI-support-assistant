import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { StaffRole } from '../types/schemas';
import { UnauthorizedPage } from '../pages/UnauthorizedPage';

interface ProtectedRouteProps {
  children: React.ReactNode;
  allowedRoles?: StaffRole[];
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  children,
  allowedRoles,
}) => {
  const { staff, isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-[#3FD2C0] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!isAuthenticated || !staff) {
    return <Navigate to="/login" replace />;
  }

  if (allowedRoles && !allowedRoles.includes(staff.role)) {
    return <UnauthorizedPage requiredRoles={allowedRoles} currentRole={staff.role} />;
  }

  return <>{children}</>;
};
