import { Link } from "react-router";

import { ROUTES } from "../../app/router/routes";
import { useAuth } from "../../app/providers/auth-context";

const FEATURES = [
  {
    title: "Генерация объекта",
    description: "Загрузите одну фотографию и получите отдельную 3D-модель.",
    icon: "◈",
  },
  {
    title: "Реконструкция сцены",
    description: "Загрузите несколько фотографий и восстановите окружение целиком.",
    icon: "◍",
  },
];

const STEPS = [
  "Загрузите фотографии",
  "Обработайте изображения",
  "Создайте 3D-контент",
  "Изучите и скачайте результат",
];

export function LandingPage() {
  const { isAuthenticated } = useAuth();
  const primaryTo = isAuthenticated ? ROUTES.dashboard : ROUTES.register;
  const primaryLabel = isAuthenticated ? "Открыть проекты" : "Начать";

  return (
    <div className="min-h-dvh bg-background">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-5">
        <span className="text-lg font-semibold tracking-tight text-text-primary">mogen</span>
        <nav aria-label="Навигация по сайту" className="flex items-center gap-3">
          {isAuthenticated ? (
            <Link
              to={ROUTES.dashboard}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-background transition hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              Мои проекты
            </Link>
          ) : (
            <>
              <Link
                to={ROUTES.login}
                className="rounded-lg px-3 py-2 text-sm font-medium text-text-secondary transition hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                Войти
              </Link>
              <Link
                to={ROUTES.register}
                className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-background transition hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                Создать аккаунт
              </Link>
            </>
          )}
        </nav>
      </header>

      <main>
        <section className="mx-auto grid w-full max-w-6xl gap-10 px-6 py-16 lg:grid-cols-2 lg:items-center lg:py-24">
          <div>
            <p className="text-sm font-medium uppercase tracking-[0.2em] text-accent">
              Фотографии → 3D
            </p>
            <h1 className="mt-4 text-4xl font-semibold leading-tight tracking-tight text-text-primary sm:text-5xl">
              Превратите фотографии в 3D-миры
            </h1>
            <p className="mt-5 max-w-xl text-base text-text-secondary">
              Создавайте детализированные 3D-объекты и реконструируйте целые окружения по
              фотографиям с помощью компьютерного зрения и искусственного интеллекта.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                to={primaryTo}
                className="rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-background transition hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                {primaryLabel}
              </Link>
              <a
                href="#features"
                className="rounded-lg border border-border bg-elevated px-5 py-2.5 text-sm font-medium text-text-primary transition hover:bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                Узнать больше
              </a>
            </div>
          </div>
          <div className="rounded-3xl border border-border bg-surface p-6 shadow-2xl">
            <div className="aspect-[4/3] rounded-2xl border border-border bg-background/60 p-6">
              <div className="grid h-full grid-cols-2 gap-4">
                <div className="flex items-center justify-center rounded-xl border border-border bg-elevated text-5xl text-accent">
                  ◈
                </div>
                <div className="flex items-center justify-center rounded-xl border border-border bg-elevated text-5xl text-accent">
                  ◍
                </div>
              </div>
            </div>
            <p className="mt-4 text-xs text-text-secondary">
              Два режима: объект по одной фотографии или сцена по серии снимков.
            </p>
          </div>
        </section>

        <section id="features" className="mx-auto w-full max-w-6xl px-6 py-12">
          <h2 className="text-2xl font-semibold tracking-tight text-text-primary">Возможности</h2>
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {FEATURES.map((feature) => (
              <article
                key={feature.title}
                className="rounded-2xl border border-border bg-surface p-6"
              >
                <span aria-hidden="true" className="text-2xl text-accent">
                  {feature.icon}
                </span>
                <h3 className="mt-3 text-lg font-semibold text-text-primary">{feature.title}</h3>
                <p className="mt-2 text-sm text-text-secondary">{feature.description}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="mx-auto w-full max-w-6xl px-6 py-12">
          <h2 className="text-2xl font-semibold tracking-tight text-text-primary">
            Как это работает
          </h2>
          <ol className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((step, index) => (
              <li key={step} className="rounded-2xl border border-border bg-surface p-5">
                <span className="text-sm font-semibold text-accent">{index + 1}</span>
                <p className="mt-2 text-sm text-text-primary">{step}</p>
              </li>
            ))}
          </ol>
        </section>
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-2 px-6 py-6 text-xs text-text-secondary sm:flex-row sm:items-center sm:justify-between">
          <span>mogen — генерация 3D по фотографиям</span>
          <span>MVP · {new Date().getFullYear()}</span>
        </div>
      </footer>
    </div>
  );
}
