export class CaptureVoiceManager {
  constructor(config) {
    this.token = config.token;
    this.sessionId = config.sessionId;
    this.language = config.language;
    this.wsUrl = config.wsUrl;
    
    this.onStateChange = config.onStateChange || (() => {});
    this.onTranscript = config.onTranscript || (() => {});
    this.onSystemMessage = config.onSystemMessage || (() => {});
    this.onError = config.onError || (() => {});
    
    this.ws = null;
    this.audioContext = null;
    this.processorNode = null;
    this.mediaStream = null;
    this.vadNode = null;
    this.reconnectAttempts = 0;
    
    // Playback state
    this.audioQueue = [];
    this.isPlaying = false;
    this.currentSource = null;
    this.stopPlaybackRequested = false;
  }

  async connect() {
    this.onStateChange('connecting');
    try {
      this.ws = new WebSocket(this.wsUrl);
      this.ws.binaryType = 'arraybuffer';
      
      this.ws.onopen = () => {
        const initData = {
          token: this.token,
          session_id: this.sessionId,
          language: this.language
        };
        this.ws.send(JSON.stringify(initData));
      };
      
      this.ws.onmessage = async (event) => {
        if (typeof event.data === 'string') {
          const data = JSON.parse(event.data);
          if (data.type === 'status') {
            if (data.status === 'connected') {
              this.reconnectAttempts = 0;
              await this.startAudioCapture();
            } else {
              this.onStateChange(data.status); // listening, processing, speaking
            }
          } else if (data.type === 'transcription') {
            this.onTranscript(data.text, data.is_final);
          } else if (data.type === 'error') {
            this.onError(data.message);
          } else if (data.type === 'audio_chunk') {
            // Header for audio, next message is bytes
            this.pendingAudioConfig = data;
          } else if (data.type === 'audio_end') {
             // Handled internally by queue
          }
        } else {
          // Binary audio data
          if (this.pendingAudioConfig && !this.stopPlaybackRequested) {
            this.audioQueue.push({
              buffer: event.data,
              sampleRate: this.pendingAudioConfig.sample_rate
            });
            this.pendingAudioConfig = null;
            this.playNextInQueue();
          }
        }
      };
      
      this.ws.onclose = () => {
        this.stopAudioCapture();
        if (this.reconnectAttempts < 3) {
          this.reconnectAttempts++;
          setTimeout(() => this.connect(), 2000);
        } else {
          this.onError('Connection lost. Please refresh.');
        }
      };
    } catch (err) {
      this.onError(err.message);
    }
  }

  async startAudioCapture() {
    if (!window.globalAudioContext) {
      window.globalAudioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    this.audioContext = window.globalAudioContext;
    if (this.audioContext.state === 'suspended') {
      await this.audioContext.resume();
    }
    
    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
          sampleRate: 16000
        } 
      });
      
      await this.audioContext.audioWorklet.addModule('/audioProcessor.js');
      
      const source = this.audioContext.createMediaStreamSource(this.mediaStream);
      this.processorNode = new AudioWorkletNode(this.audioContext, 'audio-processor');
      
      this.processorNode.port.onmessage = (e) => {
        if (e.data.type === 'audio') {
          // Send to WS if playing/not stopped
          if (this.ws && this.ws.readyState === WebSocket.OPEN && !this.isPlaying) {
             this.ws.send(e.data.buffer);
          }
        }
      };
      
      source.connect(this.processorNode);
      this.processorNode.connect(this.audioContext.destination);
      
    } catch (err) {
      this.onError('Microphone access denied: ' + err.message);
    }
  }
  
  stopAudioCapture() {
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach(t => t.stop());
    }
    if (this.processorNode) {
      this.processorNode.disconnect();
    }
  }

  sendTextInput(text) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.stopAudioPlayback();
      this.ws.send(JSON.stringify({ text_input: text }));
    }
  }

  sendControlSignal(signal) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ signal: signal }));
    }
  }

  stopAudioPlayback() {
    this.stopPlaybackRequested = true;
    this.audioQueue = [];
    if (this.currentSource) {
      try {
        this.currentSource.stop();
      } catch (e) {}
      this.currentSource = null;
    }
    this.isPlaying = false;
    
    // Re-enable in 100ms
    setTimeout(() => {
      this.stopPlaybackRequested = false;
    }, 100);
  }

  async playNextInQueue() {
    if (this.isPlaying || this.audioQueue.length === 0 || this.stopPlaybackRequested) {
      return;
    }
    
    this.isPlaying = true;
    const chunk = this.audioQueue.shift();
    
    try {
      const audioBuffer = await this.audioContext.decodeAudioData(chunk.buffer);
      this.currentSource = this.audioContext.createBufferSource();
      this.currentSource.buffer = audioBuffer;
      this.currentSource.connect(this.audioContext.destination);
      
      this.currentSource.onended = () => {
        this.isPlaying = false;
        this.currentSource = null;
        this.playNextInQueue();
      };
      
      this.currentSource.start();
    } catch (e) {
      console.error('Audio decode error', e);
      this.isPlaying = false;
      this.playNextInQueue();
    }
  }

  disconnect() {
    this.stopAudioPlayback();
    this.stopAudioCapture();
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
    }
  }
}
