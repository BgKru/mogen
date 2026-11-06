import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useLocation, useNavigate } from "react-router";

import { useAuth } from "../../app/providers/auth-context";
import { ROUTES } from "../../app/router/routes";
import { AuthCard } from "../../features/auth/components/AuthCard";
import { loginSchema, type LoginValues } from "../../features/auth/schemas/authSchemas";
import { fieldErrorsFrom, userMessageFor } from "../../shared/api/errors";
import { Alert } from "../../shared/components/Alert";
import { Button } from "../../shared/components/Button";
import { Input } from "../../shared/components/Input";
import { Spinner } from "../../shared/components/Spinner";
import { createZodResolver } from "../../shared/lib/zodResolver";

interface LocationState {
  from?: string;
}

export function LoginPage() {
  const { status, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as LocationState | null)?.from ?? ROUTES.dashboard;
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({
    resolver: createZodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  if (status === "loading") {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background">
        <Spinner className="h-8 w-8" />
      </div>
    );
  }

  if (status === "authenticated") {
    return <Navigate to={from} replace />;
  }

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await login(values);
      navigate(from, { replace: true });
    } catch (error) {
      const fieldErrors = fieldErrorsFrom(error);
      const knownFields = (["email", "password"] as const).filter((field) => fieldErrors[field]);
      if (knownFields.length > 0) {
        for (const field of knownFields) {
          setError(field, { message: fieldErrors[field] });
        }
      } else {
        setFormError(userMessageFor(error));
      }
    }
  });

  return (
    <AuthCard
      title="Вход"
      subtitle="Войдите, чтобы управлять проектами и результатами генерации."
      footer={
        <>
          Нет аккаунта?{" "}
          <Link to={ROUTES.register} className="font-medium text-accent hover:underline">
            Зарегистрироваться
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        {formError ? <Alert tone="error">{formError}</Alert> : null}
        <Input
          label="Email"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          error={errors.email?.message}
          {...register("email")}
        />
        <Input
          label="Пароль"
          type="password"
          autoComplete="current-password"
          error={errors.password?.message}
          {...register("password")}
        />
        <Button type="submit" className="w-full" isLoading={isSubmitting}>
          Войти
        </Button>
      </form>
    </AuthCard>
  );
}
