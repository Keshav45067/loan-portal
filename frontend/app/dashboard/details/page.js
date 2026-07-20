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

  const getVal = (paths, fallback = 'Not Available') => {
    for (const path of paths) {
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
        if (typeof current === 'object') {
          return JSON.stringify(current);
        }
        return String(current);
      }
    }
    return fallback;
  };

  const getFullAddress = () => {
    const addr = extractedData.address;
    if (!addr || typeof addr !== 'object') {
      return getVal(['address.address_line', 'address.full_address', 'registered_office_address', 'address.state']);
    }
    const parts = [
      addr.care_of ? `C/O ${addr.care_of}` : null,
      addr.house,
      addr.street,
      addr.locality,
      addr.vtc,
      addr.district,
      addr.state,
      addr.pincode
    ].filter(Boolean);
    return parts.join(', ') || 'Not Available';
  };

  const formatCurrency = (val) => {
    if (!val || val === 'Not Available' || val === 'no person involved' || val === 'NA') return val;
    const num = parseFloat(val);
    if (isNaN(num)) return val;
    return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(num);
  };

  // Group Details into Categories
  const categories = {
    applicant: {
      title: 'Applicant Profile',
      icon: '👤',
      data: [
        { label: 'Full Name', value: getVal(['applicant_name', 'name', 'full_name', 'holder.full_name']) },
        { label: 'Date of Birth', value: getVal(['date_of_birth', 'dob', 'holder.date_of_birth', 'year_of_birth']) },
        { label: 'Gender', value: getVal(['gender', 'holder.gender']) },
        { label: 'Mobile Number', value: appData?.phone || getVal(['phone', 'mobile_number']) },
        { label: 'Email ID', value: getVal(['email', 'email_id']) },
        { label: 'Academic Qualification', value: getVal(['education_level', 'educational_qualification', 'academic_qualification']) },
        { label: 'Marital Status', value: getVal(['marital_status']) },
        { label: 'Number of Kids', value: getVal(['number_of_kids']) },
        { label: 'Number of Family Members', value: getVal(['number_of_family_members', 'family_members']) },
        { label: 'Co-Borrower Status', value: getVal(['co_borrower']) },
        { label: 'Resident Address', value: getFullAddress() }
      ]
    },
    business: {
      title: 'Business Operations',
      icon: '💼',
      data: [
        { label: 'Enterprise Name', value: getVal(['enterprise_name']) },
        { label: 'Constitution', value: getVal(['constitution'], 'Proprietary') },
        { label: 'Business Type / Category', value: getVal(['business_type', 'type_of_business']) },
        { label: 'Existing Business Activity', value: getVal(['existing_business_activity']) },
        { label: 'Proposed Business Activity', value: getVal(['proposed_business_activity']) },
        { label: 'Date of Commencement', value: getVal(['date_of_commencement']) },
        { label: 'Experience in Activity (Years)', value: getVal(['experience_in_line_of_activity', 'experience_years']) },
        { label: 'Udyam Registration Number', value: getVal(['registration_number_of_business', 'udyam_number']) },
        { label: 'Registered Unit Status', value: getVal(['unit_is_registered'], 'Yes') },
        { label: 'Social Category', value: getVal(['social_category']) },
        { label: 'Minority Religion', value: getVal(['if_minority_religion', 'minority_religion'], 'Don\'t want to respond') }
      ]
    },
    banking: {
      title: 'Banking & Financials',
      icon: '🏦',
      data: [
        { label: 'Bank Name', value: getVal(['presently_banking_with', 'bank_name']) },
        { label: 'Saving Bank Account Number', value: getVal(['saving_bank_account_number', 'account_number']) },
        { label: 'IFSC Code', value: getVal(['ifsc_code_of_saving_bank_account_branch', 'ifsc_code']) },
        { label: 'Declared Monthly Revenue', value: formatCurrency(getVal(['monthly_revenue', 'business_revenue'])) },
        { label: 'Declared Monthly Profit', value: formatCurrency(getVal(['monthly_profit'])) },
        { label: 'Current Employees / Persons Involved', value: getVal(['number_of_persons_involved_currently', 'persons_involved']) },
        { label: 'Current Annual Wages', value: formatCurrency(getVal(['current_total_wages', 'current_wages'])) },
        { label: 'Existing Active Loans', value: getVal(['existing_loan']) },
        { label: 'Existing Monthly EMI', value: formatCurrency(getVal(['existing_loan_emi'])) },
        { label: 'Existing Loan Lender', value: getVal(['existing_loan_lender']) }
      ]
    },
    working_capital: {
      title: 'Working Capital Calculations',
      icon: '⚙️',
      data: [
        { label: 'Calculated Inventory', value: formatCurrency(getVal(['inventory', 'calculated_inventory'])), derived: true },
        { label: 'Calculated Debtors (Receivables)', value: formatCurrency(getVal(['debtors', 'calculated_debtors'])), derived: true },
        { label: 'Calculated Creditors (Payables)', value: formatCurrency(getVal(['creditors', 'calculated_creditors'])), derived: true },
        { label: 'Promoter Contribution (Working Capital)', value: formatCurrency(getVal(['promoters_contribution_in_working_capital', 'promoters_contribution_wc'])), derived: true },
        { label: 'Working Capital Limit', value: formatCurrency(getVal(['limits', 'working_capital_limit'])), derived: true },
        { label: 'Working Cycle (Months)', value: getVal(['working_cycle_months']), derived: true },
        { label: 'Cash Credit Amount Recommended', value: formatCurrency(getVal(['cash_credit_amount'])), derived: true },
        { label: 'Cash Credit Purpose', value: getVal(['cash_credit_purpose']), derived: true }
      ]
    },
    term_loan: {
      title: 'Term Loan Details',
      icon: '🚜',
      data: [
        { label: 'Machine/Equipment Cost', value: formatCurrency(getVal(['approximate_cost', 'machine_cost'])) },
        { label: 'Type of Machine/Equipment', value: getVal(['type_of_machine_equipment', 'machine_name']) },
        { label: 'Machine Purchase Purpose', value: getVal(['purpose', 'machine_purpose']) },
        { label: 'Name of Supplier', value: getVal(['name_of_supplier', 'machine_supplier']) },
        { label: 'Promoter Contribution (Term Loan)', value: formatCurrency(getVal(['promotors_contribution_in_term_loan', 'term_loan_promoter_contribution'])), derived: true },
        { label: 'Term Loan Required', value: formatCurrency(getVal(['term_loan_required', 'term_loan_required_amt'])), derived: true },
        { label: 'Repayment Period Requested', value: getVal(['repayment_period_requested_for']), derived: true },
        { label: 'Moratorium Period', value: getVal(['morotorium_period']), derived: true }
      ]
    },
    projections: {
      title: 'Financial Estimates & Projections',
      icon: '📈',
      data: [
        { label: 'Sales (Past Year II)', value: formatCurrency(getVal(['net_sales_past_year_2'])), derived: true },
        { label: 'Sales (Past Year I)', value: formatCurrency(getVal(['net_sales_past_year_1'])), derived: true },
        { label: 'Sales (Present Year)', value: formatCurrency(getVal(['net_sales_present_year'])), derived: true },
        { label: 'Sales (Next Year Projection)', value: formatCurrency(getVal(['net_sales_next_year'])), derived: true },
        { label: 'Net Profit (Past Year II)', value: formatCurrency(getVal(['net_profit_past_year_2'])), derived: true },
        { label: 'Net Profit (Past Year I)', value: formatCurrency(getVal(['net_profit_past_year_1'])), derived: true },
        { label: 'Net Profit (Present Year)', value: formatCurrency(getVal(['net_profit_present_year'])), derived: true },
        { label: 'Net Profit (Next Year Projection)', value: formatCurrency(getVal(['net_profit_next_year'])), derived: true },
        { label: 'Proposed Employee Wages (Annual)', value: formatCurrency(getVal(['proposed_total_wages', 'proposed_wages'])), derived: true },
        { label: 'Proposed Hires (Total count)', value: getVal(['proposed_number_of_persons_involved', 'proposed_number_of_people']), derived: true },
        { label: 'Total Recommended Loan (CC + Term)', value: formatCurrency(getVal(['total_loan_required_amount', 'total_calculated_loan_required'])), derived: true }
      ]
    }
  };

  const scoreStr = getVal(['credit_worthiness']);
  const creditReason = getVal(['credit_reason', 'credit_reason_explanation']);
  const isCreditPending = !scoreStr || scoreStr === 'Not Available' || scoreStr === 'Calculating...';

  // Get raw numeric score out of X/10 format
  let rawScore = 0;
  if (scoreStr && scoreStr.includes('/')) {
    rawScore = parseFloat(scoreStr.split('/')[0]) || 0;
  } else {
    rawScore = parseFloat(scoreStr) || 0;
  }

  const getScoreColor = (score) => {
    if (score >= 8) return '#10b981'; // Green
    if (score >= 5) return '#f59e0b'; // Amber
    return '#ef4444'; // Red
  };

  const toggleMapVisibility = (docId) => {
    setShowMap(prev => ({ ...prev, [docId]: !prev[docId] }));
  };

  return (
    <div style={{ background: '#03050c', color: '#fff', minHeight: '100vh', fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif' }}>
      
      {/* Dynamic Navigation Bar */}
      <nav style={{ 
        padding: '16px 32px', 
        display: 'flex', 
        justifyContent: 'space-between', 
        alignItems: 'center', 
        borderBottom: '1px solid rgba(255, 255, 255, 0.05)', 
        background: 'rgba(5, 7, 18, 0.8)', 
        backdropFilter: 'blur(20px)', 
        position: 'sticky', 
        top: 0, 
        zIndex: 10 
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <Link href="/dashboard" style={{ textDecoration: 'none', color: '#6366f1', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.875rem', fontWeight: 500 }}>
            <span>← Underwriting Hub</span>
          </Link>
          <span style={{ color: 'rgba(255,255,255,0.1)' }}>|</span>
          <span style={{ fontSize: '1rem', fontWeight: 600, color: '#fff', letterSpacing: '-0.02em' }}>Mudra Smart Underwriting Desk</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ fontSize: '0.75rem', color: '#818cf8', background: 'rgba(99, 102, 241, 0.08)', padding: '6px 14px', borderRadius: '20px', border: '1px solid rgba(99, 102, 241, 0.15)', fontWeight: 600 }}>
            ID: {appData?.application_id || 'Pending'}
          </div>
          {isCreditPending ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', color: '#f59e0b', background: 'rgba(245, 158, 11, 0.08)', padding: '6px 12px', borderRadius: '20px', border: '1px solid rgba(245, 158, 11, 0.15)', fontWeight: 600 }}>
              <span style={{ width: '8px', height: '8px', background: '#f59e0b', borderRadius: '50%', display: 'inline-block', animation: 'pulse 1.5s infinite' }}></span>
              Recalculating...
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
      <div style={{ maxWidth: '1600px', margin: '0 auto', padding: '32px', display: 'grid', gridTemplateColumns: '1.25fr 0.75fr', gap: '32px' }}>
        
        {/* Left Section: tabs for organized fields */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Custom Tabs Navigation */}
          <div style={{ 
            display: 'flex', 
            background: 'rgba(255, 255, 255, 0.02)', 
            border: '1px solid rgba(255, 255, 255, 0.04)', 
            borderRadius: '16px', 
            padding: '6px', 
            gap: '8px', 
            overflowX: 'auto',
            whiteSpace: 'nowrap'
          }}>
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
              <span style={{ fontSize: '1.5rem' }}>{categories[activeTab].icon}</span>
              <span>{categories[activeTab].title}</span>
            </h3>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
              {categories[activeTab].data.map((item, idx) => {
                // IMPORTANT: Calculate skeleton loading ONLY if the credit is pending AND the value is not available/calculated yet!
                const isCalculating = isCreditPending && item.derived && (!item.value || item.value === 'Not Available' || item.value === 'NA' || item.value === '');
                
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
        <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
          
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
                🛡️ AI Underwriting Panel
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
                  <div style={{ fontWeight: 600, color: '#f59e0b', fontSize: '0.9375rem', marginBottom: '4px' }}>Analyzing Credit Viability...</div>
                  <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Running financial models & underwriting scoring</div>
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                
                {/* Score Indicator */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '20px', padding: '20px', background: 'rgba(255,255,255,0.01)', borderRadius: '18px', border: '1px solid rgba(255,255,255,0.03)' }}>
                  <div style={{ 
                    width: '72px', 
                    height: '72px', 
                    borderRadius: '50%', 
                    border: `4px solid ${getScoreColor(rawScore)}`, 
                    display: 'flex', 
                    alignItems: 'center', 
                    justifyContent: 'center',
                    fontSize: '1.5rem', 
                    fontWeight: 800,
                    color: getScoreColor(rawScore),
                    boxShadow: `0 0 20px 0 rgba(${rawScore >= 8 ? '16, 185, 129' : rawScore >= 5 ? '245, 158, 11' : '239, 68, 68'}, 0.15)`
                  }}>
                    {rawScore}
                  </div>
                  <div>
                    <div style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '2px' }}>AI Underwriting Score</div>
                    <strong style={{ 
                      fontSize: '1rem', 
                      color: rawScore >= 8 ? '#10b981' : rawScore >= 5 ? '#fbbf24' : '#ef4444' 
                    }}>
                      {rawScore >= 8 ? 'High Creditworthiness' : rawScore >= 5 ? 'Moderate Risk' : 'High Risk Profile'}
                    </strong>
                  </div>
                </div>

                {/* Recommendation */}
                <div style={{ 
                  padding: '16px 20px', 
                  borderRadius: '16px', 
                  background: getVal(['recommendation', 'recommendation_decision']).includes('forward') || rawScore >= 6 ? 'rgba(16, 185, 129, 0.05)' : 'rgba(245, 158, 11, 0.05)',
                  border: `1px solid ${getVal(['recommendation', 'recommendation_decision']).includes('forward') || rawScore >= 6 ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)'}`,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '4px'
                }}>
                  <div style={{ fontSize: '0.75rem', color: '#94a3b8', fontWeight: 600 }}>ACTION DECISION</div>
                  <strong style={{ 
                    fontSize: '0.9375rem', 
                    color: getVal(['recommendation', 'recommendation_decision']).includes('forward') || rawScore >= 6 ? '#10b981' : '#fbbf24'
                  }}>
                    {getVal(['recommendation', 'recommendation_decision']) !== 'Not Available' 
                      ? getVal(['recommendation', 'recommendation_decision']).toUpperCase()
                      : rawScore >= 6 ? 'FORWARD TO BANK' : 'NEED RESUBMISSION'
                    }
                  </strong>
                </div>

                {/* Detailed Reasoning points */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <div style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Scoring Explanation</div>
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
                    {creditReason}
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
