import { useEffect, useRef } from 'react';

function CustomCursor() {
  const cursorRef = useRef(null);
  const particlesRef = useRef([]);
  const mousePos = useRef({ x: 0, y: 0 });
  const rafRef = useRef(null);

  useEffect(() => {
    const cursor = cursorRef.current;
    const particles = particlesRef.current;

    const handleMouseMove = (e) => {
      mousePos.current.x = e.clientX;
      mousePos.current.y = e.clientY;

      // Update cursor position
      if (cursor) {
        cursor.style.transform = `translate(calc(-50% + ${e.clientX}px), calc(-50% + ${e.clientY}px))`;
      }

      // Check if hovering over interactive elements
      const target = e.target;
      const isInteractive = target.closest('.hover-cursor') || 
                           target.closest('button') || 
                           target.closest('a') ||
                           target.tagName === 'BUTTON' ||
                           target.tagName === 'A';
      
      cursor?.classList.toggle('active', isInteractive);
    };

    // Create particle elements
    const createParticles = () => {
      particles.length = 0;
      const particleCount = 4; // Reduced from 6 for better performance
      
      for (let i = 0; i < particleCount; i++) {
        const element = document.createElement('div');
        element.className = 'custom-cursor-particle';
        element.innerHTML = DollarBillSVG();
        element.style.position = 'fixed';
        element.style.pointerEvents = 'none';
        element.style.zIndex = '9998';
        element.style.width = '24px';
        element.style.height = '32px';
        element.style.willChange = 'transform';
        document.body.appendChild(element);
        
        particles.push({
          element,
          x: 0,
          y: 0,
          vx: 0,
          vy: 0,
          rotation: 0,
          angle: (i / particleCount) * Math.PI * 2,
        });
      }
    };

    createParticles();

    // Optimized animation loop
    const animate = () => {
      const now = Date.now();
      const time = now / 1000;

      particles.forEach((particle, index) => {
        const angle = particle.angle + time * 0.5; // Orbital speed
        const distance = 45 + Math.sin(time * 1.5 + index) * 8;
        
        particle.x = mousePos.current.x + Math.cos(angle) * distance;
        particle.y = mousePos.current.y + Math.sin(angle) * distance;
        particle.rotation = (angle * 180 / Math.PI + time * 100) % 360;

        if (particle.element) {
          const isHovering = cursorRef.current?.classList.contains('active');
          particle.element.style.transform = `
            translate(${particle.x}px, ${particle.y}px) 
            translate(-50%, -50%) 
            rotate(${particle.rotation}deg) 
            scale(${isHovering ? 1.2 : 0.8})
          `;
          particle.element.style.opacity = isHovering ? '1' : '0.65';
        }
      });

      rafRef.current = requestAnimationFrame(animate);
    };

    animate();

    window.addEventListener('mousemove', handleMouseMove);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
      }

      particles.forEach(p => {
        if (p.element?.parentNode) {
          p.element.parentNode.removeChild(p.element);
        }
      });
      particles.length = 0;
    };
  }, []);

  return (
    <>
      {/* Main cursor */}
      <div
        ref={cursorRef}
        className="custom-cursor"
        style={{
          position: 'fixed',
          pointerEvents: 'none',
          zIndex: 9999,
          width: '32px',
          height: '32px',
          willChange: 'transform',
          top: 0,
          left: 0,
        }}
      >
        <div className="cursor-ring">
          <svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="16" cy="16" r="14" stroke="currentColor" strokeWidth="2" className="ring-outer" />
            <circle cx="16" cy="16" r="10" stroke="currentColor" strokeWidth="1.5" opacity="0.5" className="ring-inner" />
            <circle cx="16" cy="16" r="3" fill="currentColor" className="ring-center" />
          </svg>
        </div>
      </div>

      {/* Styles */}
      <style>{`
        .custom-cursor {
          color: rgb(59, 130, 246);
        }

        .custom-cursor.active {
          color: rgb(59, 130, 246);
          filter: drop-shadow(0 0 16px rgba(59, 130, 246, 0.6));
        }

        .cursor-ring {
          position: absolute;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
        }

        .cursor-ring svg {
          filter: drop-shadow(0 0 8px rgba(59, 130, 246, 0.3));
          transition: filter 0.3s ease;
        }

        .custom-cursor.active .cursor-ring svg {
          filter: drop-shadow(0 0 16px rgba(59, 130, 246, 0.6));
        }

        .ring-outer {
          animation: pulse-ring 2s ease-in-out infinite;
        }

        .ring-center {
          animation: pulse-center 1.5s ease-in-out infinite;
        }

        @keyframes pulse-ring {
          0%, 100% {
            r: 14;
            opacity: 1;
          }
          50% {
            r: 15;
            opacity: 0.8;
          }
        }

        @keyframes pulse-center {
          0%, 100% {
            r: 3;
            opacity: 1;
          }
          50% {
            r: 3.5;
            opacity: 0.7;
          }
        }

        .custom-cursor-particle {
          will-change: transform;
        }

        * {
          cursor: none !important;
        }
      `}</style>
    </>
  );
}

function DollarBillSVG() {
  return `
    <svg viewBox="0 0 24 32" fill="none" xmlns="http://www.w3.org/2000/svg" style="width: 100%; height: 100%;">
      <defs>
        <linearGradient id="billGradient${Math.random()}" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style="stop-color:#34d399;stop-opacity:1" />
          <stop offset="100%" style="stop-color:#10b981;stop-opacity:1" />
        </linearGradient>
      </defs>
      
      <!-- Bill background with gradient -->
      <rect x="1" y="1" width="22" height="30" rx="2" fill="url(#billGradient${Math.random()})" stroke="#059669" stroke-width="1"/>
      
      <!-- Dollar sign - larger and bolder -->
      <text x="12" y="22" font-size="22" font-weight="900" fill="#ffffff" text-anchor="middle" dominant-baseline="middle" font-family="Arial, sans-serif">$</text>
      
      <!-- Top decorative line -->
      <line x1="3" y1="4" x2="21" y2="4" stroke="#ffffff" stroke-width="0.8" opacity="0.4"/>
      
      <!-- Bottom decorative line -->
      <line x1="3" y1="28" x2="21" y2="28" stroke="#ffffff" stroke-width="0.8" opacity="0.4"/>
      
      <!-- Corner dots for authenticity -->
      <circle cx="4" cy="5" r="0.8" fill="#ffffff" opacity="0.6"/>
      <circle cx="20" cy="27" r="0.8" fill="#ffffff" opacity="0.6"/>
    </svg>
  `;
}

export default CustomCursor;
