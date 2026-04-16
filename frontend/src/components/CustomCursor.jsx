import { useEffect, useRef } from 'react';

function CustomCursor() {
  const mousePos = useRef({ x: 0, y: 0 });
  const animationRef = useRef(null);
  const billsRef = useRef([]);

  useEffect(() => {
    // Create 4 dollar bills
    for (let i = 0; i < 4; i++) {
      const bill = document.createElement('div');
      bill.style.cssText = `
        position: fixed;
        pointer-events: none;
        z-index: 9998;
        width: 32px;
        height: 44px;
        background: linear-gradient(135deg, #34d399, #10b981);
        color: white;
        font-size: 28px;
        font-weight: bold;
        border-radius: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
        border: 1.5px solid #059669;
        box-shadow: 0 4px 12px rgba(52, 211, 153, 0.4);
        opacity: 0.8;
        will-change: transform, opacity;
      `;
      bill.textContent = '$';
      document.body.appendChild(bill);
      billsRef.current.push({
        element: bill,
        x: 0,
        y: 0,
        angle: (i / 4) * Math.PI * 2,
      });
    }

    // Track mouse
    const handleMouseMove = (e) => {
      mousePos.current.x = e.clientX;
      mousePos.current.y = e.clientY;
    };

    // Animation loop
    const animate = () => {
      const time = Date.now() / 1000;

      billsRef.current.forEach((bill, index) => {
        const angle = bill.angle + time * 2;
        const radius = 55 + Math.sin(time * 1.5 + index) * 12;

        bill.x = mousePos.current.x + Math.cos(angle) * radius;
        bill.y = mousePos.current.y + Math.sin(angle) * radius;

        const rotation = (angle * 180) / Math.PI;
        bill.element.style.transform = `
          translate(${bill.x}px, ${bill.y}px) 
          translate(-50%, -50%) 
          rotate(${rotation}deg)
          scale(0.95)
        `;
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
      billsRef.current = [];
    };
  }, []);

  return (
    <style>{`
      * { cursor: none !important; }
    `}</style>
  );
}

export default CustomCursor;
