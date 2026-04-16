import { useEffect, useState, useRef } from 'react';

function CustomCursor() {
  const cursorRef = useRef(null);
  const particlesRef = useRef([]);
  const mousePos = useRef({ x: 0, y: 0 });
  const [isHovering, setIsHovering] = useState(false);
  const [hidden, setHidden] = useState(true);
  const animationRef = useRef(null);

  useEffect(() => {
    const handleMouseMove = (e) => {
      mousePos.current = { x: e.clientX, y: e.clientY };
      
      if (cursorRef.current) {
        cursorRef.current.style.left = e.clientX + 'px';
        cursorRef.current.style.top = e.clientY + 'px';
      }

      // Update particles
      if (particlesRef.current.length > 0) {
        particlesRef.current.forEach((particle, index) => {
          const angle = (index / particlesRef.current.length) * Math.PI * 2;
          const distance = 40 + Math.sin(Date.now() / 500 + angle) * 10;
          
          particle.x = mousePos.current.x + Math.cos(angle) * distance;
          particle.y = mousePos.current.y + Math.sin(angle) * distance;
          particle.rotation = (Date.now() / 20 + angle * 180) % 360;
          
          if (particle.element) {
            particle.element.style.left = particle.x + 'px';
            particle.element.style.top = particle.y + 'px';
            particle.element.style.transform = `translate(-50%, -50%) rotate(${particle.rotation}deg) scale(${isHovering ? 1 : 0.5})`;
            particle.element.style.opacity = isHovering ? 0.8 : 0.3;
          }
        });
      }
    };

    const handleMouseEnter = (e) => {
      setHidden(false);
      // Check if hovering over interactive elements
      if (e.target.closest('.hover-cursor') || e.target.closest('button') || e.target.closest('a')) {
        setIsHovering(true);
      }
    };

    const handleMouseLeave = () => {
      setHidden(true);
      setIsHovering(false);
    };

    const handleMouseOver = (e) => {
      if (e.target.closest('.hover-cursor')) {
        setIsHovering(true);
      }
    };

    const handleMouseOut = (e) => {
      if (e.target.closest('.hover-cursor')) {
        setIsHovering(false);
      }
    };

    // Create particles on mount
    const createParticles = () => {
      const particleCount = 6;
      particlesRef.current = [];
      
      for (let i = 0; i < particleCount; i++) {
        const element = document.createElement('div');
        element.className = 'custom-cursor-particle';
        element.innerHTML = i % 2 === 0 ? '💰' : '📈';
        element.style.position = 'fixed';
        element.style.pointerEvents = 'none';
        element.style.fontSize = '16px';
        element.style.zIndex = '9998';
        element.style.transition = 'all 0.3s cubic-bezier(0.23, 1, 0.320, 1)';
        document.body.appendChild(element);
        
        particlesRef.current.push({
          element,
          x: 0,
          y: 0,
          rotation: 0
        });
      }
    };

    createParticles();
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseenter', handleMouseEnter);
    window.addEventListener('mouseleave', handleMouseLeave);
    document.addEventListener('mouseover', handleMouseOver);
    document.addEventListener('mouseout', handleMouseOut);

    // Animation loop
    const animate = () => {
      animationRef.current = requestAnimationFrame(animate);
    };
    
    animate();

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseenter', handleMouseEnter);
      window.removeEventListener('mouseleave', handleMouseLeave);
      document.removeEventListener('mouseover', handleMouseOver);
      document.removeEventListener('mouseout', handleMouseOut);
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
      particlesRef.current.forEach(p => {
        if (p.element && p.element.parentNode) {
          p.element.parentNode.removeChild(p.element);
        }
      });
    };
  }, [isHovering]);

  return (
    <>
      {/* Main cursor */}
      <div
        ref={cursorRef}
        className={`custom-cursor ${hidden ? 'hidden' : ''}`}
        style={{
          position: 'fixed',
          pointerEvents: 'none',
          zIndex: 9999,
          transition: 'transform 0.1s ease-out',
          transform: `translate(-50%, -50%) scale(${isHovering ? 1.2 : 1})`,
        }}
      >
        <div className={`w-8 h-8 rounded-full border-2 transition-all duration-300 ${
          isHovering 
            ? 'border-blue-500 bg-blue-50 shadow-lg shadow-blue-500/50' 
            : 'border-gray-400 bg-white/20'
        }`}
        >
          <div className="w-1 h-1 bg-blue-500 rounded-full absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2"></div>
        </div>
      </div>

      {/* Hide default cursor */}
      <style>{`
        * {
          cursor: none !important;
        }
        
        .custom-cursor-particle {
          will-change: transform;
        }
        
        @keyframes pulse-cursor {
          0%, 100% {
            transform: scale(1);
          }
          50% {
            transform: scale(1.1);
          }
        }
      `}</style>
    </>
  );
}

export default CustomCursor;
