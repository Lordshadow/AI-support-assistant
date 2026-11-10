import React from 'react';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'danger' | 'ghost' | 'glass';
  size?: 'sm' | 'md' | 'lg';
  isPill?: boolean;
  isLoading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  variant = 'primary',
  size = 'md',
  isPill = true,
  isLoading = false,
  leftIcon,
  rightIcon,
  children,
  className = '',
  disabled,
  ...props
}) => {
  const baseStyles = 'inline-flex items-center justify-center font-semibold transition-all duration-150 cursor-pointer select-none border disabled:opacity-50 disabled:cursor-not-allowed';
  
  const sizeStyles = {
    sm: 'text-xs px-3.5 py-1.5 gap-1.5 min-h-[32px]',
    md: 'text-sm px-5 py-2.5 gap-2 min-h-[40px]',
    lg: 'text-base px-7 py-3 gap-2.5 min-h-[48px]',
  }[size];

  const pillStyle = isPill ? 'rounded-full' : 'rounded-xl';

  // Variant Styles using our CSS Tokens
  const variantStyles = {
    primary: 'bg-[#3FD2C0] hover:bg-[#24C4B0] text-[#062F2E] border-transparent shadow-[0_4px_16px_rgba(63,210,192,0.3)] hover:shadow-[0_6px_20px_rgba(63,210,192,0.45)] hover:-translate-y-0.5 active:translate-y-0',
    secondary: 'bg-[rgba(11,74,71,0.7)] hover:bg-[rgba(15,92,88,0.9)] text-[#EAF6F4] border-[rgba(63,210,192,0.25)] hover:border-[#3FD2C0]',
    outline: 'bg-transparent hover:bg-[rgba(63,210,192,0.1)] text-[#3FD2C0] border-[#3FD2C0]',
    danger: 'bg-[rgba(255,82,82,0.2)] hover:bg-[rgba(255,82,82,0.35)] text-[#FF8585] border-[rgba(255,82,82,0.4)]',
    ghost: 'bg-transparent hover:bg-[rgba(255,255,255,0.08)] text-[#EAF6F4] border-transparent',
    glass: 'glass-chrome text-[#EAF6F4] hover:border-[#3FD2C0]',
  }[variant];

  return (
    <button
      className={`${baseStyles} ${sizeStyles} ${pillStyle} ${variantStyles} ${className}`}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading ? (
        <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin mr-1" />
      ) : leftIcon ? (
        <span className="inline-flex shrink-0">{leftIcon}</span>
      ) : null}
      <span>{children}</span>
      {!isLoading && rightIcon ? <span className="inline-flex shrink-0">{rightIcon}</span> : null}
    </button>
  );
};

export interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'circular' | 'square-arrow' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  title: string;
}

export const IconButton: React.FC<IconButtonProps> = ({
  variant = 'circular',
  size = 'md',
  title,
  children,
  className = '',
  ...props
}) => {
  const sizeStyles = {
    sm: 'w-7 h-7 text-xs',
    md: 'w-9 h-9 text-sm',
    lg: 'w-11 h-11 text-base',
  }[size];

  if (variant === 'square-arrow') {
    return (
      <button
        aria-label={title}
        title={title}
        className={`corner-detail-btn ${sizeStyles} ${className}`}
        {...props}
      >
        {children}
      </button>
    );
  }

  return (
    <button
      aria-label={title}
      title={title}
      className={`inline-flex items-center justify-center rounded-full bg-[rgba(11,74,71,0.8)] border border-[rgba(63,210,192,0.25)] text-[#EAF6F4] hover:text-[#3FD2C0] hover:border-[#3FD2C0] hover:bg-[rgba(15,92,88,0.95)] transition-all duration-150 cursor-pointer ${sizeStyles} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
};
