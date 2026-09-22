type GuideStep = {
  title: string;
  detail: string;
};

export default function FeatureGuide({
  purpose,
  bestFor,
  steps,
  boundary,
}: {
  purpose: string;
  bestFor: string;
  steps: GuideStep[];
  boundary: string;
}) {
  return (
    <section className="w-full overflow-hidden rounded-lg border border-hairline-subtle bg-surface">
      <div className="grid gap-px bg-hairline-subtle lg:grid-cols-[1.15fr_0.85fr]">
        <div className="flex flex-col gap-3 bg-surface p-5 sm:p-6">
          <p className="font-mono text-[10px] tracking-[0.8px] text-brass">
            WHAT THIS IS FOR
          </p>
          <p className="max-w-3xl font-reading text-[15px] leading-relaxed text-primary sm:text-[16px]">
            {purpose}
          </p>
          <p className="font-ui text-xs leading-relaxed text-secondary">
            <span className="font-semibold text-primary">Useful when:</span>{" "}
            {bestFor}
          </p>
        </div>

        <div className="flex flex-col gap-3 bg-base p-5 sm:p-6">
          <p className="font-mono text-[10px] tracking-[0.8px] text-muted">
            HOW TO USE IT
          </p>
          <ol className="flex flex-col gap-3">
            {steps.map((step, index) => (
              <li key={step.title} className="flex items-start gap-3">
                <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border border-hairline font-mono text-[9px] text-brass">
                  {index + 1}
                </span>
                <p className="font-ui text-xs leading-relaxed text-secondary">
                  <span className="font-semibold text-primary">{step.title}.</span>{" "}
                  {step.detail}
                </p>
              </li>
            ))}
          </ol>
        </div>
      </div>
      <p className="border-t border-hairline-subtle bg-surface-raised px-5 py-3 font-ui text-[11px] leading-relaxed text-muted sm:px-6">
        <span className="font-semibold text-secondary">Important:</span> {boundary}
      </p>
    </section>
  );
}
