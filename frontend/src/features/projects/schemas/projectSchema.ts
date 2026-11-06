import { z } from "zod";

export const createProjectSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Введите название проекта.")
    .max(150, "Название должно содержать не более 150 символов."),
  type: z.enum(["OBJECT", "SCENE"], {
    message: "Выберите режим генерации.",
  }),
});

export type CreateProjectValues = z.infer<typeof createProjectSchema>;
