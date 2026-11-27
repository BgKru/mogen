declare module "@mkkellogg/gaussian-splats-3d" {

  export enum SceneFormat {
    Splat = 0,
    KSplat = 1,
    Ply = 2,
  }

  export interface SplatSceneOptions {
    format?: SceneFormat;
    showLoadingUI?: boolean;
    splatAlphaRemovalThreshold?: number;
    position?: [number, number, number];
    rotation?: [number, number, number, number];
    scale?: [number, number, number];
    onProgress?: (percent: number) => void;
  }

  export class DropInViewer extends Object3D {
    constructor(options?: Record<string, unknown>);
    addSplatScene(path: string, options?: SplatSceneOptions): Promise<void>;
    addSplatScenes(
      scenes: Array<{ path: string } & SplatSceneOptions>,
      showLoadingUI?: boolean,
    ): Promise<void>;
    setActiveSphericalHarmonicsDegrees(degrees: number): void;
    dispose(): Promise<void>;
  }
}
