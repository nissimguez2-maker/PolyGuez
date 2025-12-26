import { tokens } from './tokens';

interface SkeletonProps {
  className?: string;
  lines?: number;
  height?: string;
  variant?: 'text' | 'circular' | 'rectangular';
  width?: string;
}

export function Skeleton({
  className = '',
  lines = 1,
  height = 'h-4',
  variant = 'rectangular',
  width,
}: SkeletonProps) {
  const variantClasses = {
    text: tokens.radii.md,
    circular: tokens.radii.full,
    rectangular: tokens.radii.md,
  };

  const widthClass = width || (variant === 'circular' ? height : 'w-full');

  if (lines === 1) {
    return (
      <div
        className={`animate-pulse bg-zinc-800/50 ${variantClasses[variant]} ${height} ${widthClass} ${className}`}
        role="status"
        aria-label="Loading"
        aria-live="polite"
      />
    );
  }

  return (
    <div className={`space-y-2 ${className}`} role="status" aria-label="Loading" aria-live="polite">
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className={`animate-pulse bg-zinc-800/50 ${variantClasses[variant]} ${height} ${widthClass}`}
        />
      ))}
    </div>
  );
}
