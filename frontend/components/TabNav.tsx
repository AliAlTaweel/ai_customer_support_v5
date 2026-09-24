"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/", label: "Client Chat" },
  { href: "/human-agent", label: "Human Agent" },
  { href: "/knowledge-base", label: "Knowledge Base" },
];

export default function TabNav() {
  const pathname = usePathname();

  return (
    <nav className="border-b border-gray-200 bg-white px-6">
      <div className="mx-auto flex max-w-2xl gap-6">
        {TABS.map((tab) => {
          const active = pathname === tab.href;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={`border-b-2 px-1 py-3 text-sm font-medium transition-colors ${
                active
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-900"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
