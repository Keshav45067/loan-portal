'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import styles from './sbi-report.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export default function SbiReportPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState({});

  useEffect(() => {
    const fetchSessionData = async () => {
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
        const json = await res.json();
        if (json.extracted_data) {
          setData(json.extracted_data);
        }
      } catch (err) {
        console.error('Failed to fetch sbi data:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchSessionData();
  }, [router]);

  if (loading) {
    return <div style={{ display: 'flex', justifyContent: 'center', marginTop: '100px' }}><h2>Loading SBI Form Data...</h2></div>;
  }

  // Fallbacks for display
  const val = (key) => data[key] || '';
  
  // Handling nested aadhaar holder
  let aadhaarName = '';
  let dob = '';
  let gender = '';
  let aadhaarNo = val('aadhaar_number');
  if (data.holder) {
     aadhaarName = data.holder.full_name || '';
     dob = data.holder.date_of_birth || '';
     gender = data.holder.gender || '';
  }
  
  // Handling nested address
  let addressStr = '';
  if (data.address) {
     addressStr = `${data.address.house || ''} ${data.address.street || ''} ${data.address.locality || ''} ${data.address.district || ''} ${data.address.state || ''} ${data.address.pincode || ''}`;
  }

  return (
    <div className={styles.container}>
      <div className={styles.headerRow}>
        <div className={styles.bankLogo}>ABC BANK</div>
        <div className={styles.formTitle}>Savings Bank Account Opening Form</div>
        <div className={styles.photoBox}>
          {data.photo ? <img src={data.photo} alt="Applicant" /> : 'Photo'}
        </div>
      </div>

      <div className={styles.section}>
        <div className={styles.sectionHeader}>A. Personal Details</div>
        <div className={styles.row}>
          <div className={styles.col}>
            <div className={styles.label}>1. Full Name</div>
            <div className={styles.value}>{aadhaarName || val('full_name')}</div>
          </div>
          <div className={styles.col}>
            <div className={styles.label}>2. Father's/Husband's Name</div>
            <div className={styles.value}>{val('father_name')}</div>
          </div>
        </div>
        <div className={styles.row}>
          <div className={styles.col}>
            <div className={styles.label}>3. Date of Birth</div>
            <div className={styles.value}>{dob}</div>
          </div>
          <div className={styles.col}>
            <div className={styles.label}>4. Gender</div>
            <div className={styles.value}>{gender}</div>
          </div>
          <div className={styles.col}>
            <div className={styles.label}>5. Marital Status</div>
            <div className={styles.value}>{val('marital_status')}</div>
          </div>
        </div>
        <div className={styles.row}>
          <div className={styles.col}>
            <div className={styles.label}>6. Nationality</div>
            <div className={styles.value}>{val('nationality')}</div>
          </div>
          <div className={styles.col}>
            <div className={styles.label}>7. No. of Dependents</div>
            <div className={styles.value}>{val('dependents_count')}</div>
          </div>
        </div>
      </div>

      <div className={styles.section}>
        <div className={styles.sectionHeader}>B. Identification & Contact</div>
        <div className={styles.row}>
          <div className={styles.col}>
            <div className={styles.label}>8. PAN Number</div>
            <div className={styles.value}>{val('pan_number')}</div>
          </div>
          <div className={styles.col}>
            <div className={styles.label}>9. Aadhaar Number</div>
            <div className={styles.value}>{aadhaarNo}</div>
          </div>
        </div>
        <div className={styles.row}>
          <div className={styles.col}>
            <div className={styles.label}>10. Mobile Number</div>
            <div className={styles.value}>{val('mobile_number')}</div>
          </div>
          <div className={styles.col}>
            <div className={styles.label}>11. Email ID</div>
            <div className={styles.value}>{val('email_id')}</div>
          </div>
        </div>
        <div className={styles.row}>
          <div className={styles.col}>
            <div className={styles.label}>12. Aadhaar Address</div>
            <div className={styles.value}>{addressStr}</div>
          </div>
        </div>
        <div className={styles.row}>
          <div className={styles.col}>
            <div className={styles.label}>13. Correspondence Address</div>
            <div className={styles.value}>{val('correspondence_address') === 'YES' ? 'Different (Proof attached)' : 'Same as Aadhaar'}</div>
          </div>
        </div>
      </div>

      <div className={styles.section}>
        <div className={styles.sectionHeader}>C. Socio-Economic Details</div>
        <div className={styles.row}>
          <div className={styles.col}>
            <div className={styles.label}>14. Educational Qualification</div>
            <div className={styles.value}>{val('educational_qualification')}</div>
          </div>
          <div className={styles.col}>
            <div className={styles.label}>15. Religion</div>
            <div className={styles.value}>{val('religion')}</div>
          </div>
          <div className={styles.col}>
            <div className={styles.label}>16. Category (Caste)</div>
            <div className={styles.value}>{val('caste_category')}</div>
          </div>
        </div>
        <div className={styles.row}>
          <div className={styles.col}>
            <div className={styles.label}>17. Occupation Type</div>
            <div className={styles.value}>{val('occupation_type')}</div>
          </div>
          <div className={styles.col}>
            <div className={styles.label}>18. Organization / Designation</div>
            <div className={styles.value}>
               {data.organization_name ? `${data.organization_name} / ${val('designation')}` : val('designation')}
            </div>
          </div>
        </div>
        <div className={styles.row}>
          <div className={styles.col}>
            <div className={styles.label}>19. Source of Income</div>
            <div className={styles.value}>
              {Array.isArray(data.source_of_income) 
                ? data.source_of_income.join(', ') 
                : val('source_of_funds') || val('source_of_income')}
            </div>
          </div>
          <div className={styles.col}>
            <div className={styles.label}>20. Annual Income</div>
            <div className={styles.value}>{val('annual_income')}</div>
          </div>
          <div className={styles.col}>
            <div className={styles.label}>21. Net Worth</div>
            <div className={styles.value}>{val('net_worth')}</div>
          </div>
        </div>
        <div className={styles.row}>
          <div className={styles.col}>
            <div className={styles.label}>22. Number of Family Members</div>
            <div className={styles.value}>{val('number_of_family_members')}</div>
          </div>
          <div className={styles.col}>
            <div className={styles.label}>23. Business Type</div>
            <div className={styles.value}>{val('business_type')}</div>
          </div>
          <div className={styles.col}>
            <div className={styles.label}>24. Nature of Business</div>
            <div className={styles.value}>{val('nature_of_business')}</div>
          </div>
        </div>
        <div className={styles.row}>
          <div className={styles.col}>
            <div className={styles.label}>25. Place of Posting</div>
            <div className={styles.value}>{val('place_of_posting')}</div>
          </div>
        </div>
      </div>

      <div className={`${styles.row} noPrint`} style={{ marginTop: '20px', justifyContent: 'center' }}>
         <button onClick={() => window.print()} style={{ padding: '10px 20px', background: '#004b87', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>Print Form</button>
      </div>

    </div>
  );
}
