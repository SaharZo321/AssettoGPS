import { copyFile, mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "..");
const frontendDirectory = path.join(repositoryRoot, "frontend");
const packageDirectory = path.join(repositoryRoot, "node_modules", "maplibre-gl");
const distributionDirectory = path.join(packageDirectory, "dist");
const outputDirectory = path.join(frontendDirectory, "vendor", "maplibre-gl");

if (
  path.dirname(outputDirectory) !== path.join(frontendDirectory, "vendor")
  || path.basename(outputDirectory) !== "maplibre-gl"
) {
  throw new Error(`Refusing to write to unexpected frontend path: ${outputDirectory}`);
}

const projectManifest = JSON.parse(
  await readFile(path.join(repositoryRoot, "package.json"), "utf8")
);
const packageManifest = JSON.parse(
  await readFile(path.join(packageDirectory, "package.json"), "utf8")
);
const expectedVersion = projectManifest.dependencies?.["maplibre-gl"];

if (packageManifest.version !== expectedVersion) {
  throw new Error(
    `Expected maplibre-gl ${expectedVersion}, found ${packageManifest.version}`
  );
}

const assets = [
  ["maplibre-gl.mjs", path.join(distributionDirectory, "maplibre-gl.mjs")],
  ["maplibre-gl-shared.mjs", path.join(distributionDirectory, "maplibre-gl-shared.mjs")],
  ["maplibre-gl-worker.mjs", path.join(distributionDirectory, "maplibre-gl-worker.mjs")],
  ["maplibre-gl.css", path.join(distributionDirectory, "maplibre-gl.css")],
  ["LICENSE.txt", path.join(packageDirectory, "LICENSE.txt")],
];

await mkdir(outputDirectory, { recursive: true });
await Promise.all(
  assets.map(([name, source]) => copyFile(source, path.join(outputDirectory, name)))
);
