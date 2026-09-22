export type NavItem = {
  label: string;
  href: string;
  /** Pages the API does not back yet — flagged in the sidebar so the working
   *  features are distinguishable at a glance. */
  preview?: boolean;
};

/** Ordered by the workflow, not by the order the pages were built.
 *
 *  Sources first (you cannot ask anything until something is in the library),
 *  then the ways of reading them, then the analyses that compare what was
 *  read, and finally the lab — which operates on models rather than on the
 *  library, so it belongs at the end rather than wedged between Upload and
 *  Ask. `Upload` in particular was sitting sixth, below three pages that do
 *  nothing until it has been used. */
export const primaryNavItems: NavItem[] = [
  // Sources
  { label: "Library", href: "/library" },
  { label: "Upload", href: "/upload" },
  // Reading
  { label: "Search", href: "/search" },
  { label: "Ask", href: "/ask" },
  { label: "Research Agent", href: "/agent" },
  // Analysis across what was read
  { label: "Cross-Paper", href: "/cross-paper" },
  { label: "Claim Verification", href: "/claim-verification" },
  { label: "Reproducibility", href: "/reproducibility" },
  // Separate from the library entirely
  { label: "Training Lab", href: "/training" },
];

export const secondaryNavItems: NavItem[] = [
  { label: "Settings", href: "/settings" },
];
