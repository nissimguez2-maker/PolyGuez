import { ReactNode } from 'react';
import { tokens } from './tokens';

interface ChipProps {
  label: string;
  status: 'success' | 'warning' | 'error' | 'neutral' | 'info';
  icon?: ReactNode;
  className?: string;
  size?: 'sm' | 'md';
}

export function Chip({ label, status, icon, className = '', size = 'md' }: ChipProps) {
  const sizeClasses = {
    sm: 'px-2 py-0.5 text-[10px]',
    md: 'px-2.5 py-1 text-xs',
  };

  const statusConfig = tokens.colors.status[status];

  return (
    <div
      className={`inline-flex items-center gap-1.5 ${sizeClasses[size]} ${tokens.radii.md} font-medium border ${statusConfig.bg} ${statusConfig.text} ${statusConfig.border} ${tokens.transitions.colors} ${className}`}
      role="status"
      aria-label={`${status}: ${label}`}
    >
      {icon && <span className="flex-shrink-0 leading-none">{icon}</span>}
      <span>{label}</span>
    </div>
  );
}
