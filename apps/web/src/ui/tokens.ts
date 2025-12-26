/**
 * Design tokens for consistent spacing, radii, shadows, and typography
 * Premium trading cockpit design system
 * Base unit: 4px (0.25rem) for consistent rhythm
 */

export const tokens = {
  spacing: {
    // Padding scale (4px base unit)
    xs: 'p-2',      // 8px
    sm: 'p-3',      // 12px
    md: 'p-4',      // 16px
    lg: 'p-6',      // 24px
    xl: 'p-8',      // 32px
    '2xl': 'p-10',  // 40px
    // Gap scale
    gap: {
      xs: 'gap-1',   // 4px
      sm: 'gap-2',   // 8px
      md: 'gap-3',   // 12px
      lg: 'gap-4',   // 16px
      xl: 'gap-6',   // 24px
      '2xl': 'gap-8', // 32px
    },
    // Margin scale
    margin: {
      xs: 'm-1',    // 4px
      sm: 'm-2',    // 8px
      md: 'm-4',    // 16px
      lg: 'm-6',    // 24px
      xl: 'm-8',    // 32px
    },
  },
  radii: {
    none: 'rounded-none',
    sm: 'rounded-sm',      // 2px
    md: 'rounded-md',      // 6px
    lg: 'rounded-lg',      // 8px
    xl: 'rounded-xl',      // 12px
    '2xl': 'rounded-2xl',  // 16px
    full: 'rounded-full',
  },
  shadows: {
    none: 'shadow-none',
    sm: 'shadow-sm shadow-black/20',
    md: 'shadow-md shadow-black/30',
    lg: 'shadow-lg shadow-black/40',
    xl: 'shadow-xl shadow-black/50',
    inner: 'shadow-inner shadow-black/20',
  },
  typography: {
    // Headings - tighter tracking, bold weights
    h1: 'text-3xl font-bold tracking-tight text-zinc-100',
    h2: 'text-2xl font-semibold tracking-tight text-zinc-100',
    h3: 'text-xl font-semibold tracking-tight text-zinc-100',
    h4: 'text-lg font-medium text-zinc-100',
    h5: 'text-base font-medium text-zinc-100',
    h6: 'text-sm font-medium text-zinc-100',
    // Body text
    body: 'text-sm leading-6 text-zinc-300',
    bodyLarge: 'text-base leading-7 text-zinc-300',
    bodySmall: 'text-xs leading-5 text-zinc-400',
    // Labels and metadata
    label: 'text-xs font-medium uppercase tracking-wider text-zinc-500',
    labelSmall: 'text-[10px] font-medium uppercase tracking-widest text-zinc-500',
    // Monospace for data
    mono: 'font-mono text-sm text-zinc-200',
    monoSmall: 'font-mono text-xs text-zinc-300',
    // Numbers and stats
    number: 'font-mono font-semibold text-zinc-100',
    numberLarge: 'font-mono font-bold text-2xl text-zinc-100 tracking-tight',
  },
  colors: {
    accent: {
      primary: 'teal-500',
      hover: 'teal-600',
      active: 'teal-700',
      light: 'teal-400',
      dark: 'teal-600',
      bg: 'teal-500/10',
      border: 'teal-500/20',
    },
    surface: {
      base: 'zinc-900/95',
      elevated: 'zinc-800/95',
      overlay: 'zinc-900/98',
      border: 'zinc-800/50',
      borderHover: 'zinc-700/50',
      borderActive: 'zinc-600/50',
      hover: 'zinc-800/70',
      active: 'zinc-800/90',
    },
    status: {
      success: {
        text: 'text-emerald-400',
        bg: 'bg-emerald-500/10',
        border: 'border-emerald-500/20',
        solid: 'bg-emerald-500',
      },
      warning: {
        text: 'text-amber-400',
        bg: 'bg-amber-500/10',
        border: 'border-amber-500/20',
        solid: 'bg-amber-500',
      },
      error: {
        text: 'text-red-400',
        bg: 'bg-red-500/10',
        border: 'border-red-500/20',
        solid: 'bg-red-500',
      },
      info: {
        text: 'text-cyan-400',
        bg: 'bg-cyan-500/10',
        border: 'border-cyan-500/20',
        solid: 'bg-cyan-500',
      },
      neutral: {
        text: 'text-zinc-400',
        bg: 'bg-zinc-500/10',
        border: 'border-zinc-500/20',
        solid: 'bg-zinc-500',
      },
    },
  },
  transitions: {
    default: 'transition-all duration-200 ease-out',
    fast: 'transition-all duration-150 ease-out',
    slow: 'transition-all duration-300 ease-out',
    colors: 'transition-colors duration-150 ease-out',
    transform: 'transition-transform duration-200 ease-out',
    opacity: 'transition-opacity duration-150 ease-out',
  },
  focus: {
    ring: 'focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-zinc-900',
    ringTeal: 'focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-2 focus:ring-offset-zinc-900',
    ringZinc: 'focus:outline-none focus:ring-2 focus:ring-zinc-500 focus:ring-offset-2 focus:ring-offset-zinc-900',
  },
} as const;
