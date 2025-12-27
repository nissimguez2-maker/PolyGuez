import { tokens } from './tokens';

interface StatTileProps {
  label: string;
  value: string | number;
  subtext?: string;
  trend?: 'up' | 'down' | 'neutral';
  className?: string;
  onClick?: () => void;
}

export function StatTile({
  label,
  value,
  subtext,
  trend,
  className = '',
  onClick,
}: StatTileProps) {
  const trendColor =
    trend === 'up'
      ? 'text-emerald-400'
      : trend === 'down'
        ? 'text-red-400'
        : 'text-zinc-100';

  const interactiveClass = onClick
    ? 'cursor-pointer hover:border-zinc-700/50 hover:shadow-lg hover:-translate-y-0.5 active:translate-y-0'
    : '';

  return (
    <div
      className={`bg-zinc-900/95 border border-zinc-800/50 ${tokens.radii.lg} p-4 backdrop-blur-sm ${tokens.transitions.default} ${interactiveClass} ${className}`}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
    >
      <div className={`${tokens.typography.label} mb-2`}>{label}</div>
      <div className={`${tokens.typography.numberLarge} ${trendColor} mb-1`}>
        {value}
      </div>
      {subtext && (
        <div className={`${tokens.typography.bodySmall} mt-1.5`}>{subtext}</div>
      )}
    </div>
  );
}
