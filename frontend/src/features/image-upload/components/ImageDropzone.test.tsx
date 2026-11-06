import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "../../../test/render";
import type { SelectedImage } from "../hooks/useImageSelection";
import { ImageDropzone } from "./ImageDropzone";

function selectedImage(name = "photo.jpg"): SelectedImage {
  return {
    id: "image-1",
    file: new File([new Uint8Array([1, 2, 3])], name, { type: "image/jpeg" }),
    previewUrl: "blob:preview",
    width: 640,
    height: 480,
  };
}

function fileInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector('input[type="file"]');
  if (!(input instanceof HTMLInputElement)) {
    throw new Error("file input not found");
  }
  return input;
}

describe("ImageDropzone", () => {
  it("uses a single-file input in object mode", () => {
    const { container } = renderWithProviders(
      <ImageDropzone mode="single" items={[]} onAdd={vi.fn()} onRemove={vi.fn()} maxFiles={1} />,
    );

    expect(fileInput(container).multiple).toBe(false);
    expect(screen.getByText("Загрузить фотографию")).toBeInTheDocument();
  });

  it("uses a multi-file input in scene mode", () => {
    const { container } = renderWithProviders(
      <ImageDropzone mode="multiple" items={[]} onAdd={vi.fn()} onRemove={vi.fn()} maxFiles={10} />,
    );

    expect(fileInput(container).multiple).toBe(true);
    expect(screen.getByText("Загрузить изображения")).toBeInTheDocument();
  });

  it("passes selected files to the caller", async () => {
    const onAdd = vi.fn();
    const { container } = renderWithProviders(
      <ImageDropzone mode="single" items={[]} onAdd={onAdd} onRemove={vi.fn()} maxFiles={1} />,
    );
    const file = new File(["x"], "photo.jpg", { type: "image/jpeg" });

    fireEvent.change(fileInput(container), { target: { files: [file] } });

    await waitFor(() => expect(onAdd).toHaveBeenCalled());
  });

  it("renders previews and removes an image", () => {
    const onRemove = vi.fn();
    const image = selectedImage();
    renderWithProviders(
      <ImageDropzone
        mode="single"
        items={[image]}
        onAdd={vi.fn()}
        onRemove={onRemove}
        maxFiles={1}
      />,
    );

    expect(screen.getByAltText("Предпросмотр photo.jpg")).toBeInTheDocument();
    expect(screen.getByText("photo.jpg")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Удалить photo.jpg" }));

    expect(onRemove).toHaveBeenCalledWith(image.id);
  });

  it("disables the input and removal while disabled", () => {
    const image = selectedImage();
    const { container } = renderWithProviders(
      <ImageDropzone
        mode="single"
        items={[image]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        disabled
        maxFiles={1}
      />,
    );

    expect(fileInput(container)).toBeDisabled();
    expect(screen.getByRole("button", { name: "Удалить photo.jpg" })).toBeDisabled();
  });
});
