import { ButtonHTMLAttributes, ReactNode } from 'react';
import { tokens } from './tokens';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  children: ReactNode;
  fullWidth?: boolean;
}

export function Button({
  variant = 'primary',
  size = 'md',
  children,
  className = '',
  disabled,
  fullWidth = false,
  ...props
}: ButtonProps) {
  const sizeClasses = {
    sm: 'px-3 py-1.5 text-xs',
    md: 'px-4 py-2 text-sm',
    lg: 'px-6 py-3 text-base',
  };

  const baseClasses = `${sizeClasses[size]} ${tokens.radii.md} font-medium ${tokens.transitions.fast} disabled:opacity-50 disabled:cursor-not-allowed ${tokens.focus.ringTeal} ${fullWidth ? 'w-full' : ''}`;

  const variantClasses = {
    primary:
      'bg-teal-600 hover:bg-teal-700 active:bg-teal-800 text-white shadow-sm hover:shadow-md focus:ring-teal-500',
    secondary:
      'bg-zinc-800 hover:bg-zinc-700 active:bg-zinc-600 text-zinc-100 border border-zinc-700 hover:border-zinc-600 focus:ring-zinc-500',
    ghost:
      'hover:bg-zinc-800/50 active:bg-zinc-800/70 text-zinc-300 hover:text-zinc-100 focus:ring-zinc-500',
    danger:
      'bg-red-600/90 hover:bg-red-700 active:bg-red-800 text-white shadow-sm hover:shadow-md focus:ring-red-500',
  };

  return (
    <button
      {...props}
      className={`${baseClasses} ${variantClasses[variant]} ${className}`}
      disabled={disabled}
      aria-disabled={disabled}
    >
      {children}
    </button>
  );
}
