import { useEffect, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router";

import { useToast } from "../../app/providers/toast-context";
import { ROUTES } from "../../app/router/routes";
import { uploadProjectImage } from "../../features/image-upload/api/imagesApi";
import { GenerationModeCards } from "../../features/image-upload/components/GenerationModeCards";
import { ImageDropzone } from "../../features/image-upload/components/ImageDropzone";
import { useImageSelection } from "../../features/image-upload/hooks/useImageSelection";
import { useCreateProject } from "../../features/projects/hooks/useProjects";
import {
  createProjectSchema,
  type CreateProjectValues,
} from "../../features/projects/schemas/projectSchema";
import { appConfig } from "../../shared/config";
import { fieldErrorsFrom, userMessageFor } from "../../shared/api/errors";
import { Alert } from "../../shared/components/Alert";
import { Button } from "../../shared/components/Button";
import { Input } from "../../shared/components/Input";
import { PageHeader } from "../../shared/components/PageHeader";
import { createZodResolver } from "../../shared/lib/zodResolver";

interface UploadState {
  index: number;
  total: number;
  percent: number;
  filename: string;
}

export function CreateProjectPage() {
  const navigate = useNavigate();
  const { notify } = useToast();
  const createProjectMutation = useCreateProject();
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const [uploadState, setUploadState] = useState<UploadState | null>(null);
  const submittingRef = useRef(false);

  const resolver = useMemo(() => createZodResolver(createProjectSchema), []);
  const {
    register,
    handleSubmit,
    watch,
    setValue,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<CreateProjectValues>({
    resolver,
    mode: "onTouched",
    defaultValues: { name: "Мой 3D-проект", type: "OBJECT" },
  });

  const projectType = watch("type");
  const nameValue = watch("name");
  const isObject = projectType === "OBJECT";
  const selection = useImageSelection({
    mode: isObject ? "single" : "multiple",
    maxFiles: isObject ? 1 : appConfig.maxSceneImages,
  });
  const { items, errors: selectionErrors, addFiles, remove, clear, dismissErrors } = selection;

  useEffect(() => {
    clear();
  }, [projectType, clear]);

  const hasValidName = nameValue.trim().length > 0 && nameValue.trim().length <= 150;
  const hasValidImages = isObject ? items.length === 1 : items.length >= 1;
  const canSubmit = hasValidName && hasValidImages && !isSubmitting;

  const onSubmit = handleSubmit(async (values) => {
    if (submittingRef.current) {
      return;
    }
    submittingRef.current = true;
    setSubmissionError(null);
    try {
      const project = await createProjectMutation.mutateAsync({
        name: values.name.trim(),
        type: values.type,
      });

      const failures: string[] = [];
      for (const [index, item] of items.entries()) {
        setUploadState({
          index: index + 1,
          total: items.length,
          percent: 0,
          filename: item.file.name,
        });
        try {
          await uploadProjectImage(project.id, item.file, (percent) => {
            setUploadState((current) => (current ? { ...current, percent } : current));
          });
        } catch (error) {
          failures.push(`${item.file.name}: ${userMessageFor(error)}`);
        }
      }

      clear();
      setUploadState(null);

      if (failures.length > 0) {
        notify("Проект создан, но не все изображения загружены.", "error");
        navigate(ROUTES.projectDetails(project.id), {
          replace: true,
          state: { uploadFailures: failures },
        });
        return;
      }

      notify("Проект успешно создан.", "success");
      navigate(ROUTES.projectDetails(project.id), { replace: true });
    } catch (error) {
      setUploadState(null);
      const fieldErrors = fieldErrorsFrom(error);
      if (fieldErrors.name) {
        setError("name", { message: fieldErrors.name });
      } else if (fieldErrors.type) {
        setError("type", { message: fieldErrors.type });
      } else {
        setSubmissionError(userMessageFor(error));
      }
    } finally {
      submittingRef.current = false;
    }
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Новый проект"
        description="Выберите режим генерации, задайте название и добавьте исходные фотографии."
        actions={
          <Link
            to={ROUTES.dashboard}
            className="rounded-lg px-3 py-2 text-sm font-medium text-text-secondary transition hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Отмена
          </Link>
        }
      />

      <form onSubmit={onSubmit} noValidate className="space-y-6">
        {submissionError ? <Alert tone="error">{submissionError}</Alert> : null}

        <section className="rounded-2xl border border-border bg-surface p-5">
          <h2 className="text-lg font-semibold text-text-primary">Режим генерации</h2>
          <p className="mt-1 text-sm text-text-secondary">
            От режима зависит, сколько фотографий потребуется и какой результат вы получите.
          </p>
          <div className="mt-4">
            <GenerationModeCards
              value={projectType}
              onChange={(value) => setValue("type", value, { shouldValidate: true })}
              disabled={isSubmitting}
            />
          </div>
        </section>

        <section className="space-y-4 rounded-2xl border border-border bg-surface p-5">
          <Input
            label="Название проекта"
            placeholder="Например, «Кресло в гостиной»"
            maxLength={150}
            error={errors.name?.message}
            {...register("name")}
          />

          <div>
            <h2 className="text-lg font-semibold text-text-primary">
              {isObject ? "Фотография объекта" : "Фотографии сцены"}
            </h2>
            <p className="mt-1 text-sm text-text-secondary">
              {isObject
                ? "Для генерации объекта нужна ровно одна фотография."
                : "Добавьте несколько снимков одной локации с разных точек."}
            </p>
          </div>

          {selectionErrors.length > 0 ? (
            <Alert tone="error" title="Некоторые файлы не добавлены">
              <ul className="list-inside list-disc space-y-1">
                {selectionErrors.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
              <button
                type="button"
                onClick={dismissErrors}
                className="mt-2 text-xs font-medium underline"
              >
                Скрыть
              </button>
            </Alert>
          ) : null}

          <ImageDropzone
            mode={isObject ? "single" : "multiple"}
            items={items}
            onAdd={addFiles}
            onRemove={remove}
            disabled={isSubmitting}
            maxFiles={isObject ? 1 : appConfig.maxSceneImages}
          />

          {!isObject ? (
            <details className="rounded-xl border border-border bg-background/40 p-4">
              <summary className="cursor-pointer text-sm font-medium text-text-primary">
                Советы для лучшей реконструкции
              </summary>
              <ul className="mt-3 list-inside list-disc space-y-1 text-sm text-text-secondary">
                <li>Фотографируйте локацию с нескольких точек обзора.</li>
                <li>Оставляйте достаточное перекрытие между соседними снимками.</li>
                <li>Избегайте размытых фотографий.</li>
                <li>Используйте одинаковое освещение.</li>
                <li>Запечатлейте как можно большую часть окружения.</li>
                <li>Не допускайте движущихся объектов в кадре.</li>
              </ul>
              <p className="mt-2 text-xs text-text-secondary">
                Качество реконструкции зависит от качества снимков и покрытия камеры.
              </p>
            </details>
          ) : null}
        </section>

        {uploadState ? (
          <section
            className="rounded-2xl border border-accent/40 bg-accent/5 p-5"
            aria-live="polite"
          >
            <p className="text-sm font-medium text-text-primary">
              Загрузка {uploadState.index} из {uploadState.total}: {uploadState.filename}
            </p>
            <div
              className="mt-3 h-2 overflow-hidden rounded-full bg-background"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={uploadState.percent}
              aria-label="Прогресс загрузки изображения"
            >
              <div
                className="h-full rounded-full bg-accent transition-[width]"
                style={{ width: `${uploadState.percent}%` }}
              />
            </div>
          </section>
        ) : null}

        <div className="flex flex-col gap-3 sm:flex-row sm:justify-end">
          <Link
            to={ROUTES.dashboard}
            className="rounded-lg border border-border bg-elevated px-4 py-2 text-center text-sm font-medium text-text-primary transition hover:bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Отмена
          </Link>
          <Button type="submit" disabled={!canSubmit} isLoading={isSubmitting}>
            Создать проект
          </Button>
        </div>
        {!hasValidImages ? (
          <p className="text-right text-xs text-text-secondary">
            {isObject
              ? "Добавьте одну фотографию, чтобы создать проект."
              : "Добавьте хотя бы одну фотографию, чтобы создать проект."}
          </p>
        ) : null}
      </form>
    </div>
  );
}
