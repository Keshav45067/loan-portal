'use client';

import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { toast } from 'sonner';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export function useAuth(options = { redirectTo: '/', requireAuth: true }) {
  const router = useRouter();
  const pathname = usePathname();
  const [loading, setLoading] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [token, setToken] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [phone, setPhone] = useState(null);

  useEffect(() => {
    // Skip check on public routes
    const publicRoutes = ['/'];
    if (publicRoutes.includes(pathname)) {
      setLoading(false);
      return;
    }

    const storedToken = localStorage.getItem('token');
    const storedSessionId = localStorage.getItem('session_id');

    if (!storedToken || !storedSessionId) {
      setAuthenticated(false);
      setLoading(false);
      if (options.requireAuth !== false) {
        toast.error('Please log in with your phone number to access this page.', {
          id: 'auth-required-toast',
          duration: 4000,
        });
        router.replace(options.redirectTo || '/');
      }
      return;
    }

    // Verify token validity against backend API
    const verifyTokenWithBackend = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/applications/${storedSessionId}`, {
          headers: { 'Authorization': `Bearer ${storedToken}` }
        });

        if (res.status === 401 || res.status === 403) {
          console.warn('[AuthGuard] Token expired or invalid on backend. Clearing localStorage credentials.');
          localStorage.removeItem('token');
          localStorage.removeItem('session_id');
          setAuthenticated(false);
          setLoading(false);
          toast.error('Session expired. Please log in again.', {
            id: 'session-expired-toast',
            duration: 4000,
          });
          router.replace(options.redirectTo || '/');
          return;
        }

        setToken(storedToken);
        setSessionId(storedSessionId);
        setAuthenticated(true);
      } catch (err) {
        console.error('[AuthGuard] Verification error:', err);
        setToken(storedToken);
        setSessionId(storedSessionId);
        setAuthenticated(true);
      } finally {
        setLoading(false);
      }
    };

    verifyTokenWithBackend();
  }, [pathname, router, options.redirectTo, options.requireAuth]);

  return { authenticated, loading, token, sessionId, phone };
}

export default function AuthGuard({ children }) {
  const { authenticated, loading } = useAuth({ requireAuth: true, redirectTo: '/' });

  if (loading || !authenticated) {
    return (
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'radial-gradient(circle at center, #0f111a 0%, #050508 100%)',
        color: '#fff',
        fontFamily: 'system-ui, -apple-system, sans-serif'
      }}>
        <div style={{
          width: '48px',
          height: '48px',
          border: '3px solid rgba(255, 255, 255, 0.1)',
          borderTopColor: '#6366f1',
          borderRadius: '50%',
          animation: 'authSpin 0.8s linear infinite',
          marginBottom: '16px'
        }} />
        <style jsx global>{`
          @keyframes authSpin { to { transform: rotate(360deg); } }
        `}</style>
        <p style={{ color: '#94a3b8', fontSize: '0.95rem', fontWeight: 500 }}>
          Verifying security authorization...
        </p>
      </div>
    );
  }

  return children;
}
