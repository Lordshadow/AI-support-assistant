import React from 'react';

export interface SkeletonProps {
  className?: string;
  width?: string | number;
  height?: string | number;
  borderRadius?: string;
}

export const Skeleton: React.FC<SkeletonProps> = ({
  className = '',
  width,
  height,
  borderRadius = '8px',
}) => {
  return (
    <div
      className={`animate-pulse bg-[rgba(15,92,88,0.35)] border border-[rgba(63,210,192,0.1)] ${className}`}
      style={{
        width,
        height,
        borderRadius,
      }}
    />
  );
};

export const TableSkeleton: React.FC<{ rows?: number }> = ({ rows = 5 }) => {
  return (
    <div className="space-y-3 p-4">
      <Skeleton height="36px" borderRadius="12px" className="mb-4" />
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-4 items-center">
          <Skeleton height="24px" width="20%" borderRadius="8px" />
          <Skeleton height="24px" width="30%" borderRadius="8px" />
          <Skeleton height="24px" width="25%" borderRadius="8px" />
          <Skeleton height="24px" width="15%" borderRadius="8px" />
          <Skeleton height="24px" width="10%" borderRadius="8px" />
        </div>
      ))}
    </div>
  );
};

export const CardSkeleton: React.FC = () => {
  return (
    <div className="glass-panel p-5 rounded-2xl space-y-4">
      <div className="flex justify-between items-start">
        <div className="space-y-2 w-3/4">
          <Skeleton height="14px" width="40%" />
          <Skeleton height="22px" width="70%" />
        </div>
        <Skeleton height="32px" width="32px" borderRadius="8px" />
      </div>
      <Skeleton height="48px" width="100%" borderRadius="12px" />
    </div>
  );
};
