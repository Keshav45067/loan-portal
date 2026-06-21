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

  useEffect(() => {
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
        
        // Fetch preview URLs for GCS documents
        const docsWithUrls = await Promise.all((data.documents || []).map(async (doc) => {
          if (doc.key && doc.key.startsWith('govt_id/')) {
            try {
              const previewRes = await fetch(`${API_BASE_URL}/api/documents/preview?key=${encodeURIComponent(doc.key)}`, {
                headers: { 'Authorization': `Bearer ${token}` }
              });
              const previewData = await previewRes.json();
              if (previewData.success) {
                return { ...doc, preview_url: previewData.url };
              }
            } catch (e) {
              console.error('Failed to fetch preview URL for', doc.key, e);
            }
          }
          // Fallback if not a GCS key (e.g. legacy local upload)
          return { ...doc, preview_url: doc.key.startsWith('/') ? `${API_BASE_URL}${doc.key}` : doc.key };
        }));
        setDocuments(docsWithUrls);
      } catch (err) {
        console.error('Failed to fetch details:', err);
        router.push('/dashboard');
      } finally {
        setLoading(false);
      }
    };

    fetchDetails();
  }, [router]);

  if (loading) {
    return (
      <div className={styles.container} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'radial-gradient(circle at center, #0f111a 0%, #050508 100%)', color: '#fff' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ width: '50px', height: '50px', border: '3px solid rgba(255,255,255,0.1)', borderTopColor: '#7c3aed', borderRadius: '50%', animation: 'spin 1s linear infinite', margin: '0 auto 20px' }}></div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 500, color: '#a0aec0' }}>लोड हो रहा है...</h2>
        </div>
      </div>
    );
  }

  // Value Accessors with Fallbacks
  const getVal = (paths, fallback = 'उपलब्ध नहीं') => {
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

  // Group Details
  const personalInfo = [
    { label: 'पूरा नाम (Full Name)', value: getVal(['applicant_name', 'name', 'full_name', 'holder.full_name']) },
    { label: 'जन्म तिथि (Date of Birth)', value: getVal(['date_of_birth', 'dob', 'holder.date_of_birth', 'year_of_birth']) },
    { label: 'लिंग (Gender)', value: getVal(['gender', 'holder.gender']) },
    { label: 'पिता/पति का नाम (Father/Spouse Name)', value: getVal(['father_name', 'spouse_name', 'holder.father_name']) },
    { label: 'मोबाइल नंबर (Phone)', value: appData?.phone || getVal(['phone', 'mobile_number']) },
    { label: 'ईमेल आईडी (Email)', value: getVal(['email', 'email_id']) },
  ];

  const aadhaarInfo = [
    { label: 'आधार नंबर (Aadhaar Number)', value: getVal(['aadhaar_number']) },
    { label: 'पता (Address)', value: getVal(['address.address_line', 'address.full_address', 'address.state']) },
    { label: 'पिन कोड (Pincode)', value: getVal(['address.pincode', 'address.pin_code']) },
  ];

  const panInfo = [
    { label: 'पैन नंबर (PAN Number)', value: getVal(['pan_number']) },
    { label: 'क्या पैन सत्यापित है? (PAN Verified?)', value: getVal(['pan_confirmed']) },
  ];

  const socioEconomicInfo = [
    { label: 'वैवाहिक स्थिति (Marital Status)', value: getVal(['marital_status']) },
    { label: 'परिवार के सदस्य (Family Members)', value: getVal(['number_of_family_members', 'family_members']) },
    { label: 'धर्म (Religion)', value: getVal(['religion']) },
    { label: 'जाति (Caste Category)', value: getVal(['caste_category', 'social_category']) },
    { label: 'शैक्षिक योग्यता (Education)', value: getVal(['educational_qualification', 'education']) },
    { label: 'कुल संपत्ति (Net Worth)', value: getVal(['net_worth']) },
  ];

  const financeInfo = [
    { label: 'व्यवसाय का प्रकार (Occupation)', value: getVal(['occupation', 'occupation_type', 'business_type']) },
    { label: 'व्यवसाय की प्रकृति (Nature of Business)', value: getVal(['nature_of_business']) },
    { label: 'मासिक बिक्री (Monthly Revenue)', value: getVal(['monthly_revenue', 'business_revenue', 'business_details.monthly_revenue', 'annual_income']) },
    { label: 'मासिक लाभ (Net Profit)', value: getVal(['monthly_profit', 'business_details.monthly_profit']) },
    { label: 'स्टॉक/इन्वेंट्री (Inventory)', value: getVal(['inventory_amount', 'business_details.inventory_amount']) },
  ];

  const udyamInfo = [
    { label: 'उद्यम नंबर (Udyam Number)', value: getVal(['udyam_number']) },
    { label: 'उद्यम का नाम (Enterprise Name)', value: getVal(['enterprise_name']) },
    { label: 'पंजीकरण तिथि (Registration Date)', value: getVal(['date_of_registration', 'date_of_commencement']) },
  ];

  const bankInfo = [
    { label: 'खाता नंबर (Account Number)', value: getVal(['account_number']) },
    { label: 'बैंक का नाम (Bank Name)', value: getVal(['bank_name']) },
    { label: 'IFSC कोड (IFSC Code)', value: getVal(['ifsc_code']) },
  ];

  const renderCard = (title, icon, data) => {
    // Only render if at least one field is available
    const hasData = data.some(d => d.value && d.value !== 'उपलब्ध नहीं' && d.value !== '{}');
    if (!hasData) return null;

    return (
      <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '18px', padding: '24px' }}>
        <h3 style={{ fontSize: '1.15rem', fontWeight: 600, marginBottom: '20px', color: '#a7b4fc', display: 'flex', alignItems: 'center', gap: '8px' }}>
          {icon} {title}
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
          {data.map((item, idx) => (
            <div key={idx} style={{ paddingBottom: '12px', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginBottom: '4px' }}>{item.label}</div>
              <div style={{ fontSize: '0.9375rem', fontWeight: 600 }}>{item.value}</div>
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div style={{ background: '#090a10', color: '#fff', minHeight: '100vh', fontFamily: 'sans-serif' }}>
      {/* Header */}
      <nav style={{ padding: '20px 40px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255, 255, 255, 0.08)', background: 'rgba(9, 10, 15, 0.7)', backdropFilter: 'blur(20px)', position: 'sticky', top: 0, zIndex: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <Link href="/dashboard" style={{ textDecoration: 'none', color: '#a0aec0', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.875rem' }}>
            <span>← डैशबोर्ड पर लौटें</span>
          </Link>
          <span style={{ color: 'rgba(255,255,255,0.2)' }}>|</span>
          <span style={{ fontSize: '1rem', fontWeight: 600, color: '#fff' }}>बैंक फॉर्म विवरण (SBI Saving Account Details)</span>
        </div>
        <div style={{ fontSize: '0.8125rem', color: '#7c3aed', background: 'rgba(124, 58, 237, 0.1)', padding: '6px 12px', borderRadius: '12px', border: '1px solid rgba(124, 58, 237, 0.2)' }}>
          {appData?.application_id || 'लंबित'}
        </div>
      </nav>

      {/* Main Container */}
      <div style={{ maxWidth: '1400px', margin: '0 auto', padding: '40px', display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: '40px' }}>
        
        {/* Left Side: Parameters Grid */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '30px' }}>
          {renderCard('व्यक्तिगत विवरण (Personal Information)', '👤', personalInfo)}
          {renderCard('आधार विवरण (Aadhaar Details)', '🆔', aadhaarInfo)}
          {renderCard('पैन विवरण (PAN Details)', '💳', panInfo)}
          {renderCard('सामाजिक-आर्थिक विवरण (Socio-Economic)', '👨‍👩‍👧', socioEconomicInfo)}
          {renderCard('व्यवसाय और वित्त (Business & Financials)', '💼', financeInfo)}
          {renderCard('उद्यम विवरण (Udyam Details)', '🏢', udyamInfo)}
          {renderCard('बैंक विवरण (Bank Details)', '🏦', bankInfo)}
        </div>

        {/* Right Side: Uploaded Documents */}
        <div>
          <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '18px', padding: '24px', position: 'sticky', top: '100px' }}>
            <h3 style={{ fontSize: '1.15rem', fontWeight: 600, marginBottom: '24px', color: '#a7b4fc' }}>
              📄 अपलोड किए गए दस्तावेज़ ({documents.length})
            </h3>
            
            {documents.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '40px 20px', color: '#64748b' }}>
                <span style={{ fontSize: '2rem', display: 'block', marginBottom: '10px' }}>📁</span>
                कोई दस्तावेज़ अपलोड नहीं किया गया है
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                {documents.map((doc, idx) => (
                  <div key={idx} style={{ background: 'rgba(255, 255, 255, 0.02)', border: '1px solid rgba(255, 255, 255, 0.05)', borderRadius: '14px', padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.875rem', fontWeight: 600, color: '#e2e8f0' }}>
                        {doc.doc_type.replace(/_/g, ' ')}
                      </span>
                      <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                        {doc.name}
                      </span>
                    </div>
                    {/* Render Image preview securely */}
                    <div style={{ width: '100%', height: '200px', borderRadius: '10px', overflow: 'hidden', background: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid rgba(255, 255, 255, 0.08)' }}>
                      <img 
                        src={doc.preview_url || doc.key} 
                        alt={doc.doc_type}
                        style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
                        onError={(e) => {
                          e.target.style.display = 'none';
                          e.target.nextSibling.style.display = 'block';
                        }}
                      />
                      <div style={{ display: 'none', color: '#64748b', fontSize: '0.875rem' }}>
                        [दस्तावेज़ लोड करने में असमर्थ]
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
