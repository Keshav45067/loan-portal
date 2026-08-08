'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import AuthGuard from '../components/AuthGuard';
import styles from './capture.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

function CaptureLandingContent() {
  const router = useRouter();
  const [token, setToken] = useState('');
  const [selectedScheme, setSelectedScheme] = useState('demo_business_kyc');
  const [language, setLanguage] = useState('en');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const savedToken = localStorage.getItem('token');
    if (savedToken) {
      setToken(savedToken);
    }
  }, []);

  const handleStart = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);

    try {
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

      router.push(`/capture/${selectedScheme}?lang=${language}`);
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  };

  return (
    <div className={styles.container} style={{ background: '#f8fafc', color: '#0f172a', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* ─── Top Nav ─── */}
      <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 32px', background: '#ffffff', borderBottom: '1px solid #e2e8f0' }}>
        <div style={{ fontWeight: 700, fontSize: '1.1rem', color: '#0f172a', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span>📸</span> Document Capture Engine
        </div>
        <button 
          onClick={() => router.push('/dashboard')}
          style={{ background: 'transparent', border: '1px solid #cbd5e1', padding: '8px 16px', borderRadius: '8px', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 500 }}
        >
          Exit to Dashboard
        </button>
      </header>

      {/* ─── Main Content ─── */}
      <main style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' }}>
        <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '20px', padding: '32px', maxWidth: '440px', width: '100%', boxShadow: '0 10px 25px -5px rgba(0,0,0,0.05)' }}>
          <h2 style={{ fontSize: '1.3rem', fontWeight: 700, marginBottom: '8px' }}>Start Capture Flow</h2>
          <p style={{ color: '#64748b', fontSize: '0.9rem', marginBottom: '24px' }}>Select a document verification scheme and language to launch the interactive capture agent.</p>

          <div style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, color: '#334155', marginBottom: '6px' }}>Document Scheme</label>
            <select 
              value={selectedScheme}
              onChange={(e) => setSelectedScheme(e.target.value)}
              style={{ width: '100%', padding: '12px', borderRadius: '10px', border: '1px solid #cbd5e1', fontSize: '0.95rem', background: '#f8fafc' }}
            >
              <option value="demo_business_kyc">Demo Business KYC (Selfie, Aadhaar, PAN, Udyam)</option>
              <option value="aadhaar">Aadhaar Card (Identity & Address)</option>
              <option value="passport">Passport (Identity, Address & Visas)</option>
              <option value="bank_statement">Bank Statement (Account Details & Cheques)</option>
              <option value="pan">PAN Card (Identity Verification)</option>
              <option value="udyam">Udyam Registration Certificate (MSME Verification)</option>
              <option value="gst">GST Registration Certificate (GST REG-06)</option>
            </select>
          </div>

          <div style={{ marginBottom: '24px' }}>
            <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, color: '#334155', marginBottom: '6px' }}>Interface Language</label>
            <select 
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              style={{ width: '100%', padding: '12px', borderRadius: '10px', border: '1px solid #cbd5e1', fontSize: '0.95rem', background: '#f8fafc' }}
            >
              <option value="en">English</option>
              <option value="hi">Hindi (हिंदी)</option>
              <option value="te">Telugu (తెలుగు)</option>
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
            onClick={handleStart}
            disabled={loading}
            style={{ width: '100%', padding: '14px', fontSize: '1rem', fontWeight: 600, borderRadius: '10px', cursor: 'pointer', background: '#2563eb', color: '#fff', border: 'none' }}
          >
            {loading ? 'Starting...' : 'Start Document Capture'}
          </button>
        </div>
      </main>
    </div>
  );
}

export default function CaptureLandingPage() {
  return (
    <AuthGuard>
      <CaptureLandingContent />
    </AuthGuard>
  );
}
