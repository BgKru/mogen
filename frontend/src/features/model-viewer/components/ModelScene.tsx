import { OrbitControls } from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import { useEffect, useRef, type ComponentRef, type MutableRefObject } from "react";
import { PerspectiveCamera, type Object3D } from "three";

import type { ModelBounds, ViewerControlsHandle } from "../types/viewer.types";
import { cameraPositionForBounds, clippingPlanesForRadius } from "../utils/modelBounds";

type OrbitControlsRef = ComponentRef<typeof OrbitControls>;

interface ModelSceneProps {
  model: Object3D;
  bounds: ModelBounds;
  showGrid: boolean;
  controller: MutableRefObject<ViewerControlsHandle>;
}

/**
 * Canvas contents: the parsed model, neutral lighting, an optional grid and
 * OrbitControls. The model is centred for display only; the exported asset is
 * never modified (03_frontend_specification.md 12.5–12.9).
 */
export function ModelScene({ model, bounds, showGrid, controller }: ModelSceneProps) {
  const { camera } = useThree();
  const controlsRef = useRef<OrbitControlsRef | null>(null);

  useEffect(() => {
    if (!(camera instanceof PerspectiveCamera)) {
      return;
    }

    model.position.set(-bounds.center.x, -bounds.center.y, -bounds.center.z);

    const applyCamera = () => {
      const { near, far } = clippingPlanesForRadius(bounds.radius);
      camera.near = near;
      camera.far = far;
      camera.position.copy(cameraPositionForBounds(bounds, camera.fov));
      camera.updateProjectionMatrix();
      const controls = controlsRef.current;
      if (controls) {
        controls.target.set(0, 0, 0);
        controls.update();
      } else {
        camera.lookAt(0, 0, 0);
      }
    };

    applyCamera();
    controller.current = { fit: applyCamera, reset: applyCamera };

    return () => {
      controller.current = { fit: () => undefined, reset: () => undefined };
    };
  }, [bounds, camera, controller, model]);

  const gridSize = Math.max(bounds.radius * 4, 1);
  const gridY = -bounds.size.y / 2 - bounds.radius * 0.01;

  return (
    <>
      <primitive object={model} dispose={null} />
      {showGrid ? (
        <gridHelper args={[gridSize, 20, "#3f4658", "#282d38"]} position={[0, gridY, 0]} />
      ) : null}
      <OrbitControls
        ref={controlsRef}
        makeDefault
        enableDamping
        dampingFactor={0.08}
        enablePan
        enableZoom
        enableRotate
        minDistance={Math.max(bounds.radius * 0.05, 0.001)}
        maxDistance={Math.max(bounds.radius * 20, 1)}
      />
    </>
  );
}
