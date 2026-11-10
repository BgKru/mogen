import { Canvas } from "@react-three/fiber";
import type { MutableRefObject } from "react";
import type { Object3D } from "three";

import type { ModelBounds, ViewerBackground, ViewerControlsHandle } from "../types/viewer.types";
import { ModelScene } from "./ModelScene";

interface ModelCanvasProps {
  model: Object3D;
  bounds: ModelBounds;
  showGrid: boolean;
  background: ViewerBackground;
  controller: MutableRefObject<ViewerControlsHandle>;
}

/**
 * Responsive React Three Fiber canvas.
 *
 * `flat` keeps the renderer's default tone mapping out of the way so vertex
 * colours and reconstructed textures keep the appearance validated by the
 * worker. Lighting is deliberately neutral; no post-processing is applied.
 */
export function ModelCanvas({ model, bounds, showGrid, background, controller }: ModelCanvasProps) {
  return (
    <Canvas
      flat
      dpr={[1, 2]}
      camera={{ fov: 45, position: [2, 2, 2], near: 0.01, far: 1000 }}
      gl={{ antialias: true }}
      className="h-full w-full"
    >
      <color attach="background" args={[background === "dark" ? "#101116" : "#dde2ea"]} />
      <hemisphereLight args={["#ffffff", "#223344", 1.6]} />
      <directionalLight position={[3, 4, 5]} intensity={2.2} />
      <directionalLight position={[-4, 2, -3]} intensity={0.9} color="#88bbff" />
      <ModelScene model={model} bounds={bounds} showGrid={showGrid} controller={controller} />
    </Canvas>
  );
}
