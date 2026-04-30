"use client";

import { useEffect, useRef } from "react";

export function MouseFollower() {
  const cursorRef = useRef<HTMLDivElement>(null);
  const cursorOutlineRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let mouseX = 0;
    let mouseY = 0;
    let targetX = 0;
    let targetY = 0;
    let outlineX = 0;
    let outlineY = 0;

    const handleMouseMove = (e: MouseEvent) => {
      targetX = e.clientX;
      targetY = e.clientY;
    };

    const animateCursor = () => {
      // Smooth easing for main cursor
      mouseX += (targetX - mouseX) * 0.15;
      mouseY += (targetY - mouseY) * 0.15;

      // Smooth easing for outline (slower)
      outlineX += (targetX - outlineX) * 0.08;
      outlineY += (targetY - outlineY) * 0.08;

      if (cursorRef.current) {
        cursorRef.current.style.transform = `translate(${mouseX - 5}px, ${mouseY - 5}px)`;
      }

      if (cursorOutlineRef.current) {
        cursorOutlineRef.current.style.transform = `translate(${outlineX - 15}px, ${outlineY - 15}px)`;
      }

      requestAnimationFrame(animateCursor);
    };

    window.addEventListener("mousemove", handleMouseMove);
    animateCursor();

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
    };
  }, []);

  return (
    <>
      {/* Main cursor dot */}
      <div
        ref={cursorRef}
        className="fixed w-2.5 h-2.5 bg-gradient-to-r from-wine-900 to-white rounded-full pointer-events-none z-[9999] shadow-lg"
        style={{
          boxShadow: "0 0 8px rgba(127, 29, 29, 0.8), 0 0 16px rgba(255, 255, 255, 0.4)",
          willChange: "transform",
        }}
      />

      {/* Cursor outline circle */}
      <div
        ref={cursorOutlineRef}
        className="fixed w-7 h-7 border-2 border-wine-900 rounded-full pointer-events-none z-[9998]"
        style={{
          boxShadow: "0 0 12px rgba(127, 29, 29, 0.4) inset, 0 0 8px rgba(255, 255, 255, 0.2) inset",
          willChange: "transform",
        }}
      />
    </>
  );
}
