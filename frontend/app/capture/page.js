'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import styles from './capture.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export default function CaptureLandingPage() {
  const router = useRouter();
  const [token, setToken] = useState('');
  const [schemes, setSchemes] = useState([
    { id: 'loan-application', name: 'Personal Loan Application' },
    { id: 'sbi-account-opening', name: 'SBI Account Opening' }
  ]);
  const [selectedScheme, setSelectedScheme] = useState('loan-application');
  const [language, setLanguage] = useState('en');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const savedToken = localStorage.getItem('token');
    if (!savedToken) {
      router.push('/');
    } else {
      setToken(savedToken);
    }
  }, [router]);

  const handleStart = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);

    try {
      // Create session on gateway
      const res = await fetch(`${API_BASE_URL}/api/capture/start`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          scheme_id: selectedScheme,
          language: language
        })
      });

      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || 'Failed to start session');
      }

      // If successful, navigate to the capture flow
      router.push(`/capture/${selectedScheme}?lang=${language}`);
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  };

  return (
    <div className={styles.container}>
      <h1 className={styles.title}>Smart Document Capture</h1>
      <p className={styles.subtitle}>
        An AI-guided document collection experience. Please select your scheme and preferred language to begin.
      </p>

      <div className={styles.card}>
        <div className={styles.formGroup}>
          <label className={styles.label}>Select Scheme</label>
          <select 
            className={styles.select}
            value={selectedScheme}
            onChange={(e) => setSelectedScheme(e.target.value)}
            disabled={loading}
          >
            {schemes.map(s => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label}>Select Language</label>
          <select 
            className={styles.select}
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            disabled={loading}
          >
            <option value="en">English</option>
            <option value="hi">Hindi (हिंदी)</option>
            <option value="te">Telugu (తెలుగు)</option>
            <option value="bn">Bengali (বাংলা)</option>
            <option value="mr">Marathi (मराठी)</option>
          </select>
        </div>

        {error && (
          <div style={{ color: '#ef4444', marginBottom: '1rem', fontSize: '0.9rem', padding: '0.5rem', background: 'rgba(239,68,68,0.1)', borderRadius: '0.5rem' }}>
            {error}
          </div>
        )}

        <button 
          className={styles.button}
          onClick={handleStart}
          disabled={loading || !token}
        >
          {loading ? 'Starting...' : 'Start Capture'}
        </button>
      </div>
    </div>
  );
}
