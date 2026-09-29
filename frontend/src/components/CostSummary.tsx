import type { LeadsResponse } from "@/lib/types";

export function CostSummary({ data, browserSeconds }: { data: LeadsResponse; browserSeconds: number }) {
  return (
    <p className="font-mono text-sm">
      {data.latency_ms} ms · {browserSeconds} s
    </p>
  );
}
