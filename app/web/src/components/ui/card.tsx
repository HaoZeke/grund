import type { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("border border-[#cfc6b8] bg-[#fbf8f2] text-[#1c1915]", className)}
      {...props}
    />
  );
}
