import { rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "..");
const frontendDirectory = path.join(repositoryRoot, "frontend");
const outputDirectories = [
  {
    directory: path.join(frontendDirectory, "js"),
    expectedParent: frontendDirectory,
    expectedName: "js",
  },
  {
    directory: path.join(frontendDirectory, "vendor", "maplibre-gl"),
    expectedParent: path.join(frontendDirectory, "vendor"),
    expectedName: "maplibre-gl",
  },
];

for (const { directory, expectedParent, expectedName } of outputDirectories) {
  if (
    path.dirname(directory) !== expectedParent
    || path.basename(directory) !== expectedName
  ) {
    throw new Error(`Refusing to clean unexpected frontend path: ${directory}`);
  }
  await rm(directory, { recursive: true, force: true });
}
