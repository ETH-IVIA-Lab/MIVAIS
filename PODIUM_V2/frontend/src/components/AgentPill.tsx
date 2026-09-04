export function AgentPill({
  label,
  online,
  active,
  variant,
}: {
  label: string;
  online: boolean;
  active: boolean;
  variant: "svm" | "adv";
}) {
  const classes = ["a-pill", `pill-${variant}`];
  if (online) classes.push("online");
  if (active) classes.push(variant === "svm" ? "svm-on" : "adv-on");
  return (
    <div className={classes.join(" ")}>
      <div className="pill-dot" />
      {label}
    </div>
  );
}
