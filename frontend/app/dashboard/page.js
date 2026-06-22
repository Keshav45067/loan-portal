'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import styles from './dashboard.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export default function DashboardPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [hasData, setHasData] = useState(false);
  const [applicantName, setApplicantName] = useState('');
  const [phone, setPhone] = useState('');
  const [sessionId, setSessionId] = useState('');

  useEffect(() => {
    const fetchDashboardData = async () => {
      try {
        const token = localStorage.getItem('token');
        const sessId = localStorage.getItem('session_id');
        if (!token || !sessId) {
          router.push('/');
          return;
        }
        setSessionId(sessId);
        setPhone(localStorage.getItem('phone') || '');

        const res = await fetch(`${API_BASE_URL}/api/applications/${sessId}`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();

        if (data.status === 'ERROR' || data.status === 'NOT_FOUND') {
          setHasData(false);
          setLoading(false);
          return;
        }

        const exData = data.extracted_data || {};
        const name = exData.applicant_name || exData.name || exData.full_name || '';
        if (name) {
          setApplicantName(name);
          localStorage.setItem('applicant_name', name);
        }

        setHasData(exData.onboarding_finished === true);
      } catch (err) {
        console.error('Failed to fetch dashboard data:', err);
        setHasData(false);
      } finally {
        setLoading(false);
      }
    };

    fetchDashboardData();
  }, [router]);

  const handleLogout = () => {
    localStorage.clear();
    router.push('/');
  };

  const handleResetAndStart = async () => {
    try {
      const token = localStorage.getItem('token');
      // Set onboarding_finished to false which triggers clean DB reset and document deletion
      await fetch(`${API_BASE_URL}/api/applications/save-metadata`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          session_id: sessionId,
          fields: {
            onboarding_finished: false
          }
        })
      });
    } catch (e) {
      console.error("Failed to reset fields:", e);
    }
    router.push('/interview');
  };

  if (loading) {
    return (
      <div className={styles.container} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'radial-gradient(circle at center, #0f111a 0%, #050508 100%)', color: '#fff' }}>
        <div style={{ textAlign: 'center' }}>
          <div className={styles.spinner} style={{ width: '50px', height: '50px', border: '3px solid rgba(255,255,255,0.1)', borderTopColor: '#4a78ff', borderRadius: '50%', animation: 'spin 1s linear infinite', margin: '0 auto 20px' }}></div>
          <style jsx global>{`
            @keyframes spin { to { transform: rotate(360deg); } }
          `}</style>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 500, color: '#a0aec0' }}>Loading Dashboard...</h2>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container} style={{ background: 'radial-gradient(circle at 10% 20%, #16192b 0%, #090a0f 90%)', color: '#fff', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* ─── Top Nav ─── */}
      <nav className={styles.topNav} style={{ padding: '20px 40px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255, 255, 255, 0.08)', background: 'rgba(9, 10, 15, 0.7)', backdropFilter: 'blur(20px)' }}>
        <div className={styles.navLeft} style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div className={styles.navLogo} style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '1.25rem', fontWeight: 700, color: '#fff' }}>
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

        <div className={styles.navRight} style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
          {applicantName && (
            <div className={styles.userChip} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 16px', background: 'rgba(255, 255, 255, 0.04)', borderRadius: '20px', border: '1px solid rgba(255, 255, 255, 0.08)' }}>
              <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#22c968' }}></div>
              <span style={{ fontSize: '0.875rem', fontWeight: 500 }}>{applicantName}</span>
            </div>
          )}
          <button
            onClick={handleLogout}
            className="btn btn-ghost"
            style={{ color: '#ef4444', fontSize: '0.875rem', fontWeight: 500, padding: '8px 16px', borderRadius: '8px', cursor: 'pointer', background: 'transparent', border: 'none', display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            <span>Logout</span> 🚪
          </button>
        </div>
      </nav>

      {/* ─── Main Content ─── */}
      <main style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px' }}>
        <div style={{ background: 'rgba(255, 255, 255, 0.02)', border: '1px solid rgba(255, 255, 255, 0.06)', borderRadius: '24px', padding: '50px 40px', maxWidth: '600px', width: '100%', textAlign: 'center', backdropFilter: 'blur(40px)', boxShadow: '0 20px 50px rgba(0, 0, 0, 0.3)' }}>

          <div style={{ fontSize: '3rem', marginBottom: '20px' }}>
            {hasData ? '✅' : '🚀'}
          </div>

          <h1 style={{ fontSize: '2rem', fontWeight: 700, marginBottom: '12px', background: 'linear-gradient(135deg, #fff 0%, #a5b4fc 100%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
            {hasData ? 'Onboarding Completed' : 'SBI Savings Account Opening'}
          </h1>

          <p style={{ color: '#94a3b8', fontSize: '1rem', lineHeight: '1.6', marginBottom: '40px', maxWidth: '460px', margin: '0 auto 40px' }}>
            {hasData
              ? 'Your bank account form details and uploaded documents have been securely processed. You can review your verified details below or redo the onboarding process.'
              : 'Click the button below to start the conversational SBI savings account opening process.'}
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {hasData ? (
              <button
                id="redo-process-btn"
                onClick={handleResetAndStart}
                className="btn btn-primary"
                style={{ width: '100%', padding: '16px', fontSize: '1.05rem', fontWeight: 600, borderRadius: '12px', cursor: 'pointer', background: 'linear-gradient(135deg, #ef4444 0%, #c2410c 100%)', color: '#fff', border: 'none', transition: 'all 0.2s', boxShadow: '0 4px 15px rgba(239, 68, 68, 0.2)' }}
              >
                🔄 Re-do Onboarding Process
              </button>
            ) : (
              <button
                id="start-process-btn"
                onClick={() => router.push('/interview')}
                className="btn btn-primary"
                style={{ width: '100%', padding: '16px', fontSize: '1.05rem', fontWeight: 600, borderRadius: '12px', cursor: 'pointer', background: 'linear-gradient(135deg, #4a78ff 0%, #7c3aed 100%)', color: '#fff', border: 'none', transition: 'all 0.2s', boxShadow: '0 4px 20px rgba(74, 120, 255, 0.3)' }}
              >
                ⚡ Start Onboarding Process
              </button>
            )}

            <button
              id="view-details-btn"
              onClick={() => router.push('/dashboard/details')}
              disabled={!hasData}
              style={{
                width: '100%',
                padding: '16px',
                fontSize: '1.05rem',
                fontWeight: 600,
                borderRadius: '12px',
                cursor: hasData ? 'pointer' : 'not-allowed',
                background: hasData ? 'rgba(255, 255, 255, 0.05)' : 'rgba(255, 255, 255, 0.02)',
                color: hasData ? '#fff' : '#64748b',
                border: `1px solid ${hasData ? 'rgba(255, 255, 255, 0.12)' : 'rgba(255, 255, 255, 0.04)'}`,
                transition: 'all 0.2s'
              }}
            >
              📋 View Verified Details
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
