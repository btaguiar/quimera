import type { LeadsResponse } from "@/lib/types";

export function CostSummary({ data, browserMs }: { data: LeadsResponse; browserMs: number }) {
  return (
    <p className="font-mono text-sm">
      {data.latency_ms} ms · {browserMs} s
    </p>
  );
}
