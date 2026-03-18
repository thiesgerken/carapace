import { useEffect, useRef, useCallback } from "react";

const EDGE_ZONE = 30; // px from left edge to start a swipe-open
const SWIPE_THRESHOLD = 60; // px of horizontal travel to trigger

/**
 * Detects touch swipe gestures to open/close a drawer.
 * Swipe right from the left edge opens; swipe left anywhere closes.
 * Only active below the `md` breakpoint (< 768px).
 */
export function useSwipeDrawer(
  isOpen: boolean,
  setOpen: (open: boolean) => void,
) {
  const touchStart = useRef<{ x: number; y: number } | null>(null);
  const eligible = useRef(false);

  const onTouchStart = useCallback(
    (e: TouchEvent) => {
      const t = e.touches[0];
      touchStart.current = { x: t.clientX, y: t.clientY };
      // Eligible to open if starting near the left edge, or to close if already open
      eligible.current = isOpen || t.clientX <= EDGE_ZONE;
    },
    [isOpen],
  );

  const onTouchEnd = useCallback(
    (e: TouchEvent) => {
      if (!touchStart.current || !eligible.current) return;
      const t = e.changedTouches[0];
      const dx = t.clientX - touchStart.current.x;
      const dy = Math.abs(t.clientY - touchStart.current.y);
      touchStart.current = null;

      // Ignore if mostly vertical
      if (dy > Math.abs(dx)) return;

      if (!isOpen && dx > SWIPE_THRESHOLD) {
        setOpen(true);
      } else if (isOpen && dx < -SWIPE_THRESHOLD) {
        setOpen(false);
      }
    },
    [isOpen, setOpen],
  );

  useEffect(() => {
    // Only attach on narrow viewports
    const mql = window.matchMedia("(max-width: 767px)");

    function attach() {
      if (mql.matches) {
        document.addEventListener("touchstart", onTouchStart, {
          passive: true,
        });
        document.addEventListener("touchend", onTouchEnd, { passive: true });
      } else {
        document.removeEventListener("touchstart", onTouchStart);
        document.removeEventListener("touchend", onTouchEnd);
      }
    }

    attach();
    mql.addEventListener("change", attach);
    return () => {
      mql.removeEventListener("change", attach);
      document.removeEventListener("touchstart", onTouchStart);
      document.removeEventListener("touchend", onTouchEnd);
    };
  }, [onTouchStart, onTouchEnd]);
}
