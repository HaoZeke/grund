import type { InputHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "flex h-12 w-full min-w-0 border border-[#1c1915] bg-[#fbf8f2] px-3 text-base text-[#1c1915] placeholder:text-[#4a433c] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#143d66] disabled:opacity-70",
        className,
      )}
      {...props}
    />
  );
}
