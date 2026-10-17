import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

interface ImageLightboxProps {
  src: string
  alt: string
  onClose: () => void
}

/**
 * Full-screen zoom for a step screenshot. Clicking anywhere outside the image,
 * the close button, or Escape dismisses it; clicking the image itself does not,
 * so a user reading a label isn't thrown out mid-look.
 *
 * Portaled to <body> so no ancestor transform or overflow can clip the overlay.
 * Focus moves to the close button on open and back to the opener on close, and
 * page scroll is locked underneath — the dialog basics, without a dependency.
 */
export function ImageLightbox({ src, alt, onClose }: ImageLightboxProps) {
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeRef.current?.focus()

    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = previousOverflow
      opener?.focus()
    }
  }, [onClose])

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={alt}
      onClick={onClose}
      className="fixed inset-0 z-50 flex cursor-zoom-out items-center justify-center bg-black/80 p-4 backdrop-blur-sm animate-in fade-in-0 sm:p-10"
    >
      <button
        ref={closeRef}
        type="button"
        onClick={onClose}
        aria-label="Close"
        className="absolute top-4 right-4 flex size-10 items-center justify-center rounded-full bg-white/10 text-white transition-colors hover:bg-white/20 focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:outline-none"
      >
        <X className="size-5" />
      </button>
      <img
        src={src}
        alt={alt}
        onClick={(event) => event.stopPropagation()}
        className="max-h-full max-w-[min(100%,1600px)] cursor-default rounded-xl border border-white/10 shadow-2xl animate-in zoom-in-95 fade-in-0"
      />
    </div>,
    document.body,
  )
}
