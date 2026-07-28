'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import styles from './capture.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export default function CaptureLandingPage() {
  const router = useRouter();
  const [token, setToken] = useState('');
  const [selectedScheme, setSelectedScheme] = useState('demo_business_kyc');
  const [language, setLanguage] = useState('en');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const savedToken = localStorage.getItem('token');
    if (!savedToken) {
      router.push('/');
    } else {
      setToken(savedToken);
    }
  }, [router]);

  const handleStart = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);

    try {
      // Create session on gateway
      const res = await fetch(`${API_BASE_URL}/api/capture/start`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          scheme_id: selectedScheme,
          language: language
        })
      });

      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || 'Failed to start session');
      }

      // If successful, navigate to the capture flow
      router.push(`/capture/${selectedScheme}?lang=${language}`);
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  };

  return (
    <div className={styles.container} style={{ background: '#f8fafc', color: '#0f172a', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* ─── Top Nav ─── */}
      <nav style={{ padding: '20px 40px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #e2e8f0', background: 'rgba(255, 255, 255, 0.8)', backdropFilter: 'blur(20px)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '1.25rem', fontWeight: 700, color: '#0f172a' }}>
            <svg width="32" height="32" viewBox="0 0 48 48" fill="none">
              <circle cx="24" cy="24" r="24" fill="url(#logo-grad)" />
              <path d="M16 24C16 19.58 19.58 16 24 16V32C19.58 32 16 28.42 16 24Z" fill="white" opacity="0.9" />
              <defs>
                <linearGradient id="logo-grad" x1="0" y1="0" x2="48" y2="48">
                  <stop stopColor="#4a78ff" /><stop offset="1" stopColor="#06b6d4" />
                </linearGradient>
              </defs>
            </svg>
            <span>Augmen.io</span>
          </div>
        </div>
        <div>
          <button
            onClick={() => router.push('/dashboard')}
            className="btn btn-secondary"
            style={{ fontSize: '0.875rem', fontWeight: 500, padding: '8px 16px', borderRadius: '8px', cursor: 'pointer', background: '#ffffff', color: '#475569', border: '1px solid #cbd5e1' }}
          >
            Dashboard
          </button>
        </div>
      </nav>

      {/* ─── Main Content ─── */}
      <main style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px' }}>
        <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '24px', padding: '50px 40px', maxWidth: '500px', width: '100%', boxShadow: '0 10px 30px rgba(15, 23, 42, 0.04)' }}>
          
          <h1 style={{ fontSize: '1.75rem', fontWeight: 700, marginBottom: '12px', color: '#0f172a', textAlign: 'center' }}>
            Smart Document Capture
          </h1>

          <p style={{ color: '#475569', fontSize: '0.95rem', lineHeight: '1.6', marginBottom: '32px', textAlign: 'center' }}>
            An AI-guided document collection experience. Please select the document type and preferred language to begin.
          </p>

          <div className={styles.formGroup} style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', fontSize: '0.9rem', fontWeight: 600, color: '#475569', marginBottom: '8px' }}>Select Document Type</label>
            <select 
              className={styles.select}
              value={selectedScheme}
              onChange={(e) => setSelectedScheme(e.target.value)}
              disabled={loading}
              style={{ width: '100%', padding: '14px 18px', background: '#ffffff', border: '1px solid #cbd5e1', borderRadius: '12px', color: '#0f172a', fontSize: '1rem', outline: 'none' }}
            >
              <option value="demo_business_kyc">Demo Business KYC (Aadhaar, PAN, Udyam, GST)</option>
              <option value="aadhaar">Aadhaar Card (Identity & Address)</option>
              <option value="passport">Passport (Identity, Address & Visas)</option>
              <option value="bank_statement">Bank Statement (Account Details & Cheques)</option>
              <option value="pan">PAN Card (Identity Verification)</option>
              <option value="udyam">Udyam Registration Certificate (MSME Verification)</option>
              <option value="gst">GST Registration Certificate (GST REG-06)</option>
            </select>
          </div>

          <div className={styles.formGroup} style={{ marginBottom: '32px' }}>
            <label style={{ display: 'block', fontSize: '0.9rem', fontWeight: 600, color: '#475569', marginBottom: '8px' }}>Select Preferred Language</label>
            <select 
              className={styles.select}
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              disabled={loading}
              style={{ width: '100%', padding: '14px 18px', background: '#ffffff', border: '1px solid #cbd5e1', borderRadius: '12px', color: '#0f172a', fontSize: '1rem', outline: 'none' }}
            >
              <option value="en">English</option>
              <option value="hi">Hindi (हिंदी)</option>
              <option value="fr">French (Français)</option>
              <option value="ar">Arabic (العربية)</option>
            </select>
          </div>

          {error && (
            <div style={{ color: '#ef4444', marginBottom: '20px', fontSize: '0.9rem', padding: '12px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '12px', textAlign: 'center' }}>
              {error}
            </div>
          )}

          <button 
            className="btn btn-primary"
            onClick={handleStart}
            disabled={loading || !token}
            style={{ width: '100%', padding: '16px', fontSize: '1.05rem', fontWeight: 600, borderRadius: '12px', cursor: 'pointer', background: 'linear-gradient(135deg, #2563eb, #4f46e5)', color: '#fff', border: 'none', transition: 'all 0.2s', boxShadow: '0 4px 12px rgba(37, 99, 235, 0.15)' }}
          >
            {loading ? 'Starting...' : 'Start Document Capture'}
          </button>
        </div>
      </main>
    </div>
  );
}
