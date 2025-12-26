import { ReactNode, HTMLAttributes } from 'react';
import { tokens } from './tokens';

interface TableProps {
  children: ReactNode;
  className?: string;
  compact?: boolean;
}

export function Table({ children, className = '', compact = false }: TableProps) {
  return (
    <div className={`overflow-x-auto ${className}`}>
      <table className={`w-full border-collapse ${compact ? 'text-xs' : 'text-sm'}`}>
        {children}
      </table>
    </div>
  );
}

interface TableHeaderProps {
  children: ReactNode;
}

export function TableHeader({ children }: TableHeaderProps) {
  return (
    <thead>
      <tr className="border-b border-zinc-800/70 bg-zinc-900/50">{children}</tr>
    </thead>
  );
}

interface TableHeaderCellProps {
  children?: ReactNode;
  align?: 'left' | 'right' | 'center';
  className?: string;
  numeric?: boolean;
}

export function TableHeaderCell({
  children,
  align,
  className = '',
  numeric = false,
}: TableHeaderCellProps) {
  const alignClass = align || (numeric ? 'right' : 'left');
  const textAlign = {
    left: 'text-left',
    right: 'text-right',
    center: 'text-center',
  }[alignClass];

  return (
    <th
      className={`py-2.5 px-4 ${tokens.typography.label} ${textAlign} ${className}`}
      scope="col"
    >
      {children}
    </th>
  );
}

interface TableBodyProps {
  children: ReactNode;
}

export function TableBody({ children }: TableBodyProps) {
  return <tbody>{children}</tbody>;
}

interface TableRowProps extends HTMLAttributes<HTMLTableRowElement> {
  children: ReactNode;
  onClick?: () => void;
  className?: string;
  selected?: boolean;
}

export function TableRow({
  children,
  onClick,
  className = '',
  selected = false,
  ...props
}: TableRowProps) {
  const baseClasses = `border-b border-zinc-800/50 ${tokens.transitions.colors}`;
  const interactiveClasses = onClick
    ? 'hover:bg-zinc-800/30 cursor-pointer active:bg-zinc-800/40 focus-within:bg-zinc-800/20'
    : 'hover:bg-zinc-800/20';
  const selectedClass = selected ? 'bg-teal-500/10 border-teal-500/20' : '';

  return (
    <tr
      className={`${baseClasses} ${interactiveClasses} ${selectedClass} ${className}`}
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
      {...props}
    >
      {children}
    </tr>
  );
}

interface TableCellProps {
  children: ReactNode;
  align?: 'left' | 'right' | 'center';
  className?: string;
  colSpan?: number;
  numeric?: boolean;
}

export function TableCell({
  children,
  align,
  className = '',
  colSpan,
  numeric = false,
}: TableCellProps) {
  const alignClass = align || (numeric ? 'right' : 'left');
  const textAlign = {
    left: 'text-left',
    right: 'text-right',
    center: 'text-center',
  }[alignClass];

  const fontClass = numeric ? tokens.typography.monoSmall : '';

  return (
    <td
      className={`py-2.5 px-4 text-zinc-300 ${textAlign} ${fontClass} ${className}`}
      colSpan={colSpan}
    >
      {children}
    </td>
  );
}
