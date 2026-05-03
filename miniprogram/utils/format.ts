export function numberText(value: unknown, fallback = "--"): string {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  const num = Number(value);
  if (Number.isNaN(num)) {
    return fallback;
  }
  return Number.isInteger(num) ? `${num}` : `${Math.round(num * 10) / 10}`;
}

export function confidencePercent(value: unknown): string {
  const num = Number(value);
  if (Number.isNaN(num)) {
    return "--";
  }
  return `${Math.round(num * 100)}%`;
}

export function fieldHasWarning(warnings: Array<{ field?: string }>, field: string): boolean {
  return warnings.some((warning) => warning.field === field);
}

