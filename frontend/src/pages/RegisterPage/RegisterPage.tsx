import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useNavigate } from "react-router";

import { useAuth } from "../../app/providers/auth-context";
import { ROUTES } from "../../app/router/routes";
import { AuthCard } from "../../features/auth/components/AuthCard";
import { registerSchema, type RegisterValues } from "../../features/auth/schemas/authSchemas";
import { fieldErrorsFrom, userMessageFor } from "../../shared/api/errors";
import { Alert } from "../../shared/components/Alert";
import { Button } from "../../shared/components/Button";
import { Input } from "../../shared/components/Input";
import { Spinner } from "../../shared/components/Spinner";
import { createZodResolver } from "../../shared/lib/zodResolver";

export function RegisterPage() {
  const { status, register: registerAccount } = useAuth();
  const navigate = useNavigate();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<RegisterValues>({
    resolver: createZodResolver(registerSchema),
    defaultValues: { email: "", password: "", passwordConfirm: "" },
  });

  if (status === "loading") {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background">
        <Spinner className="h-8 w-8" />
      </div>
    );
  }

  if (status === "authenticated") {
    return <Navigate to={ROUTES.dashboard} replace />;
  }

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await registerAccount({ email: values.email, password: values.password });
      navigate(ROUTES.dashboard, { replace: true });
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
      title="Регистрация"
      subtitle="Создайте аккаунт, чтобы загружать фотографии и создавать 3D-проекты."
      footer={
        <>
          Уже есть аккаунт?{" "}
          <Link to={ROUTES.login} className="font-medium text-accent hover:underline">
            Войти
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
          autoComplete="new-password"
          hint="Минимум 8 символов."
          error={errors.password?.message}
          {...register("password")}
        />
        <Input
          label="Повторите пароль"
          type="password"
          autoComplete="new-password"
          error={errors.passwordConfirm?.message}
          {...register("passwordConfirm")}
        />
        <Button type="submit" className="w-full" isLoading={isSubmitting}>
          Создать аккаунт
        </Button>
      </form>
    </AuthCard>
  );
}
