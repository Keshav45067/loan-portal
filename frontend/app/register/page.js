'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import AuthGuard, { useAuth } from '../components/AuthGuard';
import styles from './register.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

const FALLBACK_STATES = ['Jharkhand'];

function RegisterContent() {
  const router = useRouter();
  const { token, sessionId } = useAuth();
  const [form, setForm] = useState({
    state: '',
    district: '',
    block: '',
    panchayat: '',
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
        console.warn('Failed to fetch dynamic states, using fallback', err);
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
          setDistricts([]);
        }
      } catch (err) {
        console.warn('Failed to fetch dynamic districts', err);
        setDistricts([]);
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
          setBlocks([]);
        }
      } catch (err) {
        console.warn('Failed to fetch dynamic blocks', err);
        setBlocks([]);
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
          setPanchayats([]);
        }
      } catch (err) {
        console.warn('Failed to fetch dynamic panchayats', err);
        setPanchayats([]);
      }
    }
    fetchPanchayats();
  }, [form.block]);

  const canSubmit = () => {
    if (!form.state || !form.district || !form.block) return false;
    // If block has panchayats in DB, panchayat is required. If block has 0 panchayats (e.g. Dhanbad), it is optional.
    if (panchayats.length > 0 && !form.panchayat) return false;
    return true;
  };


  const handleSubmit = async () => {
    if (!canSubmit()) return;
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
          rseti: '',
          skip: false,
          cadre_id: ''
        })
      });
      
      const data = await res.json();
      setLoading(false);

      if (data.success) {
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
  };

  return (
    <div className={styles.container}>
      {/* Header */}
      <header className={styles.header}>
        <button className="btn btn-ghost" onClick={() => router.push('/')} id="back-btn" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <path d="M19 12H5M12 19l-7-7 7-7" />
          </svg>
          Back
        </button>
        <div className={styles.headerCenter}>
          <span className="badge badge-accent">Applicant Registration</span>
        </div>
        <div style={{ width: 80 }} />
      </header>

      {/* Main Content */}
      <main className={styles.main}>
        {error && <p className={styles.error} style={{ color: 'var(--accent-danger)', textAlign: 'center', marginBottom: '16px' }}>{error}</p>}

        <div className={`${styles.stepContent} animate-in`}>
          <div className={styles.stepHeader}>
            <h2>Select Your Location</h2>
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
              <label className={styles.selectLabel}>
                Panchayat {form.block && panchayats.length === 0 ? '(Not Applicable)' : ''}
              </label>
              <select
                id="panchayat-select"
                className={`input ${styles.select}`}
                value={form.panchayat}
                onChange={e => setForm({ ...form, panchayat: e.target.value })}
                disabled={!form.block || panchayats.length === 0}
              >
                {panchayats.length > 0 ? (
                  <>
                    <option value="">Select Panchayat...</option>
                    {panchayats.map(p => <option key={p} value={p}>{p}</option>)}
                  </>
                ) : (
                  <option value="">{form.block ? 'N/A (Direct Block Registration)' : 'Select Block First'}</option>
                )}
              </select>
            </div>

          </div>
        </div>
      </main>

      {/* Footer with CTA */}
      <footer className={styles.footer}>
        <button
          id="submit-btn"
          className="btn btn-primary btn-lg"
          onClick={handleSubmit}
          disabled={!canSubmit() || loading}
          style={{ width: '100%', maxWidth: 400 }}
        >
          {loading ? (
            <span className={styles.spinner} />
          ) : (
            <>
              Complete Registration
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
