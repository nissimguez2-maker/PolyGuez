import { ReactNode } from 'react';
import { tokens } from './tokens';

interface SectionHeaderProps {
  title: string;
  actions?: ReactNode;
  description?: string;
  className?: string;
  divider?: boolean;
}

export function SectionHeader({
  title,
  actions,
  description,
  className = '',
  divider = false,
}: SectionHeaderProps) {
  return (
    <div className={`${divider ? 'border-b border-zinc-800/50 pb-4' : ''} mb-6 ${className}`}>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <h2 className={`${tokens.typography.h3} mb-1`}>{title}</h2>
          {description && (
            <p className={`${tokens.typography.bodySmall} mt-1.5`}>{description}</p>
          )}
        </div>
        {actions && (
          <div className={`flex items-center ${tokens.spacing.gap.sm} ml-4 flex-shrink-0`}>
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}
