import { readFile } from "node:fs/promises";
import path from "node:path";

import { notebooksByExperiment } from "@/lib/experiments";

/** Serves the Colab notebook for one experiment.
 *
 * The mapping comes from the shared registry rather than a second literal —
 * the previous copy listed two of the three notebooks, so the reranker's
 * download link would have 404'd even once the page offered it. */
export async function GET(
  _request: Request,
  context: { params: Promise<{ task: string }> },
) {
  const { task } = await context.params;
  const filename = Object.hasOwn(notebooksByExperiment, task)
    ? notebooksByExperiment[task]
    : undefined;
  if (!filename) return new Response("Unknown training notebook", { status: 404 });
  try {
    const data = await readFile(path.join(process.cwd(), "colab", filename));
    return new Response(data, {
      headers: {
        "Content-Type": "application/x-ipynb+json",
        "Content-Disposition": `attachment; filename="${filename}"`,
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    return new Response("Training notebook is unavailable", { status: 503 });
  }
}
