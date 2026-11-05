"use client";

import { memo, type ReactNode } from "react";
import {
  motion,
  useMotionValue,
  useReducedMotion,
  useSpring,
} from "framer-motion";

export function MagneticButton({
  children,
  onClick,
  disabled,
  className = "button",
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  className?: string;
  type?: "button" | "submit";
}) {
  const reduced = useReducedMotion();
  const x = useMotionValue(0),
    y = useMotionValue(0);
  const sx = useSpring(x, { stiffness: 100, damping: 20 }),
    sy = useSpring(y, { stiffness: 100, damping: 20 });
  return (
    <motion.button
      type={type}
      className={className}
      onClick={onClick}
      disabled={disabled}
      style={{ x: sx, y: sy }}
      onPointerMove={(event) => {
        if (reduced || disabled || event.pointerType !== "mouse") return;
        const rect = event.currentTarget.getBoundingClientRect();
        x.set((event.clientX - rect.left - rect.width / 2) * 0.045);
        y.set((event.clientY - rect.top - rect.height / 2) * 0.06);
      }}
      onPointerLeave={() => {
        x.set(0);
        y.set(0);
      }}
    >
      {children}
    </motion.button>
  );
}

export const VoiceMark = memo(function VoiceMark({
  active = false,
  large = false,
}: {
  active?: boolean;
  large?: boolean;
}) {
  const reduced = useReducedMotion();
  return (
    <div
      aria-hidden="true"
      className={`flex items-center justify-center ${large ? "h-32 gap-2.5" : "h-6 gap-1"}`}
    >
      {[0.35, 0.65, 1, 0.75, 0.45].map((scale, index) => (
        <motion.span
          key={index}
          className={`block rounded-full bg-current ${large ? "h-20 w-2.5" : "h-5 w-1"}`}
          initial={false}
          animate={{
            scaleY: active && !reduced ? [scale, 1 - scale / 2, scale] : scale,
          }}
          transition={{
            duration: 1.7,
            repeat: active && !reduced ? Infinity : 0,
            delay: index * 0.12,
            ease: "easeInOut",
          }}
        />
      ))}
    </div>
  );
});
