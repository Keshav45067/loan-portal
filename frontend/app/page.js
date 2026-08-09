'use client';

import { useState, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import styles from './page.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

const COUNTRY_CODES = [
  { name: 'India', code: '+91', flag: '🇮🇳', iso: 'IN' },
  { name: 'Armenia', code: '+374', flag: '🇦🇲', iso: 'AM' },
  { name: 'United States', code: '+1', flag: '🇺🇸', iso: 'US' },
  { name: 'United Kingdom', code: '+44', flag: '🇬🇧', iso: 'GB' },
  { name: 'France', code: '+33', flag: '🇫🇷', iso: 'FR' },
  { name: 'Canada', code: '+1', flag: '🇨🇦', iso: 'CA' },
  { name: 'Australia', code: '+61', flag: '🇦🇺', iso: 'AU' },
  { name: 'Germany', code: '+49', flag: '🇩🇪', iso: 'DE' },
  { name: 'Singapore', code: '+65', flag: '🇸🇬', iso: 'SG' },
  { name: 'United Arab Emirates', code: '+971', flag: '🇦🇪', iso: 'AE' },
  { name: 'Saudi Arabia', code: '+966', flag: '🇸🇦', iso: 'SA' },
  { name: 'Japan', code: '+81', flag: '🇯🇵', iso: 'JP' },
  { name: 'Brazil', code: '+55', flag: '🇧🇷', iso: 'BR' },
  { name: 'Nepal', code: '+977', flag: '🇳🇵', iso: 'NP' },
  { name: 'Bangladesh', code: '+880', flag: '🇧🇩', iso: 'BD' },
  { name: 'Sri Lanka', code: '+94', flag: '🇱🇰', iso: 'LK' },
];

export default function LoginPage() {
  const router = useRouter();
  const [step, setStep] = useState('phone'); // 'phone' | 'otp'
  const [phone, setPhone] = useState('');
  const [selectedCountry, setSelectedCountry] = useState(COUNTRY_CODES[0]); // Default to India (+91)
  const [isCountryDropdownOpen, setIsCountryDropdownOpen] = useState(false);
  const [countrySearch, setCountrySearch] = useState('');
  const dropdownRef = useRef(null);
  const searchInputRef = useRef(null);

  const [otp, setOtp] = useState(['', '', '', '']);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [countdown, setCountdown] = useState(0);
  const otpRefs = useRef([]);

  // Auto-redirect to dashboard if user is already logged in
  useEffect(() => {
    const token = localStorage.getItem('token');
    const sessionId = localStorage.getItem('session_id');
    if (token && sessionId) {
      router.push('/dashboard');
    }
  }, [router]);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsCountryDropdownOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Auto focus search input when dropdown opens
  useEffect(() => {
    if (isCountryDropdownOpen && searchInputRef.current) {
      searchInputRef.current.focus();
    }
  }, [isCountryDropdownOpen]);

  const filteredCountries = COUNTRY_CODES.filter(c => 
    c.name.toLowerCase().includes(countrySearch.toLowerCase()) || 
    c.code.includes(countrySearch)
  );

  // OTP countdown
  useEffect(() => {
    if (countdown <= 0) return;
    const timer = setInterval(() => setCountdown(c => c - 1), 1000);
    return () => clearInterval(timer);
  }, [countdown]);

  const handleSendOtp = async (e) => {
    if (e) e.preventDefault();
    if (phone.length < 7 || phone.length > 15) {
      setError('Please enter a valid mobile number');
      return;
    }
    setLoading(true);
    setError('');

    const fullPhone = `${selectedCountry.code}${phone}`;

    try {
      const res = await fetch(`${API_BASE_URL}/api/auth/send-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: fullPhone }),
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

    const fullPhone = `${selectedCountry.code}${phone}`;

    try {
      const res = await fetch(`${API_BASE_URL}/api/auth/verify-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: fullPhone, otp: otpStr }),
      });
      const data = await res.json();
      setLoading(false);

        if (data.success) {
          toast.success('OTP verified successfully!');
          localStorage.setItem('token', data.token);
          localStorage.setItem('session_id', data.session_id);

          const params = new URLSearchParams(window.location.search);
          if (params.get('capture') === 'true') {
            router.push('/capture');
          } else if (data.registration_completed === false) {
            toast.info('Please complete your location details to finish registration.');
            router.push('/register');
          } else {
            router.push('/dashboard');
          }
        } else {
          setError(data.error || 'Invalid OTP. Please try again.');
          toast.error(data.error || 'Invalid OTP. Please try again.');
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
      {/* Left Panel — Augmen Branding & Mudra Loan Showcase */}
      <div className={styles.brandPanel}>
        <div className={styles.brandContent}>
          
          {/* Augmen Official Logo & Header */}
          <div className={styles.brandHeader}>
            <div className={styles.logoWrapper}>
              <svg viewBox="0 0 36 40" fill="none" className={styles.augmenLogoSvg}>
                <path d="M18 0L36 34H27L18 16L9 34H0L18 0Z" fill="url(#augmen-grad)" />
                <path d="M18 10L25 25H11L18 10Z" fill="#090d16" stroke="#4a78ff" strokeWidth="0.8" />
                <circle cx="18" cy="18" r="2" fill="#4a78ff" />
                <defs>
                  <linearGradient id="augmen-grad" x1="0" y1="0" x2="36" y2="40">
                    <stop stopColor="#4a78ff" />
                    <stop offset="1" stopColor="#22c968" />
                  </linearGradient>
                </defs>
              </svg>
              <span className={styles.brandName}>AUGMEN</span>
            </div>
            <span className={styles.badgePill}>
              <span className={styles.badgePulse}></span>
              Micro-Loans Portal
            </span>
          </div>

          <h1 className={styles.brandTitle}>
            Conversational <br />
            <span className={styles.textGradient}>Micro-Loan</span> Portal
          </h1>

          <p className={styles.brandSubtitle}>
            Apply for micro-loans up to ₹10 Lakhs through a natural voice conversation in your preferred language. Powered by Augmen Conversational AI.
          </p>

          {/* Mudra Loan Feature Showcase */}
          <div className={styles.features}>
            <div className={`${styles.featureItem} animate-in animate-delay-1`}>
              <div className={styles.featureIcon}>🎙️</div>
              <div>
                <p className={styles.featureTitle}>Voice-Guided Micro-Loan Application</p>
                <p className={styles.featureDesc}>Speak naturally in Hindi or English. Answer simple questions about your business with zero typing.</p>
              </div>
            </div>

            <div className={`${styles.featureItem} animate-in animate-delay-2`}>
              <div className={styles.featureIcon}>🪪</div>
              <div>
                <p className={styles.featureTitle}>Instant Document Verification</p>
                <p className={styles.featureDesc}>Scan Aadhaar, PAN, Voter ID, & Udyam Registration. Details are extracted and validated automatically.</p>
              </div>
            </div>

            <div className={`${styles.featureItem} animate-in animate-delay-3`}>
              <div className={styles.featureIcon}>⚡</div>
              <div>
                <p className={styles.featureTitle}>Automated Credit & Financial Assessment</p>
                <p className={styles.featureDesc}>Real-time computation of working capital, inventory, and loan eligibility score for instant disbursement approval.</p>
              </div>
            </div>
          </div>

          {/* Trust Badges Footer */}
          <div className={styles.trustFooter}>
            <div className={styles.trustItem}>
              <span className={styles.trustCheck}>✓</span>
              <span>Shishu, Kishor & Tarun Schemes</span>
            </div>
            <div className={styles.trustDivider} />
            <div className={styles.trustItem}>
              <span className={styles.trustCheck}>✓</span>
              <span>Bank-Grade Encryption</span>
            </div>
            <div className={styles.trustDivider} />
            <div className={styles.trustItem}>
              <span className={styles.trustCheck}>✓</span>
              <span>ISO 27001 Certified</span>
            </div>
          </div>

        </div>

        {/* Floating Glowing Orbs */}
        <div className={styles.brandOrb1} aria-hidden="true" />
        <div className={styles.brandOrb2} aria-hidden="true" />
      </div>

      {/* Right Panel — Mobile Auth Form */}
      <div className={styles.formPanel}>
        <div className={styles.formCard}>
          {step === 'phone' ? (
            <form onSubmit={handleSendOtp} className={`${styles.form} animate-in`}>
              <div className={styles.formHeader}>
                <div className={styles.formBadge}>Apply Now</div>
                <h2>Start Your Micro-Loan Application 🚀</h2>
                <p className="text-muted">Enter your 10-digit mobile number to proceed</p>
              </div>

              <div className={styles.phoneInput} ref={dropdownRef}>
                <div className={styles.phonePrefixWrapper}>
                  <button
                    type="button"
                    className={styles.phonePrefixBtn}
                    onClick={() => setIsCountryDropdownOpen(!isCountryDropdownOpen)}
                    aria-label="Select Country Code"
                  >
                    <span>{selectedCountry.flag}</span>
                    <span>{selectedCountry.code}</span>
                    <span className={styles.dropdownArrow}>{isCountryDropdownOpen ? '▲' : '▼'}</span>
                  </button>

                  {isCountryDropdownOpen && (
                    <div className={styles.countryDropdown}>
                      <div className={styles.countrySearchWrapper}>
                        <input
                          ref={searchInputRef}
                          type="text"
                          className={styles.countrySearchInput}
                          placeholder="Search country or code..."
                          value={countrySearch}
                          onChange={e => setCountrySearch(e.target.value)}
                        />
                      </div>
                      <div className={styles.countryList}>
                        {filteredCountries.length > 0 ? (
                          filteredCountries.map(c => (
                            <button
                              key={`${c.iso}-${c.code}`}
                              type="button"
                              className={`${styles.countryOption} ${selectedCountry.iso === c.iso ? styles.countryOptionActive : ''}`}
                              onClick={() => {
                                setSelectedCountry(c);
                                setIsCountryDropdownOpen(false);
                                setCountrySearch('');
                              }}
                            >
                              <span className={styles.countryFlag}>{c.flag}</span>
                              <span className={styles.countryName}>{c.name}</span>
                              <span className={styles.countryDialCode}>{c.code}</span>
                            </button>
                          ))
                        ) : (
                          <div className={styles.noCountryFound}>No country found</div>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                <input
                  id="phone-input"
                  type="tel"
                  className="input"
                  placeholder="98765 43210"
                  maxLength={15}
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
                disabled={loading || phone.length < 7}
                style={{ width: '100%' }}
              >
                {loading ? (
                  <span className={styles.spinner} />
                ) : (
                  <>
                    Send OTP Verification Code
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M5 12h14M12 5l7 7-7 7" />
                    </svg>
                  </>
                )}
              </button>

              <p className={styles.terms}>
                By logging in, you agree to our <a href="#">Terms of Service</a> & <a href="#">Privacy Policy</a>. Data is secured under DPDP guidelines.
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
                  Back to Phone
                </button>
                <h2>Enter OTP Code</h2>
                <p className="text-muted">
                  Code sent to {selectedCountry.code} {phone}
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
                {loading ? <span className={styles.spinner} /> : 'Verify & Begin Application ✓'}
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
