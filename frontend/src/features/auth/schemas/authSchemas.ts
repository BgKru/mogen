import { z } from "zod";

export const loginSchema = z.object({
  email: z.string().min(1, "Введите email.").email("Введите корректный email."),
  password: z.string().min(1, "Введите пароль."),
});

export type LoginValues = z.infer<typeof loginSchema>;

export const registerSchema = z
  .object({
    email: z.string().min(1, "Введите email.").email("Введите корректный email."),
    password: z
      .string()
      .min(8, "Пароль должен содержать минимум 8 символов.")
      .max(128, "Пароль должен содержать не более 128 символов."),
    passwordConfirm: z.string().min(1, "Повторите пароль."),
  })
  .refine((values) => values.password === values.passwordConfirm, {
    path: ["passwordConfirm"],
    message: "Пароли не совпадают.",
  });

export type RegisterValues = z.infer<typeof registerSchema>;
