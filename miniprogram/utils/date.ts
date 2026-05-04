export function toDateString(date = new Date()): string {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function todayCn(date = new Date()): string {
  const weekdays = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"];
  return `${date.getMonth() + 1}月${date.getDate()}日${weekdays[date.getDay()]}`;
}

export function greeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 11) return "早上好";
  if (hour < 14) return "中午好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

export function shortTime(iso?: string): string {
  if (!iso) return "";
  const date = new Date(normalizeIsoForClient(iso));
  if (Number.isNaN(date.getTime())) return "";
  return `${`${date.getHours()}`.padStart(2, "0")}:${`${date.getMinutes()}`.padStart(2, "0")}`;
}

function normalizeIsoForClient(iso: string): string {
  if (/[zZ]$|[+-]\d{2}:\d{2}$/.test(iso)) {
    return iso;
  }
  return `${iso}Z`;
}

export function isoNowWithTimezone(): string {
  const date = new Date();
  const offsetMin = -date.getTimezoneOffset();
  const sign = offsetMin >= 0 ? "+" : "-";
  const abs = Math.abs(offsetMin);
  const hh = `${Math.floor(abs / 60)}`.padStart(2, "0");
  const mm = `${abs % 60}`.padStart(2, "0");
  return `${date.toISOString().slice(0, 19)}${sign}${hh}:${mm}`;
}
