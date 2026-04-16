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

    // Create particle elements with proper SVG
    const createParticles = () => {
      particles.length = 0;
      const particleCount = 4;
      
      for (let i = 0; i < particleCount; i++) {
        const element = document.createElement('div');
        element.className = 'custom-cursor-particle';
        element.style.position = 'fixed';
        element.style.pointerEvents = 'none';
        element.style.zIndex = '9998';
        element.style.width = '24px';
        element.style.height = '32px';
        element.style.willChange = 'transform';
        element.style.display = 'flex';
        element.style.alignItems = 'center';
        element.style.justifyContent = 'center';
        
        // Create SVG element properly
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('viewBox', '0 0 24 32');
        svg.setAttribute('width', '24');
        svg.setAttribute('height', '32');
        svg.setAttribute('style', 'width: 100%; height: 100%;');
        
        // Define gradient
        const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
        const gradient = document.createElementNS('http://www.w3.org/2000/svg', 'linearGradient');
        gradient.setAttribute('id', `billGradient${i}`);
        gradient.setAttribute('x1', '0%');
        gradient.setAttribute('y1', '0%');
        gradient.setAttribute('x2', '100%');
        gradient.setAttribute('y2', '100%');
        
        const stop1 = document.createElementNS('http://www.w3.org/2000/svg', 'stop');
        stop1.setAttribute('offset', '0%');
        stop1.setAttribute('style', 'stop-color:#34d399;stop-opacity:1');
        
        const stop2 = document.createElementNS('http://www.w3.org/2000/svg', 'stop');
        stop2.setAttribute('offset', '100%');
        stop2.setAttribute('style', 'stop-color:#10b981;stop-opacity:1');
        
        gradient.appendChild(stop1);
        gradient.appendChild(stop2);
        defs.appendChild(gradient);
        svg.appendChild(defs);
        
        // Bill background
        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', '1');
        rect.setAttribute('y', '1');
        rect.setAttribute('width', '22');
        rect.setAttribute('height', '30');
        rect.setAttribute('rx', '2');
        rect.setAttribute('fill', `url(#billGradient${i})`);
        rect.setAttribute('stroke', '#059669');
        rect.setAttribute('stroke-width', '1');
        svg.appendChild(rect);
        
        // Dollar sign
        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', '12');
        text.setAttribute('y', '22');
        text.setAttribute('font-size', '22');
        text.setAttribute('font-weight', '900');
        text.setAttribute('fill', '#ffffff');
        text.setAttribute('text-anchor', 'middle');
        text.setAttribute('dominant-baseline', 'middle');
        text.setAttribute('font-family', 'Arial, sans-serif');
        text.textContent = '$';
        svg.appendChild(text);
        
        // Top line
        const line1 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line1.setAttribute('x1', '3');
        line1.setAttribute('y1', '4');
        line1.setAttribute('x2', '21');
        line1.setAttribute('y2', '4');
        line1.setAttribute('stroke', '#ffffff');
        line1.setAttribute('stroke-width', '0.8');
        line1.setAttribute('opacity', '0.4');
        svg.appendChild(line1);
        
        // Bottom line
        const line2 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line2.setAttribute('x1', '3');
        line2.setAttribute('y1', '28');
        line2.setAttribute('x2', '21');
        line2.setAttribute('y2', '28');
        line2.setAttribute('stroke', '#ffffff');
        line2.setAttribute('stroke-width', '0.8');
        line2.setAttribute('opacity', '0.4');
        svg.appendChild(line2);
        
        element.appendChild(svg);
        document.body.appendChild(element);
        
        particles.push({
          element,
          x: 0,
          y: 0,
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
        const angle = particle.angle + time * 0.5;
        const distance = 45 + Math.sin(time * 1.5 + index) * 8;
        
        particle.x = mousePos.current.x + Math.cos(angle) * distance;
        particle.y = mousePos.current.y + Math.sin(angle) * distance;
        particle.rotation = (angle * 180 / Math.PI + time * 100) % 360;

        if (particle.element) {
          const isHovering = cursorRef.current?.classList.contains('active');
          const scale = isHovering ? 1.2 : 0.8;
          const opacity = isHovering ? '1' : '0.65';
          
          particle.element.style.transform = `translate(${particle.x}px, ${particle.y}px) translate(-50%, -50%) rotate(${particle.rotation}deg) scale(${scale})`;
          particle.element.style.opacity = opacity;
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

export default CustomCursor;
