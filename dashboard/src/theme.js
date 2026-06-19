// Shared visual helpers for the three system states and severities.

export const HEALTHY = "var(--color-healthy)";
export const CRITICAL = "var(--color-critical)";

// Overall page mood. The backend reports HEALTHY | CRITICAL; the frontend adds
// a transient HEALED state right after remediation.
export function moodColor(status) {
  return status === "CRITICAL" ? CRITICAL : HEALTHY;
}

export function statusDot(status) {
  switch (status) {
    case "critical":
      return CRITICAL;
    case "warning":
      return "#E0A106";
    default:
      return HEALTHY;
  }
}

export function severityColor(sev) {
  switch (sev) {
    case "critical":
      return CRITICAL;
    case "warning":
      return "#E0A106";
    default:
      return "#5BA8FF";
  }
}
