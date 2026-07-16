'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import styles from './dashboard.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export default function DashboardPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [sessionId, setSessionId] = useState('');
  const [applicantName, setApplicantName] = useState('');

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

        const res = await fetch(`${API_BASE_URL}/api/applications/${sessId}`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();

        if (data && data.extracted_data) {
          const exData = data.extracted_data;
          const name = exData.applicant_name || exData.name || exData.full_name || '';
          if (name) {
            setApplicantName(name);
            localStorage.setItem('applicant_name', name);
          }
        }
      } catch (err) {
        console.error('Failed to fetch dashboard data:', err);
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

  const handleStartVoice = async () => {
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
      <div className={styles.container} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'radial-gradient(circle at center, #0f111a 0%, #050508 100%)', color: '#fff', height: '100vh' }}>
        <div style={{ textAlign: 'center' }}>
          <div className={styles.spinner} style={{ width: '50px', height: '50px', border: '3px solid rgba(255,255,255,0.1)', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 1s linear infinite', margin: '0 auto 20px' }}></div>
          <style jsx global>{`
            @keyframes spin { to { transform: rotate(360deg); } }
          `}</style>
          <h2 style={{ fontSize: '1rem', fontWeight: 500, color: '#94a3b8' }}>Loading Workspace...</h2>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container} style={{ background: 'radial-gradient(circle at center, #0f111d 0%, #040508 100%)', color: '#fff', minHeight: '100vh', display: 'flex', flexDirection: 'column', fontFamily: 'system-ui, -apple-system, sans-serif' }}>
      
      {/* ─── Global Animation Styles ─── */}
      <style jsx global>{`
        @keyframes fadeInUp {
          from {
            opacity: 0;
            transform: translateY(24px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        .animate-fade-in {
          animation: fadeIn 1.2s ease forwards;
        }
        .animate-slide-up {
          animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }
        .glow-card:hover {
          border-color: rgba(59, 130, 246, 0.35) !important;
          box-shadow: 0 20px 40px rgba(59, 130, 246, 0.05), inset 0 0 12px rgba(59, 130, 246, 0.05) !important;
          transform: translateY(-4px) scale(1.01) !important;
        }
      `}</style>

      {/* ─── Top Navbar ─── */}
      <nav className="animate-fade-in" style={{ padding: '24px 48px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255, 255, 255, 0.05)', background: 'rgba(4, 5, 8, 0.4)', backdropFilter: 'blur(24px)', zIndex: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '1.15rem', fontWeight: 700, color: '#fff' }}>
            <svg width="32" height="32" viewBox="0 0 48 48" fill="none">
              <circle cx="24" cy="24" r="24" fill="url(#logo-grad)" />
              <path d="M16 24C16 19.58 19.58 16 24 16V32C19.58 32 16 28.42 16 24Z" fill="white" opacity="0.95" />
              <defs>
                <linearGradient id="logo-grad" x1="0" y1="0" x2="48" y2="48">
                  <stop stopColor="#3b82f6" /><stop offset="1" stopColor="#06b6d4" />
                </linearGradient>
              </defs>
            </svg>
            <span style={{ letterSpacing: '-0.02em' }}>Augmen.io</span>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          {applicantName && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 14px', background: 'rgba(255, 255, 255, 0.02)', borderRadius: '20px', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
              <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10b981' }}></div>
              <span style={{ fontSize: '0.8rem', fontWeight: 500, color: '#cbd5e1' }}>{applicantName}</span>
            </div>
          )}
          <button
            onClick={handleLogout}
            style={{ color: '#ef4444', fontSize: '0.85rem', fontWeight: 600, padding: '8px 16px', borderRadius: '8px', cursor: 'pointer', background: 'rgba(239, 68, 68, 0.05)', border: '1px solid rgba(239, 68, 68, 0.15)', display: 'flex', alignItems: 'center', gap: '6px', transition: 'all 0.2s' }}
            onMouseOver={(e) => e.currentTarget.style.background = 'rgba(239, 68, 68, 0.1)'}
            onMouseOut={(e) => e.currentTarget.style.background = 'rgba(239, 68, 68, 0.05)'}
          >
            Logout 🚪
          </button>
        </div>
      </nav>

      {/* ─── Main Hub ─── */}
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '40px 24px', zIndex: 1 }}>
        <div className="animate-slide-up" style={{ maxWidth: '840px', width: '100%', textAlign: 'center' }}>
          
          {/* Tag */}
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '6px 14px', background: 'rgba(59, 130, 246, 0.06)', border: '1px solid rgba(59, 130, 246, 0.18)', borderRadius: '99px', marginBottom: '24px', backdropFilter: 'blur(10px)' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#3b82f6', boxShadow: '0 0 8px #3b82f6' }}></span>
            <span style={{ fontSize: '0.72rem', fontWeight: 700, letterSpacing: '0.12em', color: '#60a5fa', textTransform: 'uppercase' }}>
              Metadata-Driven Intelligent Pipelines
            </span>
          </div>

          {/* Heading */}
          <h1 style={{ fontSize: '2.5rem', fontWeight: 800, letterSpacing: '-0.03em', marginBottom: '16px', background: 'linear-gradient(135deg, #ffffff 0%, #94a3b8 100%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
            Unified Schema-Driven Projects
          </h1>

          {/* Description */}
          <p style={{ color: '#94a3b8', fontSize: '1rem', lineHeight: '1.6', maxWidth: '580px', margin: '0 auto 56px' }}>
            Select a project engine below. Both pipelines are fully metadata-configured, generating fields and validation constraints dynamically from database registry configurations.
          </p>

          {/* Cards Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '24px', width: '100%', textAlign: 'left' }}>
            
            {/* Card 1: Voice Assistant */}
            <div 
              onClick={handleStartVoice}
              className="glow-card"
              style={{
                background: 'rgba(255, 255, 255, 0.015)',
                border: '1px solid rgba(255, 255, 255, 0.06)',
                borderRadius: '24px',
                padding: '36px',
                cursor: 'pointer',
                transition: 'all 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
                height: '240px',
                backdropFilter: 'blur(20px)'
              }}
            >
              <div>
                {/* Icon Container */}
                <div style={{ width: '48px', height: '48px', borderRadius: '16px', background: 'rgba(59, 130, 246, 0.08)', border: '1px solid rgba(59, 130, 246, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '24px', fontSize: '1.4rem' }}>
                  🎙️
                </div>
                <h3 style={{ fontSize: '1.2rem', fontWeight: 700, color: '#fff', marginBottom: '10px', letterSpacing: '-0.01em' }}>
                  Dynamic Voice Assistant
                </h3>
                <p style={{ fontSize: '0.85rem', color: '#94a3b8', lineHeight: '1.5' }}>
                  Conversational speech agent collecting user data through real-time audio analysis, dynamic questions, and context sync.
                </p>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.85rem', fontWeight: 600, color: '#3b82f6', marginTop: '12px' }}>
                Launch Assistant ➔
              </div>
            </div>

            {/* Card 2: Document Extractor */}
            <div 
              onClick={() => router.push('/capture')}
              className="glow-card"
              style={{
                background: 'rgba(255, 255, 255, 0.015)',
                border: '1px solid rgba(255, 255, 255, 0.06)',
                borderRadius: '24px',
                padding: '36px',
                cursor: 'pointer',
                transition: 'all 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
                height: '240px',
                backdropFilter: 'blur(20px)'
              }}
            >
              <div>
                {/* Icon Container */}
                <div style={{ width: '48px', height: '48px', borderRadius: '16px', background: 'rgba(6, 182, 212, 0.08)', border: '1px solid rgba(6, 182, 212, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '24px', fontSize: '1.4rem' }}>
                  📄
                </div>
                <h3 style={{ fontSize: '1.2rem', fontWeight: 700, color: '#fff', marginBottom: '10px', letterSpacing: '-0.01em' }}>
                  Dynamic Document Extractor
                </h3>
                <p style={{ fontSize: '0.85rem', color: '#94a3b8', lineHeight: '1.5' }}>
                  Automated computer vision scanner providing real-time edge detection, auto-torch control, and VLM field parsing.
                </p>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.85rem', fontWeight: 600, color: '#06b6d4', marginTop: '12px' }}>
                Open Extractor ➔
              </div>
            </div>

          </div>

        </div>
      </main>
    </div>
  );
}
