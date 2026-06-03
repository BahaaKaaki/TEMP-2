import { forwardRef } from 'react';
import { cn } from '@/lib/utils';

const Textarea = forwardRef(({
  className,
  ...props
}, ref) => {
  return (
    <textarea
      ref={ref}
      className={cn(
        "block w-full px-12 py-8 text-base text-text bg-[var(--color-surface)]",
        "border border-[var(--color-border)] rounded-base",
        "transition-colors duration-fast ease-standard",
        "focus:border-primary focus:outline focus:outline-2 focus:outline-primary",
        "placeholder:text-text-secondary",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        "resize-y",
        className
      )}
      {...props}
    />
  );
});

Textarea.displayName = "Textarea";

export default Textarea;
