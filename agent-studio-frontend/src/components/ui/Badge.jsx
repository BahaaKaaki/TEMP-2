import { cn } from '@/lib/utils';

export default function Badge({ children, variant = "default", className }) {
  const variants = {
    default: "bg-secondary text-text",
    success: "bg-[rgba(var(--color-success-rgb),0.15)] text-[var(--color-success)] border border-[rgba(var(--color-success-rgb),0.25)]",
    error: "bg-[rgba(var(--color-error-rgb),0.15)] text-[var(--color-error)] border border-[rgba(var(--color-error-rgb),0.25)]",
    warning: "bg-[rgba(var(--color-warning-rgb),0.15)] text-[var(--color-warning)] border border-[rgba(var(--color-warning-rgb),0.25)]",
    info: "bg-[rgba(var(--color-info-rgb),0.15)] text-[var(--color-info)] border border-[rgba(var(--color-info-rgb),0.25)]"
  };

  return (
    <span
      className={cn(
        "inline-flex items-center px-12 py-6 rounded-full font-medium text-sm",
        variants[variant],
        className
      )}
    >
      {children}
    </span>
  );
}
