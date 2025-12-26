import { ReactNode } from 'react';
import { Button } from './Button';
import { tokens } from './tokens';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
  className?: string;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className = '',
}: EmptyStateProps) {
  return (
    <div
      className={`flex flex-col items-center justify-center py-16 px-4 text-center ${className}`}
      role="status"
      aria-live="polite"
    >
      {icon && (
        <div className={`mb-4 text-zinc-500/60 ${tokens.transitions.opacity}`}>
          {icon}
        </div>
      )}
      <h3 className={`${tokens.typography.h4} mb-2 text-zinc-200`}>{title}</h3>
      {description && (
        <p className={`${tokens.typography.body} text-zinc-400 mb-6 max-w-md`}>
          {description}
        </p>
      )}
      {action && (
        <Button variant="primary" onClick={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  );
}
