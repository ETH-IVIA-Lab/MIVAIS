
export function CameraIcon({ size = 13 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ verticalAlign: "-2px" }}
    >
      <rect x="2" y="6" width="13" height="12" rx="2" />
      <path d="M15 10.5l7-3.5v10l-7-3.5" />
    </svg>
  );
}
