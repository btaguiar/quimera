export function ExampleChips({
  examples,
  onPick,
}: {
  examples: string[];
  onPick: (text: string) => void;
}) {
  return (
    <ul className="flex flex-wrap items-center gap-2" aria-label="Exemplos">
      {examples.map((ex) => (
        <li key={ex}>
          <button
            type="button"
            onClick={() => onPick(ex)}
            className="rounded-md border border-border px-2.5 py-1 text-[13px] text-muted-foreground transition-colors duration-150 hover:border-line-strong hover:bg-surface-3 hover:text-foreground"
          >
            {ex}
          </button>
        </li>
      ))}
    </ul>
  );
}
