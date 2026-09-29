export function ExampleChips({
  examples,
  onPick,
}: {
  examples: string[];
  onPick: (text: string) => void;
}) {
  return (
    <ul className="flex flex-wrap gap-2" aria-label="Exemplos">
      {examples.map((ex) => (
        <li key={ex}>
          <button
            type="button"
            onClick={() => onPick(ex)}
            className="rounded-full border border-border bg-secondary px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-accent hover:text-foreground"
          >
            {ex}
          </button>
        </li>
      ))}
    </ul>
  );
}
