import type { ReactNode } from "react";

export function ParticipantCard({
  wide,
  centered,
  children,
}: {
  wide?: boolean;
  centered?: boolean;
  children: ReactNode;
}) {
  const cls = ["p-card", wide ? "wide" : "", centered ? "centered" : ""].filter(Boolean).join(" ");
  return (
    <div className="p-frame">
      <main className={cls}>{children}</main>
    </div>
  );
}
