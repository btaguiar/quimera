import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

export function SqlBlock({ sql }: { sql: string }) {
  const [copiado, setCopiado] = useState(false);
  const [falha, setFalha] = useState(false);

  useEffect(() => {
    setCopiado(false);
    setFalha(false);
  }, [sql]);

  return (
    <div>
      <pre
        tabIndex={0}
        aria-label="SQL"
        className="overflow-x-auto rounded-lg border border-border bg-card p-4 font-mono text-xs leading-relaxed"
      >
        {sql}
      </pre>
      <Button
        type="button"
        variant="outline"
        className="mt-2 border-border bg-transparent font-mono text-xs"
        onClick={() => {
          const clipboard = navigator.clipboard;
          if (!clipboard) {
            setFalha(true);
            return;
          }
          void clipboard
            .writeText(sql)
            .then(() => {
              setFalha(false);
              setCopiado(true);
            })
            .catch(() => {
              setCopiado(false);
              setFalha(true);
            });
        }}
      >
        {copiado ? "copiado" : "copiar SQL"}
      </Button>
      {falha ? (
        <p className="mt-2 font-mono text-xs text-muted-foreground">
          não foi possível copiar — selecione o SQL manualmente
        </p>
      ) : null}
    </div>
  );
}
