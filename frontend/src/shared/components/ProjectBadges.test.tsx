import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ProjectStatus, ProjectType } from "../../shared/types/api";
import { ProjectStatusBadge, ProjectTypeBadge } from "./ProjectBadges";

const STATUSES: Array<[ProjectStatus, string]> = [
  ["CREATED", "Создан"],
  ["UPLOADING", "Загрузка"],
  ["PENDING", "Ожидание"],
  ["PROCESSING", "Обработка"],
  ["COMPLETED", "Завершено"],
  ["FAILED", "Ошибка"],
];

const TYPES: Array<[ProjectType, string]> = [
  ["OBJECT", "Генерация объекта"],
  ["SCENE", "Реконструкция сцены"],
];

describe("ProjectStatusBadge", () => {
  it.each(STATUSES)("renders a text label for %s", (status, label) => {
    render(<ProjectStatusBadge status={status} />);

    expect(screen.getByText(label)).toBeInTheDocument();
  });
});

describe("ProjectTypeBadge", () => {
  it.each(TYPES)("renders a text label for %s", (type, label) => {
    render(<ProjectTypeBadge type={type} />);

    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
