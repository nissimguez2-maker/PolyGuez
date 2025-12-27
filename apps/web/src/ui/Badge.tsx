interface BadgeProps {
  status: 'running' | 'paused' | 'error';
  children?: React.ReactNode;
}

export function Badge({ status, children }: BadgeProps) {
  const statusClasses = {
    running: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
    paused: 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30',
    error: 'bg-red-500/20 text-red-400 border-red-500/30',
  };

  const statusLabels = {
    running: 'Running',
    paused: 'Paused',
    error: 'Error',
  };

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${statusClasses[status]}`}
    >
      {children ?? statusLabels[status]}
    </span>
  );
}

