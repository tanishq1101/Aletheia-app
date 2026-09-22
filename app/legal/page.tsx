import Link from "next/link";
import ThemeToggle from "@/components/ThemeToggle";

export const metadata = {
  title: "Terms & Privacy | Aletheia",
  description:
    "The terms of use and privacy policy for the Aletheia research workspace.",
};

const updatedOn = "22 September 2026";

function Section({
  number,
  title,
  children,
}: {
  number: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="scroll-mt-8 border-t border-hairline-subtle pt-8" id={`section-${number}`}>
      <div className="grid gap-3 sm:grid-cols-[72px_minmax(0,1fr)] sm:gap-6">
        <p className="font-mono text-[11px] tracking-[1.2px] text-brass">{number}</p>
        <div className="flex min-w-0 flex-col gap-4">
          <h2 className="font-display text-[23px] font-black leading-tight text-primary sm:text-[27px]">
            {title}
          </h2>
          <div className="space-y-4 font-reading text-[15px] leading-[1.7] text-secondary sm:text-[16px]">
            {children}
          </div>
        </div>
      </div>
    </section>
  );
}

function DetailList({ items }: { items: string[] }) {
  return (
    <ul className="grid gap-2 border-l border-hairline pl-4 font-ui text-[13px] leading-relaxed text-secondary">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

export default function LegalPage() {
  return (
    <main className="flex min-h-full w-full flex-1 flex-col items-center bg-base">
      <header className="flex w-full max-w-[1120px] items-center justify-between gap-4 px-6 py-5 sm:px-10 sm:py-6">
        <Link href="/" className="flex items-center gap-3 rounded-sm" aria-label="Aletheia home">
          <span className="h-[2px] w-8 bg-brass" />
          <span className="font-display text-[17px] font-black tracking-tight text-primary">
            Aletheia
          </span>
        </Link>
        <div className="flex items-center gap-2 sm:gap-3">
          <ThemeToggle />
          <Link
            href="/sign-in"
            className="rounded-md px-3 py-2 font-ui text-[13px] text-secondary transition-colors hover:text-primary"
          >
            Sign in
          </Link>
        </div>
      </header>

      <section className="w-full border-y border-hairline-subtle bg-surface">
        <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-6 px-6 py-14 sm:px-10 sm:py-20">
          <p className="font-mono text-[11px] tracking-[1.32px] text-brass">LEGAL INFORMATION</p>
          <div className="flex max-w-[800px] flex-col gap-5">
            <h1 className="font-display text-[38px] font-black leading-[1.08] tracking-tight text-primary sm:text-[56px]">
              Terms of use &amp; privacy
            </h1>
            <p className="font-reading text-[17px] leading-[1.65] text-secondary sm:text-[19px]">
              The rules for using Aletheia and a precise account of the data its
              current implementation processes. Effective {updatedOn}.
            </p>
          </div>
          <aside className="max-w-[840px] rounded-lg border border-brass/50 bg-base px-5 py-4 font-ui text-[13px] leading-relaxed text-secondary">
            <span className="font-semibold text-primary">Deployment notice. </span>
            Aletheia can be self-hosted or run by a third party. The organisation
            operating the deployment is the service operator and controller of
            your data. Before a production launch, that operator must publish its
            legal name, physical address, privacy contact, applicable jurisdiction,
            retention schedule, and any processor-specific terms. Those facts are
            not present in this codebase, so this page does not pretend otherwise.
          </aside>
        </div>
      </section>

      <div className="mx-auto grid w-full max-w-[1120px] gap-10 px-6 py-12 sm:px-10 lg:grid-cols-[215px_minmax(0,1fr)] lg:py-16">
        <nav aria-label="On this page" className="lg:sticky lg:top-8 lg:self-start">
          <p className="mb-3 font-mono text-[10px] tracking-[1.2px] text-muted">ON THIS PAGE</p>
          <div className="flex flex-wrap gap-x-4 gap-y-2 lg:flex-col lg:gap-1">
            <a className="font-ui text-[13px] text-secondary hover:text-brass" href="#terms">Terms of use</a>
            <a className="font-ui text-[13px] text-secondary hover:text-brass" href="#privacy">Privacy policy</a>
            <a className="font-ui text-[13px] text-secondary hover:text-brass" href="#section-01">Using Aletheia</a>
            <a className="font-ui text-[13px] text-secondary hover:text-brass" href="#section-06">Information we process</a>
            <a className="font-ui text-[13px] text-secondary hover:text-brass" href="#section-09">Retention &amp; deletion</a>
          </div>
        </nav>

        <div className="flex min-w-0 flex-col gap-14">
          <article id="terms" className="scroll-mt-8 flex flex-col gap-8">
            <div className="flex flex-col gap-3">
              <p className="font-mono text-[11px] tracking-[1.32px] text-brass">PART I</p>
              <h2 className="font-display text-[30px] font-black text-primary sm:text-[36px]">Terms of use</h2>
              <p className="font-ui text-[13px] leading-relaxed text-muted">
                These terms govern access to and use of the Aletheia software and
                any hosted service made available by its operator.
              </p>
            </div>

            <Section number="01" title="Agreement, eligibility, and access">
              <p>
                By creating an account, signing in, uploading material, or using
                Aletheia, you agree to these Terms. If you use it for an employer,
                university, or other organisation, you confirm that you are
                authorised to bind that organisation to these Terms.
              </p>
              <p>
                Use the service only where you are legally able to enter this
                agreement. Keep account credentials and authentication methods
                secure. You are responsible for activity performed through your
                account unless unauthorised access results from the operator&apos;s
                failure to provide the safeguards it has promised in writing.
              </p>
            </Section>

            <Section number="02" title="What the service does — and does not do">
              <p>
                Aletheia stores and processes a research library, extracts document
                content, retrieves relevant passages, and can generate answers,
                comparisons, verification results, and research reports. Citations
                are checked against retrieved evidence, but that check is not a
                guarantee that an answer is complete, accurate, original, suitable
                for a particular purpose, or accepted by a publisher, reviewer, or
                regulator.
              </p>
              <p>
                The service is an assistive research tool, not medical, legal,
                financial, safety, clinical, peer-review, or professional advice.
                You must independently review source material and any generated
                output before relying on it, publishing it, or making a decision
                that could affect people, property, or rights.
              </p>
            </Section>

            <Section number="03" title="Your content and permissions">
              <p>
                You retain ownership of the documents, prompts, project names, and
                other material you submit (&ldquo;Your Content&rdquo;). You grant the
                operator the limited permission needed to host, copy, parse, index,
                retrieve, display, transform, and transmit Your Content solely to
                operate, secure, troubleshoot, and improve the service as described
                in this page and the operator&apos;s published deployment terms.
              </p>
              <p>
                You are responsible for ensuring you have all permissions,
                consents, licences, and legal bases necessary to upload and process
                Your Content. Do not upload material that is confidential,
                restricted, export-controlled, subject to a data-use agreement, or
                personal data requiring heightened safeguards unless the deployment
                is expressly approved for that material in writing.
              </p>
            </Section>

            <Section number="04" title="Acceptable use">
              <DetailList
                items={[
                  "Do not use the service to violate law, intellectual-property rights, confidentiality duties, or institutional research rules.",
                  "Do not attempt to bypass authentication, rate limits, access controls, or security protections; scan, probe, or disrupt the service; or access another person’s project or content.",
                  "Do not submit malware, deceptive files, unlawful content, or content intended to harm, exploit, or identify people without a lawful basis.",
                  "Do not represent generated output as independently verified human research, or remove source attribution where it is required.",
                ]}
              />
            </Section>

            <Section number="05" title="Service changes, suspension, and liability">
              <p>
                The operator may change, suspend, or discontinue features to
                maintain security, meet legal obligations, or improve the service.
                It may suspend access where it reasonably believes use breaches
                these Terms, creates a security risk, or could harm the service or
                others. Where feasible, it will provide notice and an opportunity
                to export or remove content.
              </p>
              <p>
                To the fullest extent permitted by applicable law, the service is
                provided &ldquo;as is&rdquo; and &ldquo;as available.&rdquo; No warranty is made that it
                will be uninterrupted, error-free, secure against every threat, or
                fit for a specific research outcome. Nothing here excludes liability
                that cannot lawfully be excluded. Any additional limits, governing
                law, dispute process, and commercial terms must be supplied by the
                deployment operator before production use.
              </p>
            </Section>
          </article>

          <article id="privacy" className="scroll-mt-8 flex flex-col gap-8">
            <div className="flex flex-col gap-3">
              <p className="font-mono text-[11px] tracking-[1.32px] text-brass">PART II</p>
              <h2 className="font-display text-[30px] font-black text-primary sm:text-[36px]">Privacy policy</h2>
              <p className="font-ui text-[13px] leading-relaxed text-muted">
                This describes the data flows implemented in this repository. It is
                not a substitute for deployment-specific notices required by law.
              </p>
            </div>

            <Section number="06" title="Information we process">
              <p>The exact data processed depends on the features and configuration enabled by the operator.</p>
              <DetailList
                items={[
                  "Account information: a Clerk account identifier and, where supplied by the identity token, email address and username. Clerk manages sign-in methods such as Google, email, and username.",
                  "Workspace information: projects, project descriptions, source filenames, file hashes, processing status, and timestamps.",
                  "Research content: uploaded files; extracted text, sections, pages, figures, tables, equations, document metadata, and derived embeddings used for retrieval.",
                  "Interaction content: search terms, questions, generated answers, citation metadata, and — when conversations are used — stored conversation messages and answer metadata.",
                  "Technical information: request identifiers and rate-limit counters. When no authenticated identity is available, rate limiting may use the request IP address. The selected project ID is also stored in the browser’s local storage.",
                ]}
              />
            </Section>

            <Section number="07" title="Why we use information and when it leaves the deployment">
              <p>
                The service uses this information to authenticate users, create and
                operate projects, ingest and search sources, produce requested
                research features, prevent abuse, diagnose failures, and maintain
                the service. The operator must identify its lawful basis for each
                processing purpose where privacy law requires one.
              </p>
              <p>
                Embedding and reranking run locally in the Aletheia backend. A
                hosted AI provider is called only for generated answers,
                research-agent planning and step answers, and explicitly requested
                figure interpretation. When one of those features is used, the
                relevant prompt and retrieved evidence — which can contain Your
                Content — are sent to the enabled provider: OpenAI or Google
                Gemini. The implementation is configured to use one enabled
                provider at a time; it does not silently fail over to the other.
              </p>
              <p>
                A research-agent query may also be sent to Europe PMC and Crossref
                to retrieve public research metadata or abstracts. Do not place
                sensitive information in a query you do not want disclosed to those
                public services.
              </p>
            </Section>

            <Section number="08" title="Service providers, storage, and security">
              <p>
                Depending on configuration, data is stored in PostgreSQL and a
                vector index (Chroma or pgvector); uploaded originals are stored on
                local server storage or Cloudflare R2; and rate-limit counters may
                be stored in Redis. Authentication is provided by Clerk. These are
                processors or infrastructure providers chosen by the operator, not
                a promise that every deployment uses every service listed here.
              </p>
              <p>
                The code includes file-size validation, authentication support,
                project-scoped data structures, rate limiting, and deletion paths
                for project content. Security is a shared operational responsibility:
                the operator must configure access controls, encryption, backups,
                logging, secret management, vendor agreements, and incident response
                appropriate to its deployment. No system can guarantee absolute
                security.
              </p>
            </Section>

            <Section number="09" title="Retention, deletion, and your choices">
              <p>
                The codebase does not define a fixed retention period. Workspace
                content remains until it is deleted through the service or under a
                deployment operator&apos;s retention rules. Deleting a source removes
                its database record and triggers removal of the original stored file
                and its vector entries; deleting a project cascades to its papers,
                derived records, jobs, and conversations. Storage and vector removal
                are best-effort after the database deletion, so an operator must run
                reconciliation and backup-expiry processes to meet a deletion
                commitment.
              </p>
              <p>
                Deleting content in Aletheia does not by itself delete copies that
                a hosted AI provider, public discovery service, backup system, or
                another lawful recipient retains under its own policy. Ask the
                deployment operator for its retention schedule, backup handling,
                account-deletion process, and any available export process before
                uploading sensitive material.
              </p>
            </Section>

            <Section number="10" title="Your rights, international transfers, and changes">
              <p>
                Depending on where you live, you may have rights to access, correct,
                delete, restrict, object to, or receive a portable copy of personal
                information, and to complain to a supervisory authority. Submit a
                request through the support or privacy channel published by the
                deployment operator. The repository does not provide a universal
                privacy contact, data-protection officer, or automated account
                deletion endpoint.
              </p>
              <p>
                Using hosted infrastructure or AI providers can involve processing
                outside your country. The operator is responsible for assessing and
                documenting the transfer mechanism required for its deployment. We
                may update this page when the service or its data flows change; the
                effective date above identifies the current version. Material changes
                should be notified by the deployment operator where required.
              </p>
            </Section>
          </article>
        </div>
      </div>

      <footer className="w-full border-t border-hairline-subtle bg-surface">
        <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-3 px-6 py-8 sm:flex-row sm:items-center sm:justify-between sm:px-10">
          <p className="font-ui text-xs text-muted">Aletheia — grounded research intelligence.</p>
          <Link href="/" className="font-mono text-[11px] tracking-[1.1px] text-brass hover:text-brass-bright">
            RETURN TO THE ARCHIVE →
          </Link>
        </div>
      </footer>
    </main>
  );
}
