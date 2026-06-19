import { useEffect, useRef, useState } from "react";

// Count-animates from the previous value to the new one whenever it changes
// (FRONTEND_SPEC Section 4 motion: "big numbers count-animate when values
// change"). easeOutCubic, ~600ms.
export default function AnimatedNumber({
  value,
  duration = 600,
  format = (v) => Math.round(v).toLocaleString(),
  className,
  style,
}) {
  const [display, setDisplay] = useState(value ?? 0);
  const fromRef = useRef(value ?? 0);
  const rafRef = useRef(0);

  useEffect(() => {
    const from = fromRef.current;
    const to = value ?? 0;
    if (from === to) return;
    const start = performance.now();
    cancelAnimationFrame(rafRef.current);

    const tick = (now) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(from + (to - from) * eased);
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = to;
      }
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [value, duration]);

  return (
    <span className={className} style={style}>
      {format(display)}
    </span>
  );
}
