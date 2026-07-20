'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import styles from './dashboard.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export default function DashboardPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
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
      } catch (err) {
        console.error('Failed to fetch dashboard data:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchDashboardData();
  }, [router]);

  const handleStartVoice = async () => {
    try {
      const token = localStorage.getItem('token');
      // Force 'mudra-grocery' scheme ID and set onboarding_finished to false for a clean interview reset
      await fetch(`${API_BASE_URL}/api/applications/save-metadata`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          session_id: sessionId,
          fields: {
            scheme_id: 'mudra-grocery',
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
          <div className={styles.spinner} style={{ width: '50px', height: '50px', border: '3px solid rgba(255,255,255,0.1)', borderTopColor: '#6366f1', borderRadius: '50%', animation: 'spin 1s linear infinite', margin: '0 auto 20px' }}></div>
          <style jsx global>{`
            @keyframes spin { to { transform: rotate(360deg); } }
          `}</style>
          <h2 style={{ fontSize: '1rem', fontWeight: 500, color: '#94a3b8' }}>Workspace लोड हो रहा है...</h2>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container} style={{ background: 'radial-gradient(circle at center, #0a0b12 0%, #030406 100%)', color: '#fff', minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', fontFamily: 'system-ui, -apple-system, sans-serif', padding: '24px' }}>
      
      <style jsx global>{`
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(20px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .animate-fade-up {
          animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }
        .start-btn {
          background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
          color: white;
          border: none;
          padding: 16px 40px;
          border-radius: 16px;
          font-size: 1.125rem;
          font-weight: 700;
          cursor: pointer;
          transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
          box-shadow: 0 4px 20px rgba(99, 102, 241, 0.3);
        }
        .start-btn:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 30px rgba(99, 102, 241, 0.5);
          background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%);
        }
        .start-btn:active {
          transform: translateY(0);
        }
      `}</style>

      <div className="animate-fade-up" style={{ 
        maxWidth: '480px', 
        width: '100%', 
        textAlign: 'center', 
        background: 'rgba(255, 255, 255, 0.01)', 
        border: '1px solid rgba(255, 255, 255, 0.03)', 
        borderRadius: '32px', 
        padding: '48px 32px', 
        boxShadow: '0 24px 64px rgba(0,0,0,0.5)',
        backdropFilter: 'blur(30px)'
      }}>
        
        {/* Loan Icon */}
        <div style={{ 
          width: '72px', 
          height: '72px', 
          borderRadius: '24px', 
          background: 'rgba(99, 102, 241, 0.08)', 
          border: '1px solid rgba(99, 102, 241, 0.2)', 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'center', 
          margin: '0 auto 32px',
          fontSize: '2.25rem',
          boxShadow: '0 8px 32px rgba(99, 102, 241, 0.05)'
        }}>
          🛒
        </div>

        {/* Hindi Title */}
        <h1 style={{ 
          fontSize: '2.25rem', 
          fontWeight: 800, 
          letterSpacing: '-0.02em', 
          marginBottom: '16px',
          color: '#fff'
        }}>
          माइक्रो लोन
        </h1>

        {/* Hindi Subtitle */}
        <p style={{ 
          color: '#94a3b8', 
          fontSize: '1rem', 
          lineHeight: '1.6', 
          marginBottom: '40px',
          padding: '0 16px'
        }}>
          मुद्रा किराना (Kirana) लोन के लिए अपना डिजिटल आवेदन शुरू करें।
        </p>

        {/* Start Button */}
        <button onClick={handleStartVoice} className="start-btn">
          आवेदन शुरू करें ➔
        </button>

      </div>
    </div>
  );
}
