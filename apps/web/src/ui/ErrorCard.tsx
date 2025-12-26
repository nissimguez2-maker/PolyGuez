import { Card } from './Card';
import { Button } from './Button';

interface ErrorCardProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorCard({ title = 'Error', message, onRetry, className = '' }: ErrorCardProps) {
  return (
    <Card className={className}>
      <div className="flex items-start gap-4">
        <div className="flex-1">
          <h3 className="text-lg font-semibold text-red-400 mb-2">{title}</h3>
          <p className="text-sm text-zinc-400">{message}</p>
        </div>
        {onRetry && (
          <Button variant="secondary" onClick={onRetry}>
            Refresh
          </Button>
        )}
      </div>
    </Card>
  );
}

