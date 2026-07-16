import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const sourceRoot = new URL("../src/", import.meta.url).pathname;

function listSourceFiles(directoryPath) {
  return readdirSync(directoryPath, { withFileTypes: true }).flatMap((entry) => {
    const entryPath = join(directoryPath, entry.name);
    if (entry.isDirectory()) {
      return listSourceFiles(entryPath);
    }
    return entryPath.endsWith(".jsx") || entryPath.endsWith(".js") ? [entryPath] : [];
  });
}

const files = listSourceFiles(sourceRoot);
const violations = [];

for (const filePath of files) {
  const content = readFileSync(filePath, "utf8");
  if (content.includes("window.location.reload()")) {
    violations.push(`${filePath}: uses window.location.reload()`);
  }
}

if (violations.length) {
  console.error(violations.join("\n"));
  process.exit(1);
}
