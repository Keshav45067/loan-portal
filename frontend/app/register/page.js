'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import AuthGuard, { useAuth } from '../components/AuthGuard';
import styles from './register.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

const FALLBACK_STATES = ['Jharkhand', 'Bihar', 'Uttar Pradesh', 'Madhya Pradesh', 'Rajasthan', 'Chhattisgarh'];
const FALLBACK_DISTRICTS = {
  'Jharkhand': ['Ranchi', 'Dumka', 'Deoghar', 'Bokaro', 'Giridih'],
  'Bihar': ['Patna', 'Gaya', 'Muzaffarpur', 'Bhagalpur', 'Nalanda'],
  'Uttar Pradesh': ['Lucknow', 'Varanasi', 'Kanpur', 'Agra'],
  'Madhya Pradesh': ['Bhopal', 'Indore', 'Gwalior'],
  'Rajasthan': ['Jaipur', 'Jodhpur', 'Udaipur'],
  'Chhattisgarh': ['Raipur', 'Bilaspur', 'Durg']
};
const FALLBACK_BLOCKS = {
  'Ranchi': ['Kanke', 'Namkum', 'Ratu', 'Bundu', 'Tamar'],
  'Dumka': ['Dumka Sadar', 'Masalia', 'Jama', 'Shikaripara'],
  'Deoghar': ['Deoghar Sadar', 'Devipur', 'Mohanpur'],
  'Bokaro': ['Chas', 'Bermo', 'Jaridih'],
  'Giridih': ['Giridih Sadar', 'Gandey', 'Pirtandr'],
  'Patna': ['Patna Sadar', 'Phulwari Sharif', 'Digha'],
  'Gaya': ['Gaya Sadar', 'Bodhgaya', 'Manpur']
};
const FALLBACK_PANCHAYATS = {
  'Kanke': ['Kanke Gram', 'Hatu Gram', 'Kuchu Gram', 'Tupudana'],
  'Namkum': ['Namkum Gram', 'Sukurhutu', 'Jonha', 'Pithoria'],
  'Ratu': ['Ratu Gram', 'Kathitand'],
  'Bundu': ['Bundu Gram', 'Taimara'],
  'Tamar': ['Tamar Gram', 'Saligutu'],
  'Dumka Sadar': ['Dumka Gram', 'Dudhani'],
  'Patna Sadar': ['Patna Gram', 'Anisabad']
};

const RSETIS = ['RSETI Ranchi', 'RSETI Dumka', 'RSETI Deoghar', 'RSETI Bokaro'];

function RegisterContent() {
  const router = useRouter();
  const { token, sessionId } = useAuth();
  const [step, setStep] = useState(0); // 0: Location, 1: RSETI
  const [form, setForm] = useState({
    state: '',
    district: '',
    block: '',
    panchayat: '',
    rseti: '',
  });

  // Dynamic Location Lists
  const [states, setStates] = useState(FALLBACK_STATES);
  const [districts, setDistricts] = useState([]);
  const [blocks, setBlocks] = useState([]);
  const [panchayats, setPanchayats] = useState([]);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Fetch States dynamically on mount
  useEffect(() => {
    async function fetchStates() {
      try {
        const res = await fetch(`${API_BASE_URL}/api/applications/location-tree?level=states`);
        const data = await res.json();
        if (data.success && data.items && data.items.length > 0) {
          setStates(data.items.map(item => item.name));
        }
      } catch (err) {
        console.warn('Failed to fetch dynamic states, using fallback list', err);
      }
    }
    fetchStates();
  }, []);

  // Fetch Districts when state changes
  useEffect(() => {
    if (!form.state) {
      setDistricts([]);
      return;
    }
    async function fetchDistricts() {
      try {
        const res = await fetch(`${API_BASE_URL}/api/applications/location-tree?level=districts&parent_id=${encodeURIComponent(form.state)}`);
        const data = await res.json();
        if (data.success && data.items && data.items.length > 0) {
          setDistricts(data.items.map(item => item.name));
        } else {
          setDistricts(FALLBACK_DISTRICTS[form.state] || ['Central District', 'North District', 'South District', 'East District', 'West District']);
        }
      } catch (err) {
        setDistricts(FALLBACK_DISTRICTS[form.state] || ['Central District', 'North District', 'South District', 'East District', 'West District']);
      }
    }
    fetchDistricts();
  }, [form.state]);

  // Fetch Blocks when district changes
  useEffect(() => {
    if (!form.district) {
      setBlocks([]);
      return;
    }
    async function fetchBlocks() {
      try {
        const res = await fetch(`${API_BASE_URL}/api/applications/location-tree?level=blocks&parent_id=${encodeURIComponent(form.district)}`);
        const data = await res.json();
        if (data.success && data.items && data.items.length > 0) {
          setBlocks(data.items.map(item => item.name));
        } else {
          setBlocks(FALLBACK_BLOCKS[form.district] || [`${form.district} Sadar`, `${form.district} North`, `${form.district} South`]);
        }
      } catch (err) {
        setBlocks(FALLBACK_BLOCKS[form.district] || [`${form.district} Sadar`, `${form.district} North`, `${form.district} South`]);
      }
    }
    fetchBlocks();
  }, [form.district]);

  // Fetch Panchayats when block changes
  useEffect(() => {
    if (!form.block) {
      setPanchayats([]);
      return;
    }
    async function fetchPanchayats() {
      try {
        const res = await fetch(`${API_BASE_URL}/api/applications/location-tree?level=panchayats&parent_id=${encodeURIComponent(form.block)}`);
        const data = await res.json();
        if (data.success && data.items && data.items.length > 0) {
          setPanchayats(data.items.map(item => item.name));
        } else {
          setPanchayats(FALLBACK_PANCHAYATS[form.block] || [`${form.block} Gram Panchayat 1`, `${form.block} Gram Panchayat 2`, `${form.block} Gram Panchayat 3`]);
        }
      } catch (err) {
        setPanchayats(FALLBACK_PANCHAYATS[form.block] || [`${form.block} Gram Panchayat 1`, `${form.block} Gram Panchayat 2`, `${form.block} Gram Panchayat 3`]);
      }
    }
    fetchPanchayats();
  }, [form.block]);

  const steps = [
    { label: 'Location', icon: '📍' },
    { label: 'RSETI Center', icon: '🏛️' },
  ];

  const canNext = () => {
    switch (step) {
      case 0: return form.state && form.district && form.block && form.panchayat;
      case 1: return form.rseti;
      default: return false;
    }
  };

  const handleNext = async () => {
    if (step === 0) {
      setStep(1);
    } else {
      setLoading(true);
      setError('');
      try {
        const res = await fetch(`${API_BASE_URL}/api/applications/save-panchayat`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({
            session_id: sessionId,
            state: form.state,
            district: form.district,
            block: form.block,
            panchayat: form.panchayat,
            rseti: form.rseti,
            skip: false,
            cadre_id: ''
          })
        });
        
        const data = await res.json();
        setLoading(false);

        if (data.success) {
          if (data.application_id) {
            localStorage.setItem('application_id', data.application_id);
          }
          toast.success('Registration completed successfully!');
          router.push('/dashboard');
        } else {
          const errMsg = data.error || 'Failed to save registration. Please try again.';
          setError(errMsg);
          toast.error(errMsg);
        }
      } catch (err) {
        setLoading(false);
        setError('Failed to connect to the server.');
        toast.error('Failed to connect to the server.');
        console.error(err);
      }
    }
  };

  const handleBack = () => {
    if (step > 0) setStep(0);
    else router.push('/');
  };

  return (
    <div className={styles.container}>
      {/* Header */}
      <header className={styles.header}>
        <button className="btn btn-ghost" onClick={handleBack} id="back-btn" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <path d="M19 12H5M12 19l-7-7 7-7" />
          </svg>
          Back
        </button>
        <div className={styles.headerCenter}>
          <span className="badge badge-accent">Registration</span>
        </div>
        <div style={{ width: 80 }} />
      </header>

      {/* Progress Bar */}
      <div className={styles.progressBar}>
        <div className={styles.progressFill} style={{ width: `${((step + 1) / 2) * 100}%` }} />
      </div>

      {/* Step Indicators */}
      <div className={styles.stepIndicators}>
        {steps.map((s, i) => (
          <div key={i} className={`${styles.stepDot} ${i <= step ? styles.stepDotActive : ''} ${i === step ? styles.stepDotCurrent : ''}`}>
            <span>{i < step ? '✓' : s.icon}</span>
            <span className={styles.stepDotLabel}>{s.label}</span>
          </div>
        ))}
      </div>

      {/* Content */}
      <main className={styles.main}>
        {error && <p className={styles.error} style={{ color: 'var(--accent-danger)', textAlign: 'center', marginBottom: '16px' }}>{error}</p>}

        {/* Step 0: Location */}
        {step === 0 && (
          <div className={`${styles.stepContent} animate-in`} key="location">
            <div className={styles.stepHeader}>
              <h2>Select Location</h2>
              <p className="text-muted">State ➔ District ➔ Block ➔ Panchayat</p>
            </div>
            <div className={styles.locationGrid}>
              <div className={styles.selectWrap}>
                <label className={styles.selectLabel}>State</label>
                <select
                  id="state-select"
                  className={`input ${styles.select}`}
                  value={form.state}
                  onChange={e => setForm({ ...form, state: e.target.value, district: '', block: '', panchayat: '' })}
                >
                  <option value="">Select State...</option>
                  {states.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div className={styles.selectWrap}>
                <label className={styles.selectLabel}>District</label>
                <select
                  id="district-select"
                  className={`input ${styles.select}`}
                  value={form.district}
                  onChange={e => setForm({ ...form, district: e.target.value, block: '', panchayat: '' })}
                  disabled={!form.state}
                >
                  <option value="">Select District...</option>
                  {districts.map(d => <option key={d} value={d}>{d}</option>)}
                </select>
              </div>
              <div className={styles.selectWrap}>
                <label className={styles.selectLabel}>Block</label>
                <select
                  id="block-select"
                  className={`input ${styles.select}`}
                  value={form.block}
                  onChange={e => setForm({ ...form, block: e.target.value, panchayat: '' })}
                  disabled={!form.district}
                >
                  <option value="">Select Block...</option>
                  {blocks.map(b => <option key={b} value={b}>{b}</option>)}
                </select>
              </div>
              <div className={styles.selectWrap}>
                <label className={styles.selectLabel}>Panchayat</label>
                <select
                  id="panchayat-select"
                  className={`input ${styles.select}`}
                  value={form.panchayat}
                  onChange={e => setForm({ ...form, panchayat: e.target.value })}
                  disabled={!form.block}
                >
                  <option value="">Select Panchayat...</option>
                  {panchayats.map(p => <option key={p} value={p}>{p}</option>)}
                </select>
              </div>
            </div>
          </div>
        )}

        {/* Step 1: RSETI */}
        {step === 1 && (
          <div className={`${styles.stepContent} animate-in`} key="rseti">
            <div className={styles.stepHeader}>
              <h2>Choose RSETI Center</h2>
              <p className="text-muted">Select your training/onboarding center</p>
            </div>
            <div className={styles.optionGrid}>
              {RSETIS.map(r => (
                <button
                  key={r}
                  id={`rseti-${r.replace(/\s/g, '-')}`}
                  className={`${styles.optionCard} ${form.rseti === r ? styles.optionSelected : ''}`}
                  onClick={() => setForm({ ...form, rseti: r })}
                >
                  <span className={styles.optionIcon}>🏛️</span>
                  <span>{r}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </main>

      {/* Footer with CTA */}
      <footer className={styles.footer}>
        <button
          id="next-btn"
          className="btn btn-primary btn-lg"
          onClick={handleNext}
          disabled={!canNext() || loading}
          style={{ width: '100%', maxWidth: 400 }}
        >
          {loading ? (
            <span className={styles.spinner} />
          ) : step === 1 ? (
            <>
              Complete Registration
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            </>
          ) : (
            <>
              Continue
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            </>
          )}
        </button>
      </footer>
    </div>
  );
}

export default function RegisterPage() {
  return (
    <AuthGuard>
      <RegisterContent />
    </AuthGuard>
  );
}
