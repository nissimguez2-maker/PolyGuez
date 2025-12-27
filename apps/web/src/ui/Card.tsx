import { ReactNode, HTMLAttributes } from 'react';
import { tokens } from './tokens';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  className?: string;
  padding?: 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'none';
  hover?: boolean;
  variant?: 'default' | 'elevated' | 'outlined';
}

export function Card({
  children,
  className = '',
  padding = 'md',
  hover = false,
  variant = 'default',
  ...props
}: CardProps) {
  const paddingClass = padding === 'none' ? '' : tokens.spacing[padding];
  
  const variantClasses = {
    default: 'bg-zinc-900/95 border border-zinc-800/50',
    elevated: 'bg-zinc-800/95 border border-zinc-700/30 shadow-lg shadow-black/40',
    outlined: 'bg-transparent border-2 border-zinc-800/50',
  };

  const hoverClass = hover
    ? 'hover:border-zinc-700/50 hover:shadow-lg hover:shadow-black/40 hover:-translate-y-0.5'
    : '';

  return (
    <div
      {...props}
      className={`${variantClasses[variant]} ${tokens.radii.lg} ${tokens.shadows.md} ${paddingClass} backdrop-blur-sm ${tokens.transitions.default} ${hoverClass} ${className}`}
    >
      {children}
    </div>
  );
}
