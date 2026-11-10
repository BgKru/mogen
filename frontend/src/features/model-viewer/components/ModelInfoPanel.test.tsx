import { screen } from "@testing-library/react";
import { BufferAttribute, BufferGeometry, Group, Mesh, MeshStandardMaterial } from "three";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "../../../test/render";
import { ModelInfoPanel } from "./ModelInfoPanel";
import type { GenerationResult, GenerationTaskSummary, Project } from "../../../shared/types/api";

const project: Project = {
  id: "9f1c2c1e-4a6e-4f8f-9d5b-2a7c3e4d5f60",
  name: "Замок Ссо",
  type: "SCENE",
  status: "COMPLETED",
  sourceImageCount: 11,
  resultAvailable: true,
  currentResult: null,
  latestTask: null,
  createdAt: "2026-11-08T10:00:00Z",
  updatedAt: "2026-11-08T10:05:00Z",
};

const result: GenerationResult = {
  id: "29dd63bc-8ebb-48a3-8808-c1b45f59db6c",
  projectId: project.id,
  taskId: "b738439b-457f-4f42-9257-9a4658ba07dd",
  format: "GLB",
  mimeType: "model/gltf-binary",
  fileSizeBytes: 959_504,
  metadata: { meshes_count: 1, vertices_count: 16_539, faces_count: 28_991 },
  isCurrent: true,
  createdAt: "2026-11-08T10:04:00Z",
};

const failedTask: GenerationTaskSummary = {
  id: "379073b3-80d5-4b1d-b571-2ea689cc39ff",
  taskType: "SCENE",
  status: "FAILED",
  stage: "SPARSE_RECONSTRUCTION",
  progressPercent: null,
  statusMessage: null,
  errorCode: "INSUFFICIENT_REGISTERED_IMAGES",
  errorMessage: null,
  createdAt: "2026-11-08T10:00:00Z",
  startedAt: null,
  finishedAt: null,
};

describe("ModelInfoPanel", () => {
  it("shows project, file and live mesh facts", () => {
    renderWithProviders(
      <ModelInfoPanel
        project={project}
        result={result}
        stats={null}
        latestTask={null}
        isProcessing={false}
      />,
    );

    expect(screen.getByRole("heading", { name: project.name })).toBeInTheDocument();
    expect(screen.getByText("Реконструкция сцены")).toBeInTheDocument();
    expect(screen.getByText("GLB")).toBeInTheDocument();
    expect(screen.getByText("937 КБ")).toBeInTheDocument();
    expect(screen.getByText("16 539")).toBeInTheDocument();
    expect(screen.getByText("28 991")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Скачать GLB" })).toHaveAttribute(
      "href",
      `/api/v1/projects/${project.id}/download`,
    );
  });

  it("prefers measurements from the loaded model", () => {
    const group = new Group();
    const geometry = new BufferGeometry();
    geometry.setAttribute(
      "position",
      new BufferAttribute(new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]), 3),
    );
    group.add(new Mesh(geometry, new MeshStandardMaterial()));

    renderWithProviders(
      <ModelInfoPanel
        project={project}
        result={result}
        stats={{
          meshes: 1,
          vertices: 3,
          triangles: 1,
          materials: 1,
          textures: 0,
          hasTextures: false,
          hasVertexColors: false,
        }}
        latestTask={null}
        isProcessing={false}
      />,
    );

    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.queryByText("16 539")).not.toBeInTheDocument();
  });

  it("keeps the previous result visible after a failed attempt", () => {
    renderWithProviders(
      <ModelInfoPanel
        project={project}
        result={result}
        stats={null}
        latestTask={failedTask}
        isProcessing={false}
      />,
    );

    expect(screen.getByText("Показан предыдущий результат")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Скачать GLB" })).toBeInTheDocument();
  });

  it("reports that a new generation is running", () => {
    renderWithProviders(
      <ModelInfoPanel
        project={project}
        result={result}
        stats={null}
        latestTask={null}
        isProcessing
      />,
    );

    expect(screen.getByText("Идёт новая генерация")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Перейти к проекту" })).toHaveAttribute(
      "href",
      `/projects/${project.id}`,
    );
  });
});
