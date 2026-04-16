import { useEffect } from 'react';

function CustomCursor() {
  useEffect(() => {
    // Skip on mobile/touch devices (only for desktop cursors)
    if (window.matchMedia('(hover: none)').matches || window.matchMedia('(pointer: coarse)').matches) {
      return;
    }

    const bills = [];
    let mouseX = 0;
    let mouseY = 0;
    let frameCount = 0;

    // Create 4 dollar bills
    for (let i = 0; i < 4; i++) {
      const bill = document.createElement('div');
      bill.innerHTML = '$';
      bill.style.position = 'fixed';
      bill.style.top = '0';
      bill.style.left = '0';
      bill.style.width = '25px';
      bill.style.height = '30px';
      bill.style.fontSize = '20px';
      bill.style.fontWeight = '900';
      bill.style.color = '#ffffff';
      bill.style.background = 'linear-gradient(135deg, #34d399 0%, #10b981 100%)';
      bill.style.border = '1.5px solid #059669';
      bill.style.borderRadius = '4px';
      bill.style.display = 'flex';
      bill.style.alignItems = 'center';
      bill.style.justifyContent = 'center';
      bill.style.boxShadow = '0 6px 12px rgba(52, 211, 153, 0.6)';
      bill.style.zIndex = '999999';
      bill.style.pointerEvents = 'none';
      bill.style.willChange = 'transform';
      bill.style.fontFamily = 'Arial Black, sans-serif';
      bill.style.userSelect = 'none';

      document.body.appendChild(bill);
      bills.push({
        el: bill,
        x: 0,
        y: 0,
        angle: (i / 4) * Math.PI * 2,
      });
    }

    // Track mouse
    const handleMouseMove = (e) => {
      mouseX = e.clientX;
      mouseY = e.clientY;
    };

    document.addEventListener('mousemove', handleMouseMove, false);

    // Animation loop
    const animate = () => {
      frameCount++;
      const time = frameCount / 60; // 60fps timer

      bills.forEach((bill, i) => {
        const angle = bill.angle + time * 2.4;
        const distance = 35 + Math.sin(time + i) * 8;

        bill.x = mouseX + Math.cos(angle) * distance;
        bill.y = mouseY + Math.sin(angle) * distance;

        const rotation = (angle * 180) / Math.PI;
        const scale = 0.9 + Math.sin(time * 2 + i) * 0.15;

        bill.el.style.transform = `translate(${bill.x - 12.5}px, ${bill.y - 15}px) rotate(${rotation}deg) scale(${scale})`;
        bill.el.style.opacity = '0.95';
      });

      requestAnimationFrame(animate);
    };

    animate();

    // Cleanup
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      bills.forEach((bill) => {
        if (bill.el.parentNode) {
          bill.el.parentNode.removeChild(bill.el);
        }
      });
    };
  }, []);

  return null;
}

export default CustomCursor;
