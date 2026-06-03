import { forwardRef } from 'react';
import { cn } from '@/lib/utils';

const Select = forwardRef(({
  className,
  children,
  ...props
}, ref) => {
  return (
    <select
      ref={ref}
      className={cn(
        "custom-select block w-full px-3 py-2 text-sm font-medium text-white bg-[#121212]",
        "border border-[#464646] rounded-lg",
        "transition-all duration-200",
        "focus:border-[#d93854] focus:outline-none focus:ring-2 focus:ring-[#d93854]/30 focus:shadow-lg",
        "hover:border-[#d93854]/50",
        "cursor-pointer appearance-none",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        "bg-no-repeat bg-[right_0.75rem_center] bg-[length:1.125rem] pr-10",
        className
      )}
      {...props}
    >
      {children}
    </select>
  );
});

Select.displayName = "Select";

export default Select;
