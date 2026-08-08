'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import AuthGuard, { useAuth } from '../components/AuthGuard';
import styles from './dashboard.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

const SCHEME_ICONS = {
  'mudra-grocery': '🛒',
  'mudra-dairy': '🥛',
  'mudra-salon': '💇',
  'mudra-electric': '⚡',
  'mudra-furniture': '🪑',
  'mudra-garage': '🔧',
  'mudra-goatry': '🐐',
  'mudra-poultry': '🐔',
  'mudra-clothing': '👔',
  'mudra-tailor': '🪡',
  'sbi-account-opening': '🏦',
  'documents-qa': '📄',
  'default': '💼'
};

const STAGE_LABELS = {
  'REGISTRATION': 'Registration',
  'INTERVIEW': 'Voice Interview',
  'VOICE_QA': 'Voice Q&A',
  'DOCUMENTATION': 'Document Verification',
  'COMPLETED': 'Completed & Submitted',
  'APPROVED_BY_LVL_1': 'Approved by Level 1 Admin'
};

function DashboardContent() {
  const router = useRouter();
  const { token, sessionId, phone } = useAuth();
  
  const [loading, setLoading] = useState(true);
  const [myApplications, setMyApplications] = useState([]);
  const [availableSchemes, setAvailableSchemes] = useState([]);
  const [activeTab, setActiveTab] = useState('overview'); // 'overview' | 'schemes' | 'applications'
  const [startingSchemeId, setStartingSchemeId] = useState(null);

  useEffect(() => {
    async function loadDashboardData() {
      setLoading(true);
      try {
        // 1. Fetch user applications
        const appRes = await fetch(`${API_BASE_URL}/api/applications/my-applications`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        const appData = await appRes.json();
        if (appData.success && appData.applications) {
          setMyApplications(appData.applications);
        }

        // 2. Fetch available schemes
        const schemeRes = await fetch(`${API_BASE_URL}/api/schemes`);
        const schemeData = await schemeRes.json();
        if (schemeData.success && schemeData.schemes) {
          setAvailableSchemes(schemeData.schemes);
        }
      } catch (err) {
        console.error('Failed to load dashboard data:', err);
        toast.error('Failed to load live dashboard data.');
      } finally {
        setLoading(false);
      }
    }

    if (token) {
      loadDashboardData();
    }
  }, [token]);

  const handleStartScheme = async (schemeIdToStart) => {
    setStartingSchemeId(schemeIdToStart);
    try {
      // Save metadata and reset onboarding finished for clean interview start
      await fetch(`${API_BASE_URL}/api/applications/save-metadata`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          session_id: sessionId,
          fields: {
            scheme_id: schemeIdToStart,
            onboarding_finished: false
          }
        })
      });
      localStorage.setItem('scheme_id', schemeIdToStart);
      toast.success(`Starting ${schemeIdToStart.replace('mudra-', '').replace('-', ' ')} application...`);
      router.push('/interview');
    } catch (e) {
      console.error('Failed to start scheme:', e);
      toast.error('Failed to start application. Please try again.');
      setStartingSchemeId(null);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('session_id');
    localStorage.removeItem('phone');
    localStorage.removeItem('application_id');
    toast.info('You have been logged out.');
    router.push('/');
  };

  // Extract applied scheme IDs for filtering unapplied schemes
  const appliedSchemeIds = new Set(myApplications.map(a => a.scheme_id));
  const unappliedSchemes = availableSchemes.filter(s => !appliedSchemeIds.has(s.scheme_id));

  // Determine user location string if available
  const firstApp = myApplications[0] || {};
  const userLocation = [firstApp.panchayat, firstApp.district, firstApp.state].filter(Boolean).join(', ') || 'Registered Applicant';

  if (loading) {
    return (
      <div className={styles.container} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', background: '#06080f', color: '#fff' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ width: '50px', height: '50px', border: '3px solid rgba(255,255,255,0.1)', borderTopColor: '#6366f1', borderRadius: '50%', animation: 'dashSpin 1s linear infinite', margin: '0 auto 20px' }}></div>
          <style jsx global>{` @keyframes dashSpin { to { transform: rotate(360deg); } } `}</style>
          <h2 style={{ fontSize: '1rem', fontWeight: 500, color: '#94a3b8' }}>Loading your dashboard...</h2>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container} style={{ background: 'radial-gradient(circle at top center, #0f172a 0%, #06080f 100%)', color: '#f8fafc', minHeight: '100vh' }}>
      
      {/* Top Navigation Header */}
      <nav className={styles.topNav}>
        <div className={styles.navLeft}>
          <div className={styles.navLogo}>
            <svg width="24" height="24" viewBox="0 0 36 40" fill="none">
              <path d="M18 0L36 34H27L18 16L9 34H0L18 0Z" fill="url(#brand-grad)" />
              <defs>
                <linearGradient id="brand-grad" x1="0" y1="0" x2="36" y2="40">
                  <stop stopColor="#6366f1" />
                  <stop offset="1" stopColor="#a855f7" />
                </linearGradient>
              </defs>
            </svg>
            <span style={{ fontWeight: 800, fontSize: '1.25rem', letterSpacing: '-0.02em', background: 'linear-gradient(135deg, #fff 0%, #cbd5e1 100%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
              Augmen
            </span>
          </div>

          <div className={styles.navTabs}>
            <button className={`${styles.navTab} ${activeTab === 'overview' ? styles.navTabActive : ''}`} onClick={() => setActiveTab('overview')}>
              Overview
            </button>
            <button className={`${styles.navTab} ${activeTab === 'applications' ? styles.navTabActive : ''}`} onClick={() => setActiveTab('applications')}>
              My Applications ({myApplications.length})
            </button>
            <button className={`${styles.navTab} ${activeTab === 'schemes' ? styles.navTabActive : ''}`} onClick={() => setActiveTab('schemes')}>
              Browse Schemes ({availableSchemes.length})
            </button>
          </div>
        </div>

        <div className={styles.navRight}>
          <div className={styles.userChip}>
            <div className={styles.userAvatar}>
              {phone ? phone.slice(-2) : 'US'}
            </div>
            <span style={{ color: '#e2e8f0' }}>{phone || 'User'}</span>
          </div>
          <button className="btn btn-ghost" onClick={handleLogout} style={{ fontSize: '0.85rem', color: '#94a3b8' }}>
            Logout
          </button>
        </div>
      </nav>

      {/* Main Container */}
      <main className={styles.main}>
        
        {/* User Hero Banner */}
        <section className={styles.heroCard}>
          <div className={styles.heroLeft}>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '6px 14px', borderRadius: '100px', background: 'rgba(99, 102, 241, 0.12)', border: '1px solid rgba(99, 102, 241, 0.25)', color: '#818cf8', fontSize: '0.8125rem', fontWeight: 600, marginBottom: '16px' }}>
              📍 {userLocation}
            </div>
            <h1 style={{ fontSize: '2.25rem', fontWeight: 800, letterSpacing: '-0.03em', color: '#fff', marginBottom: '8px' }}>
              Welcome Back!
            </h1>
            <p style={{ color: '#94a3b8', fontSize: '1rem', maxWidth: '520px', lineHeight: '1.6' }}>
              Manage your active loan applications and explore government financial schemes tailored for your small business.
            </p>
          </div>

          <div className={styles.heroRight}>
            <div className={styles.heroStat}>
              <span className={styles.heroValue}>{myApplications.length}</span>
              <span style={{ fontSize: '0.8125rem', color: '#94a3b8', fontWeight: 500 }}>Applied Schemes</span>
            </div>
            <div className={styles.heroStat}>
              <span className={styles.heroValue}>{availableSchemes.length}</span>
              <span style={{ fontSize: '0.8125rem', color: '#94a3b8', fontWeight: 500 }}>Available Schemes</span>
            </div>
          </div>
        </section>

        {/* Section 1: My Applied Loan Schemes (Dynamic Schema & Status) */}
        <section>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
            <div>
              <h2 style={{ fontSize: '1.35rem', fontWeight: 700, color: '#f8fafc', letterSpacing: '-0.01em' }}>
                Your Applied Loan Schemes
              </h2>
              <p style={{ color: '#64748b', fontSize: '0.875rem' }}>
                Track live status, extracted details, and progress across all your applications
              </p>
            </div>
          </div>

          {myApplications.length === 0 ? (
            <div className="card" style={{ textAlign: 'center', padding: '48px 24px', background: 'rgba(15, 23, 42, 0.4)', border: '1px border-subtle', borderRadius: '24px' }}>
              <div style={{ fontSize: '3rem', marginBottom: '16px' }}>📋</div>
              <h3 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#f8fafc', marginBottom: '8px' }}>No Active Applications</h3>
              <p style={{ color: '#94a3b8', fontSize: '0.95rem', marginBottom: '24px', maxWidth: '400px', margin: '0 auto 24px' }}>
                You have not applied for any loan schemes yet. Browse available schemes below to begin your digital application.
              </p>
              <button className="btn btn-primary" onClick={() => setActiveTab('schemes')}>
                Browse Available Schemes
              </button>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              {myApplications.map((app, idx) => {
                const schemeId = app.scheme_id || 'mudra-grocery';
                const icon = SCHEME_ICONS[schemeId] || SCHEME_ICONS['default'];
                const formattedName = schemeId.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
                const stageLabel = STAGE_LABELS[app.stage] || app.stage || 'In Progress';
                const isFinished = app.onboarding_finished || app.completion_status === 'COMPLETED';

                // Extract dynamic fields from extracted_data
                const extData = app.extracted_data || {};
                const dynamicFields = Object.entries(extData).filter(([k, v]) => 
                  v !== null && v !== undefined && v !== '' && 
                  !['session_id', 'onboarding_finished', 'trigger_evaluations'].includes(k) &&
                  typeof v !== 'object'
                );

                return (
                  <div key={idx} className="card" style={{ 
                    background: 'rgba(15, 23, 42, 0.6)', 
                    border: '1px solid rgba(255, 255, 255, 0.08)', 
                    borderRadius: '24px', 
                    padding: '28px',
                    boxShadow: '0 20px 40px rgba(0, 0, 0, 0.3)',
                    backdropFilter: 'blur(20px)'
                  }}>
                    {/* Header Row */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px', marginBottom: '24px', paddingBottom: '20px', borderBottom: '1px solid rgba(255, 255, 255, 0.06)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <div style={{ width: '56px', height: '56px', borderRadius: '18px', background: 'rgba(99, 102, 241, 0.1)', border: '1px solid rgba(99, 102, 241, 0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.75rem' }}>
                          {icon}
                        </div>
                        <div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <h3 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#fff' }}>{formattedName}</h3>
                            <span className="badge badge-accent" style={{ fontSize: '0.75rem' }}>
                              {app.application_id || 'Application'}
                            </span>
                          </div>
                          <p style={{ color: '#94a3b8', fontSize: '0.85rem', marginTop: '4px' }}>
                            Session ID: <code style={{ color: '#818cf8' }}>{app.session_id}</code>
                          </p>
                        </div>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <span style={{ 
                          padding: '6px 14px', 
                          borderRadius: '100px', 
                          fontSize: '0.8125rem', 
                          fontWeight: 700,
                          background: isFinished ? 'rgba(16, 185, 129, 0.15)' : 'rgba(99, 102, 241, 0.15)',
                          color: isFinished ? '#34d399' : '#818cf8',
                          border: `1px solid ${isFinished ? 'rgba(16, 185, 129, 0.3)' : 'rgba(99, 102, 241, 0.3)'}`
                        }}>
                          {isFinished ? '✓ Completed' : `● ${stageLabel}`}
                        </span>

                        <button 
                          className="btn btn-primary"
                          onClick={() => handleStartScheme(schemeId)}
                          disabled={startingSchemeId === schemeId}
                          style={{ padding: '10px 20px', borderRadius: '12px', fontSize: '0.875rem' }}
                        >
                          {startingSchemeId === schemeId ? 'Opening...' : isFinished ? 'Review Application' : 'Continue Interview ➔'}
                        </button>
                      </div>
                    </div>

                    {/* Dynamic Extracted Details Grid */}
                    {dynamicFields.length > 0 && (
                      <div>
                        <h4 style={{ fontSize: '0.875rem', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '14px' }}>
                          Extracted Application Details
                        </h4>
                        <div className={styles.dataGrid}>
                          {dynamicFields.map(([key, val]) => (
                            <div key={key} className={styles.dataItem} style={{ background: 'rgba(255, 255, 255, 0.02)', border: '1px solid rgba(255, 255, 255, 0.04)', borderRadius: '12px' }}>
                              <span className={styles.dataKey}>{key.replace(/_/g, ' ')}</span>
                              <span className={styles.dataVal} style={{ color: '#f1f5f9' }}>{String(val)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Section 2: Available Loan Schemes (Dynamic Discovery & Apply Trigger) */}
        <section style={{ marginTop: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
            <div>
              <h2 style={{ fontSize: '1.35rem', fontWeight: 700, color: '#f8fafc', letterSpacing: '-0.01em' }}>
                Explore Available Loan Schemes
              </h2>
              <p style={{ color: '#64748b', fontSize: '0.875rem' }}>
                Apply for micro loans, business expansion schemes, and government financial assistance
              </p>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '20px' }}>
            {availableSchemes.map((scheme) => {
              const schemeId = scheme.scheme_id;
              const isApplied = appliedSchemeIds.has(schemeId);
              const icon = SCHEME_ICONS[schemeId] || SCHEME_ICONS['default'];
              const title = scheme.display_name || schemeId.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');

              return (
                <div 
                  key={schemeId} 
                  className="card"
                  style={{ 
                    background: 'rgba(15, 23, 42, 0.4)', 
                    border: isApplied ? '1px solid rgba(16, 185, 129, 0.2)' : '1px solid rgba(255, 255, 255, 0.06)', 
                    borderRadius: '20px', 
                    padding: '24px',
                    display: 'flex',
                    flexDirection: 'column',
                    justify: 'space-between',
                    transition: 'all 0.3s ease',
                    position: 'relative'
                  }}
                >
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                      <div style={{ width: '48px', height: '48px', borderRadius: '14px', background: 'rgba(99, 102, 241, 0.08)', border: '1px solid rgba(99, 102, 241, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.5rem' }}>
                        {icon}
                      </div>
                      {isApplied && (
                        <span className="badge badge-accent" style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#34d399', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
                          Applied
                        </span>
                      )}
                    </div>

                    <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: '#fff', marginBottom: '8px' }}>
                      {title}
                    </h3>
                    
                    <p style={{ color: '#94a3b8', fontSize: '0.85rem', lineHeight: '1.5', marginBottom: '20px' }}>
                      Complete your digital application through our natural voice assistant in Hindi or English.
                    </p>

                    <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '20px' }}>
                      {(scheme.languages || ['hi', 'en']).map(lang => (
                        <span key={lang} style={{ padding: '3px 8px', borderRadius: '6px', background: 'rgba(255, 255, 255, 0.04)', color: '#cbd5e1', fontSize: '0.75rem', fontWeight: 500 }}>
                          {lang.toUpperCase()}
                        </span>
                      ))}
                    </div>
                  </div>

                  <button
                    className={isApplied ? 'btn btn-ghost' : 'btn btn-primary'}
                    onClick={() => handleStartScheme(schemeId)}
                    disabled={startingSchemeId === schemeId}
                    style={{ width: '100%', justifyContent: 'center', borderRadius: '12px', padding: '12px' }}
                  >
                    {startingSchemeId === schemeId ? 'Opening...' : isApplied ? 'View / Continue Application' : 'Apply Now ➔'}
                  </button>
                </div>
              );
            })}
          </div>
        </section>

      </main>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <AuthGuard>
      <DashboardContent />
    </AuthGuard>
  );
}
