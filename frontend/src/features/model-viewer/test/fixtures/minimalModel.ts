/**
 * A minimal valid GLB: one triangle, one standard material, no textures.
 *
 * Produced once with `.proof/make-viewer-fixture.mjs` (three.js GLTFLoader and
 * the Khronos validator accept it). Kept as base64 so Vitest can decode it in
 * jsdom without binary-asset transforms.
 */
export const MINIMAL_GLB_BASE64 =
  "Z2xURgIAAAD0AgAArAIAAEpTT057ImFzc2V0Ijp7InZlcnNpb24iOiIyLjAiLCJnZW5lcmF0b3IiOiJtb2dlbi12aWV3ZXItZml4dHVyZSJ9LCJzY2VuZSI6MCwic2NlbmVzIjpbeyJub2RlcyI6WzBdfV0sIm5vZGVzIjpbeyJtZXNoIjowLCJuYW1lIjoiVHJpYW5nbGUifV0sIm1lc2hlcyI6W3sicHJpbWl0aXZlcyI6W3siYXR0cmlidXRlcyI6eyJQT1NJVElPTiI6MH0sImluZGljZXMiOjEsIm1hdGVyaWFsIjowfV19XSwibWF0ZXJpYWxzIjpbeyJuYW1lIjoiRml4dHVyZSIsInBick1ldGFsbGljUm91Z2huZXNzIjp7ImJhc2VDb2xvckZhY3RvciI6WzAuOCwwLjQsMC4yLDFdLCJtZXRhbGxpY0ZhY3RvciI6MCwicm91Z2huZXNzRmFjdG9yIjoxfX1dLCJidWZmZXJzIjpbeyJieXRlTGVuZ3RoIjo0NH1dLCJidWZmZXJWaWV3cyI6W3siYnVmZmVyIjowLCJieXRlT2Zmc2V0IjowLCJieXRlTGVuZ3RoIjozNiwidGFyZ2V0IjozNDk2Mn0seyJidWZmZXIiOjAsImJ5dGVPZmZzZXQiOjM2LCJieXRlTGVuZ3RoIjo2LCJ0YXJnZXQiOjM0OTYzfV0sImFjY2Vzc29ycyI6W3siYnVmZmVyVmlldyI6MCwiY29tcG9uZW50VHlwZSI6NTEyNiwiY291bnQiOjMsInR5cGUiOiJWRUMzIiwibWluIjpbMCwwLDBdLCJtYXgiOlsxLDEsMF19LHsiYnVmZmVyVmlldyI6MSwiY29tcG9uZW50VHlwZSI6NTEyMywiY291bnQiOjMsInR5cGUiOiJTQ0FMQVIifV19ICAsAAAAQklOAAAAAAAAAAAAAAAAAAAAgD8AAAAAAAAAAAAAAAAAAIA/AAAAAAAAAQACAAAA";

/** Decode the fixture GLB into the ArrayBuffer GLTFLoader.parse expects. */
export function minimalGlbArrayBuffer(): ArrayBuffer {
  const binary = atob(MINIMAL_GLB_BASE64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

/** Decode the fixture GLB as a Blob, matching the download response type. */
export function minimalGlbBlob(): Blob {
  return new Blob([minimalGlbArrayBuffer()], { type: "model/gltf-binary" });
}
