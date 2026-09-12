import Link from "next/link";
import type { ReactNode } from "react";

/** The public landing page.
 *
 * This used to be a redirect into `/library`, which meant a signed-out visitor
 * was bounced straight to a sign-in form having never been told what the thing
 * is. Everything claimed below is something the system actually does; the
 * numbers are the ones recorded in `backend/docs/research-models.md` and the
 * model artifacts, not rounded-up versions of them. The one model that
 * underperforms is stated as underperforming — a page about not fabricating
 * citations is a bad place to start fabricating results.
 */

const authConfigured = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);

export const metadata = {
  title: "Aletheia — grounded research intelligence",
  description:
    "Ask questions across your own papers and get answers whose every citation is checked against the retrieved evidence, or an honest refusal.",
};

type Capability = {
  name: string;
  href: string;
  blurb: string;
};

const capabilities: Capability[] = [
  {
    name: "Search",
    href: "/search",
    blurb:
      "Semantic retrieval over every page you have ingested, reranked by a cross-encoder rather than by keyword overlap.",
  },
  {
    name: "Ask",
    href: "/ask",
    blurb:
      "A grounded answer with inline citations. Every cited passage is one the retriever actually returned.",
  },
  {
    name: "Research Agent",
    href: "/agent",
    blurb:
      "A bounded planner that breaks a question into sub-questions, answers each from the corpus, and returns the full trace.",
  },
  {
    name: "Cross-Paper",
    href: "/cross-paper",
    blurb:
      "Where several papers agree, disagree, or simply do not address the same thing — with the passages that decide it.",
  },
  {
    name: "Claim Verification",
    href: "/claim-verification",
    blurb:
      "Take a claim, find what the corpus says about it, and label it supported, contradicted or unaddressed.",
  },
  {
    name: "Reproducibility",
    href: "/reproducibility",
    blurb:
      "What a paper actually gives you: code, data, environment, hardware — and what it leaves out.",
  },
  {
    name: "Training Lab",
    href: "/training",
    blurb:
      "The three models trained for this project, their learning curves, held-out metrics, and downloadable notebooks.",
  },
  {
    name: "Library",
    href: "/library",
    blurb:
      "Upload PDFs and watch them parse into pages, sections, figures, tables and equation candidates.",
  },
];

type Guarantee = {
  eyebrow: string;
  title: string;
  body: ReactNode;
};

const guarantees: Guarantee[] = [
  {
    eyebrow: "01",
    title: "A citation it cannot support is not returned",
    body: (
      <>
        Evidence passages are handed to the model with opaque IDs, and the
        answer is re-checked against them server-side. An ID the model invented
        is not a footnote that happens to be wrong — it fails validation, and
        the answer does not ship with it.
      </>
    ),
  },
  {
    eyebrow: "02",
    title: "“The corpus does not say” is a valid answer",
    body: (
      <>
        When the retrieved passages do not settle a question, the system says
        so instead of assembling a fluent paragraph out of the nearest
        available text. Most of the damage done by research assistants is done
        confidently.
      </>
    ),
  },
  {
    eyebrow: "03",
    title: "The retrieval runs on your machine",
    body: (
      <>
        Embeddings and reranking are local ONNX models — no key, no per-query
        spend, and no page of your unpublished work sent anywhere to be
        indexed. Only the final answering step calls a hosted model.
      </>
    ),
  },
  {
    eyebrow: "04",
    title: "The evaluation splits are leakage-free",
    body: (
      <>
        Held-out sets are split by question ID, so passages from one question
        cannot appear on both sides. It is the difference between a metric and
        a number that looks like one.
      </>
    ),
  },
];

const pipeline = [
  { step: "Ingest", detail: "PDF → pages, sections, figures, tables, equations" },
  { step: "Embed", detail: "jina-embeddings-v2-small-en, locally" },
  { step: "Retrieve", detail: "Chroma, falling back to pgvector" },
  { step: "Rerank", detail: "cross-encoder over the candidate set" },
  { step: "Answer", detail: "grounded generation with opaque evidence IDs" },
  { step: "Validate", detail: "every citation checked before it is returned" },
];

const models = [
  {
    name: "Multi-source relevance",
    result: "89.87%",
    caption: "held-out accuracy, against an 84.96% lexical baseline",
    good: true,
  },
  {
    name: "Neural reranker",
    result: "0.717 MRR",
    caption: "Recall@6 0.799, reproduced exactly on a full re-ingest",
    good: true,
  },
  {
    name: "Scientific stance",
    result: "54%",
    caption: "experimental — below its majority-class baseline, and shipped saying so",
    good: false,
  },
];

function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <p className="font-mono text-[11px] tracking-[1.32px] text-brass">{children}</p>
  );
}

export default function LandingPage() {
  return (
    <main className="flex w-full flex-1 flex-col items-center bg-base">
      {/* --- Masthead ------------------------------------------------------ */}
      <header className="flex w-full max-w-[1120px] items-center justify-between px-6 py-6 sm:px-10">
        <div className="flex items-center gap-3">
          <div className="h-[2px] w-8 bg-brass" />
          <span className="font-display text-[17px] font-black tracking-tight text-primary">
            Aletheia
          </span>
        </div>
        <nav className="flex items-center gap-2 sm:gap-4">
          <Link
            href="/sign-in"
            className="rounded-md px-3 py-2 font-ui text-[13px] text-secondary transition-colors hover:text-primary"
          >
            Sign in
          </Link>
          <Link
            href={authConfigured ? "/sign-up" : "/library"}
            className="rounded-md border border-hairline bg-surface px-4 py-2 font-ui text-[13px] font-medium text-primary transition-colors hover:border-brass"
          >
            {authConfigured ? "Create account" : "Open the app"}
          </Link>
        </nav>
      </header>

      {/* --- Hero ---------------------------------------------------------- */}
      <section className="flex w-full max-w-[1120px] flex-col gap-10 px-6 pb-20 pt-12 sm:px-10 sm:pt-20">
        <div className="flex max-w-[760px] flex-col gap-6">
          <Eyebrow>THE ARCHIVE</Eyebrow>
          <h1 className="font-display text-[40px] font-black leading-[1.08] tracking-tight text-primary sm:text-[62px]">
            Answers you can follow
            <br />
            back to the page.
          </h1>
          <p className="max-w-[620px] font-reading text-[17px] leading-[1.65] text-secondary sm:text-[19px]">
            Aletheia reads the papers you give it and answers questions across
            them. Every citation in an answer is checked against the passages
            that were actually retrieved — so a reference either resolves to
            real text in your library, or the answer does not make it.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Link
            href={authConfigured ? "/sign-up" : "/library"}
            className="rounded-md bg-oxblood px-6 py-[13px] font-ui text-sm font-semibold text-primary transition-colors hover:bg-oxblood-bright"
          >
            {authConfigured ? "Create an account" : "Continue to the library"}
          </Link>
          <Link
            href="/search"
            className="rounded-md border border-hairline bg-surface px-6 py-[13px] font-ui text-sm font-semibold text-primary transition-colors hover:border-brass"
          >
            Explore the workspace
          </Link>
        </div>

        {!authConfigured && (
          <p className="max-w-[620px] rounded-md border border-hairline-subtle bg-surface px-4 py-3 font-ui text-xs leading-relaxed text-muted">
            This build has no Clerk keys configured, so sign-in is switched off
            and everything belongs to a single seeded development user. Anyone
            who can reach it can read and change everything in it.
          </p>
        )}
      </section>

      {/* --- The problem --------------------------------------------------- */}
      <section className="w-full border-y border-hairline-subtle bg-surface">
        <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-6 px-6 py-16 sm:px-10">
          <Eyebrow>THE PROBLEM</Eyebrow>
          <h2 className="max-w-[820px] font-display text-[28px] font-black leading-[1.2] text-primary sm:text-[36px]">
            A fabricated citation looks exactly like a real one.
          </h2>
          <p className="max-w-[720px] font-reading text-[16px] leading-[1.7] text-secondary sm:text-[17px]">
            That is the whole difficulty. A language model asked about a
            literature will produce plausible author names, plausible years and
            a plausible page number, and nothing about the output signals which
            parts came from a document and which were assembled to fit the
            sentence. Checking is slower than asking, so it usually does not
            happen. Aletheia is built the other way around: the checking is not
            optional and not the reader&rsquo;s job.
          </p>
        </div>
      </section>

      {/* --- Guarantees ---------------------------------------------------- */}
      <section className="flex w-full max-w-[1120px] flex-col gap-10 px-6 py-20 sm:px-10">
        <div className="flex flex-col gap-3">
          <Eyebrow>WHAT IT GUARANTEES</Eyebrow>
          <h2 className="max-w-[700px] font-display text-[28px] font-black leading-[1.2] text-primary sm:text-[34px]">
            Four properties, each enforced in code rather than asked for in a
            prompt.
          </h2>
        </div>

        <div className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-hairline-subtle bg-hairline-subtle sm:grid-cols-2">
          {guarantees.map((item) => (
            <article
              key={item.eyebrow}
              className="flex flex-col gap-3 bg-base p-7"
            >
              <p className="font-mono text-[11px] tracking-[1.32px] text-brass">
                {item.eyebrow}
              </p>
              <h3 className="font-display text-[19px] font-black leading-snug text-primary">
                {item.title}
              </h3>
              <p className="font-reading text-[15px] leading-[1.65] text-secondary">
                {item.body}
              </p>
            </article>
          ))}
        </div>
      </section>

      {/* --- Pipeline ------------------------------------------------------ */}
      <section className="w-full border-y border-hairline-subtle bg-surface">
        <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-8 px-6 py-16 sm:px-10">
          <div className="flex flex-col gap-3">
            <Eyebrow>THE PATH A QUESTION TAKES</Eyebrow>
            <h2 className="max-w-[700px] font-display text-[28px] font-black leading-[1.2] text-primary sm:text-[34px]">
              Six steps, and the last one can reject the fifth.
            </h2>
          </div>

          <ol className="flex flex-col gap-px overflow-hidden rounded-lg border border-hairline-subtle bg-hairline-subtle">
            {pipeline.map((stage, index) => (
              <li
                key={stage.step}
                className="flex flex-col gap-1 bg-surface px-6 py-4 sm:flex-row sm:items-baseline sm:gap-6"
              >
                <span className="w-6 shrink-0 font-mono text-[11px] text-muted">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="w-[120px] shrink-0 font-ui text-[14px] font-semibold text-primary">
                  {stage.step}
                </span>
                <span className="font-ui text-[13px] leading-relaxed text-secondary">
                  {stage.detail}
                </span>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* --- Capabilities -------------------------------------------------- */}
      <section className="flex w-full max-w-[1120px] flex-col gap-10 px-6 py-20 sm:px-10">
        <div className="flex flex-col gap-3">
          <Eyebrow>THE WORKSPACE</Eyebrow>
          <h2 className="max-w-[700px] font-display text-[28px] font-black leading-[1.2] text-primary sm:text-[34px]">
            Eight ways into the same corpus.
          </h2>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {capabilities.map((item) => (
            <Link
              key={item.name}
              href={item.href}
              className="group flex flex-col gap-2 rounded-lg border border-hairline-subtle bg-surface p-5 transition-colors hover:border-brass"
            >
              <h3 className="font-display text-[16px] font-black text-primary">
                {item.name}
              </h3>
              <p className="font-ui text-[13px] leading-[1.6] text-secondary">
                {item.blurb}
              </p>
              <span className="mt-auto pt-2 font-mono text-[11px] tracking-[1.1px] text-muted transition-colors group-hover:text-brass">
                OPEN →
              </span>
            </Link>
          ))}
        </div>
      </section>

      {/* --- Models -------------------------------------------------------- */}
      <section className="w-full border-y border-hairline-subtle bg-surface">
        <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-8 px-6 py-16 sm:px-10">
          <div className="flex flex-col gap-3">
            <Eyebrow>TRAINED FOR THIS PROJECT</Eyebrow>
            <h2 className="max-w-[760px] font-display text-[28px] font-black leading-[1.2] text-primary sm:text-[34px]">
              Three models, with the one that did not work labelled as such.
            </h2>
            <p className="max-w-[700px] font-reading text-[16px] leading-[1.7] text-secondary">
              Each was trained from the checked-in benchmark, split by question
              ID, and is reproducible from a notebook in{" "}
              <code className="font-mono text-[13px] text-brass">colab/</code>.
              The stance classifier sits below its own majority-class baseline.
              It is shown here for the same reason it is shown in the app:
              removing it would make the other two look like the whole story.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {models.map((model) => (
              <div
                key={model.name}
                className="flex flex-col gap-2 rounded-lg border border-hairline-subtle bg-base p-6"
              >
                <p className="font-ui text-[13px] font-semibold text-primary">
                  {model.name}
                </p>
                <p
                  className={`font-display text-[30px] font-black ${
                    model.good ? "text-brass-bright" : "text-muted"
                  }`}
                >
                  {model.result}
                </p>
                <p className="font-ui text-[12px] leading-relaxed text-muted">
                  {model.caption}
                </p>
              </div>
            ))}
          </div>

          <Link
            href="/training"
            className="font-mono text-[11px] tracking-[1.1px] text-brass transition-colors hover:text-brass-bright"
          >
            SEE THE LEARNING CURVES →
          </Link>
        </div>
      </section>

      {/* --- Close --------------------------------------------------------- */}
      <section className="flex w-full max-w-[1120px] flex-col items-start gap-6 px-6 py-20 sm:px-10">
        <div className="h-[2px] w-12 bg-brass" />
        <h2 className="max-w-[620px] font-display text-[30px] font-black leading-[1.15] text-primary sm:text-[40px]">
          Put your own papers in and ask it something hard.
        </h2>
        <p className="max-w-[560px] font-reading text-[16px] leading-[1.7] text-secondary">
          Upload a PDF, wait for it to parse, and ask a question it can only
          answer by reading. The interesting result is the one where it tells
          you the corpus does not cover it.
        </p>
        <Link
          href={authConfigured ? "/sign-up" : "/upload"}
          className="rounded-md bg-oxblood px-6 py-[13px] font-ui text-sm font-semibold text-primary transition-colors hover:bg-oxblood-bright"
        >
          {authConfigured ? "Create an account" : "Upload a paper"}
        </Link>
      </section>

      {/* --- Footer -------------------------------------------------------- */}
      <footer className="w-full border-t border-hairline-subtle">
        <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-3 px-6 py-8 sm:flex-row sm:items-center sm:justify-between sm:px-10">
          <p className="font-ui text-xs text-muted">
            Aletheia — grounded research intelligence.
          </p>
          <p className="font-mono text-[11px] tracking-[1.1px] text-muted">
            RETRIEVAL LOCAL · ANSWERING HOSTED · CITATIONS VERIFIED
          </p>
        </div>
      </footer>
    </main>
  );
}
