import PreviewNotice from "@/components/PreviewNotice";
import RepoMetadataCard from "@/components/RepoMetadataCard";
import CheckStatusIcon from "@/components/CheckStatusIcon";
import { reproducibilityCheck } from "@/lib/preview-data";

export default function ReproducibilityPage() {
  const { paperTitle, repo, checklist } = reproducibilityCheck;

  return (
    <div className="flex w-full flex-col items-start gap-6">
      <h1 className="font-display text-[28px] font-semibold text-primary">
        Reproducibility Checker
      </h1>

      <PreviewNotice>
        Nothing here talks to a repository yet. The checklist below is a fixture
        showing the intended shape of the check.
      </PreviewNotice>

      <p className="font-ui text-[13px] text-secondary">{paperTitle}</p>

      <RepoMetadataCard
        repository={repo.repository}
        commit={repo.commit}
        environment={repo.environment}
        lastVerified={repo.lastVerified}
      />

      <p className="font-ui text-[15px] font-semibold text-primary">Verification checklist</p>

      <div className="flex w-full shrink-0 flex-col items-start gap-px">
        {checklist.map((item) => (
          <div
            key={item.id}
            className="flex w-full items-center gap-3 bg-surface px-[18px] py-3"
          >
            <CheckStatusIcon status={item.status} />
            <p className="min-w-px flex-1 font-ui text-[13px] text-primary">{item.label}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
