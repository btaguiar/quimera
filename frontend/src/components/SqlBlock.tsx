import { useState } from "react";
import { Button } from "@/components/ui/button";

export function SqlBlock({ sql }: { sql: string }) {
  const [copiado, setCopiado] = useState(false);
  return (
    <div>
      <pre
        tabIndex={0}
        className="overflow-x-auto rounded-lg border border-border bg-card p-4 font-mono text-xs leading-relaxed"
      >
        {sql}
      </pre>
      <Button
        type="button"
        variant="outline"
        className="mt-2 border-border bg-transparent font-mono text-xs"
        onClick={() => {
          void navigator.clipboard?.writeText(sql).then(() => setCopiado(true));
        }}
      >
        {copiado ? "copiado" : "copiar SQL"}
      </Button>
    </div>
  );
}
