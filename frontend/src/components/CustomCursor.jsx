import { useEffect, useRef } from 'react';

function CustomCursor() {
  const cursorRef = useRef(null);
  const particlesRef = useRef([]);
  const mousePos = useRef({ x: 0, y: 0 });
  const lastPos = useRef({ x: 0, y: 0 });
  const rafRef = useRef(null);
  const particleCanvasRef = useRef(null);
  const contextRef = useRef(null);

  useEffect(() => {
    const cursor = cursorRef.current;
    const particles = particlesRef.current;

    const handleMouseMove = (e) => {
      mousePos.current.x = e.clientX;
      mousePos.current.y = e.clientY;

      // Update cursor position
      if (cursor) {
        cursor.style.left = e.clientX + 'px';
        cursor.style.top = e.clientY + 'px';
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

    const handleMouseEnter = () => {
      cursor?.classList.remove('hidden');
    };

    const handleMouseLeave = () => {
      cursor?.classList.add('hidden');
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
            scale(${isHovering ? 1 : 0.6})
          `;
          particle.element.style.opacity = isHovering ? '0.85' : '0.4';
        }
      });

      rafRef.current = requestAnimationFrame(animate);
    };

    animate();

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseenter', handleMouseEnter);
    window.addEventListener('mouseleave', handleMouseLeave);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseenter', handleMouseEnter);
      window.removeEventListener('mouseleave', handleMouseLeave);
      
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
        className="custom-cursor hidden"
        style={{
          position: 'fixed',
          pointerEvents: 'none',
          zIndex: 9999,
          width: '32px',
          height: '32px',
          willChange: 'transform',
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
          transition: color 0.3s ease;
        }

        .custom-cursor.active {
          color: rgb(59, 130, 246);
        }

        .custom-cursor.hidden {
          display: none;
        }

        .cursor-ring {
          position: absolute;
          top: -50%;
          left: -50%;
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
      <!-- Bill background -->
      <rect x="2" y="2" width="20" height="28" rx="2" fill="#10b981" stroke="#059669" stroke-width="1.5"/>
      
      <!-- Security pattern -->
      <g opacity="0.15">
        <circle cx="8" cy="8" r="1.5" fill="#000"/>
        <circle cx="16" cy="8" r="1.5" fill="#000"/>
        <circle cx="8" cy="24" r="1.5" fill="#000"/>
        <circle cx="16" cy="24" r="1.5" fill="#000"/>
      </g>
      
      <!-- Dollar sign -->
      <text x="12" y="20" font-size="18" font-weight="bold" fill="#fff" text-anchor="middle" font-family="system-ui">$</text>
      
      <!-- Shimmer effect -->
      <defs>
        <linearGradient id="shimmer" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style="stop-color:#fff;stop-opacity:0" />
          <stop offset="50%" style="stop-color:#fff;stop-opacity:0.3" />
          <stop offset="100%" style="stop-color:#fff;stop-opacity:0" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="20" height="28" rx="2" fill="url(#shimmer)" stroke="none"/>
    </svg>
  `;
}

export default CustomCursor;
