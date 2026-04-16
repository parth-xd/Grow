import { useEffect, useRef } from 'react';

function CustomCursor() {
  const mousePos = useRef({ x: 0, y: 0 });
  const animationRef = useRef(null);
  const billsRef = useRef([]);
  const sparklesRef = useRef([]);

  useEffect(() => {
    // Create 4 dollar bills
    for (let i = 0; i < 4; i++) {
      const bill = document.createElement('div');
      bill.style.cssText = `
        position: fixed;
        pointer-events: none;
        z-index: 9998;
        width: 36px;
        height: 48px;
        background: linear-gradient(135deg, #34d399 0%, #10b981 100%);
        color: white;
        font-size: 32px;
        font-weight: 900;
        border-radius: 6px;
        display: flex;
        align-items: center;
        justify-content: center;
        border: 2px solid #059669;
        box-shadow: 
          0 8px 16px rgba(52, 211, 153, 0.4),
          inset -1px -1px 3px rgba(0, 0, 0, 0.2);
        opacity: 0.92;
        will-change: transform, opacity;
        font-family: 'Arial', sans-serif;
      `;
      bill.textContent = '$';
      document.body.appendChild(bill);
      billsRef.current.push({
        element: bill,
        x: 0,
        y: 0,
        vx: 0,
        vy: 0,
        angle: (i / 4) * Math.PI * 2,
        trail: [],
      });
    }

    // Create sparkle particles
    const createSparkles = () => {
      for (let i = 0; i < 12; i++) {
        const sparkle = document.createElement('div');
        sparkle.style.cssText = `
          position: fixed;
          pointer-events: none;
          z-index: 9997;
          width: 4px;
          height: 4px;
          background: rgba(52, 211, 153, 0.8);
          border-radius: 50%;
          box-shadow: 0 0 8px #34d399;
          opacity: 0;
          will-change: transform, opacity;
        `;
        document.body.appendChild(sparkle);
        sparklesRef.current.push({
          element: sparkle,
          x: 0,
          y: 0,
          vx: 0,
          vy: 0,
          life: 0,
          maxLife: 0.8,
        });
      }
    };

    createSparkles();

    // Track mouse
    const handleMouseMove = (e) => {
      mousePos.current.x = e.clientX;
      mousePos.current.y = e.clientY;
    };

    // Emit sparkles
    let sparkleCounter = 0;
    const emitSparkles = () => {
      sparkleCounter++;
      if (sparkleCounter % 3 === 0) {
        const randomBill = billsRef.current[Math.floor(Math.random() * 4)];
        for (let i = 0; i < 2; i++) {
          const sparkle = sparklesRef.current[Math.floor(Math.random() * sparklesRef.current.length)];
          if (sparkle && sparkle.life <= 0) {
            sparkle.x = randomBill.x;
            sparkle.y = randomBill.y;
            sparkle.vx = (Math.random() - 0.5) * 150;
            sparkle.vy = (Math.random() - 0.5) * 150;
            sparkle.life = 1;
          }
        }
      }
    };

    // Animation loop
    const animate = () => {
      const time = Date.now() / 1000;
      const dt = 1 / 60; // 60fps

      // Update bills
      billsRef.current.forEach((bill, index) => {
        const angle = bill.angle + time * 2.2;
        const radius = 60 + Math.sin(time * 1.3 + index) * 14;

        bill.x = mousePos.current.x + Math.cos(angle) * radius;
        bill.y = mousePos.current.y + Math.sin(angle) * radius;

        const rotation = (angle * 180) / Math.PI;
        const wiggle = Math.sin(time * 4 + index) * 0.05;
        
        bill.element.style.transform = `
          translate(${bill.x}px, ${bill.y}px) 
          translate(-50%, -50%) 
          rotate(${rotation + wiggle * 10}deg)
          scale(${0.92 + wiggle})
        `;
      });

      // Update sparkles
      emitSparkles();
      sparklesRef.current.forEach((sparkle) => {
        sparkle.life -= dt;
        if (sparkle.life > 0) {
          sparkle.x += sparkle.vx * dt;
          sparkle.y += sparkle.vy * dt;
          sparkle.vy += 100 * dt; // gravity
          
          const opacity = (sparkle.life / sparkle.maxLife) * 0.8;
          sparkle.element.style.transform = `translate(${sparkle.x}px, ${sparkle.y}px) scale(${1 + (1 - sparkle.life / sparkle.maxLife)})`;
          sparkle.element.style.opacity = opacity;
        } else {
          sparkle.element.style.opacity = 0;
        }
      });

      animationRef.current = requestAnimationFrame(animate);
    };

    animate();
    window.addEventListener('mousemove', handleMouseMove);

    // Cleanup
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      if (animationRef.current) cancelAnimationFrame(animationRef.current);
      billsRef.current.forEach((bill) => {
        if (bill.element.parentNode) bill.element.parentNode.removeChild(bill.element);
      });
      sparklesRef.current.forEach((sparkle) => {
        if (sparkle.element.parentNode) sparkle.element.parentNode.removeChild(sparkle.element);
      });
      billsRef.current = [];
      sparklesRef.current = [];
    };
  }, []);

  return (
    <style>{`
      * { cursor: none !important; }
      
      @keyframes moneyFloat {
        0%, 100% { filter: drop-shadow(0 4px 8px rgba(52, 211, 153, 0.4)); }
        50% { filter: drop-shadow(0 8px 16px rgba(52, 211, 153, 0.6)); }
      }
    `}</style>
  );
}

export default CustomCursor;
