export type NavItem = {
  label: string;
  href: string;
  /** Pages the API does not back yet — flagged in the sidebar so the working
   *  features are distinguishable at a glance. */
  preview?: boolean;
};

export const primaryNavItems: NavItem[] = [
  { label: "Library", href: "/library" },
  { label: "Search", href: "/search" },
  { label: "Ask", href: "/ask" },
  { label: "Research Agent", href: "/agent" },
  { label: "Training Lab", href: "/training" },
  { label: "Upload", href: "/upload" },
  { label: "Cross-Paper", href: "/cross-paper" },
  { label: "Claim Verification", href: "/claim-verification" },
  { label: "Reproducibility", href: "/reproducibility" },
];

export const secondaryNavItems: NavItem[] = [
  { label: "Settings", href: "/settings" },
];
