/** Fixtures for the pages the API does not back yet.
 *
 * Cross-paper comparison, claim extraction/verification and reproducibility
 * checking are a later phase of the backend PRD — there is no endpoint to call.
 * The pages still render so the workspace is reviewable end to end, and each
 * one carries a <PreviewNotice> saying the numbers below are fixtures.
 *
 * Everything the backend *does* cover — papers, ingestion, search, answers —
 * comes from `lib/api.ts`. Nothing in this file is used by those pages.
 */

export type AgreementStatus = "supports" | "contradicts" | "unverified";

export type CrossPaperEntry = {
  id: string;
  label: string;
  title: string;
};

export type ClaimAgreementRow = {
  id: string;
  claim: string;
  agreements: Record<string, AgreementStatus>;
};

export const crossPaperWorkspace: {
  summary: string;
  papers: CrossPaperEntry[];
  claims: ClaimAgreementRow[];
} = {
  summary: "Comparing 3 papers on reasoning-scale claims",
  papers: [
    {
      id: "alaya",
      label: "Alaya et al.",
      title: "Emergent Reasoning Chains (Alaya et al.)",
    },
    {
      id: "bakshi",
      label: "Bakshi et al.",
      title: "Compute-Optimal Reasoning Without Scale (Bakshi et al.)",
    },
    {
      id: "lindqvist",
      label: "Lindqvist et al.",
      title: "Small Models, Structured Reasoning (Lindqvist et al.)",
    },
  ],
  claims: [
    {
      id: "claim-parameter-scaling",
      claim: "Reasoning ability scales primarily with parameter count",
      agreements: {
        alaya: "contradicts",
        bakshi: "supports",
        lindqvist: "contradicts",
      },
    },
    {
      id: "claim-routing-predicts-accuracy",
      claim: "Routing/expert specialization predicts downstream reasoning accuracy",
      agreements: {
        alaya: "supports",
        bakshi: "unverified",
        lindqvist: "supports",
      },
    },
    {
      id: "claim-small-models-match-large",
      claim: "Small models can match large-model reasoning with the right training signal",
      agreements: {
        alaya: "unverified",
        bakshi: "supports",
        lindqvist: "supports",
      },
    },
    {
      id: "claim-cot-supervision-required",
      claim: "Explicit chain-of-thought supervision is required for reliable multi-step reasoning",
      agreements: {
        alaya: "contradicts",
        bakshi: "unverified",
        lindqvist: "contradicts",
      },
    },
  ],
};

export type ClaimVerificationStatus = "verified" | "disputed" | "unverified";

export type VerifiedClaim = {
  id: string;
  text: string;
  status: ClaimVerificationStatus;
  confidence: number;
  sourceCount: number;
};

export const claimVerification: {
  paperTitle: string;
  claims: VerifiedClaim[];
} = {
  paperTitle: "Emergent Reasoning Chains in Sparse Mixture Models",
  claims: [
    {
      id: "claim-early-specialization",
      text: "Reasoning-relevant experts specialize early in training, before step 12k.",
      status: "verified",
      confidence: 91,
      sourceCount: 4,
    },
    {
      id: "claim-routing-entropy-correlation",
      text: "Routing entropy correlates with downstream reasoning accuracy across all three model scales tested.",
      status: "disputed",
      confidence: 44,
      sourceCount: 2,
    },
    {
      id: "claim-probe-predicts-benchmark",
      text: "The probe predicts benchmark performance before fine-tuning completes.",
      status: "unverified",
      confidence: 0,
      sourceCount: 0,
    },
    {
      id: "claim-sparse-outperforms-dense",
      text: "Sparse MoE models outperform dense models of equal active-parameter count on reasoning benchmarks.",
      status: "verified",
      confidence: 78,
      sourceCount: 3,
    },
    {
      id: "claim-linear-probing-detectable",
      text: "Reasoning specialization is detectable via linear probing of routing statistics alone.",
      status: "verified",
      confidence: 85,
      sourceCount: 5,
    },
    {
      id: "claim-utilization-plateau",
      text: "Expert utilization plateaus by the midpoint of training regardless of model scale.",
      status: "unverified",
      confidence: 12,
      sourceCount: 1,
    },
    {
      id: "claim-entropy-stronger-predictor",
      text: "Routing entropy is a stronger predictor of reasoning accuracy than raw parameter count.",
      status: "verified",
      confidence: 82,
      sourceCount: 4,
    },
    {
      id: "claim-zero-shot-transfer",
      text: "Reasoning capability transfers zero-shot across unrelated benchmark domains.",
      status: "unverified",
      confidence: 8,
      sourceCount: 0,
    },
    {
      id: "claim-generalizes-to-dense",
      text: "Probe-based specialization signals generalize to dense transformer baselines.",
      status: "verified",
      confidence: 73,
      sourceCount: 2,
    },
  ],
};

export type CheckStatus = "pass" | "warning" | "pending";

export type ChecklistItem = {
  id: string;
  label: string;
  status: CheckStatus;
};

export const reproducibilityCheck: {
  paperTitle: string;
  repo: {
    repository: string;
    commit: string;
    environment: string;
    lastVerified: string;
  };
  checklist: ChecklistItem[];
} = {
  paperTitle: "Emergent Reasoning Chains in Sparse Mixture Models",
  repo: {
    repository: "halden-ai/sparse-reasoning",
    commit: "a3f9c1e",
    environment: "Python 3.11 · torch 2.4",
    lastVerified: "Aug 22, 2026",
  },
  checklist: [
    {
      id: "check-dependencies-resolve",
      label: "Dependencies resolve cleanly from lockfile",
      status: "pass",
    },
    {
      id: "check-environment-matches-ci",
      label: "Declared environment matches repo's CI config",
      status: "pass",
    },
    {
      id: "check-seeds-documented",
      label: "Reported random seeds documented",
      status: "pass",
    },
    {
      id: "check-results-reproduce",
      label: "Headline results reproduce within stated tolerance",
      status: "warning",
    },
    {
      id: "check-dataset-splits",
      label: "Dataset splits match paper's stated methodology",
      status: "pending",
    },
  ],
};
