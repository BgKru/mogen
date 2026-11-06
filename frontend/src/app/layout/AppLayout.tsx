import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";

import { Button } from "../../shared/components/Button";
import { useAuth } from "../providers/auth-context";
import { ROUTES } from "../router/routes";

const NAV_ITEMS = [
  { to: ROUTES.dashboard, label: "Проекты" },
  { to: ROUTES.createProject, label: "Новый проект" },
];

function pageTitle(pathname: string): string {
  if (pathname === ROUTES.dashboard) {
    return "Мои проекты";
  }
  if (pathname === ROUTES.createProject) {
    return "Новый проект";
  }
  if (/^\/projects\/[^/]+$/.test(pathname)) {
    return "Проект";
  }
  return "mogen";
}

function navClass({ isActive }: { isActive: boolean }): string {
  return `rounded-lg px-3 py-2 text-sm font-medium transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
    isActive
      ? "bg-accent/15 text-accent"
      : "text-text-secondary hover:bg-elevated hover:text-text-primary"
  }`;
}

export function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  async function handleLogout() {
    setIsLoggingOut(true);
    try {
      await logout();
    } catch {
      // The local session is cleared even when the request fails.
    } finally {
      setIsLoggingOut(false);
      navigate(ROUTES.home, { replace: true });
    }
  }

  const email = user?.email ?? "";
  const initial = email.slice(0, 1).toUpperCase() || "?";

  return (
    <div className="flex min-h-dvh bg-background">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-sidebar p-4 md:flex">
        <NavLink
          to={ROUTES.dashboard}
          className="rounded-lg px-3 py-2 text-lg font-semibold tracking-tight text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          mogen
        </NavLink>
        <nav aria-label="Основная навигация" className="mt-6 flex flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} className={navClass} end>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto border-t border-border pt-4">
          <div className="flex items-center gap-3 px-2">
            <span
              aria-hidden="true"
              className="flex h-9 w-9 items-center justify-center rounded-full bg-elevated text-sm font-semibold text-accent"
            >
              {initial}
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-text-primary">{email}</p>
              <p className="text-xs text-text-secondary">Аккаунт</p>
            </div>
          </div>
          <Button
            variant="ghost"
            className="mt-3 w-full justify-start"
            onClick={handleLogout}
            isLoading={isLoggingOut}
          >
            Выйти
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 items-center justify-between gap-4 border-b border-border bg-background/80 px-4 backdrop-blur sm:px-6">
          <div className="flex items-center gap-4">
            <span className="text-base font-semibold text-text-primary md:hidden">mogen</span>
            <p className="hidden text-sm font-medium text-text-secondary md:block">
              {pageTitle(location.pathname)}
            </p>
            <nav aria-label="Мобильная навигация" className="flex items-center gap-1 md:hidden">
              {NAV_ITEMS.map((item) => (
                <NavLink key={item.to} to={item.to} className={navClass} end>
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden truncate text-sm text-text-secondary sm:block">{email}</span>
            <Button
              variant="ghost"
              className="md:hidden"
              onClick={handleLogout}
              isLoading={isLoggingOut}
            >
              Выйти
            </Button>
          </div>
        </header>
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <div className="mx-auto w-full max-w-[1440px]">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
