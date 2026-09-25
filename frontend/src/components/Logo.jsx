export default function Logo({ size = 28 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 36 36"
      fill="none"
      aria-hidden="true"
      data-testid="logo-mark"
    >
      <circle cx="18" cy="18" r="14" stroke="#A2B9EE" strokeWidth="1.6" strokeDasharray="3 5" />
      <path
        d="M18 2v8M18 26v8M2 18h8M26 18h8"
        stroke="#0A0E12"
        strokeWidth="2.4"
        strokeLinecap="round"
      />
      <circle cx="18" cy="18" r="4" fill="#AEDDF0" />
    </svg>
  );
}
