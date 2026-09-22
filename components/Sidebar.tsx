"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";
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
  const mobileMenu = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    if (mobileMenu.current) mobileMenu.current.open = false;
  }, [pathname]);

  return (
    <>
      <details
        ref={mobileMenu}
        className="group relative z-30 w-full shrink-0 border-b border-hairline-subtle bg-surface md:hidden"
      >
        <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-4 py-3.5 [&::-webkit-details-marker]:hidden">
          <div className="min-w-px">
            <p className="font-mono text-[9px] tracking-[1px] text-brass">THE ARCHIVE</p>
            <p className="truncate font-display text-base font-semibold text-primary">
              Research Intelligence
            </p>
          </div>
          <span className="shrink-0 rounded-md border border-hairline px-3 py-2 font-ui text-xs font-medium text-secondary group-open:border-brass group-open:text-primary">
            <span className="group-open:hidden">Menu</span>
            <span className="hidden group-open:inline">Close</span>
          </span>
        </summary>
        <div className="absolute inset-x-0 top-full max-h-[calc(100dvh-60px)] overflow-y-auto border-b border-hairline bg-surface p-3 shadow-[0_18px_40px_-24px_rgb(0_0_0/0.9)]">
          <nav className="grid grid-cols-2 gap-1">
            {primaryNavItems.map((item) => (
              <NavLink
                key={item.href}
                item={item}
                active={pathname === item.href || pathname.startsWith(`${item.href}/`)}
              />
            ))}
            {secondaryNavItems.map((item) => (
              <NavLink
                key={item.href}
                item={item}
                active={pathname === item.href || pathname.startsWith(`${item.href}/`)}
              />
            ))}
          </nav>
        </div>
      </details>

      <aside className="hidden min-h-0 w-[260px] shrink-0 flex-col items-start gap-1 overflow-y-auto border-r border-hairline-subtle bg-surface px-6 py-7 md:flex">
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
    </>
  );
}
