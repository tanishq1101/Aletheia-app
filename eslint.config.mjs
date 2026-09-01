import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // The FastAPI service and its own tooling live here; it is not part of
    // this Next app's lint or type-check surface.
    "backend/**",
  ]),
]);

export default eslintConfig;
