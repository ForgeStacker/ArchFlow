import { motion } from "framer-motion";
import { useEffect, useRef } from "react";
import gsap from "gsap";

/**
 * GSAP drives the floating service-icon illustration: each tile drifts on
 * its own independent slow loop plus a shared pointer-parallax, while
 * Framer Motion handles the one-time entrance of the text block. This is a
 * decorative hero only — no state, no data dependency.
 */
export function HeroSection() {
  const containerRef = useRef<HTMLDivElement>(null);
  const tileRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    const timeline = gsap.timeline({ repeat: -1, yoyo: true, defaults: { ease: "sine.inOut" } });
    tileRefs.current.forEach((tile, index) => {
      if (!tile) return;
      timeline.to(
        tile,
        { y: index % 2 === 0 ? -10 : 10, duration: 4 + index * 0.6 },
        0,
      );
    });

    const handlePointerMove = (event: PointerEvent) => {
      const bounds = containerRef.current?.getBoundingClientRect();
      if (!bounds) return;
      const relativeX = (event.clientX - bounds.left) / bounds.width - 0.5;
      gsap.to(tileRefs.current, {
        x: (index) => relativeX * (6 + index * 2),
        rotate: (index) => relativeX * (index % 2 === 0 ? 3 : -3),
        duration: 0.9,
        ease: "power2.out",
        overwrite: "auto",
      });
    };

    const node = containerRef.current;
    node?.addEventListener("pointermove", handlePointerMove);
    return () => {
      node?.removeEventListener("pointermove", handlePointerMove);
      timeline.kill();
    };
  }, []);

  return (
    <div className="grid grid-cols-1 items-center gap-8 lg:grid-cols-[1.1fr_0.9fr]">
      <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
        <p className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">
          AI-powered architecture diagrams
        </p>
        <h1 className="mt-2 text-[34px] font-bold leading-[1.15] tracking-tight text-text-primary">
          Turn your ideas into
          <br />
          <span className="text-brand">production-ready</span> architecture diagrams.
        </h1>
        <p className="mt-3 max-w-md text-[15px] leading-relaxed text-text-secondary">
          Describe your system in plain language. The compiler handles the
          architecture, icons, and connections.
        </p>
      </motion.div>

      <motion.div
        ref={containerRef}
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.6, delay: 0.1 }}
        className="relative hidden h-[220px] rounded-2xl bg-hero-wash lg:block"
      >
        <svg className="absolute inset-0 h-full w-full" aria-hidden="true">
          <line x1="30%" y1="35%" x2="55%" y2="55%" stroke="#B85738" strokeWidth="1.5" strokeDasharray="4 5" opacity="0.35" />
          <line x1="55%" y1="55%" x2="78%" y2="30%" stroke="#4D8A6A" strokeWidth="1.5" strokeDasharray="4 5" opacity="0.35" />
          <line x1="55%" y1="55%" x2="75%" y2="70%" stroke="#5577A8" strokeWidth="1.5" strokeDasharray="4 5" opacity="0.35" />
        </svg>

        <IconTile
          tileRef={(el) => (tileRefs.current[0] = el)}
          className="left-[16%] top-[28%]"
          iconId="aws:service:compute:aws-lambda"
          label="AWS Lambda"
        />
        <IconTile
          tileRef={(el) => (tileRefs.current[1] = el)}
          className="left-[48%] top-[46%]"
          iconId="aws:service:databases:amazon-dynamodb"
          label="Amazon DynamoDB"
        />
        <IconTile
          tileRef={(el) => (tileRefs.current[2] = el)}
          className="left-[70%] top-[18%]"
          iconId="aws:service:networking-content-delivery:amazon-api-gateway"
          label="Amazon API Gateway"
          small
        />
        <IconTile
          tileRef={(el) => (tileRefs.current[3] = el)}
          className="left-[68%] top-[62%]"
          iconId="aws:service:storage:amazon-simple-storage-service"
          label="Amazon S3"
        />

        <span className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full border border-border bg-surface px-3 py-1 text-[11px] font-medium text-text-secondary shadow-card">
          From idea to diagram
        </span>
      </motion.div>
    </div>
  );
}

interface IconTileProps {
  className: string;
  iconId: string;
  label: string;
  small?: boolean;
  tileRef: (el: HTMLDivElement | null) => void;
}

function iconAssetUrl(iconId: string): string {
  return `/api/icons/${encodeURIComponent(iconId)}/asset`;
}

function IconTile({ className, iconId, label, small, tileRef }: IconTileProps) {
  return (
    <div
      ref={tileRef}
      className={`absolute grid animate-float-slow place-items-center rounded-xl border border-border bg-surface shadow-elevated ${
        small ? "h-10 w-10" : "h-12 w-12"
      } ${className}`}
    >
      <img
        src={iconAssetUrl(iconId)}
        alt={label}
        title={label}
        loading="eager"
        className="h-[72%] w-[72%] object-contain"
      />
    </div>
  );
}
