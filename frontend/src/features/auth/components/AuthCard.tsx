import type { ReactNode } from "react";
import { Link } from "react-router";

import { ROUTES } from "../../../app/router/routes";

interface AuthCardProps {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer: ReactNode;
}

/** Centred authentication card shared by the login and registration pages. */
export function AuthCard({ title, subtitle, children, footer }: AuthCardProps) {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-4 py-10">
      <section className="w-full max-w-md rounded-2xl border border-border bg-surface p-8 shadow-2xl">
        <Link
          to={ROUTES.home}
          className="text-sm font-semibold tracking-tight text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          mogen
        </Link>
        <h1 className="mt-6 text-2xl font-semibold tracking-tight text-text-primary">{title}</h1>
        <p className="mt-2 text-sm text-text-secondary">{subtitle}</p>
        <div className="mt-6">{children}</div>
        <div className="mt-6 text-center text-sm text-text-secondary">{footer}</div>
      </section>
    </main>
  );
}
