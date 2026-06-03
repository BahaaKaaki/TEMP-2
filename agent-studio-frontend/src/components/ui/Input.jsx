import { forwardRef } from 'react';
import { cn } from '@/lib/utils';

const Input = forwardRef(({
  className,
  type = "text",
  ...props
}, ref) => {
  return (
    <input
      type={type}
      ref={ref}
      className={cn(
        "block w-full px-4 py-2 text-base bg-[#121212]",
        "border border-[#464646] rounded-lg",
        "text-white",
        "placeholder:text-[#6b6b6b]",
        "transition-colors duration-fast ease-standard",
        "focus:border-[#d93854] focus:outline-none focus:ring-1 focus:ring-[#d93854]",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        className
      )}
      {...props}
    />
  );
});

Input.displayName = "Input";

export default Input;
