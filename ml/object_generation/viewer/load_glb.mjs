/**
 * Load a generated GLB with the same Three.js GLTFLoader the viewer will use.
 *
 * Usage: node load_glb.mjs /path/to/model.glb
 *
 * This is the "compatible viewer" check from roadmap task 5.2: it parses the
 * file through Three.js and reports geometry, material and vertex-colour facts.
 * It intentionally performs no rendering; the browser screenshot uses
 * viewer.html with the same loader.
 *
 * Scene reconstructions are textured rather than vertex-coloured. Pass
 * `--allow-textured` to require texture/UV facts instead of COLOR_0 (Phase 6
 * SCENE-AC-22 evidence); the default object-generation behaviour is unchanged.
 */
import { readFile } from "node:fs/promises";
import { Box3, Vector3 } from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { validateBytes } from "gltf-validator";

const args = process.argv.slice(2);
const allowTextured = args.includes("--allow-textured");
const path = args.find((value) => !value.startsWith("--"));
if (!path) {
  console.error("usage: node load_glb.mjs [--allow-textured] <model.glb>");
  process.exit(2);
}

const bytes = await readFile(path);
const arrayBuffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);

// Khronos official glTF Validator (structural conformance).
const report = await validateBytes(new Uint8Array(arrayBuffer));
if (report.issues.numErrors > 0) {
  console.error("glTF Validator errors:", JSON.stringify(report.issues.messages, null, 2));
  process.exit(1);
}

const loader = new GLTFLoader();
const gltf = await new Promise((resolve, reject) => {
  loader.parse(arrayBuffer, "", resolve, reject);
});

let meshes = 0;
let vertices = 0;
let triangles = 0;
let coloredPrimitives = 0;
let texturedPrimitives = 0;
let uvPrimitives = 0;
const materials = new Set();

gltf.scene.traverse((object) => {
  if (!object.isMesh) return;
  meshes += 1;
  const geometry = object.geometry;
  const position = geometry.getAttribute("position");
  vertices += position?.count ?? 0;
  const index = geometry.getIndex();
  triangles += (index ? index.count : position?.count ?? 0) / 3;
  if (geometry.getAttribute("color")) coloredPrimitives += 1;
  if (geometry.getAttribute("uv")) uvPrimitives += 1;
  const materialList = Array.isArray(object.material) ? object.material : [object.material];
  for (const material of materialList) {
    if (!material) continue;
    materials.add(material.uuid);
    if (material.map) texturedPrimitives += 1;
  }
});

const bounds = new Box3().setFromObject(gltf.scene);
const size = bounds.getSize(new Vector3());

if (meshes < 1 || vertices < 3 || triangles < 1) {
  console.error("Three.js loaded no usable geometry", { meshes, vertices, triangles });
  process.exit(1);
}
if (allowTextured) {
  if (uvPrimitives < 1) {
    console.error("Three.js found no UV coordinates on the scene mesh");
    process.exit(1);
  }
  if (texturedPrimitives < 1) {
    console.error("Three.js found no textured material on the scene mesh");
    process.exit(1);
  }
} else if (coloredPrimitives < 1) {
  console.error("Three.js found no COLOR_0 vertex colours");
  process.exit(1);
}

console.log(
  JSON.stringify(
    {
      threejs: "loaded",
      gltfValidatorErrors: report.issues.numErrors,
      gltfValidatorWarnings: report.issues.numWarnings,
      meshes,
      vertices,
      triangles: Math.round(triangles),
      coloredPrimitives,
      texturedPrimitives,
      uvPrimitives,
      materials: materials.size,
      boundingBox: { width: size.x, height: size.y, depth: size.z },
    },
    null,
    2,
  ),
);
