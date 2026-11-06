import type { ReactNode } from "react";

type AlertTone = "error" | "info" | "success" | "warning";

interface AlertProps {
  tone?: AlertTone;
  title?: string;
  children: ReactNode;
  className?: string;
}

const TONE_CLASSES: Record<AlertTone, string> = {
  error: "border-error/40 bg-error/10 text-error",
  info: "border-accent/40 bg-accent/10 text-accent",
  success: "border-success/40 bg-success/10 text-success",
  warning: "border-warning/40 bg-warning/10 text-warning",
};

export function Alert({ tone = "error", title, children, className = "" }: AlertProps) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-xl border px-4 py-3 text-sm ${TONE_CLASSES[tone]} ${className}`}
    >
      {title ? <p className="font-medium">{title}</p> : null}
      <div className={title ? "mt-1 opacity-90" : "opacity-90"}>{children}</div>
    </div>
  );
}
