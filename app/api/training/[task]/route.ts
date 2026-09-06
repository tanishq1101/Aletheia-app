import { readFile } from "node:fs/promises";
import path from "node:path";

const notebooks: Record<string, string> = {
  relevance: "Aletheia_Multisource_Relevance_Colab.ipynb",
  stance: "Aletheia_Scientific_Stance_Colab.ipynb",
};

export async function GET(_request: Request, context: { params: Promise<{ task: string }> }) {
  const { task } = await context.params;
  const filename = Object.hasOwn(notebooks, task) ? notebooks[task] : undefined;
  if (!filename) return new Response("Unknown training notebook", { status: 404 });
  try {
    const data = await readFile(path.join(process.cwd(), "colab", filename));
    return new Response(data, { headers: {
      "Content-Type": "application/x-ipynb+json",
      "Content-Disposition": `attachment; filename="${filename}"`,
      "X-Content-Type-Options": "nosniff",
    } });
  } catch {
    return new Response("Training notebook is unavailable", { status: 503 });
  }
}
