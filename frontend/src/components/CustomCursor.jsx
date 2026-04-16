import { useEffect, useRef } from 'react';

function CustomCursor() {
  const containerRef = useRef(null);
  const mousePos = useRef({ x: window.innerWidth / 2, y: window.innerHeight / 2 });
  const animationRef = useRef(null);
  const billsRef = useRef([]);

  useEffect(() => {
    // Create 4 dollar bills with better initial positioning
    for (let i = 0; i < 4; i++) {
      const bill = document.createElement('div');
      bill.className = 'money-bill';
      bill.textContent = '$';
      bill.style.position = 'fixed';
      bill.style.pointerEvents = 'none';
      bill.style.zIndex = '9999';
      bill.style.width = '40px';
      bill.style.height = '52px';
      bill.style.background = 'linear-gradient(135deg, #34d399 0%, #10b981 100%)';
      bill.style.color = '#ffffff';
      bill.style.fontSize = '36px';
      bill.style.fontWeight = '900';
      bill.style.borderRadius = '6px';
      bill.style.border = '2px solid #059669';
      bill.style.display = 'flex';
      bill.style.alignItems = 'center';
      bill.style.justifyContent = 'center';
      bill.style.boxShadow = '0 10px 20px rgba(52, 211, 153, 0.5), inset -2px -2px 4px rgba(0,0,0,0.2)';
      bill.style.fontFamily = "'Arial Black', sans-serif";
      bill.style.willChange = 'transform';
      
      document.body.appendChild(bill);
      billsRef.current.push({
        element: bill,
        x: 0,
        y: 0,
        angle: (i / 4) * Math.PI * 2,
        index: i,
      });
    }

    // Handle mouse movement
    const onMouseMove = (e) => {
      mousePos.current.x = e.clientX;
      mousePos.current.y = e.clientY;
    };

    document.addEventListener('mousemove', onMouseMove);

    // Animation loop
    let frameCount = 0;
    const animate = () => {
      frameCount++;
      const time = frameCount / 60; // Convert frames to seconds at 60fps

      billsRef.current.forEach((bill, index) => {
        // Calculate orbital position
        const angle = bill.angle + time * 2.5;
        const radius = 70 + Math.sin(time * 1.2 + index * 0.5) * 15;

        // Position relative to mouse
        bill.x = mousePos.current.x + Math.cos(angle) * radius;
        bill.y = mousePos.current.y + Math.sin(angle) * radius;

        // Calculate rotation
        const rotation = (angle * 180 / Math.PI) + Math.sin(time * 5 + index) * 5;
        const wobble = Math.sin(time * 3 + index * Math.PI / 2) * 0.08;
        const scale = 1 + wobble;

        // Apply transform
        bill.element.style.transform = `
          translate(calc(-50% + ${bill.x}px), calc(-50% + ${bill.y}px))
          rotate(${rotation}deg)
          scale(${scale})
        `;
        
        // Add glow pulse
        const glowIntensity = 0.3 + Math.sin(time * 2) * 0.2;
        bill.element.style.boxShadow = `
          0 ${10 + glowIntensity * 10}px ${20 + glowIntensity * 10}px rgba(52, 211, 153, ${0.5 + glowIntensity}),
          inset -2px -2px 4px rgba(0,0,0,0.2)
        `;
      });

      animationRef.current = requestAnimationFrame(animate);
    };

    animate();

    // Cleanup
    return () => {
      document.removeEventListener('mousemove', onMouseMove);
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
      billsRef.current.forEach((bill) => {
        if (bill.element && bill.element.parentNode) {
          bill.element.parentNode.removeChild(bill.element);
        }
      });
      billsRef.current = [];
    };
  }, []);

  return (
    <div ref={containerRef} style={{ position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 9999 }}>
      <style>{`
        * {
          cursor: none !important;
        }
        
        .money-bill {
          box-shadow: 0 10px 20px rgba(52, 211, 153, 0.5);
          animation: moneyPulse 2s ease-in-out infinite;
        }
        
        @keyframes moneyPulse {
          0%, 100% {
            text-shadow: 0 0 0 rgba(52, 211, 153, 0);
          }
          50% {
            text-shadow: 0 0 8px rgba(52, 211, 153, 0.6);
          }
        }
      `}</style>
    </div>
  );
}

export default CustomCursor;
