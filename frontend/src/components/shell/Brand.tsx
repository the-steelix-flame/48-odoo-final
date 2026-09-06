/**
 * The DealFlow360 mark and wordmark.  Owner: the-steelix-flame.
 *
 * One definition, three surfaces. The sidebar and the login panel had their
 * own hand-rolled copies at different sizes, and the customer portal had no
 * mark at all — just the words — so the product looked like two products
 * depending on which side of it you were signed in to.
 *
 * Sizes are explicit rather than scaled by CSS: the inner diamond and the dot
 * are small enough that a transform makes them blur.
 */

const SIZES = {
  sm: { box: 28, radius: 9, diamond: 12, dot: 5, inset: 4, text: "text-[16px]" },
  md: { box: 34, radius: 11, diamond: 15, dot: 6, inset: 5, text: "text-[19px]" },
  lg: { box: 40, radius: 12, diamond: 18, dot: 8, inset: 6, text: "text-2xl" },
} as const;

export function BrandMark({ size = "sm" }: { size?: keyof typeof SIZES }) {
  const s = SIZES[size];
  return (
    <div
      className="relative flex shrink-0 items-center justify-center bg-gradient-to-br from-[#22D3EE] via-[#0891B2] to-[#0E7490] shadow-[inset_0_0_0_1px_rgba(255,255,255,0.34),0_8px_18px_-10px_rgba(8,145,178,0.9)]"
      style={{ height: s.box, width: s.box, borderRadius: s.radius }}
      aria-hidden
    >
      <div
        className="rotate-45 rounded-[3px] bg-[#F8FAFC]"
        style={{ height: s.diamond, width: s.diamond }}
      />
      <div
        className="absolute rounded-full bg-[#0F172A]"
        style={{ height: s.dot, width: s.dot, bottom: s.inset, right: s.inset }}
      />
    </div>
  );
}

export function Brand({
  size = "sm",
  className = "",
}: {
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const s = SIZES[size];
  return (
    <span className={`flex items-center gap-[10px] ${className}`}>
      <BrandMark size={size} />
      <span
        className={`font-heading font-semibold tracking-[-0.02em] text-[#F8FAFC] ${s.text}`}
      >
        DealFlow<span className="text-[#22D3EE]">360</span>
      </span>
    </span>
  );
}
