/**
 * Test Voice Assistant Layout
 * 
 * Provides isolated full-screen layout with Satoshi font (same as Hindi repo).
 * Removes parent layout's background orbs.
 */

export const metadata = {
  title: 'Voice Assistant Test — Mudra AI',
  description: 'Isolated voice assistant testing environment with real-time debug',
};

export default function TestVALayout({ children }) {
  return (
    <div style={{ position: 'relative', width: '100%', height: '100vh', overflow: 'hidden' }}>
      <link
        href="https://api.fontshare.com/v2/css?f[]=satoshi@300,400,500,600,700,800,900&display=swap"
        rel="stylesheet"
      />
      <style>{`
        /* Override parent layout's floating orbs for this route */
        .floating-orb { display: none !important; }
      `}</style>
      {children}
    </div>
  );
}
