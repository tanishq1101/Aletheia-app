"use client";

import {
  useCallback,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import type { Suggestion } from "@/lib/suggestions";

/** The Ask box, with an inline completion for the suggested next question.
 *
 * The suggestion is drawn as ghost text *behind* the textarea rather than put
 * into its value, so it is never mistaken for something the reader typed and
 * never submitted by accident. Tab commits the whole question in one press —
 * not the next word, and not a prefix — because a half-inserted question is
 * worse than none.
 *
 * The overlay has to track the textarea's metrics exactly or the ghost text
 * drifts out from under the caret, so both share one typography class string.
 */
const FIELD_TYPOGRAPHY =
  "w-full resize-none font-ui text-[15px] leading-[1.55] tracking-normal";

export default function QuestionComposer({
  value,
  onChange,
  onSubmit,
  suggestions,
  disabled,
  pending,
  placeholder,
  footer,
  submitLabel = "Ask",
  pendingLabel = "Thinking…",
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  suggestions: Suggestion[];
  disabled?: boolean;
  pending?: boolean;
  placeholder: string;
  /** Rendered to the left of the submit button — the source count, usually. */
  footer?: React.ReactNode;
  submitLabel?: string;
  pendingLabel?: string;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const hintId = useId();
  const liveId = useId();
  const [index, setIndex] = useState(0);
  const [dismissed, setDismissed] = useState(false);

  // A new set of suggestions is a new turn: start at the first one, and give
  // a reader who dismissed the last set a fresh offer.
  //
  // Compared by *contents*, not by the array's identity. A caller that builds
  // the list inline — the obvious way to use this component — hands over a new
  // array every render, and resetting on identity snapped the index back to 0
  // before the reader's next keypress: cycling looked implemented and did
  // nothing. Adjusted during render rather than in an effect so the reset and
  // the new suggestions are painted together, never one frame apart.
  const identity = suggestions.map((suggestion) => suggestion.text).join("\u0000");
  const [seen, setSeen] = useState(identity);
  if (seen !== identity) {
    setSeen(identity);
    setIndex(0);
    setDismissed(false);
  }

  /** Which suggestion is on offer right now.
   *
   * With an empty field it is whichever one the reader last cycled to. Once
   * they start typing it becomes the first suggestion their text is a prefix
   * of — so the ghost line follows the sentence they are visibly heading
   * towards instead of sitting on a suggestion they have already typed past.
   * `-1` means nothing matches, and nothing is offered: completing text that
   * is not a prefix would rewrite what they wrote. */
  const offeredIndex = useMemo(() => {
    if (suggestions.length === 0) return -1;
    if (value.length === 0) return index;

    const typed = value.toLowerCase();
    const isPrefixOf = (position: number) => {
      const candidate = suggestions[position].text;
      return (
        candidate.length > value.length &&
        candidate.toLowerCase().startsWith(typed)
      );
    };

    // Prefer the one already on offer, then search forward from it so that
    // cycling still decides between two suggestions sharing a prefix.
    for (let offset = 0; offset < suggestions.length; offset += 1) {
      const position = (index + offset) % suggestions.length;
      if (isPrefixOf(position)) return position;
    }
    return -1;
  }, [index, suggestions, value]);

  const shownIndex = offeredIndex === -1 ? index : offeredIndex;
  const active =
    offeredIndex === -1 || dismissed || pending
      ? null
      : suggestions[offeredIndex];

  /** What Tab would add: always the remainder of a whole question. */
  const completion = active ? active.text.slice(value.length) : "";

  const accept = useCallback(() => {
    if (!active) return;
    onChange(active.text);
    const field = textareaRef.current;
    if (field) {
      field.focus();
      // Next frame: the new value has to be in the DOM before the caret can be
      // put after it.
      requestAnimationFrame(() =>
        field.setSelectionRange(active.text.length, active.text.length),
      );
    }
  }, [active, onChange]);

  const cycle = useCallback(
    (step: number) => {
      if (suggestions.length === 0) return;
      setDismissed(false);
      // Step from what is on screen, which may not be `index` when the typed
      // text has moved the offer on to another suggestion.
      setIndex((current) => {
        const from = offeredIndex === -1 ? current : offeredIndex;
        return (from + step + suggestions.length) % suggestions.length;
      });
    },
    [offeredIndex, suggestions.length],
  );

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    const field = event.currentTarget;
    const caretAtEnd =
      field.selectionStart === value.length && field.selectionEnd === value.length;

    if (event.key === "Tab" && completion && !event.shiftKey) {
      // Only when there is something to complete — otherwise Tab must keep
      // moving focus, or the form becomes a keyboard trap.
      event.preventDefault();
      accept();
      return;
    }

    // The other half of the autocomplete idiom: at the end of the line, → takes
    // the rest of it.
    if (event.key === "ArrowRight" && completion && caretAtEnd) {
      event.preventDefault();
      accept();
      return;
    }

    if ((event.key === "ArrowDown" || event.key === "ArrowUp") && completion) {
      event.preventDefault();
      cycle(event.key === "ArrowDown" ? 1 : -1);
      return;
    }

    if (event.key === "Escape" && completion) {
      event.preventDefault();
      setDismissed(true);
      return;
    }

    // Enter sends; Shift+Enter keeps the newline.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      onSubmit();
    }
  };

  return (
    <div className="flex w-full shrink-0 flex-col items-start gap-3">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
        className="flex w-full flex-col items-start gap-3 rounded-lg border border-brass bg-surface px-5 py-4 transition-colors focus-within:border-brass-bright"
      >
        <div className="relative w-full">
          {/* The ghost line. `aria-hidden` because the same text is announced
              through the live region below — read twice, it is noise. */}
          <div
            aria-hidden="true"
            className={`${FIELD_TYPOGRAPHY} pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words`}
          >
            <span className="invisible">{value}</span>
            <span className="text-muted/70">{completion}</span>
          </div>

          <textarea
            ref={textareaRef}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
            rows={2}
            disabled={disabled}
            placeholder={completion ? "" : placeholder}
            aria-describedby={hintId}
            className={`${FIELD_TYPOGRAPHY} relative bg-transparent text-primary placeholder:text-muted focus:outline-none disabled:cursor-not-allowed`}
          />
        </div>

        <div className="flex w-full flex-wrap items-center gap-3">
          <p className="min-w-px flex-1 font-mono text-[10px] text-muted">{footer}</p>
          <button
            type="submit"
            disabled={disabled || pending || !value.trim()}
            className="shrink-0 rounded-md bg-oxblood px-[18px] py-[9px] font-ui text-[13px] font-semibold text-on-accent transition-colors hover:bg-oxblood-bright disabled:cursor-not-allowed disabled:bg-surface-raised disabled:text-muted"
          >
            {pending ? pendingLabel : submitLabel}
          </button>
        </div>
      </form>

      {suggestions.length > 0 && !pending && (
        <div className="suggestion-in flex w-full flex-col items-start gap-2">
          <div className="flex w-full flex-wrap items-center gap-2">
            <p className="font-mono text-[10px] tracking-[0.6px] text-muted">
              NEXT QUESTION
            </p>
            {suggestions.map((suggestion, position) => {
              const isActive = position === shownIndex && !dismissed;
              return (
                <button
                  key={suggestion.text}
                  type="button"
                  title={suggestion.reason}
                  aria-pressed={isActive}
                  onClick={() => {
                    setDismissed(false);
                    setIndex(position);
                    onChange(suggestion.text);
                    textareaRef.current?.focus();
                  }}
                  className={`max-w-full shrink truncate rounded-full border px-[13px] py-[6px] font-ui text-xs transition-colors ${
                    isActive
                      ? "border-brass bg-surface-raised text-primary"
                      : "border-hairline-subtle text-secondary hover:border-brass hover:text-primary"
                  }`}
                >
                  {suggestion.text}
                </button>
              );
            })}
          </div>

          <p id={hintId} className="font-ui text-[11px] text-muted">
            {completion ? (
              <>
                <kbd className="rounded-[3px] border border-hairline px-1 font-mono text-[10px] text-secondary">
                  Tab
                </kbd>{" "}
                writes the whole question ·{" "}
                <kbd className="rounded-[3px] border border-hairline px-1 font-mono text-[10px] text-secondary">
                  ↑↓
                </kbd>{" "}
                for another ·{" "}
                <kbd className="rounded-[3px] border border-hairline px-1 font-mono text-[10px] text-secondary">
                  Esc
                </kbd>{" "}
                to dismiss
                {active ? ` · ${active.reason}` : ""}
              </>
            ) : (
              "Suggestions are built from passages this project actually returned — pick one, or ignore them and type your own."
            )}
          </p>

          {/* Keyboard users need to know what Tab is about to insert without
              being able to see the ghost text. */}
          <p id={liveId} aria-live="polite" className="sr-only">
            {completion && active
              ? `Suggested question: ${active.text}. Press Tab to insert it.`
              : ""}
          </p>
        </div>
      )}
    </div>
  );
}
