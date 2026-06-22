'use client';

import { useState, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import styles from './page.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export default function LoginPage() {
  const router = useRouter();
  const [step, setStep] = useState('phone'); // 'phone' | 'otp'
  const [phone, setPhone] = useState('');
  const [otp, setOtp] = useState(['', '', '', '']);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [countdown, setCountdown] = useState(0);
  const otpRefs = useRef([]);

  // OTP countdown
  useEffect(() => {
    if (countdown <= 0) return;
    const timer = setInterval(() => setCountdown(c => c - 1), 1000);
    return () => clearInterval(timer);
  }, [countdown]);

  const handleSendOtp = async (e) => {
    if (e) e.preventDefault();
    if (phone.length !== 10) {
      setError('Please enter a valid 10-digit mobile number');
      return;
    }
    setLoading(true);
    setError('');

    try {
      const res = await fetch(`${API_BASE_URL}/api/auth/send-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone }),
      });
      const data = await res.json();
      setLoading(false);

      if (data.success) {
        setStep('otp');
        setCountdown(30);
        setOtp(['', '', '', '']);
        setTimeout(() => otpRefs.current[0]?.focus(), 100);
      } else {
        setError(data.error || 'Failed to send OTP. Please try again.');
      }
    } catch (err) {
      setLoading(false);
      setError('Failed to connect to the server.');
      console.error(err);
    }
  };

  const handleOtpChange = (index, value) => {
    if (!/^\d?$/.test(value)) return;
    const newOtp = [...otp];
    newOtp[index] = value;
    setOtp(newOtp);

    if (value && index < 3) {
      otpRefs.current[index + 1]?.focus();
    }
  };

  const handleOtpKeyDown = (index, e) => {
    if (e.key === 'Backspace' && !otp[index] && index > 0) {
      otpRefs.current[index - 1]?.focus();
    }
  };

  const handleVerifyOtp = async (e) => {
    e.preventDefault();
    const otpStr = otp.join('');
    if (otpStr.length !== 4) {
      setError('Please enter a 4-digit OTP');
      return;
    }
    setLoading(true);
    setError('');

    try {
      const res = await fetch(`${API_BASE_URL}/api/auth/verify-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone, otp: otpStr }),
      });
      const data = await res.json();
      setLoading(false);

      if (data.success) {
        localStorage.setItem('token', data.token);
        localStorage.setItem('session_id', data.session_id);
        localStorage.setItem('phone', phone);

        router.push('/dashboard');
      } else {
        setError(data.error || 'Invalid OTP. Please try again.');
      }
    } catch (err) {
      setLoading(false);
      setError('Failed to connect to the server.');
      console.error(err);
    }
  };

  return (
    <div className={styles.container}>
      {/* Left Panel — Branding */}
      <div className={styles.brandPanel}>
        <div className={styles.brandContent}>
          <div className={styles.logoMark}>
            <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
              <circle cx="24" cy="24" r="24" fill="url(#logo-grad)" />
              <path d="M16 24C16 19.58 19.58 16 24 16V32C19.58 32 16 28.42 16 24Z" fill="white" opacity="0.9" />
              <path d="M24 16C28.42 16 32 19.58 32 24C32 28.42 28.42 32 24 32" stroke="white" strokeWidth="2.5" strokeLinecap="round" opacity="0.6" />
              <circle cx="28" cy="20" r="2" fill="white" opacity="0.8" />
              <defs>
                <linearGradient id="logo-grad" x1="0" y1="0" x2="48" y2="48">
                  <stop stopColor="#4a78ff" />
                  <stop offset="1" stopColor="#7c3aed" />
                </linearGradient>
              </defs>
            </svg>
          </div>
          <h1 className={styles.brandTitle}>
            <span className="text-gradient">Augmen.io</span>
          </h1>
          <p className={styles.brandSubtitle}>
            Conversational Bank Onboarding Demo
          </p>

          <div className={styles.features}>
            <div className={`${styles.featureItem} animate-in animate-delay-1`}>
              <div className={styles.featureIcon}>🎙️</div>
              <div>
                <p className={styles.featureTitle}>Voice-Guided Onboarding</p>
                <p className={styles.featureDesc}>Speak naturally to complete your account opening form.</p>
              </div>
            </div>
            <div className={`${styles.featureItem} animate-in animate-delay-2`}>
              <div className={styles.featureIcon}>🪪</div>
              <div>
                <p className={styles.featureTitle}>Smart Document Extraction</p>
                <p className={styles.featureDesc}>Scan your Aadhaar & PAN. AI automatically extracts verified details.</p>
              </div>
            </div>
            <div className={`${styles.featureItem} animate-in animate-delay-3`}>
              <div className={styles.featureIcon}>⚡</div>
              <div>
                <p className={styles.featureTitle}>Real-time Verification</p>
                <p className={styles.featureDesc}>Your savings account details are processed instantly with zero typing.</p>
              </div>
            </div>
          </div>
        </div>

        {/* Decorative orb */}
        <div className={styles.brandOrb} aria-hidden="true" />
      </div>

      {/* Right Panel — Auth Form */}
      <div className={styles.formPanel}>
        <div className={styles.formCard}>
          {step === 'phone' ? (
            <form onSubmit={handleSendOtp} className={`${styles.form} animate-in`}>
              <div className={styles.formHeader}>
                <h2>Welcome 🚀</h2>
                <p className="text-muted">Enter your mobile number to begin onboarding</p>
              </div>

              <div className={styles.phoneInput}>
                <div className={styles.phonePrefix}>
                  <span>🇮🇳</span>
                  <span>+91</span>
                </div>
                <input
                  id="phone-input"
                  type="tel"
                  className="input"
                  placeholder="98765 43210"
                  maxLength={10}
                  value={phone}
                  onChange={e => setPhone(e.target.value.replace(/\D/g, ''))}
                  autoFocus
                  autoComplete="tel"
                />
              </div>

              {error && <p className={styles.error}>{error}</p>}

              <button
                id="send-otp-btn"
                type="submit"
                className="btn btn-primary btn-lg"
                disabled={loading || phone.length !== 10}
                style={{ width: '100%' }}
              >
                {loading ? (
                  <span className={styles.spinner} />
                ) : (
                  <>
                    Send OTP Code
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M5 12h14M12 5l7 7-7 7" />
                    </svg>
                  </>
                )}
              </button>

              <p className={styles.terms}>
                By continuing, you agree to our <a href="#">Privacy Policy</a> and <a href="#">Terms of Service</a>
              </p>
            </form>
          ) : (
            <form onSubmit={handleVerifyOtp} className={`${styles.form} animate-in`}>
              <div className={styles.formHeader}>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => { setStep('phone'); setOtp(['', '', '', '']); }}
                  style={{ marginBottom: '8px', padding: '4px 0', display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                    <path d="M19 12H5M12 19l-7-7 7-7" />
                  </svg>
                  Back
                </button>
                <h2>Enter OTP Code</h2>
                <p className="text-muted">
                  Sent to +91 {phone.slice(0, 5)} {phone.slice(5)}
                </p>
              </div>

              <div className={styles.otpContainer}>
                {otp.map((digit, i) => (
                  <input
                    key={i}
                    id={`otp-${i}`}
                    ref={el => otpRefs.current[i] = el}
                    type="text"
                    inputMode="numeric"
                    className={`input input-otp ${digit ? styles.otpFilled : ''}`}
                    maxLength={1}
                    value={digit}
                    onChange={e => handleOtpChange(i, e.target.value)}
                    onKeyDown={e => handleOtpKeyDown(i, e)}
                    autoComplete="one-time-code"
                  />
                ))}
              </div>

              {error && <p className={styles.error}>{error}</p>}

              <button
                id="verify-otp-btn"
                type="submit"
                className="btn btn-primary btn-lg"
                disabled={loading || otp.join('').length !== 4}
                style={{ width: '100%' }}
              >
                {loading ? <span className={styles.spinner} /> : 'Verify & Proceed ✓'}
              </button>

              <div className={styles.resend}>
                {countdown > 0 ? (
                  <p className="text-muted text-sm">
                    Resend code in <span className={styles.countdown}>{countdown}</span> seconds
                  </p>
                ) : (
                  <button
                    type="button"
                    className="btn btn-ghost text-sm"
                    onClick={() => handleSendOtp()}
                  >
                    Resend OTP Code
                  </button>
                )}
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
