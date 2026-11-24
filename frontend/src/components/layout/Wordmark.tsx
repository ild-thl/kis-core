import Image from "next/image";

/** The name of the platform as text, for places that need it as a string. */
const BRAND_NAME = "askFrancis";

// The wordmark has no bird, so it is flatter: these heights keep the width the old logo had.
const SIZES = { sm: { plate: "logo-plate logo-plate--sm", img: "h-3.5", francis: "h-[1.625rem]" }, md: { plate: "logo-plate", img: "h-[1.0625rem]", francis: "h-[2.125rem]" } } as const;

/** The transparent logo on a white plate, the plate is styled in CSS so the ground stays adjustable. */
export default function Wordmark({ size = "md", className = "", birdOnly = false, francis = false, plate = true, themed = false }: { size?: keyof typeof SIZES; className?: string; birdOnly?: boolean; francis?: boolean; plate?: boolean; themed?: boolean }) {
  const s = SIZES[size];
  if (themed) {
    // Without a plate on the page ground: the dark wordmark in light mode, the white one in dark mode.
    return (
      <span className={`inline-flex items-center ${className}`.trim()}>
        <Image src="/logos/askfrancis-logo-transparent-black-ohne-francis.svg" alt={BRAND_NAME} width={90} height={13} className={`${s.img} w-auto dark:hidden`} priority />
        <Image src="/logos/askfrancis-logo-transparent-white-ohne-francis.svg" alt={BRAND_NAME} width={90} height={13} className={`${s.img} w-auto hidden dark:block`} priority />
      </span>
    );
  }
  if (birdOnly) {
    return (
      <span className={`${s.plate} ${className}`.trim()}>
        <Image src="/logos/kis-vogel.svg" alt={BRAND_NAME} width={154} height={78} className={`${s.img} w-auto`} priority />
      </span>
    );
  }
  if (!plate) {
    // Without the plate the wordmark is white on the blue bar; with Francis he stands left of the name.
    return (
      <span className={`inline-flex items-center ${className}`.trim()}>
        {francis ? (
          <Image src="/logos/askfrancis-logo-transparent-white.svg" alt={BRAND_NAME} width={121} height={26} className={`${s.francis} logo-francis w-auto`} priority />
        ) : (
          <Image src="/logos/askfrancis-logo-transparent-white-ohne-francis.svg" alt={BRAND_NAME} width={90} height={13} className={`${s.img} w-auto`} priority />
        )}
      </span>
    );
  }
  if (francis) {
    return (
      <span className={`${s.plate} ${className}`.trim()}>
        <Image src="/logos/askfrancis-logo-transparent-black.svg" alt={BRAND_NAME} width={121} height={23} className={`${s.francis} logo-francis w-auto`} priority />
      </span>
    );
  }
  return (
    <span className={`${s.plate} ${className}`.trim()}>
      <Image src="/logos/askfrancis-logo-transparent-black-ohne-francis.svg" alt={BRAND_NAME} width={90} height={13} className={`${s.img} w-auto`} priority />
    </span>
  );
}
