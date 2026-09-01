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
  { label: "Upload", href: "/upload" },
  { label: "Cross-Paper", href: "/cross-paper", preview: true },
  { label: "Claim Verification", href: "/claim-verification", preview: true },
  { label: "Reproducibility", href: "/reproducibility", preview: true },
];

export const secondaryNavItems: NavItem[] = [
  { label: "Settings", href: "/settings" },
];
