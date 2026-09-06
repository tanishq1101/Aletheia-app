"use client";

import { useRef, useState, type ChangeEvent, type DragEvent } from "react";

const MAX_BYTES = 50 * 1024 * 1024; // Mirrors MAX_UPLOAD_BYTES on the API.

export default function Dropzone({
  onFile,
  disabled,
  busy,
}: {
  onFile: (file: File) => void;
  disabled?: boolean;
  busy?: boolean;
}) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // The API is authoritative. The browser only catches size before a 50MB
  // round trip; sources are deliberately not restricted to PDFs.
  const accept = (file: File | undefined) => {
    if (!file) return;
    if (file.size > MAX_BYTES) {
      setLocalError(
        `${file.name} is ${(file.size / 1024 / 1024).toFixed(1)}MB — the limit is 50MB.`,
      );
      return;
    }
    setLocalError(null);
    onFile(file);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragOver(false);
    if (disabled) return;
    accept(event.dataTransfer.files?.[0]);
  };

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    accept(event.target.files?.[0]);
    // Reset so re-picking the same file fires `change` again.
    event.target.value = "";
  };

  return (
    <div className="flex w-full shrink-0 flex-col items-start gap-2">
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(event) => {
          if (disabled) return;
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setIsDragOver(true);
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          setIsDragOver(false);
        }}
        onDrop={handleDrop}
        className={`flex w-full shrink-0 flex-col items-center justify-center gap-3 rounded-lg border border-dashed py-16 transition-colors focus:outline-none focus:border-brass-bright ${
          disabled ? "cursor-not-allowed opacity-60 border-hairline" : "cursor-pointer"
        } ${isDragOver ? "border-brass bg-surface-raised" : "border-hairline"}`}
      >
        <div
          className={`size-12 shrink-0 rounded-full border-2 transition-colors ${
            isDragOver || busy ? "border-brass-bright" : "border-brass"
          } ${busy ? "animate-pulse" : ""}`}
        />
        <p className="font-ui text-[15px] font-medium text-primary">
          {busy
            ? "Uploading…"
            : "Drag & drop a source, or click to browse"}
        </p>
        <p className="font-ui text-xs text-muted">
          Single file · up to 50MB · PDFs, text, documents, slides, data files, and attachments
        </p>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="*/*"
        onChange={handleChange}
        className="hidden"
      />

      {localError && (
        <p className="font-ui text-xs text-error">{localError}</p>
      )}
    </div>
  );
}
