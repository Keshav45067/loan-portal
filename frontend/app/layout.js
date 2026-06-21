import './globals.css';

export const metadata = {
  title: 'Augmen — Smart Loan Solutions',
  description: 'AI-powered voice-driven loan processing platform for rural India. Complete your loan application through a natural Hindi voice conversation.',
  keywords: 'loan, AI, voice, mudra, rural banking, India, fintech',
};

export default function RootLayout({ children }) {
  return (
    <html lang="hi">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <meta name="theme-color" content="#06080f" />
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
      </head>
      <body>
        {/* Decorative floating orbs */}
        <div className="floating-orb floating-orb-1" aria-hidden="true" />
        <div className="floating-orb floating-orb-2" aria-hidden="true" />
        <div className="floating-orb floating-orb-3" aria-hidden="true" />

        {children}
      </body>
    </html>
  );
}
