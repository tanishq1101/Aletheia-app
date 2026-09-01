"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { primaryNavItems, secondaryNavItems, type NavItem } from "./nav-items";

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={`flex w-full items-center gap-[10px] rounded shrink-0 px-[14px] py-[10px] font-ui text-sm transition-colors ${
        active
          ? "bg-surface-raised text-primary font-semibold"
          : "text-secondary font-normal hover:bg-surface-raised/60 hover:text-primary"
      }`}
    >
      <span
        className={`size-[5px] shrink-0 rounded-full ${
          active ? "bg-primary" : "bg-secondary"
        }`}
      />
      <span className="min-w-px flex-1">{item.label}</span>
      {item.preview && (
        <span
          title="Not backed by the API yet"
          className="shrink-0 rounded-[3px] border border-hairline px-1.5 py-px font-mono text-[8px] tracking-[0.4px] text-muted"
        >
          PREVIEW
        </span>
      )}
    </Link>
  );
}

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-full w-[260px] shrink-0 flex-col items-start gap-1 overflow-y-auto border-r border-hairline-subtle bg-surface px-6 py-7">
      <div className="flex flex-col items-start gap-0.5 whitespace-nowrap">
        <p className="font-mono text-[11px] tracking-[1.1px] text-brass">
          THE ARCHIVE
        </p>
        <p className="font-display text-xl font-semibold text-primary">
          Research Intelligence
        </p>
      </div>

      <div className="h-8 w-px shrink-0" />

      <nav className="flex w-full shrink-0 flex-col items-start gap-0.5">
        {primaryNavItems.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            active={pathname === item.href || pathname.startsWith(`${item.href}/`)}
          />
        ))}
      </nav>

      <div className="min-h-px w-full flex-1" />

      <nav className="flex w-full shrink-0 flex-col items-start">
        {secondaryNavItems.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            active={pathname === item.href || pathname.startsWith(`${item.href}/`)}
          />
        ))}
      </nav>
    </aside>
  );
}
