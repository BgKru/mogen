// Khronos glTF Validator on a generated scene asset (no DOM required).
import { readFile } from "node:fs/promises";
import { validateBytes } from "gltf-validator";

const file = process.argv[2];
if (!file) {
  console.error("usage: node validate-glb.mjs <asset.glb>");
  process.exit(2);
}
const bytes = await readFile(file);
const report = await validateBytes(new Uint8Array(bytes));
const summary = {
  file,
  bytes: bytes.length,
  errors: report.issues.numErrors,
  warnings: report.issues.numWarnings,
  infos: report.issues.numInfos,
  hints: report.issues.numHints,
  messages: report.issues.messages,
  info: {
    version: report.info?.version,
    generator: report.info?.generator,
    drawCallCount: report.info?.drawCallCount,
    totalVertexCount: report.info?.totalVertexCount,
    totalTriangleCount: report.info?.totalTriangleCount,
    materialCount: report.info?.materialCount,
    hasTextures: report.info?.hasTextures,
    hasDefaultScene: report.info?.hasDefaultScene,
  },
};
console.log(JSON.stringify(summary, null, 2));
if (report.issues.numErrors > 0) process.exit(1);
