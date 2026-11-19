export function Footer() {
  return (
    <footer className="relative z-10 border-t border-line">
      <div className="mx-auto flex max-w-6xl flex-col gap-1 px-4 py-4 text-xs text-faint sm:flex-row sm:items-center sm:justify-between">
        <p>
          <span className="font-semibold text-warn">Warning:</span> most brand-new tokens are high-risk, illiquid or
          outright scams (honeypots, rug pulls). A fast pump is often followed by a faster dump. Nothing here is
          financial advice. Do your own research.
        </p>
        <p className="shrink-0 font-mono">Data: PumpPortal · pumpdev · publicnode · DexScreener</p>
      </div>
    </footer>
  );
}
