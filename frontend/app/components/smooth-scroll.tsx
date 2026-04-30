"use client";

import { useEffect } from "react";

export function SmoothScroll() {
  useEffect(() => {
    const handleWheel = (e: WheelEvent) => {
      // Only apply smooth scroll easing if scrolling vertically
      if (Math.abs(e.deltaY) > 0) {
        e.preventDefault();

        // Get current scroll position
        let currentScroll = window.scrollY;
        const targetScroll = currentScroll + e.deltaY;

        // Smooth easing function
        const smoothScroll = () => {
          currentScroll += (targetScroll - currentScroll) * 0.1;

          // Stop when close enough
          if (Math.abs(targetScroll - currentScroll) > 0.5) {
            window.scrollTo(0, currentScroll);
            requestAnimationFrame(smoothScroll);
          } else {
            window.scrollTo(0, targetScroll);
          }
        };

        requestAnimationFrame(smoothScroll);
      }
    };

    window.addEventListener("wheel", handleWheel, { passive: false });

    return () => {
      window.removeEventListener("wheel", handleWheel);
    };
  }, []);

  return null;
}
