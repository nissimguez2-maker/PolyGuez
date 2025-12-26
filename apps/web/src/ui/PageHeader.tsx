import { ReactNode } from 'react';
import { tokens } from './tokens';

interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: ReactNode;
  breadcrumbs?: ReactNode;
  className?: string;
  divider?: boolean;
}

export function PageHeader({
  title,
  description,
  actions,
  breadcrumbs,
  className = '',
  divider = true,
}: PageHeaderProps) {
  return (
    <div className={`${divider ? 'border-b border-zinc-800/50 pb-6' : 'pb-2'} mb-8 ${className}`}>
      {breadcrumbs && (
        <div className={`mb-3 ${tokens.typography.bodySmall} text-zinc-500`}>
          {breadcrumbs}
        </div>
      )}
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <h1 className={`${tokens.typography.h1} mb-2`}>{title}</h1>
          {description && (
            <p className={`${tokens.typography.body} text-zinc-400 max-w-2xl mt-1`}>
              {description}
            </p>
          )}
        </div>
        {actions && (
          <div className={`flex items-center ${tokens.spacing.gap.sm} flex-shrink-0`}>
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}
