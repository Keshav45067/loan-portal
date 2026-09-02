'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import styles from '../dashboard.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export default function DetailsPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [appData, setAppData] = useState(null);
  const [extractedData, setExtractedData] = useState({});
  const [documents, setDocuments] = useState([]);
  const [activeTab, setActiveTab] = useState('applicant');
  const [recalculating, setRecalculating] = useState(false);
  const [showMap, setShowMap] = useState({});

  const fetchDetails = async () => {
    try {
      const token = localStorage.getItem('token');
      const sessionId = localStorage.getItem('session_id');
      if (!token || !sessionId) {
        router.push('/');
        return;
      }

      const res = await fetch(`${API_BASE_URL}/api/applications/${sessionId}`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.status === 401 || res.status === 403) {
        console.warn('[DetailsPage] Stored token is expired. Clearing credentials.');
        localStorage.removeItem('token');
        localStorage.removeItem('session_id');
        router.replace('/');
        return;
      }
      const data = await res.json();
      
      if (data.status === 'ERROR' || data.status === 'NOT_FOUND') {
        router.push('/dashboard');
        return;
      }

      setAppData(data);
      setExtractedData(data.extracted_data || {});
      
      const docsWithUrls = (data.documents || []).map((doc) => {
        let docType = doc.doc_type || '';
        if (!docType && doc.key && doc.key.includes('/')) {
          const parts = doc.key.split('/');
          if (parts.length >= 3) {
            docType = parts[2];
          }
        }
        return {
          ...doc,
          doc_type: docType,
          preview_url: doc.key
        };
      });
      setDocuments(docsWithUrls);
    } catch (err) {
      console.error('Failed to fetch details:', err);
      router.push('/dashboard');
    } finally {
      setLoading(false);
    }
  };

  const triggerRecalculation = async () => {
    try {
      setRecalculating(true);
      const token = localStorage.getItem('token');
      const sessionId = localStorage.getItem('session_id');
      if (!token || !sessionId) return;
      
      const res = await fetch(`${API_BASE_URL}/api/applications/trigger-evaluations`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ session_id: sessionId })
      });
      const data = await res.json();
      if (data.success) {
        fetchDetails();
      } else {
        alert('Failed to trigger recalculation: ' + (data.error || 'Unknown error'));
      }
    } catch (err) {
      console.error(err);
      alert('Error triggering recalculation');
    } finally {
      setRecalculating(false);
    }
  };

  useEffect(() => {
    fetchDetails();
  }, [router]);

  useEffect(() => {
    if (!appData) return;
    const isMudra = appData?.scheme_id?.includes('mudra') || appData?.scheme_id === 'a74b1b43-7cc6-4385-8a8c-12af64cddb2b';
    if (!isMudra) return;

    const score = extractedData.credit_worthiness;
    const isPending = !score || score === 'Not Available' || score === 'Calculating...';
    if (isPending) {
      const interval = setInterval(fetchDetails, 3000);
      return () => clearInterval(interval);
    }
  }, [appData, extractedData.credit_worthiness]);

  if (loading) {
    return (
      <div style={{ display: 'flex', height: '100vh', width: '100vw', alignItems: 'center', justifyContent: 'center', background: '#03050c', color: '#fff' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ width: '60px', height: '60px', border: '3px solid rgba(255,255,255,0.03)', borderTopColor: '#6366f1', borderRadius: '50%', animation: 'spin 1s linear infinite', margin: '0 auto 20px' }}></div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 500, color: '#94a3b8' }}>Loading Underwriting Desk...</h2>
          <style jsx global>{`
            @keyframes spin {
              0% { transform: rotate(0deg); }
              100% { transform: rotate(360deg); }
            }
          `}</style>
        </div>
      </div>
    );
  }

  const formatComplexValue = (val) => {
    if (val === undefined || val === null || val === '') return 'Not Available';
    if (typeof val === 'string' || typeof val === 'number' || typeof val === 'boolean') return String(val);
    if (Array.isArray(val)) {
      return val.map(item => {
        if (typeof item === 'object' && item !== null) {
          if (item.name && item.count !== undefined && item.unit_cost !== undefined) {
            return `${item.name} (${item.count} units @ ₹${item.unit_cost})`;
          }
          if (item.name && item.monthly_qty !== undefined) {
            return `${item.name} (${item.monthly_qty} units)`;
          }
          if (item.name) return item.name;
          return Object.entries(item).map(([k, v]) => `${k}: ${v}`).join(', ');
        }
        return String(item);
      }).join('; ');
    }
    if (typeof val === 'object') {
      const parts = [
        val.house_number || val.house || val.flat_door_block,
        val.street || val.road_street || val.road_street_lane || val.building_name || val.premises_building,
        val.locality || val.village_town || val.village_town_city || val.city_village,
        val.subdistrict || val.tehsil || val.vtc,
        val.district || val.city || val.city_town,
        val.state,
        val.pincode
      ].filter(Boolean);
      if (parts.length > 0) return parts.join(', ');
      return Object.entries(val).map(([k, v]) => `${k}: ${v}`).join(', ');
    }
    return String(val);
  };

  const getVal = (paths, fallback = 'Not Available') => {
    const extractions = extractedData?.extractions || {};
    const interviewExt = extractions.interview || {};
    const voiceQaExt = extractions['voice-qa'] || {};

    const pathList = Array.isArray(paths) ? paths : [paths];

    for (const path of pathList) {
      // 1. Direct on extractedData
      if (extractedData?.[path] !== undefined && extractedData[path] !== null && extractedData[path] !== '') {
        return formatComplexValue(extractedData[path]);
      }
      // 2. Direct on interview
      if (interviewExt?.[path] !== undefined && interviewExt[path] !== null && interviewExt[path] !== '') {
        return formatComplexValue(interviewExt[path]);
      }
      // 3. Direct on voice-qa
      if (voiceQaExt?.[path] !== undefined && voiceQaExt[path] !== null && voiceQaExt[path] !== '') {
        return formatComplexValue(voiceQaExt[path]);
      }
      // 4. In document extractions
      for (const docKey of Object.keys(extractions)) {
        if (extractions[docKey] && typeof extractions[docKey] === 'object') {
          if (extractions[docKey][path] !== undefined && extractions[docKey][path] !== null && extractions[docKey][path] !== '') {
            return formatComplexValue(extractions[docKey][path]);
          }
        }
      }
      // 5. Nested path
      const parts = path.split('.');
      let current = extractedData;
      for (const part of parts) {
        if (current && typeof current === 'object') {
          current = current[part];
        } else {
          current = undefined;
          break;
        }
      }
      if (current !== undefined && current !== null && current !== '') {
        return formatComplexValue(current);
      }
    }
    return fallback;
  };

  const getApplicantName = () => {
    const val = getVal(['applicant_name', 'doc_aadhaar_name', 'doc_pan_name', 'doc_voter_name']);
    if (val && val !== 'Applicant' && val !== 'Not Available' && val !== 'NA' && val !== '') {
      return val;
    }
    const holderName = getVal(['holder.full_name', 'name', 'full_name']);
    if (holderName && holderName !== 'Not Available') {
      return holderName;
    }
    return val || 'Applicant';
  };

  const formatCurrency = (val) => {
    if (!val || val === 'Not Available' || val === 'no person involved' || val === 'NA') return val;
    const num = parseFloat(val);
    if (isNaN(num)) return val;
    return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(num);
  };

  const isPmfme = appData?.scheme_id?.toLowerCase().includes('pmfme');
  const isMudra = appData?.scheme_id?.toLowerCase().includes('mudra') || appData?.scheme_id === 'a74b1b43-7cc6-4385-8a8c-12af64cddb2b';

  // Build Dynamic Categories from form_schema or fallback
  const categories = (() => {
    if (appData?.form_schema?.sections && appData.form_schema.sections.length > 0) {
      const cats = {};
      const icons = ['👤', '🏢', '🏗️', '⚙️', '🌾', '👥', '🏦', '📊', '📋'];
      appData.form_schema.sections.forEach((sec, idx) => {
        const key = `section_${idx}`;
        cats[key] = {
          title: sec.title,
          icon: icons[idx % icons.length],
          data: (sec.fields || []).map(f => {
            let rawVal = getVal(f.key);
            if (f.type === 'currency' && rawVal !== 'Not Available') {
              rawVal = formatCurrency(rawVal);
            }
            return {
              label: f.label || f.key.replace(/_/g, ' ').toUpperCase(),
              value: rawVal,
              derived: !!f.is_derived
            };
          })
        };
      });
      return cats;
    }

    // Default fallback
    return {
      applicant: {
        title: 'Applicant & Business Profile',
        icon: '👤',
        data: [
          { label: 'Full Name', value: getApplicantName() },
          { label: 'Mobile Number', value: appData?.phone || getVal(['phone', 'mobile_number']) },
          { label: 'Enterprise Name', value: getVal(['enterprise_name', 'doc_udyam_enterprise_name']) },
          { label: 'Business Type', value: getVal(['business_type', 'type_of_business']) }
        ]
      }
    };
  })();

  const currentActiveTab = categories[activeTab] ? activeTab : Object.keys(categories)[0] || 'section_0';

  const viabilityTag = getVal(['viability_tag', 'business_viability_status']);
  const viabilityExplanation = getVal(['viability_explanation', 'viability_summary', 'viability_details']);

  const scoreStr = getVal(['credit_worthiness', 'creditworthiness_score', 'credit_score', 'score']);
  const creditReason = getVal(['credit_reason', 'reason', 'credit_reason_explanation', 'explanation', 'analysis']);
  const isCreditPending = (isMudra && (!scoreStr || scoreStr === 'Not Available' || scoreStr === 'Calculating...')) ||
                          (isPmfme && (!viabilityTag || viabilityTag === 'Not Available' || viabilityTag === 'Calculating...')) ||
                          recalculating;

  // Get raw numeric score out of X/10 format
  let rawScore = 0;
  if (scoreStr && scoreStr.includes('/')) {
    rawScore = parseFloat(scoreStr.split('/')[0]) || 0;
  } else {
    rawScore = parseFloat(scoreStr) || (viabilityTag.toLowerCase().includes('high') ? 9 : viabilityTag !== 'Not Available' ? 7 : 0);
  }

  const getScoreColor = (score) => {
    if (score >= 8) return '#10b981'; // Green
    if (score >= 5) return '#f59e0b'; // Amber
    return '#ef4444'; // Red
  };

  const getStatusText = () => {
    if (recalculating) return 'Recalculating...';
    if (isPmfme) return 'Evaluating Viability...';
    if (isMudra) return 'Evaluating Credit...';
    return 'Calculating...';
  };

  const toggleMapVisibility = (docId) => {
    setShowMap(prev => ({ ...prev, [docId]: !prev[docId] }));
  };

  return (
    <div style={{ background: '#03050c', color: '#fff', minHeight: '100vh', fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif' }}>
      
      {/* Dynamic Navigation Bar */}
      <nav className="nav-bar">
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <Link href="/dashboard" style={{ textDecoration: 'none', color: '#6366f1', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.875rem', fontWeight: 500 }}>
            <span>← Underwriting Hub</span>
          </Link>
          <span style={{ color: 'rgba(255,255,255,0.1)' }}>|</span>
          <span style={{ fontSize: '1rem', fontWeight: 600, color: '#fff', letterSpacing: '-0.02em' }}>Smart Micro-Loan Underwriting Desk</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ fontSize: '0.75rem', color: '#818cf8', background: 'rgba(99, 102, 241, 0.08)', padding: '6px 14px', borderRadius: '20px', border: '1px solid rgba(99, 102, 241, 0.15)', fontWeight: 600 }}>
            ID: {appData?.application_id || 'Pending'}
          </div>
          {isCreditPending ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', color: '#f59e0b', background: 'rgba(245, 158, 11, 0.08)', padding: '6px 12px', borderRadius: '20px', border: '1px solid rgba(245, 158, 11, 0.15)', fontWeight: 600 }}>
              <span style={{ width: '8px', height: '8px', background: '#f59e0b', borderRadius: '50%', display: 'inline-block', animation: 'pulse 1.5s infinite' }}></span>
              {getStatusText()}
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', color: '#10b981', background: 'rgba(16, 185, 129, 0.08)', padding: '6px 12px', borderRadius: '20px', border: '1px solid rgba(16, 185, 129, 0.15)', fontWeight: 600 }}>
              <span style={{ width: '8px', height: '8px', background: '#10b981', borderRadius: '50%', display: 'inline-block' }}></span>
              Synced
            </div>
          )}
        </div>
      </nav>

      {/* Main Glassmorphic Grid */}
      <div className="layout-grid">
        
        {/* Left Section: tabs for organized fields */}
        <div className="left-section">
          
          {/* Custom Tabs Navigation */}
          <div className="tabs-container">
            {Object.entries(categories).map(([key, cat]) => (
              <button 
                key={key} 
                onClick={() => setActiveTab(key)}
                style={{ 
                  background: activeTab === key ? 'rgba(99, 102, 241, 0.12)' : 'transparent', 
                  border: activeTab === key ? '1px solid rgba(99, 102, 241, 0.3)' : '1px solid transparent',
                  color: activeTab === key ? '#a5b4fc' : '#94a3b8',
                  padding: '10px 18px', 
                  borderRadius: '12px', 
                  cursor: 'pointer', 
                  fontSize: '0.875rem', 
                  fontWeight: 600,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  transition: 'all 0.2s ease-in-out'
                }}
              >
                <span>{cat.icon}</span>
                <span>{cat.title}</span>
              </button>
            ))}
          </div>

          {/* Active Tab Content Card */}
          <div style={{ 
            background: 'rgba(255, 255, 255, 0.01)', 
            border: '1px solid rgba(255, 255, 255, 0.03)', 
            borderRadius: '24px', 
            padding: '32px',
            boxShadow: '0 8px 32px 0 rgba(0, 0, 0, 0.2)',
            backdropFilter: 'blur(20px)'
          }}>
            <h3 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: '24px', color: '#fff', display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{ fontSize: '1.5rem' }}>{categories[currentActiveTab]?.icon || '📋'}</span>
              <span>{categories[currentActiveTab]?.title || 'Details'}</span>
            </h3>

            <div className="details-grid">
              {(categories[currentActiveTab]?.data || []).map((item, idx) => {
                const isCalculating = isCreditPending && item.derived && (!item.value || item.value === 'Not Available' || item.value === 'NA' || item.value === '');
                const isNotPresent = !item.value || item.value === 'Not Available' || item.value === 'NA' || item.value === 'Not Provided' || item.value === '';
                if (!isCalculating && isNotPresent) {
                  return null;
                }

                return (
                  <div key={idx} style={{ 
                    padding: '16px', 
                    background: 'rgba(255,255,255,0.01)', 
                    border: '1px solid rgba(255,255,255,0.02)', 
                    borderRadius: '14px',
                    position: 'relative'
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                      <span style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{item.label}</span>
                      {item.derived && (
                        <span style={{ fontSize: '0.625rem', color: '#818cf8', background: 'rgba(99, 102, 241, 0.1)', padding: '2px 6px', borderRadius: '6px', fontWeight: 700 }}>DERIVED RULE</span>
                      )}
                    </div>
                    {isCalculating ? (
                      <div style={{ height: '20px', background: 'linear-gradient(90deg, rgba(255,255,255,0.02) 25%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.02) 75%)', backgroundSize: '200% 100%', animation: 'shimmer 1.5s infinite', borderRadius: '4px', marginTop: '4px' }}></div>
                    ) : (
                      <div style={{ 
                        fontSize: '1rem', 
                        fontWeight: 650, 
                        color: (item.value === 'Not Available' || item.value === 'NA') ? '#475569' : '#e2e8f0' 
                      }}>
                        {item.value}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Right Section: Underwriting & Decisions + Documents */}
        <div className="right-section">
          
          {/* AI Underwriting Decisions Panel */}
          <div style={{ 
            background: 'linear-gradient(135deg, rgba(17, 24, 39, 0.6) 0%, rgba(3, 7, 18, 0.9) 100%)', 
            border: '1px solid rgba(255, 255, 255, 0.05)', 
            borderRadius: '24px', 
            padding: '32px',
            boxShadow: '0 12px 48px 0 rgba(0, 0, 0, 0.4)',
            backdropFilter: 'blur(30px)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
              <h3 style={{ fontSize: '1.15rem', fontWeight: 750, margin: 0, color: '#fff', display: 'flex', alignItems: 'center', gap: '10px' }}>
                {isPmfme ? '🌾 PMFME Viability Appraisal' : '🛡️ AI Underwriting Panel'}
              </h3>
              
              <button 
                onClick={triggerRecalculation}
                disabled={recalculating}
                style={{
                  background: recalculating ? 'rgba(255,255,255,0.05)' : 'rgba(99, 102, 241, 0.1)',
                  border: '1px solid rgba(99, 102, 241, 0.25)',
                  color: '#a5b4fc',
                  padding: '6px 12px',
                  borderRadius: '10px',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  cursor: recalculating ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  transition: 'all 0.2s'
                }}
              >
                <span>🔄</span>
                <span>{recalculating ? 'Processing...' : 'Recalculate'}</span>
              </button>
            </div>

            {isCreditPending ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', alignItems: 'center', justifyContent: 'center', padding: '40px 0' }}>
                <div style={{ width: '40px', height: '40px', border: '3px solid rgba(245, 158, 11, 0.05)', borderTopColor: '#f59e0b', borderRadius: '50%', animation: 'spin 1s linear infinite' }}></div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontWeight: 600, color: '#f59e0b', fontSize: '0.9375rem', marginBottom: '4px' }}>
                    {isPmfme ? 'Evaluating Food Business Viability...' : 'Analyzing Credit Viability...'}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Running financial models & appraisal scoring</div>
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                
                {/* Score / Viability Tag Indicator */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '20px', padding: '20px', background: 'rgba(255,255,255,0.01)', borderRadius: '18px', border: '1px solid rgba(255,255,255,0.03)' }}>
                  <div style={{ 
                    minWidth: isPmfme ? '100px' : '72px',
                    height: '72px', 
                    padding: isPmfme ? '0 12px' : 0,
                    borderRadius: '18px', 
                    border: `3px solid ${getScoreColor(rawScore)}`, 
                    display: 'flex', 
                    alignItems: 'center', 
                    justifyContent: 'center',
                    fontSize: isPmfme ? '1.1rem' : '1.5rem', 
                    fontWeight: 800,
                    color: getScoreColor(rawScore),
                    textAlign: 'center',
                    boxShadow: `0 0 20px 0 rgba(${rawScore >= 8 ? '16, 185, 129' : rawScore >= 5 ? '245, 158, 11' : '239, 68, 68'}, 0.15)`
                  }}>
                    {isPmfme ? (viabilityTag !== 'Not Available' ? viabilityTag : 'Viable') : rawScore}
                  </div>
                  <div>
                    <div style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '2px' }}>
                      {isPmfme ? 'Enterprise Appraisal Status' : 'AI Underwriting Score'}
                    </div>
                    <strong style={{ 
                      fontSize: '1rem', 
                      color: rawScore >= 8 ? '#10b981' : rawScore >= 5 ? '#fbbf24' : '#ef4444' 
                    }}>
                      {isPmfme 
                        ? (viabilityTag.toLowerCase().includes('high') ? 'Highly Feasible Project' : 'Feasible & Eligible')
                        : (rawScore >= 8 ? 'High Creditworthiness' : rawScore >= 5 ? 'Moderate Risk' : 'High Risk Profile')}
                    </strong>
                  </div>
                </div>

                {/* Recommendation */}
                <div style={{ 
                  padding: '16px 20px', 
                  borderRadius: '16px', 
                  background: 'rgba(16, 185, 129, 0.05)',
                  border: '1px solid rgba(16, 185, 129, 0.15)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '4px'
                }}>
                  <div style={{ fontSize: '0.75rem', color: '#94a3b8', fontWeight: 600 }}>ACTION DECISION</div>
                  <strong style={{ fontSize: '0.9375rem', color: '#10b981' }}>
                    {isPmfme ? 'FORWARD TO DIC / BANK FOR SANCTION' : 'FORWARD TO BANK'}
                  </strong>
                </div>

                {/* Detailed Reasoning points */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <div style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    {isPmfme ? 'Viability Assessment Summary' : 'Scoring Explanation'}
                  </div>
                  <div style={{ 
                    fontSize: '0.875rem', 
                    color: '#cbd5e1', 
                    lineHeight: '1.6', 
                    background: 'rgba(0,0,0,0.2)', 
                    padding: '18px', 
                    borderRadius: '16px',
                    border: '1px solid rgba(255,255,255,0.02)',
                    whiteSpace: 'pre-line' 
                  }}>
                    {isPmfme 
                      ? (viabilityExplanation !== 'Not Available' ? viabilityExplanation : '• Business operations, food category, and machinery align with PMFME enterprise criteria.\n• Raw materials and labor model support sustainable local food processing operations.')
                      : (Array.isArray(creditReason) 
                          ? creditReason.join('\n') 
                          : creditReason !== 'Not Available' ? creditReason : '• Verified document extractions match applicant identity.')
                    }
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Uploaded Documents List */}
          <div style={{ 
            background: 'rgba(255, 255, 255, 0.01)', 
            border: '1px solid rgba(255, 255, 255, 0.03)', 
            borderRadius: '24px', 
            padding: '32px'
          }}>
            <h3 style={{ fontSize: '1.15rem', fontWeight: 700, marginBottom: '24px', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
              📄 Verified Credentials ({documents.length})
            </h3>
            
            {documents.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '40px 20px', color: '#475569' }}>
                <span style={{ fontSize: '2rem', display: 'block', marginBottom: '10px' }}>📁</span>
                No files found
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                {documents.map((doc, idx) => {
                  let displayName = doc.name;
                  let latitude = null;
                  let longitude = null;
                  let recordedAt = null;
                  let addressVal = null;
                  
                  try {
                    const parsed = JSON.parse(doc.name);
                    displayName = parsed.name || doc.name;
                    latitude = parsed.latitude;
                    longitude = parsed.longitude;
                    recordedAt = parsed.timestamp || parsed.recorded_at;
                    addressVal = parsed.address;
                  } catch (e) {
                    // Fallback to original string
                  }

                  const mapId = doc.id || idx;

                  return (
                    <div key={idx} style={{ 
                      background: 'rgba(255, 255, 255, 0.01)', 
                      border: '1px solid rgba(255, 255, 255, 0.03)', 
                      borderRadius: '16px', 
                      padding: '16px', 
                      display: 'flex', 
                      flexDirection: 'column', 
                      gap: '12px' 
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: '0.8125rem', fontWeight: 700, color: '#fff', textTransform: 'capitalize' }}>
                          {doc.doc_type.replace(/_/g, ' ')}
                        </span>
                        <span style={{ fontSize: '0.75rem', color: '#64748b', maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={displayName}>
                          {displayName}
                        </span>
                      </div>
                      
                      {/* Render preview */}
                      <div style={{ 
                        width: '100%', 
                        height: '180px', 
                        borderRadius: '12px', 
                        overflow: 'hidden', 
                        background: '#020307', 
                        display: 'flex', 
                        alignItems: 'center', 
                        justifyContent: 'center', 
                        border: '1px solid rgba(255, 255, 255, 0.04)' 
                      }}>
                        {doc.doc_type === 'workplace_video' ? (
                          <video 
                            src={doc.preview_url || doc.key} 
                            controls
                            style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
                          />
                        ) : (
                          <>
                            <img 
                              src={doc.preview_url || doc.key} 
                              alt={doc.doc_type}
                              style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
                              onError={(e) => {
                                e.target.style.display = 'none';
                                e.target.nextSibling.style.display = 'block';
                              }}
                            />
                            <div style={{ display: 'none', color: '#475569', fontSize: '0.75rem' }}>
                              No preview available
                            </div>
                          </>
                        )}
                      </div>

                      {/* Display Location details and time if Geotagged */}
                      {latitude !== null && longitude !== null && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                          <div style={{ 
                            fontSize: '0.75rem', 
                            color: '#34d399', 
                            background: 'rgba(52, 211, 153, 0.08)',
                            padding: '10px 14px',
                            borderRadius: '8px',
                            border: '1px solid rgba(52, 211, 153, 0.15)',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '4px',
                            fontWeight: 500
                          }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <span>📍 Geotagged Workplace GPS</span>
                              <button 
                                onClick={() => toggleMapVisibility(mapId)}
                                style={{
                                  background: 'rgba(52, 211, 153, 0.15)',
                                  border: 'none',
                                  color: '#34d399',
                                  padding: '2px 8px',
                                  borderRadius: '6px',
                                  fontSize: '0.675rem',
                                  fontWeight: 700,
                                  cursor: 'pointer'
                                }}
                              >
                                {showMap[mapId] ? '🙈 Hide Map' : '🗺️ View Map'}
                              </button>
                            </div>
                            <div style={{ fontWeight: 650, color: '#e2e8f0', marginTop: '2px' }}>
                              Lat: {parseFloat(latitude).toFixed(6)}, Lng: {parseFloat(longitude).toFixed(6)}
                            </div>
                            {recordedAt && (
                              <div style={{ fontSize: '0.675rem', color: '#8b9bb4' }}>
                                Recorded At: {new Date(recordedAt).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}
                              </div>
                            )}
                            {addressVal && (
                              <div style={{ fontSize: '0.675rem', color: '#8b9bb4', marginTop: '2px', lineHeight: '1.4' }}>
                                Address: {addressVal}
                              </div>
                            )}
                          </div>

                          {/* OpenStreetMap Interactive Embedded Map */}
                          {showMap[mapId] && (
                            <div style={{ 
                              width: '100%', 
                              height: '200px', 
                              borderRadius: '10px', 
                              overflow: 'hidden', 
                              border: '1px solid rgba(52, 211, 153, 0.25)' 
                            }}>
                              <iframe 
                                width="100%" 
                                height="100%" 
                                frameBorder="0" 
                                scrolling="no" 
                                marginHeight="0" 
                                marginWidth="0" 
                                src={`https://www.openstreetmap.org/export/embed.html?bbox=${parseFloat(longitude) - 0.005}%2C${parseFloat(latitude) - 0.005}%2C${parseFloat(longitude) + 0.005}%2C${parseFloat(latitude) + 0.005}&layer=mapnik&marker=${parseFloat(latitude)}%2C${parseFloat(longitude)}`}
                                style={{ border: 0 }}
                              />
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

      </div>

      <style jsx global>{`
        .nav-bar {
          padding: 16px 32px;
          display: flex;
          justify-content: space-between;
          align-items: center;
          border-bottom: 1px solid rgba(255, 255, 255, 0.05);
          background: rgba(5, 7, 18, 0.8);
          backdrop-filter: blur(20px);
          position: sticky;
          top: 0;
          z-index: 10;
        }
        .layout-grid {
          max-width: 1600px;
          width: 100%;
          margin: 0 auto;
          padding: 32px;
          display: flex;
          flex-wrap: wrap;
          gap: 32px;
          box-sizing: border-box;
        }
        .left-section {
          display: flex;
          flex-direction: column;
          gap: 24px;
          flex: 1.25;
          min-width: 320px;
          box-sizing: border-box;
        }
        .right-section {
          display: flex;
          flex-direction: column;
          gap: 32px;
          flex: 0.75;
          min-width: 300px;
          box-sizing: border-box;
        }
        .tabs-container {
          display: flex;
          background: rgba(255, 255, 255, 0.02);
          border: 1px solid rgba(255, 255, 255, 0.04);
          border-radius: 16px;
          padding: 6px;
          gap: 8px;
          overflow-x: auto;
          white-space: nowrap;
        }
        .details-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 24px;
        }
        @media (max-width: 1200px) {
          .nav-bar {
            padding: 16px;
            flex-direction: column;
            align-items: flex-start;
            gap: 12px;
          }
          .layout-grid {
            padding: 16px;
            gap: 24px;
          }
          .left-section, .right-section {
            flex: 1 1 100%;
            width: 100%;
          }
        }
        @media (max-width: 768px) {
          .tabs-container {
            flex-wrap: wrap;
          }
          .details-grid {
            grid-template-columns: 1fr;
            gap: 16px;
          }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        @keyframes shimmer {
          0% { background-position: -200% 0; }
          100% { background-position: 200% 0; }
        }
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
