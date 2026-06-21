'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import styles from './register.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

const STATES = ['Jharkhand', 'Bihar', 'Uttar Pradesh', 'Madhya Pradesh', 'Rajasthan', 'Chhattisgarh'];
const DISTRICTS = {
  'Jharkhand': ['Ranchi', 'Dumka', 'Deoghar', 'Bokaro', 'Giridih'],
  'Bihar': ['Patna', 'Gaya', 'Muzaffarpur', 'Bhagalpur', 'Nalanda'],
};
const BLOCKS = {
  'Ranchi': ['Kanke', 'Namkum', 'Ratu', 'Bundu', 'Tamar'],
  'Dumka': ['Dumka Sadar', 'Masalia', 'Jama', 'Shikaripara'],
  'Deoghar': ['Deoghar Sadar', 'Devipur', 'Mohanpur'],
  'Bokaro': ['Chas', 'Bermo', 'Jaridih'],
  'Giridih': ['Giridih Sadar', 'Gandey', 'Pirtandr'],
  'Patna': ['Patna Sadar', 'Phulwari Sharif', 'Digha'],
  'Gaya': ['Gaya Sadar', 'Bodhgaya', 'Manpur'],
  'Muzaffarpur': ['Mushahari', 'Kanti', 'Minapur'],
  'Bhagalpur': ['Jagdishpur', 'Nathnagar', 'Sabhour'],
  'Nalanda': ['Biharsharif', 'Rajgir', 'Harnaut'],
};
const PANCHAYATS = {
  'Kanke': ['Kanke Gram', 'Hatu Gram', 'Kuchu Gram', 'Tupudana'],
  'Namkum': ['Namkum Gram', 'Sukurhutu', 'Jonha', 'Pithoria'],
  'Ratu': ['Ratu Gram', 'Kathitand'],
  'Bundu': ['Bundu Gram', 'Taimara'],
  'Tamar': ['Tamar Gram', 'Saligutu'],
  'Dumka Sadar': ['Dumka Gram', 'Dudhani'],
  'Masalia': ['Masalia Gram', 'Kundahit'],
  'Jama': ['Jama Gram', 'Bhadwari'],
  'Shikaripara': ['Shikaripara Gram', 'Pinargaria'],
  'Deoghar Sadar': ['Deoghar Gram', 'Jasidih'],
  'Devipur': ['Devipur Gram', 'Rikhiya'],
  'Mohanpur': ['Mohanpur Gram', 'Tapovan'],
  'Chas': ['Chas Gram', 'Chira Chas'],
  'Bermo': ['Phusro', 'Bermo Gram'],
  'Jaridih': ['Jaridih Gram', 'Tenughat'],
  'Giridih Sadar': ['Giridih Gram', 'Barki Saraiya'],
  'Gandey': ['Gandey Gram', 'Ahilyapur'],
  'Pirtandr': ['Pirtandr Gram', 'Madhuban'],
  'Patna Sadar': ['Patna Gram', 'Anisabad'],
  'Phulwari Sharif': ['Phulwari Gram', 'Khagaul'],
  'Digha': ['Digha Gram', 'Kurji'],
  'Gaya Sadar': ['Gaya Gram', 'Delha'],
  'Bodhgaya': ['Bodhgaya Gram', 'Mastipur'],
  'Manpur': ['Manpur Gram', 'Buniadganj'],
  'Mushahari': ['Mushahari Gram', 'Bela'],
  'Kanti': ['Kanti Gram', 'Kaparpura'],
  'Minapur': ['Minapur Gram', 'Panapur'],
  'Jagdishpur': ['Jagdishpur Gram', 'Babupur'],
  'Nathnagar': ['Nathnagar Gram', 'Champanagar'],
  'Sabhour': ['Sabhour Gram', 'Mamalkha'],
  'Biharsharif': ['Biharsharif Gram', 'Sohtarai'],
  'Rajgir': ['Rajgir Gram', 'Mora'],
  'Harnaut': ['Harnaut Gram', 'Cheran'],
};

const RSETIS = ['RSETI Ranchi', 'RSETI Dumka', 'RSETI Deoghar', 'RSETI Bokaro'];

export default function RegisterPage() {
  const router = useRouter();
  const [step, setStep] = useState(0); // 0: Location, 1: RSETI
  const [form, setForm] = useState({
    state: '',
    district: '',
    block: '',
    panchayat: '',
    rseti: '',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [token, setToken] = useState('');
  const [sessionId, setSessionId] = useState('');

  useEffect(() => {
    const savedToken = localStorage.getItem('token');
    const savedSessionId = localStorage.getItem('session_id');
    if (!savedToken || !savedSessionId) {
      router.push('/');
    } else {
      setToken(savedToken);
      setSessionId(savedSessionId);
    }
  }, [router]);

  const steps = [
    { label: 'स्थान चुनें', icon: '📍' },
    { label: 'RSETI केंद्र', icon: '🏛️' },
  ];

  const districts = DISTRICTS[form.state] || [];
  const blocks = BLOCKS[form.district] || [];
  const panchayats = PANCHAYATS[form.block] || [];

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
          localStorage.setItem('application_id', data.application_id);
          router.push('/documents');
        } else {
          setError(data.error || 'पंजीकरण सहेजने में विफल। कृपया पुन: प्रयास करें।');
        }
      } catch (err) {
        setLoading(false);
        setError('सर्वर से कनेक्ट करने में विफल।');
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
        <button className="btn btn-ghost" onClick={handleBack} id="back-btn">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <path d="M19 12H5M12 19l-7-7 7-7" />
          </svg>
          वापस
        </button>
        <div className={styles.headerCenter}>
          <span className="badge badge-accent">पंजीकरण</span>
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
              <h2>स्थान चुनें</h2>
              <p className="text-muted">राज्य → जिला → ब्लॉक → पंचायत</p>
            </div>
            <div className={styles.locationGrid}>
              <div className={styles.selectWrap}>
                <label className={styles.selectLabel}>राज्य</label>
                <select
                  id="state-select"
                  className={`input ${styles.select}`}
                  value={form.state}
                  onChange={e => setForm({ ...form, state: e.target.value, district: '', block: '', panchayat: '' })}
                >
                  <option value="">चुनें...</option>
                  {STATES.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div className={styles.selectWrap}>
                <label className={styles.selectLabel}>जिला</label>
                <select
                  id="district-select"
                  className={`input ${styles.select}`}
                  value={form.district}
                  onChange={e => setForm({ ...form, district: e.target.value, block: '', panchayat: '' })}
                  disabled={!form.state}
                >
                  <option value="">चुनें...</option>
                  {districts.map(d => <option key={d} value={d}>{d}</option>)}
                </select>
              </div>
              <div className={styles.selectWrap}>
                <label className={styles.selectLabel}>ब्लॉक</label>
                <select
                  id="block-select"
                  className={`input ${styles.select}`}
                  value={form.block}
                  onChange={e => setForm({ ...form, block: e.target.value, panchayat: '' })}
                  disabled={!form.district}
                >
                  <option value="">चुनें...</option>
                  {blocks.map(b => <option key={b} value={b}>{b}</option>)}
                </select>
              </div>
              <div className={styles.selectWrap}>
                <label className={styles.selectLabel}>पंचायत</label>
                <select
                  id="panchayat-select"
                  className={`input ${styles.select}`}
                  value={form.panchayat}
                  onChange={e => setForm({ ...form, panchayat: e.target.value })}
                  disabled={!form.block}
                >
                  <option value="">चुनें...</option>
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
              <h2>RSETI चुनें</h2>
              <p className="text-muted">आपका RSETI केंद्र कौन सा है?</p>
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
              पंजीकरण पूरा करें
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            </>
          ) : (
            <>
              आगे बढ़ें
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
