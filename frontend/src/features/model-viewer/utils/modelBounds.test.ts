import { Mesh, MeshStandardMaterial, BoxGeometry, Object3D, Vector3 } from "three";
import { describe, expect, it } from "vitest";

import {
  cameraDistanceForBounds,
  cameraPositionForBounds,
  clippingPlanesForRadius,
  computeModelBounds,
} from "./modelBounds";

describe("modelBounds", () => {
  it("measures a centred 2x2x2 box", () => {
    const mesh = new Mesh(new BoxGeometry(2, 2, 2), new MeshStandardMaterial());
    const bounds = computeModelBounds(mesh);

    expect(bounds.center.distanceTo(new Vector3(0, 0, 0))).toBeLessThan(1e-9);
    expect(bounds.size.x).toBeCloseTo(2);
    expect(bounds.size.y).toBeCloseTo(2);
    expect(bounds.size.z).toBeCloseTo(2);
    expect(bounds.radius).toBeCloseTo(Math.sqrt(3));
  });

  it("respects an object offset without mutating it", () => {
    const group = new Object3D();
    const mesh = new Mesh(new BoxGeometry(1, 1, 1), new MeshStandardMaterial());
    mesh.position.set(4, 2, 0);
    group.add(mesh);

    const bounds = computeModelBounds(group);

    expect(bounds.center.x).toBeCloseTo(4);
    expect(bounds.center.y).toBeCloseTo(2);
    expect(mesh.position.x).toBe(4);
  });

  it("returns a safe radius for an empty object", () => {
    const bounds = computeModelBounds(new Object3D());
    expect(bounds.radius).toBeGreaterThan(0);
  });

  it("frames the model with a positive distance and sane clipping planes", () => {
    const distance = cameraDistanceForBounds(1, 45);
    expect(distance).toBeGreaterThan(1);

    const position = cameraPositionForBounds(
      { center: new Vector3(), size: new Vector3(2, 2, 2), radius: 1 },
      45,
    );
    expect(position.length()).toBeCloseTo(distance);

    const { near, far } = clippingPlanesForRadius(1);
    expect(near).toBeGreaterThan(0);
    expect(far).toBeGreaterThan(near);
  });
});
