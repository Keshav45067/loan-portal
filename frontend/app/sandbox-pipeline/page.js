'use client';

import { useState, useRef } from 'react';
import styles from './sandbox-pipeline.module.css';

const DEFAULT_MANIFEST = {
  "document_id": "doc_aadhaar_002",
  "title": { "English": "Aadhaar Card", "Hindi": "आधार कार्ड" },
  "proves": ["identity", "address"],
  "required_when": "always",
  "expects": ["doc_aadhaar_name", "doc_aadhaar_dob", "doc_aadhaar_gender", "doc_aadhaar_last4", "doc_aadhaar_address"],
  "parts": [
    {
      "id": "front",
      "name": { "English": "Front Side", "Hindi": "सामने का हिस्सा" },
      "title": { "English": "front side", "Hindi": "सामने का हिस्सा" },
      "anchors": ["Government of India", "DOB", "Year of Birth"],
      "provides": ["doc_aadhaar_name", "doc_aadhaar_dob", "doc_aadhaar_gender", "doc_aadhaar_last4"],
      "orientation": "landscape"
    },
    {
      "id": "back",
      "name": { "English": "Back Side", "Hindi": "पीछे का हिस्सा" },
      "title": { "English": "back side", "Hindi": "पीछे का हिस्सा" },
      "anchors": ["Address", "S/O", "D/O", "W/O", "C/O", "PIN"],
      "provides": ["doc_aadhaar_address", "doc_aadhaar_last4"],
      "orientation": "landscape"
    }
  ],
  "sources": [
    { "type": "upload", "formats": ["image/jpeg", "image/png", "application/pdf"], "max_mb": 10 },
    { "type": "camera" }
  ],
  "ocr": { "lang": ["en", "hi"], "table_mode": false },
  "quality": {
    "min_box_confidence": 0.50,
    "min_anchor_hits": 2,
    "blur_var_min": 200,
    "blur_unrecoverable_floor": 30.0
  },
  "quality_policy": {
    "allow_deskew": true,
    "allow_glare_removal": true,
    "allow_contrast_enhancement": true,
    "allow_denoise": false,
    "allow_gamma": true,
    "allow_white_balance": false,
    "allow_sharpen": true,
    "allow_qr_masking": true
  },
  "prompts": {
    "ask_part": {
      "en": "Please capture the {part_title} of your {document_title}.",
      "hi": "कृपया अपने {document_title} का {part_title} कैप्चर करें।"
    },
    "success": {
      "en": "Scanned successfully.",
      "hi": "सफलतापूर्वक स्कैन हो गया।"
    },
    "error_blur": {
      "en": "Image is too blurry. Please hold your phone steady for 2 seconds and capture in a well-lit room.",
      "hi": "छवि बहुत धुंधली है। कृपया अपने फोन को 2 सेकंड के लिए स्थिर रखें और अच्छी रोशनी वाले कमरे में कैप्चर करें।"
    },
    "error_wrong_page": {
      "en": "Wrong document page detected. Please flip the card and capture the correct side.",
      "hi": "गलत दस्तावेज़ पृष्ठ पाया गया। कृपया कार्ड को पलटें और सही साइड कैप्चर करें।"
    },
    "error_low_confidence": {
      "en": "Text details are unreadable. Move to a brighter area, avoid camera shake, and ensure the document is flat.",
      "hi": "अक्षरों का विवरण पढ़ा नहीं जा सका। अधिक रोशनी वाले स्थान पर जाएं, कैमरा हिलने से बचाएं और सुनिश्चित करें कि दस्तावेज़ सीधा और समतल है।"
    }
  }
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export default function SandboxPipelinePage() {
  const [manifestStr, setManifestStr] = useState(JSON.stringify(DEFAULT_MANIFEST, null, 2));
  const [pageId, setPageId] = useState('front');
  const [language, setLanguage] = useState('en');
  const [selectedFile, setSelectedFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  
  // Pipeline state
  const [isInitialized, setIsInitialized] = useState(false);
  const [steps, setSteps] = useState([]); // [{ stageName, imageSrc, metrics, decisions, qualityGate }]
  const [decisions, setDecisions] = useState([]); // Planned decisions remaining
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [sessionId, setSessionId] = useState('');
  
  const fileInputRef = useRef(null);

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      setSelectedFile(file);
      setPreviewUrl(URL.createObjectURL(file));
      // Reset sandbox state
      setIsInitialized(false);
      setSteps([]);
      setDecisions([]);
      setCurrentStepIndex(0);
      setError(null);
    }
  };

  const handleInit = async () => {
    if (!selectedFile) {
      alert("Please upload or select an image file first.");
      return;
    }
    setLoading(true);
    setError(null);

    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("manifest_json", manifestStr);
    formData.append("page_id", pageId);
    formData.append("language", language);

    try {
      const res = await fetch(`${API_BASE_URL}/api/sandbox/pipeline/init`, {
        method: "POST",
        body: formData
      });
      const data = await res.json();
      if (!data.success) {
        setError(data.error || "Initialization failed");
        setLoading(false);
        return;
      }

      // Add step 0 (Original image and metrics)
      setSteps([{
        stageName: "Original Image (Initial Stage)",
        imageSrc: `data:image/jpeg;base64,${data.image_base64}`,
        metrics: data.metrics,
        decisions: data.decisions,
        qualityGate: data.quality_gate,
        logs: data.logs || []
      }]);
      setDecisions(data.decisions);
      setSessionId(data.session_id || '');
      setCurrentStepIndex(0);
      setIsInitialized(true);
    } catch (err) {
      setError(err.message || "Request failed");
    } finally {
      setLoading(false);
    }
  };

  const handleNextStep = async () => {
    if (currentStepIndex >= decisions.length) {
      return; // No more steps
    }
    
    setLoading(true);
    setError(null);

    const nextDecision = decisions[currentStepIndex];
    // Use the base64 from the most recent step
    const currentStepImage = steps[steps.length - 1].imageSrc.replace(/^data:image\/[a-z]+;base64,/, '');

    const isFinal = currentStepIndex === decisions.length - 1;

    try {
      const res = await fetch(`${API_BASE_URL}/api/sandbox/pipeline/step`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_base64: currentStepImage,
          action: nextDecision.action,
          reason: nextDecision.reason,
          manifest_json: manifestStr,
          page_id: pageId,
          language: language,
          is_final_step: isFinal,
          session_id: sessionId
        })
      });

      const data = await res.json();
      if (!data.success) {
        setError(data.error || "Execution step failed");
        setLoading(false);
        return;
      }

      // Append step results
      setSteps(prev => [...prev, {
        stageName: `Step ${currentStepIndex + 1}: ${nextDecision.action}`,
        actionReason: nextDecision.reason,
        imageSrc: `data:image/jpeg;base64,${data.image_base64}`,
        metrics: data.metrics,
        qualityGate: data.quality_gate,
        logs: data.logs || []
      }]);

      setCurrentStepIndex(prev => prev + 1);
    } catch (err) {
      setError(err.message || "Step request failed");
    } finally {
      setLoading(false);
    }
  };

  const highlightAnchors = (text, anchors) => {
    if (!text || !anchors || anchors.length === 0) return text;
    // Create regex matching any of the anchors
    const escaped = anchors.map(a => a.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&'));
    const regex = new RegExp(`(${escaped.join('|')})`, 'gi');
    
    const parts = text.split(regex);
    return parts.map((part, idx) => {
      const match = anchors.some(a => a.toLowerCase() === part.toLowerCase());
      return match ? <mark key={idx} className={styles.highlight}>{part}</mark> : part;
    });
  };

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.headerLogo}>
          <div className={styles.circleGrad} />
          <h1>Backend Processing Pipeline Sandbox</h1>
        </div>
        <p>Step-by-step trace of image quality metrics, preprocessing actions, and quality gates</p>
      </header>

      <div className={styles.contentLayout}>
        {/* LEFT COLUMN: SETUP PANEL */}
        <div className={styles.panelLeft}>
          <div className={styles.card}>
            <h3>1. Upload Document Image</h3>
            <div className={styles.uploadArea} onClick={() => fileInputRef.current.click()}>
              {previewUrl ? (
                <img src={previewUrl} alt="Preview" className={styles.imgPreview} />
              ) : (
                <div className={styles.uploadPrompt}>
                  <span>📁 Click to Upload Document</span>
                  <p>JPEG or PNG format supported</p>
                </div>
              )}
              <input type="file" ref={fileInputRef} onChange={handleFileChange} style={{ display: 'none' }} accept="image/*" />
            </div>
          </div>

          <div className={styles.card}>
            <h3>2. Document Config (Manifest JSON)</h3>
            <textarea
              className={styles.manifestTextArea}
              value={manifestStr}
              onChange={(e) => setManifestStr(e.target.value)}
            />
          </div>

          <div className={styles.card}>
            <h3>3. Setup Configuration</h3>
            <div className={styles.row}>
              <div className={styles.inputGroup}>
                <label>Page / Part ID</label>
                <select value={pageId} onChange={(e) => setPageId(e.target.value)}>
                  <option value="front">front</option>
                  <option value="back">back</option>
                </select>
              </div>
              <div className={styles.inputGroup}>
                <label>Language</label>
                <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                  <option value="en">English (en)</option>
                  <option value="hi">Hindi (hi)</option>
                  <option value="te">Telugu (te)</option>
                </select>
              </div>
            </div>
            
            <button className={styles.btnInit} onClick={handleInit} disabled={loading || !selectedFile}>
              {loading ? "Initializing..." : "🚀 Initialize Sandbox Session"}
            </button>
            {error && <div className={styles.errorBanner}>{error}</div>}
          </div>
        </div>

        {/* RIGHT COLUMN: PIPELINE TRAIL */}
        <div className={styles.panelRight}>
          <div className={styles.trailHeader}>
            <h2>Pipeline Execution Trace</h2>
            {isInitialized && (
              <div className={styles.stepProgressRow}>
                <span>Step {currentStepIndex} of {decisions.length} recovery actions applied</span>
                {currentStepIndex < decisions.length ? (
                  <button className={styles.btnNext} onClick={handleNextStep} disabled={loading}>
                    {loading ? "Applying..." : `Next: Apply '${decisions[currentStepIndex].action}' ➡️`}
                  </button>
                ) : (
                  <div className={styles.completeBadge}>🎉 Preprocessing Complete</div>
                )}
              </div>
            )}
          </div>

          {!isInitialized ? (
            <div className={styles.emptyState}>
              <div className={styles.emptyIcon}>🔍</div>
              <h3>No Active Session</h3>
              <p>Configure details on the left and click Initialize to begin step-by-step pipeline tracing.</p>
            </div>
          ) : (
            <div className={styles.trailList}>
              {steps.map((step, idx) => (
                <div key={idx} className={styles.trailCard} style={{ animationDelay: `${idx * 0.1}s` }}>
                  <div className={styles.trailCardHeader}>
                    <h4>{step.stageName}</h4>
                    {step.actionReason && (
                      <span className={styles.reasonBadge}>Reason: {step.actionReason}</span>
                    )}
                  </div>

                  <div className={styles.trailCardBody}>
                    {/* Visual Comparison / Image display */}
                    <div className={styles.imageDisplay}>
                      <img src={step.imageSrc} alt={step.stageName} className={styles.processedImage} />
                    </div>

                    {/* Metrics Grid */}
                    <div className={styles.metricsPanel}>
                      <h5>Quality Metrics</h5>
                      <div className={styles.metricsGrid}>
                        <div className={styles.metricItem}>
                          <span className={styles.metricLabel}>Blur Variance</span>
                          <span className={styles.metricValue}>{step.metrics.blur.toFixed(2)}</span>
                        </div>
                        <div className={styles.metricItem}>
                          <span className={styles.metricLabel}>Brightness</span>
                          <span className={styles.metricValue}>{step.metrics.brightness.toFixed(3)}</span>
                        </div>
                        <div className={styles.metricItem}>
                          <span className={styles.metricLabel}>Contrast</span>
                          <span className={styles.metricValue}>{step.metrics.contrast.toFixed(3)}</span>
                        </div>
                        <div className={styles.metricItem}>
                          <span className={styles.metricLabel}>Glare Fraction</span>
                          <span className={styles.metricValue}>{(step.metrics.glare * 100).toFixed(1)}%</span>
                        </div>
                        <div className={styles.metricItem}>
                          <span className={styles.metricLabel}>Shadow Fraction</span>
                          <span className={styles.metricValue}>{(step.metrics.shadow * 100).toFixed(1)}%</span>
                        </div>
                        <div className={styles.metricItem}>
                          <span className={styles.metricLabel}>Rotation Angle</span>
                          <span className={styles.metricValue}>{step.metrics.rotation.toFixed(1)}°</span>
                        </div>
                        <div className={styles.metricItem}>
                          <span className={styles.metricLabel}>QR Codes Detected</span>
                          <span className={styles.metricValue}>{step.metrics.has_qr_codes ? `Yes (${step.metrics.qr_coordinates ? step.metrics.qr_coordinates.length : 0})` : 'No'}</span>
                        </div>
                        {step.metrics.has_qr_codes && step.metrics.qr_coordinates && step.metrics.qr_coordinates.length > 0 && (
                          <div className={styles.metricItem} style={{ gridColumn: 'span 2' }}>
                            <span className={styles.metricLabel}>QR Coordinates</span>
                            <span className={styles.metricValue} style={{ fontSize: '0.75rem', fontFamily: 'monospace' }}>
                              {step.metrics.qr_coordinates.map((c, cIdx) => `[${cIdx+1}] x:${c.x}, y:${c.y}, w:${c.width}, h:${c.height}`).join(' | ')}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Decisions listed only in original image stage */}
                  {idx === 0 && step.decisions && (
                    <div className={styles.plannedDecisions}>
                      <h5>Planned Preprocessing Pipeline</h5>
                      {step.decisions.length === 0 ? (
                        <p className={styles.infoText}>✅ No quality policy violations detected. Image satisfies manifest thresholds.</p>
                      ) : (
                        <ol>
                          {step.decisions.map((dec, dIdx) => (
                            <li key={dIdx}>
                              <strong>{dec.action}</strong>: <span>{dec.reason}</span>
                            </li>
                          ))}
                        </ol>
                      )}
                    </div>
                  )}

                  {/* Quality Gate / OCR results (shown for intermediate/final stages only) */}
                  {step.qualityGate && (
                    <div className={styles.qualityGatePanel}>
                      <div className={styles.gateHeader}>
                        <h5>Quality Gate Verification</h5>
                        <span className={step.qualityGate.passed ? styles.gatePass : styles.gateFail}>
                          {step.qualityGate.passed ? "PASS" : `FAIL (${step.qualityGate.failure_reason || step.qualityGate.error})`}
                        </span>
                      </div>
                      <div className={styles.gateDetails}>
                        <div className={styles.gateGrid}>
                          <div><strong>Detected Part:</strong> <span>{step.qualityGate.part_id || "Unidentified"}</span></div>
                          <div><strong>OCR Confidence:</strong> <span>{(step.qualityGate.ocr_confidence * 100).toFixed(0)}%</span></div>
                          <div><strong>Anchor Hits:</strong> <span>{step.qualityGate.anchor_hits} matched</span></div>
                        </div>

                        {step.qualityGate.anchors_detailed && Object.keys(step.qualityGate.anchors_detailed).length > 0 && (
                          <div className={styles.anchorsDetailedContainer}>
                            <strong>Anchor Evaluation Details:</strong>
                            <div className={styles.anchorsPartsGrid}>
                              {Object.entries(step.qualityGate.anchors_detailed).map(([pId, anchors]) => (
                                <div key={pId} className={`${styles.anchorsPartCard} ${pageId === pId ? styles.targetPartCard : ''}`}>
                                  <span className={styles.anchorsPartTitle}>
                                    Part '{pId}' ({anchors.filter(a => a.matched).length} / {anchors.length} matches)
                                  </span>
                                  <ul className={styles.anchorsList}>
                                    {anchors.map((a, aIdx) => (
                                      <li key={aIdx} className={a.matched ? styles.anchorMatched : styles.anchorUnmatched}>
                                        <span className={styles.checkIcon}>{a.matched ? "✓" : "✗"}</span> {a.anchor}
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {step.qualityGate.ocr_text && (
                          <div className={styles.ocrTextContainer}>
                            <strong>Extracted Text (Marked Matches):</strong>
                            <pre className={styles.ocrText}>
                              {highlightAnchors(step.qualityGate.ocr_text, JSON.parse(manifestStr).parts.find(p => p.id === pageId)?.anchors || [])}
                            </pre>
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Execution Logs */}
                  {step.logs && step.logs.length > 0 && (
                    <div className={styles.stepLogsContainer}>
                      <h5>Execution Logs</h5>
                      <pre className={styles.stepLogs}>
                        {step.logs.join('\n')}
                      </pre>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
