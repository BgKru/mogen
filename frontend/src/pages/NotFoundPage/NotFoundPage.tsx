import { Link } from "react-router";

import { ROUTES } from "../../app/router/routes";

export function NotFoundPage() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-background p-6">
      <section className="w-full max-w-md rounded-2xl border border-border bg-surface p-8 text-center">
        <p className="text-sm font-medium uppercase tracking-[0.2em] text-accent">404</p>
        <h1 className="mt-3 text-2xl font-semibold text-text-primary">Страница не найдена</h1>
        <p className="mt-2 text-sm text-text-secondary">
          Запрошенная страница не существует или была перемещена.
        </p>
        <Link
          to={ROUTES.home}
          className="mt-6 inline-block rounded-lg bg-accent px-4 py-2 text-sm font-medium text-background transition hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          На главную
        </Link>
      </section>
    </main>
  );
}
