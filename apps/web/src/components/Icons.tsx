import type { SVGProps } from "react";

/**
 * Inline SVG only — no icon package, no sprite fetch. The product runs
 * air-gapped, so every asset the page needs is in the bundle.
 *
 * Icons here are decorative *in addition to* a label, never instead of one:
 * 03-ux-spec.md requires status to carry an icon **and** a word, so each is
 * marked aria-hidden and the meaning lives in the adjacent text.
 */
type IconProps = SVGProps<SVGSVGElement>;

function Icon({ children, ...props }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {children}
    </svg>
  );
}

export function LockIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="4.5" y="10.5" width="15" height="10" rx="2.5" />
      <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
      <circle cx="12" cy="15.5" r="1.1" fill="currentColor" stroke="none" />
    </Icon>
  );
}

export function CloudIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M7.5 18.5h9.2a3.8 3.8 0 0 0 .4-7.6 5.4 5.4 0 0 0-10.3-1.2A3.9 3.9 0 0 0 7.5 18.5Z" />
    </Icon>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m5 12.5 4.4 4.4L19 7.3" />
    </Icon>
  );
}

export function AlertIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M12 4.8 21 19.5H3L12 4.8Z" />
      <path d="M12 10.5v4" />
      <circle cx="12" cy="17" r="0.9" fill="currentColor" stroke="none" />
    </Icon>
  );
}

export function PendingIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4.4l2.8 1.7" />
    </Icon>
  );
}

export function ArrowRightIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4.5 12h14" />
      <path d="m13 6.5 5.5 5.5-5.5 5.5" />
    </Icon>
  );
}

export function BlockedIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="8" />
      <path d="m6.6 6.6 10.8 10.8" />
    </Icon>
  );
}

/** The product mark: two planes and the span between them. */
export function BridgeMark(props: IconProps) {
  return (
    <Icon strokeWidth={1.5} {...props}>
      <path d="M3.5 15.5h17" />
      <path d="M6 15.5V11" />
      <path d="M18 15.5V11" />
      <path d="M3.5 11.2c3.6-4.6 13.4-4.6 17 0" />
      <path d="M12 8.2v7.3" />
    </Icon>
  );
}

export function UploadIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M12 16.5V4.8" />
      <path d="m7 9.8 5-5 5 5" />
      <path d="M4.5 15.5v2a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-2" />
    </Icon>
  );
}

export function FileIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M13.5 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9l-5.5-5.5Z" />
      <path d="M13.5 3.5V9H19" />
    </Icon>
  );
}

/** An in-flight stage. A ring with a gap, so it reads as "not yet closed". */
export function RunningIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M20 12a8 8 0 1 0-2.7 6" />
    </Icon>
  );
}

/** A stage not yet reached. Hollow on purpose: nothing has happened here. */
export function DotIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="4.2" />
    </Icon>
  );
}

export function RetryIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3" />
      <path d="M19.5 4.5V9H15" />
    </Icon>
  );
}

export function CloseIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m6.8 6.8 10.4 10.4" />
      <path d="m17.2 6.8-10.4 10.4" />
    </Icon>
  );
}

export function InfoIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 11.2v5" />
      <circle cx="12" cy="8.2" r="0.9" fill="currentColor" stroke="none" />
    </Icon>
  );
}

/** Held for a person — a hand, not a cross. These are not failures. */
export function HandIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M9 11V5.8a1.4 1.4 0 0 1 2.8 0V11" />
      <path d="M11.8 10.6V4.9a1.4 1.4 0 0 1 2.8 0v5.7" />
      <path d="M14.6 11V6.9a1.4 1.4 0 0 1 2.8 0v7.6a5.5 5.5 0 0 1-5.5 5.5h-.6a5 5 0 0 1-4-2l-2.2-3a1.4 1.4 0 0 1 2.1-1.8L9 15.1V11" />
    </Icon>
  );
}

/** AI could draft this. A spark, never a robot: the model proposes (ADR-007). */
export function SparkIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M12 4.2 13.6 9l4.8 1.6-4.8 1.6L12 17l-1.6-4.8L5.6 10.6 10.4 9 12 4.2Z" />
      <path d="M18.4 16.2 19 18l1.8.6-1.8.6-.6 1.8-.6-1.8-1.8-.6 1.8-.6.6-1.8Z" />
    </Icon>
  );
}

export function DownloadIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M12 4.5v11.7" />
      <path d="m7 11.2 5 5 5-5" />
      <path d="M4.5 18.5v1a1 1 0 0 0 1 1h13a1 1 0 0 0 1-1v-1" />
    </Icon>
  );
}

/**
 * The validation verdict. A shield, because the question it answers is "has
 * anything checked this" — and it is drawn *empty* so an unverified verdict
 * does not borrow the reassurance of a tick it has not earned.
 */
export function ShieldIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M12 3.5 19 6v6.2c0 4-2.9 6.9-7 8.3-4.1-1.4-7-4.3-7-8.3V6l7-2.5Z" />
    </Icon>
  );
}

/** Source on the left, target on the right: the comparison itself. */
export function CompareIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="3.5" y="5.5" width="7" height="13" rx="1.6" />
      <rect x="13.5" y="5.5" width="7" height="13" rx="1.6" />
      <path d="M10.5 12h3" />
    </Icon>
  );
}
