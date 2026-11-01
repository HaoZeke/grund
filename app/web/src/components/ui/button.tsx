import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap text-sm font-semibold transition-colors disabled:pointer-events-none disabled:bg-[#d9d0c4] disabled:text-[#1c1915] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#143d66]",
  {
    variants: {
      variant: {
        default: "bg-[#143d66] text-[#f6f1e7] hover:bg-[#0e2c4c]",
        outline: "border border-[#cfc6b8] bg-transparent text-[#1c1915] hover:bg-[#efe8dc]",
        stamp: "bg-[#8f1d2c] text-[#f6f1e7] hover:bg-[#731624]",
        ghost: "bg-transparent text-[#143d66] hover:bg-[#efe8dc]",
      },
      size: {
        default: "h-11 px-4",
        sm: "h-8 px-3 text-xs tracking-wide",
        icon: "h-11 w-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean };

export function Button({ className, variant, size, asChild = false, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : "button";
  return <Comp className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
